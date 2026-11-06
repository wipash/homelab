"""Read-only, fail-closed storage gates for reversible NAS maintenance."""

import json
import re
import sys
from collections.abc import Callable


Run = Callable[[list[str]], str]
NAS_ADDRESS = "10.0.16.16"
_SSH = [
    "ssh", "-p", "22222", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
    "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2", f"wipash@{NAS_ADDRESS}",
]
_PORT_PROBE = (
    "import socket,sys; "
    "connection=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=3); "
    "connection.close()"
)


def _read(run: Run, argv: list[str], label: str, blockers: list[str]) -> str | None:
    try:
        result = run(argv)
        if not isinstance(result, str):
            raise ValueError("command did not return text")
        return result
    except Exception as exc:
        blockers.append(f"{label}: {type(exc).__name__}: {exc}")
        return None


def _unescape(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def _mounts(text: str) -> list[tuple[str, str, str, set[str]]]:
    """Parse procfs, rejecting empty/truncated output and command diagnostics."""
    mounts = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if (
            len(fields) != 6
            or not fields[1].startswith("/")
            or not fields[4].isdigit()
            or not fields[5].isdigit()
        ):
            raise ValueError(f"invalid /proc/mounts record at line {number}")
        source, target, filesystem, options, _, _ = fields
        modes = set(options.split(","))
        if not modes.intersection({"ro", "rw"}):
            raise ValueError(f"missing mount access mode at line {number}")
        mounts.append((_unescape(source), _unescape(target), filesystem, modes))
    if not any(target == "/" for _, target, _, _ in mounts):
        raise ValueError("/proc/mounts is empty or has no root filesystem")
    return mounts


def _hosts(plan: dict) -> set[str]:
    hosts = plan.get("nas_hosts")
    if not isinstance(hosts, (list, set, tuple)) or not hosts:
        raise ValueError("plan has no NAS hosts")
    if any(not isinstance(host, str) or not host.strip() for host in hosts):
        raise ValueError("plan has an invalid NAS host")
    return {host.lower().rstrip(".").strip("[]") for host in hosts}


def _nfs_host(source: str) -> str:
    if source.startswith("[") and "]:" in source:
        return source[1:source.index("]:")].lower()
    return source.partition(":")[0].lower().rstrip(".")


def storage_blockers(plan: dict, run: Run) -> list[str]:
    """Return reasons node storage is unsafe for NAS shutdown; never unmount/logout.

    The injected runner must impose command deadlines and raise on nonzero exits.
    All iSCSI sessions block in this dedicated cluster, even without mounted pods.
    """
    blockers: list[str] = []
    try:
        hosts = _hosts(plan)
    except ValueError as exc:
        return [str(exc)]
    nodes = plan.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["plan has no nodes to inspect for storage cleanup"]
    claims = {claim["pv"] for claim in plan.get("nas_claims", []) if claim.get("pv")}
    for node in nodes:
        address = node.get("address")
        name = node.get("name") or address or "unknown node"
        if not isinstance(address, str) or not address:
            blockers.append(f"{name}: no node address for storage inspection")
            continue
        sessions = _read(
            run, ["talosctl", "-n", address, "ls", "/sys/class/iscsi_session"],
            f"{name}: cannot inspect iSCSI sessions", blockers,
        )
        if sessions is not None:
            entries = [line.strip() for line in sessions.splitlines() if line.strip()]
            active = [entry for entry in entries if re.fullmatch(r"session\d+", entry)]
            if not entries or any(
                entry not in {".", ".."} and not re.fullmatch(r"session\d+", entry)
                for entry in entries
            ):
                blockers.append(f"{name}: unrecognized iSCSI session listing; cannot prove cleanup")
            if active:
                blockers.append(f"{name}: {len(active)} iSCSI session(s) remain ({', '.join(active)})")
        text = _read(
            run, ["talosctl", "-n", address, "read", "/proc/mounts"],
            f"{name}: cannot inspect host mounts", blockers,
        )
        if text is None:
            continue
        try:
            mounts = _mounts(text)
        except ValueError as exc:
            blockers.append(f"{name}: {exc}")
            continue
        for source, target, filesystem, options in mounts:
            nfs = filesystem in {"nfs", "nfs4"} and (
                _nfs_host(source) in hosts
                or any(option.startswith("addr=") and option[5:].lower() in hosts for option in options)
            )
            csi = "/csi.san.synology.com/" in target or any(
                f"/volumes/kubernetes.io~csi/{pv}/" in target for pv in claims
            )
            if nfs or csi:
                kind = "NAS NFS" if nfs else "Synology CSI"
                blockers.append(f"{name}: {kind} mount remains at {target}")
    return blockers


def nas_ready(plan: dict, run: Run) -> list[str]:
    """Return reasons DSM storage is not ready to resume apps, not just open ports.

    Every discovered /volumeN must be an exact writable NAS mountpoint. Service,
    filesystem and bounded TCP checks must all pass; app mount readiness is the
    caller's subsequent responsibility. The runner must bound command duration.
    """
    blockers: list[str] = []
    volumes = plan.get("volumes")
    if not isinstance(volumes, list) or not volumes or any(
        not isinstance(volume, str) or not re.fullmatch(r"/volume[1-9]\d*", volume)
        for volume in volumes
    ):
        return ["plan has no valid NAS /volumeN roots to inspect"]
    protocols = plan.get("nas_protocols")
    if not isinstance(protocols, list) or not protocols or any(
        protocol not in {"iscsi", "nfs"} for protocol in protocols
    ):
        return ["plan has no valid NAS storage protocols to inspect"]
    status = _read(
        run, _SSH + ["sudo", "-n", "/usr/syno/bin/synopkg", "status", "ScsiTarget"],
        "NAS: cannot inspect ScsiTarget", blockers,
    )
    if status is not None:
        try:
            package = json.loads(status)
            if not isinstance(package, dict) or package.get("package") != "ScsiTarget":
                raise ValueError("unexpected ScsiTarget status JSON")
            if package.get("status") != "running":
                blockers.append("NAS: ScsiTarget package is not running")
            aspect = package.get("aspect", {})
            if not isinstance(aspect, dict):
                raise ValueError("invalid ScsiTarget aspect JSON")
            active = aspect.get("active")
            if active is not None and (
                not isinstance(active, dict) or active.get("status") != "running"
            ):
                blockers.append("NAS: ScsiTarget active status is not running")
        except (ValueError, TypeError) as exc:
            blockers.append(f"NAS: cannot parse ScsiTarget status: {exc}")
    text = _read(run, _SSH + ["cat", "/proc/mounts"], "NAS: cannot inspect mounts", blockers)
    if text is not None:
        try:
            mounts = _mounts(text)
            for volume in sorted(set(volumes)):
                matching = [options for _, target, _, options in mounts if target == volume]
                if not matching:
                    blockers.append(f"NAS: {volume} is not mounted")
                elif any("ro" in options or "rw" not in options for options in matching):
                    blockers.append(f"NAS: {volume} is not mounted read-write")
        except ValueError as exc:
            blockers.append(f"NAS: {exc}")
    for protocol, port in (("iscsi", 3260), ("nfs", 2049)):
        if protocol in protocols:
            _read(
                run, [sys.executable, "-c", _PORT_PROBE, NAS_ADDRESS, str(port)],
                f"NAS: {protocol.upper()} TCP port {port} is unreachable", blockers,
            )
    return blockers

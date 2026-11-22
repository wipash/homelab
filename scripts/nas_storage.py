"""Read-only, fail-closed storage gates for reversible NAS maintenance."""

from collections import Counter
from collections.abc import Callable
import hashlib
import json
import posixpath
import re
import sys


Run = Callable[[list[str]], str]
KubeCommand = Callable[..., str]
NAS_ADDRESS = "10.0.16.16"
CSI_DRIVER = "csi.san.synology.com"
_GLOBALMOUNT_RE = re.compile(
    r"^/var/lib/kubelet/plugins/kubernetes\.io/csi/csi\.san\.synology\.com/([0-9a-f]{64})/globalmount$"
)
_SYNOLOGY_PVC_IQN_RE = re.compile(
    r"^iqn\.2000-01\.com\.synology:[^.]+\.(pvc-[0-9a-f-]+)$", re.IGNORECASE
)
_ATTACHED_DISK_RE = re.compile(r"Attached scsi disk\s+(\S+)\s+State:\s*(.+)")
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


def _portal_host(portal: str) -> str:
    hostport = portal.partition(",")[0].strip()
    if hostport.startswith("[") and "]:" in hostport:
        return hostport[1:hostport.index("]:")].lower()
    return hostport.partition(":")[0].lower().rstrip(".")


def _device_matches_disk(source: str, disk: str) -> bool:
    return bool(re.fullmatch(rf"/dev/{re.escape(disk)}(?:p?\d+)?", source))


def _pv_claim_label(pv: dict | None) -> str:
    if not pv:
        return ""
    ref = pv.get("spec", {}).get("claimRef")
    if ref and ref.get("namespace") and ref.get("name"):
        return f" ({ref['namespace']}/{ref['name']})"
    return ""


def _csi_node_pods(resources: dict) -> dict[str, str]:
    pods: dict[str, str] = {}
    for pod in resources.get("pods", []):
        meta = pod.get("metadata", {})
        if (
            meta.get("namespace") == "synology-csi"
            and meta.get("labels", {}).get("app") == "synology-csi-node"
            and not meta.get("deletionTimestamp")
            and pod.get("status", {}).get("phase") == "Running"
            and pod.get("spec", {}).get("nodeName")
        ):
            pods[pod["spec"]["nodeName"]] = meta["name"]
    return pods


def _parse_iscsi_sessions(text: str) -> list[dict]:
    """Parse `iscsiadm -m session -P 3`, failing closed on truncated blocks."""
    sessions: list[dict] = []
    current_target: str | None = None
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("Target:"):
            target_tokens = line[len("Target:"):].strip().split()
            if not target_tokens:
                raise ValueError("missing IQN in Target line")
            current_target = target_tokens[0]
            current = {
                "target": current_target,
                "portal": "",
                "sid": "",
                "connection_state": "unknown",
                "session_state": "unknown",
                "disks": [],
            }
            sessions.append(current)
        elif line.startswith("Current Portal:"):
            if current is None or current_target is None:
                raise ValueError("portal without target in iscsiadm output")
            if current["sid"]:
                current = {
                    "target": current_target,
                    "portal": "",
                    "sid": "",
                    "connection_state": "unknown",
                    "session_state": "unknown",
                    "disks": [],
                }
                sessions.append(current)
            current["portal"] = line[len("Current Portal:"):].strip()
        elif line.startswith("Persistent Portal:") and current is not None and not current["portal"]:
            current["portal"] = line[len("Persistent Portal:"):].strip()
        elif line.startswith("SID:"):
            if current is None:
                raise ValueError("SID without target in iscsiadm output")
            sid = line[len("SID:"):].strip()
            if not sid.isdigit():
                raise ValueError(f"invalid SID in iscsiadm output: {sid!r}")
            current["sid"] = sid
        elif line.startswith("iSCSI Connection State:") and current is not None:
            current["connection_state"] = line[len("iSCSI Connection State:"):].strip()
        elif line.startswith("iSCSI Session State:") and current is not None:
            current["session_state"] = line[len("iSCSI Session State:"):].strip()
        elif current is not None:
            disk_match = _ATTACHED_DISK_RE.search(line)
            if disk_match:
                current["disks"].append((disk_match.group(1), disk_match.group(2).strip()))
    for session in sessions:
        if not session["sid"] or not session["target"]:
            raise ValueError("incomplete session record in iscsiadm output")
    return sessions


def _inspect_vol_data(
    address: str, target: str, mount_hash: str, run: Run,
) -> tuple[str | None, str | None]:
    vol_data_path = posixpath.join(posixpath.dirname(target), "vol_data.json")
    try:
        raw = run(["talosctl", "-n", address, "read", vol_data_path])
        if not isinstance(raw, str):
            raise ValueError("vol_data.json read did not return text")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("vol_data.json is not a JSON object")
        if data.get("driverName") != CSI_DRIVER:
            raise ValueError(f"unexpected driverName {data.get('driverName')!r}")
        handle = data.get("volumeHandle")
        if not isinstance(handle, str) or not handle:
            raise ValueError("missing volumeHandle")
        if hashlib.sha256(handle.encode()).hexdigest() != mount_hash:
            raise ValueError("volumeHandle hash does not match mount directory")
        return handle, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def inspect_node_storage(
    plan: dict, resources: dict, run: Run, kube_command: KubeCommand,
) -> dict:
    """Inspect node NAS mounts and iSCSI sessions, classifying provable orphans.

    Read-only: never unmounts or logs out. Any item matching an existing PV, an
    active VolumeAttachment, a non-PVC target, or a shared/unverifiable mount
    stays a non-orphan blocker.
    """
    blockers: list[str] = []
    orphan_mounts: list[dict] = []
    orphan_sessions: list[dict] = []
    warnings: list[str] = []
    try:
        hosts = _hosts(plan)
    except ValueError as exc:
        return {"blockers": [str(exc)], "orphan_mounts": [], "orphan_sessions": [], "warnings": [str(exc)]}
    nodes = plan.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        msg = "plan has no nodes to inspect for storage cleanup"
        return {"blockers": [msg], "orphan_mounts": [], "orphan_sessions": [], "warnings": [msg]}

    claims = {claim["pv"] for claim in plan.get("nas_claims", []) if claim.get("pv")}
    pvs = resources.get("persistentvolumes", [])
    pv_by_name = {pv["metadata"]["name"]: pv for pv in pvs if pv.get("metadata", {}).get("name")}
    pv_by_handle: dict[str, dict] = {}
    pv_by_handle_hash: dict[str, dict] = {}
    for pv in pvs:
        csi = pv.get("spec", {}).get("csi", {})
        handle = csi.get("volumeHandle")
        if csi.get("driver") == CSI_DRIVER and isinstance(handle, str) and handle:
            pv_by_handle[handle] = pv
            pv_by_handle_hash[hashlib.sha256(handle.encode()).hexdigest()] = pv
    attached_pvs = {
        va.get("spec", {}).get("source", {}).get("persistentVolumeName")
        for va in resources.get("volumeattachments", [])
        if va.get("spec", {}).get("attacher") == CSI_DRIVER
    }
    attached_pvs.discard(None)
    csi_pods = _csi_node_pods(resources)

    for node in nodes:
        address = node.get("address")
        name = node.get("name") or address or "unknown node"
        if not isinstance(address, str) or not address:
            msg = f"{name}: no node address for storage inspection"
            blockers.append(msg)
            warnings.append(msg)
            continue
        csi_pod = csi_pods.get(name)

        mounts: list[tuple[str, str, str, set[str]]] | None = None
        mount_text = _read(
            run, ["talosctl", "-n", address, "read", "/proc/mounts"],
            f"{name}: cannot inspect host mounts", blockers,
        )
        if mount_text is None:
            warnings.append(blockers[-1])
        else:
            try:
                mounts = _mounts(mount_text)
            except ValueError as exc:
                msg = f"{name}: {exc}"
                blockers.append(msg)
                warnings.append(msg)

        orphan_mount_targets: set[str] = set()
        if mounts is not None:
            source_counts = Counter(source for source, _, _, _ in mounts)
            for source, target, filesystem, options in mounts:
                nfs = filesystem in {"nfs", "nfs4"} and (
                    _nfs_host(source) in hosts
                    or any(option.startswith("addr=") and option[5:].lower() in hosts for option in options)
                )
                if nfs:
                    blockers.append(f"{name}: NAS NFS mount remains at {target} ({source})")
                    continue
                csi = f"/{CSI_DRIVER}/" in target or any(
                    f"/volumes/kubernetes.io~csi/{pv}/" in target for pv in claims
                )
                if not csi:
                    continue
                match = _GLOBALMOUNT_RE.match(target)
                if not match:
                    blockers.append(f"{name}: Synology CSI mount remains at {target}")
                    continue
                mount_hash = match.group(1)
                live_pv = pv_by_handle_hash.get(mount_hash)
                if live_pv is not None:
                    pv_name = live_pv["metadata"]["name"]
                    blockers.append(
                        f"{name}: Synology CSI globalmount remains for {pv_name}{_pv_claim_label(live_pv)} at {target}"
                    )
                    continue
                handle, err = _inspect_vol_data(address, target, mount_hash, run)
                if err is not None:
                    msg = f"{name}: Synology CSI globalmount remains at {target} (cannot verify vol_data.json: {err})"
                    blockers.append(msg)
                    warnings.append(msg)
                    continue
                if handle in pv_by_handle:
                    live_pv = pv_by_handle[handle]
                    pv_name = live_pv["metadata"]["name"]
                    blockers.append(
                        f"{name}: Synology CSI globalmount remains for {pv_name}{_pv_claim_label(live_pv)} at {target}"
                    )
                    continue
                if source_counts[source] != 1:
                    blockers.append(
                        f"{name}: Synology CSI globalmount remains at {target} "
                        f"(volumeHandle={handle}, device {source} shared by {source_counts[source]} mounts)"
                    )
                    continue
                desc = (
                    f"{name}: orphaned Synology CSI globalmount {target} "
                    f"(volumeHandle={handle}, device={source}, options={','.join(sorted(options))}, no matching PV)"
                )
                blockers.append(desc)
                orphan_mount_targets.add(target)
                orphan_mounts.append({
                    "node": name,
                    "address": address,
                    "pod": csi_pod,
                    "target": target,
                    "source": source,
                    "volume_handle": handle,
                    "description": desc,
                })

        session_text = _read(
            run, ["talosctl", "-n", address, "ls", "/sys/class/iscsi_session"],
            f"{name}: cannot inspect iSCSI sessions", blockers,
        )
        if session_text is None:
            warnings.append(blockers[-1])
            continue
        entries = [line.strip() for line in session_text.splitlines() if line.strip()]
        if not entries or any(
            entry not in {".", ".."} and not re.fullmatch(r"session\d+", entry)
            for entry in entries
        ):
            msg = f"{name}: unrecognized iSCSI session listing; cannot prove cleanup"
            blockers.append(msg)
            warnings.append(msg)
            continue
        active_sids = {entry[len("session"):] for entry in entries if re.fullmatch(r"session\d+", entry)}
        if not active_sids:
            continue
        if not csi_pod:
            msg = (
                f"{name}: {len(active_sids)} iSCSI session(s) remain "
                f"({', '.join(sorted(f'session{sid}' for sid in active_sids))}); "
                "no running synology-csi-node pod to inspect them"
            )
            blockers.append(msg)
            warnings.append(msg)
            continue
        try:
            iscsi_output = kube_command(
                "-n", "synology-csi", "exec", csi_pod, "-c", "csi-plugin", "--",
                "chroot", "/host", "/usr/local/sbin/iscsiadm", "-m", "session", "-P", "3",
            )
            parsed = _parse_iscsi_sessions(iscsi_output)
        except Exception as exc:
            if "No active sessions" in str(exc):
                parsed = []
            else:
                msg = (
                    f"{name}: {len(active_sids)} iSCSI session(s) remain "
                    f"({', '.join(sorted(f'session{sid}' for sid in active_sids))}); "
                    f"cannot inspect via iscsiadm: {exc}"
                )
                blockers.append(msg)
                warnings.append(msg)
                continue

        parsed_by_sid = {session["sid"]: session for session in parsed}
        for sid in sorted(active_sids, key=int):
            session = parsed_by_sid.get(sid)
            if session is None:
                blockers.append(f"{name}: iSCSI session{sid} remains (not present in iscsiadm output)")
                continue
            target_iqn = session["target"]
            state = f"{session['session_state']}/{session['connection_state']}"
            portal_ok = bool(session["portal"]) and _portal_host(session["portal"]) in hosts
            iqn_match = _SYNOLOGY_PVC_IQN_RE.match(target_iqn)
            pv_name = iqn_match.group(1) if iqn_match else None
            live_pv = pv_by_name.get(pv_name) if pv_name else None
            if live_pv is not None:
                blockers.append(
                    f"{name}: iSCSI session{sid} remains for {pv_name}{_pv_claim_label(live_pv)} "
                    f"({target_iqn}, state={state})"
                )
                continue
            if not portal_ok or pv_name is None:
                blockers.append(f"{name}: iSCSI session{sid} remains ({target_iqn}, state={state})")
                continue
            if pv_name in attached_pvs:
                blockers.append(
                    f"{name}: iSCSI session{sid} remains ({target_iqn}, state={state}, VolumeAttachment still present)"
                )
                continue
            if mounts is None:
                blockers.append(
                    f"{name}: iSCSI session{sid} remains ({target_iqn}, state={state}, host mounts unreadable)"
                )
                continue
            mounted_any = False
            mounted_non_orphan = False
            for disk, _ in session["disks"]:
                for source, mount_target, _, _ in mounts:
                    if _device_matches_disk(source, disk):
                        mounted_any = True
                        if mount_target not in orphan_mount_targets:
                            mounted_non_orphan = True
            if mounted_non_orphan:
                blockers.append(
                    f"{name}: iSCSI session{sid} remains ({target_iqn}, state={state}, disk still mounted)"
                )
                continue
            desc = f"{name}: orphaned iSCSI session{sid} ({target_iqn}, state={state}, no matching PV)"
            blockers.append(desc)
            orphan_sessions.append({
                "node": name,
                "address": address,
                "pod": csi_pod,
                "sid": sid,
                "target": target_iqn,
                "pv_name": pv_name,
                "state": state,
                "unmounted": not mounted_any,
                "description": desc,
            })

    return {
        "blockers": blockers,
        "orphan_mounts": orphan_mounts,
        "orphan_sessions": orphan_sessions,
        "warnings": warnings,
    }


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

"""Behavioral tests; all remote observations are supplied in memory."""

import copy
import json
import subprocess
import unittest

from nas_storage import nas_ready, storage_blockers


ROOT = "/dev/root / ext4 rw,relatime 0 0\n"
NAS_MOUNTS = (
    ROOT
    + "/dev/mapper/cachedev_1 /volume1 btrfs rw,nodev,relatime 0 0\n"
    + "/dev/mapper/cachedev_0 /volume3 btrfs rw,nodev,noatime 0 0\n"
)
RUNNING = json.dumps({
    "aspect": {"active": {"status": "running", "status_code": 0}},
    "package": "ScsiTarget",
    "status": "running",
})
PLAN = {
    "nas_hosts": ["10.0.16.16", "brian.sk.mcgrath.nz"],
    "nodes": [
        {"name": "hp1", "address": "10.0.16.133"},
        {"name": "hp2", "address": "10.0.16.135"},
    ],
    "nas_claims": [{"namespace": "media", "name": "data", "pv": "pvc-data"}],
    "volumes": ["/volume1", "/volume3"],
    "nas_protocols": ["iscsi", "nfs"],
}


class Observations:
    """A tiny observation adapter, not a subprocess or network emulator."""

    def __init__(self):
        self.sessions = {"10.0.16.133": ".\n", "10.0.16.135": ".\n"}
        self.node_mounts = {"10.0.16.133": ROOT, "10.0.16.135": ROOT}
        self.status = RUNNING
        self.mounts = NAS_MOUNTS
        self.ports = {3260: "", 2049: ""}

    def __call__(self, argv):
        if argv[0] == "talosctl":
            address = argv[argv.index("-n") + 1]
            if argv[-2:] == ["ls", "/sys/class/iscsi_session"]:
                result = self.sessions[address]
            elif argv[-2:] == ["read", "/proc/mounts"]:
                result = self.node_mounts[address]
            else:
                raise AssertionError("unexpected Talos observation")
        elif argv[0] == "ssh":
            if argv[-2:] == ["status", "ScsiTarget"]:
                result = self.status
            elif argv[-2:] == ["cat", "/proc/mounts"]:
                result = self.mounts
            else:
                raise AssertionError("unexpected NAS observation")
        elif "-c" in argv:
            result = self.ports[int(argv[-1])]
        else:
            raise AssertionError("unexpected observation")
        if isinstance(result, Exception):
            raise result
        return result


class StorageBlockersTests(unittest.TestCase):
    def setUp(self):
        self.run = Observations()
        self.plan = copy.deepcopy(PLAN)

    def test_dot_only_sessions_and_local_mounts_allow_shutdown(self):
        self.run.sessions["10.0.16.135"] = ".\n..\n"
        self.run.node_mounts["10.0.16.133"] += (
            "/dev/sda4 /var/lib/kubelet/local xfs rw,relatime 0 0\n"
            "10.0.16.99:/data /other nfs4 rw,addr=10.0.16.99 0 0\n"
        )
        self.assertEqual(storage_blockers(self.plan, self.run), [])

    def test_any_iscsi_session_blocks_even_without_nas_mounts(self):
        self.run.sessions["10.0.16.135"] = ".\nsession3929\nsession43\n"
        blockers = storage_blockers(self.plan, self.run)
        self.assertEqual(len(blockers), 1)
        self.assertIn("hp2", blockers[0])
        self.assertIn("2 iSCSI session(s)", blockers[0])

    def test_nfs_ip_alias_and_addr_option_all_block(self):
        sources = [
            "10.0.16.16:/volume1/Media",
            "BRIAN.SK.MCGRATH.NZ.:/volume1/Media",
            "unlisted-alias:/volume1/Media",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.run.node_mounts["10.0.16.133"] = (
                    ROOT + f"{source} /var/lib/kubelet/media nfs4 rw,addr=10.0.16.16 0 0\n"
                )
                blockers = storage_blockers(self.plan, self.run)
                self.assertEqual(len(blockers), 1)
                self.assertIn("NAS NFS mount remains", blockers[0])

    def test_nfs_alias_match_does_not_depend_on_addr_option(self):
        self.run.node_mounts["10.0.16.133"] += (
            "brian.sk.mcgrath.nz:/volume1/Media /media nfs rw 0 0\n"
        )
        self.assertTrue(storage_blockers(self.plan, self.run))

    def test_escaped_nfs_mount_path_is_readable_in_blocker(self):
        self.run.node_mounts["10.0.16.133"] += (
            "10.0.16.16:/volume1/Media /media/My\\040Books nfs4 rw 0 0\n"
        )
        self.assertIn("/media/My Books", storage_blockers(self.plan, self.run)[0])

    def test_lingering_csi_mounts_block_even_after_session_disappears(self):
        targets = [
            "/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/hash/globalmount",
            "/var/lib/kubelet/pods/pod/volumes/kubernetes.io~csi/pvc-data/mount",
        ]
        for target in targets:
            with self.subTest(target=target):
                self.run.node_mounts["10.0.16.133"] = ROOT + f"/dev/sdb {target} ext4 ro 0 0\n"
                blockers = storage_blockers(self.plan, self.run)
                self.assertIn("Synology CSI mount remains", blockers[0])

    def test_session_errors_and_zero_exit_diagnostics_fail_closed(self):
        for result in ("", "error: unavailable\n", ".\npermission denied\n", RuntimeError("unreachable")):
            with self.subTest(result=result):
                self.run.sessions["10.0.16.133"] = result
                self.assertTrue(storage_blockers(self.plan, self.run))

    def test_mount_errors_and_malformed_output_fail_closed(self):
        for result in ("", "error reading mounts", ROOT + "ERROR: denied\n", RuntimeError("timeout")):
            with self.subTest(result=result):
                self.run.node_mounts["10.0.16.133"] = result
                self.assertTrue(storage_blockers(self.plan, self.run))

    def test_all_nodes_and_both_inspections_contribute_blockers(self):
        self.run.sessions["10.0.16.133"] = RuntimeError("session query failed")
        self.run.node_mounts["10.0.16.133"] = RuntimeError("mount query failed")
        self.run.sessions["10.0.16.135"] = ".\nsession42\n"
        blockers = storage_blockers(self.plan, self.run)
        self.assertEqual(len(blockers), 3)
        self.assertTrue(any("hp2" in blocker for blocker in blockers))

    def test_missing_inventory_cannot_prove_cleanup(self):
        for field, value in (("nodes", []), ("nodes", [{"name": "hp1"}]), ("nas_hosts", [])):
            with self.subTest(field=field, value=value):
                plan = copy.deepcopy(PLAN)
                plan[field] = value
                self.assertTrue(storage_blockers(plan, self.run))

    def test_does_not_modify_plan(self):
        original = copy.deepcopy(self.plan)
        storage_blockers(self.plan, self.run)
        self.assertEqual(self.plan, original)


class NasReadyTests(unittest.TestCase):
    def setUp(self):
        self.run = Observations()
        self.plan = copy.deepcopy(PLAN)

    def test_service_writable_roots_and_endpoints_are_ready(self):
        self.assertEqual(nas_ready(self.plan, self.run), [])

    def test_ports_and_service_do_not_replace_exact_volume_mounts(self):
        self.run.mounts = ROOT + "/dev/md1 /volume1/Media btrfs rw 0 0\n"
        blockers = nas_ready(self.plan, self.run)
        self.assertEqual(len(blockers), 2)
        self.assertTrue(any("/volume1 is not mounted" in blocker for blocker in blockers))
        self.assertTrue(any("/volume3 is not mounted" in blocker for blocker in blockers))

    def test_readonly_root_blocks_even_when_other_volume_is_writable(self):
        self.run.mounts = NAS_MOUNTS.replace("/volume3 btrfs rw", "/volume3 btrfs ro")
        blockers = nas_ready(self.plan, self.run)
        self.assertEqual(len(blockers), 1)
        self.assertIn("/volume3 is not mounted read-write", blockers[0])

    def test_contradictory_mount_modes_fail_closed(self):
        self.run.mounts = NAS_MOUNTS.replace("/volume1 btrfs rw", "/volume1 btrfs rw,ro")
        self.assertTrue(nas_ready(self.plan, self.run))

    def test_duplicate_mount_cannot_hide_readonly_entry(self):
        self.run.mounts += "/dev/md9 /volume3 btrfs ro 0 0\n"
        self.assertTrue(nas_ready(self.plan, self.run))

    def test_writable_mounts_and_ports_do_not_replace_running_service(self):
        self.run.status = json.dumps({"package": "ScsiTarget", "status": "start_failed"})
        self.assertIn("ScsiTarget package is not running", nas_ready(self.plan, self.run)[0])

    def test_conflicting_active_service_status_blocks(self):
        package = json.loads(RUNNING)
        package["aspect"]["active"]["status"] = "stopped"
        self.run.status = json.dumps(package)
        self.assertTrue(nas_ready(self.plan, self.run))

    def test_service_status_errors_and_invalid_json_fail_closed(self):
        for result in (
            "", "running", "null", "[]", "{}",
            json.dumps({"package": "OtherPackage", "status": "running"}),
            json.dumps({"package": "ScsiTarget", "status": "running", "aspect": []}),
            RuntimeError("SSH unavailable"),
        ):
            with self.subTest(result=result):
                self.run.status = result
                self.assertTrue(nas_ready(self.plan, self.run))

    def test_mount_command_failure_or_diagnostics_block(self):
        for result in (RuntimeError("SSH timeout"), "", NAS_MOUNTS + "permission denied\n"):
            with self.subTest(result=result):
                self.run.mounts = result
                self.assertTrue(nas_ready(self.plan, self.run))

    def test_each_required_endpoint_must_be_reachable(self):
        for port in (3260, 2049):
            with self.subTest(port=port):
                run = Observations()
                run.ports[port] = OSError("connection refused")
                blockers = nas_ready(self.plan, run)
                self.assertEqual(len(blockers), 1)
                self.assertIn(str(port), blockers[0])

    def test_protocol_selection_does_not_require_unused_nfs(self):
        self.plan["nas_protocols"] = ["iscsi"]
        self.run.ports[2049] = OSError("NFS intentionally disabled")
        self.assertEqual(nas_ready(self.plan, self.run), [])
    def test_all_health_dimensions_report_failures_together(self):
        self.run.status = subprocess.TimeoutExpired("ssh", 10)
        self.run.mounts = ROOT
        self.run.ports[3260] = OSError("connection refused")
        blockers = nas_ready(self.plan, self.run)
        self.assertEqual(len(blockers), 4)

    def test_missing_or_malformed_storage_inventory_blocks(self):
        for field, value in (
            ("volumes", []), ("volumes", ["/volume1/Media"]),
            ("nas_protocols", []), ("nas_protocols", ["unknown"]),
        ):
            with self.subTest(field=field, value=value):
                plan = copy.deepcopy(PLAN)
                plan[field] = value
                self.assertTrue(nas_ready(plan, self.run))

    def test_does_not_modify_plan(self):
        original = copy.deepcopy(self.plan)
        nas_ready(self.plan, self.run)
        self.assertEqual(self.plan, original)


if __name__ == "__main__":
    unittest.main()

"""Behavioral tests; all remote observations are supplied in memory."""

import copy
import hashlib
import json
import subprocess
import unittest

from nas_storage import inspect_node_storage, nas_ready, storage_blockers


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


def _iscsi_block(target, sid, portal="10.0.16.16:3260,1", conn="IN LOGIN", sess="FREE", disks=()):
    lines = [
        f"Target: {target} (non-flash)",
        f"\tCurrent Portal: {portal}",
        f"\tPersistent Portal: {portal}",
        f"\t\tSID: {sid}",
        f"\t\tiSCSI Connection State: {conn}",
        f"\t\tiSCSI Session State: {sess}",
    ]
    for disk, state in disks:
        lines.append(f"\t\t\tAttached scsi disk {disk}\t\tState: {state}")
    return "\n".join(lines) + "\n"


def _csi_pod(name, node):
    return {
        "metadata": {"name": name, "namespace": "synology-csi", "labels": {"app": "synology-csi-node"}},
        "spec": {"nodeName": node},
        "status": {"phase": "Running"},
    }


def _pv(name, handle, claim_ns="default", claim_name="app-data"):
    return {
        "metadata": {"name": name},
        "spec": {
            "claimRef": {"namespace": claim_ns, "name": claim_name},
            "csi": {"driver": "csi.san.synology.com", "volumeHandle": handle},
        },
    }


class InspectNodeStorageTests(unittest.TestCase):
    def setUp(self):
        self.plan = copy.deepcopy(PLAN)
        self.sessions = {"10.0.16.133": ".\n", "10.0.16.135": ".\n"}
        self.node_mounts = {"10.0.16.133": ROOT, "10.0.16.135": ROOT}
        self.vol_data = {}
        self.iscsi_out = {"synology-csi-node-hp1": "", "synology-csi-node-hp2": ""}
        self.resources = {
            "persistentvolumes": [],
            "volumeattachments": [],
            "pods": [_csi_pod("synology-csi-node-hp1", "hp1"), _csi_pod("synology-csi-node-hp2", "hp2")],
        }

    def run_cmd(self, argv):
        self.assertEqual(argv[0], "talosctl")
        address = argv[argv.index("-n") + 1]
        if argv[-2:] == ["ls", "/sys/class/iscsi_session"]:
            result = self.sessions[address]
        elif argv[-2:] == ["read", "/proc/mounts"]:
            result = self.node_mounts[address]
        elif argv[-2] == "read" and argv[-1].endswith("/vol_data.json"):
            result = self.vol_data[argv[-1]]
        else:
            raise AssertionError(f"unexpected command: {argv}")
        if isinstance(result, Exception):
            raise result
        return result

    def kube_cmd(self, *args):
        pod = args[args.index("exec") + 1]
        result = self.iscsi_out[pod]
        if isinstance(result, Exception):
            raise result
        return result

    def test_classifies_orphaned_globalmounts_and_dead_sessions_without_matching_pv(self):
        orphan_handle = "8aa4d1fa-d0ef-4fa8-8f91-6cabb44330fc"
        orphan_hash = hashlib.sha256(orphan_handle.encode()).hexdigest()
        mount_dir = f"/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/{orphan_hash}"
        self.node_mounts["10.0.16.133"] += f"/dev/sdah {mount_dir}/globalmount ext4 rw,relatime,shutdown 0 0\n"
        self.vol_data[f"{mount_dir}/vol_data.json"] = json.dumps({
            "driverName": "csi.san.synology.com", "volumeHandle": orphan_handle,
        })
        self.sessions["10.0.16.133"] = ".\nsession30\n"
        self.iscsi_out["synology-csi-node-hp1"] = _iscsi_block(
            "iqn.2000-01.com.synology:brian.pvc-c99fb3fa-8965-4757-90a8-27ec9d8440f2",
            "30", disks=[("sdab", "transport-offline")],
        )
        result = inspect_node_storage(self.plan, self.resources, self.run_cmd, self.kube_cmd)
        self.assertEqual(len(result["orphan_mounts"]), 1)
        self.assertEqual(result["orphan_mounts"][0]["volume_handle"], orphan_handle)
        self.assertEqual(result["orphan_mounts"][0]["pod"], "synology-csi-node-hp1")
        self.assertEqual(len(result["orphan_sessions"]), 1)
        self.assertEqual(result["orphan_sessions"][0]["sid"], "30")
        self.assertTrue(result["orphan_sessions"][0]["unmounted"])
        self.assertEqual(result["warnings"], [])

    def test_live_pv_mounts_and_sessions_are_never_classified_as_orphans(self):
        live_handle = "a1709615-06ab-44c5-839f-cdd6f6f26304"
        live_hash = hashlib.sha256(live_handle.encode()).hexdigest()
        pv_name = "pvc-11111111-2222-3333-4444-555555555555"
        self.resources["persistentvolumes"] = [_pv(pv_name, live_handle, "default", "actual")]
        mount_dir = f"/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/{live_hash}"
        self.node_mounts["10.0.16.133"] += f"/dev/sdb {mount_dir}/globalmount ext4 rw,relatime 0 0\n"
        self.sessions["10.0.16.133"] = ".\nsession12\n"
        self.iscsi_out["synology-csi-node-hp1"] = _iscsi_block(
            f"iqn.2000-01.com.synology:brian.{pv_name}",
            "12", conn="LOGGED IN", sess="LOGGED_IN", disks=[("sdb", "running")],
        )
        result = inspect_node_storage(self.plan, self.resources, self.run_cmd, self.kube_cmd)
        self.assertEqual(result["orphan_mounts"], [])
        self.assertEqual(result["orphan_sessions"], [])
        self.assertTrue(any(pv_name in b and "default/actual" in b for b in result["blockers"]))
        self.assertTrue(any("session12" in b and "default/actual" in b for b in result["blockers"]))

    def test_coupled_orphan_mount_and_session_marks_session_mounted_until_unmounted(self):
        orphan_handle = "6449b3d1-3699-40ab-b37f-612deb71f746"
        orphan_hash = hashlib.sha256(orphan_handle.encode()).hexdigest()
        mount_dir = f"/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/{orphan_hash}"
        self.node_mounts["10.0.16.133"] += f"/dev/sdab {mount_dir}/globalmount ext4 rw,relatime 0 0\n"
        self.vol_data[f"{mount_dir}/vol_data.json"] = json.dumps({
            "driverName": "csi.san.synology.com", "volumeHandle": orphan_handle,
        })
        self.sessions["10.0.16.133"] = ".\nsession30\n"
        self.iscsi_out["synology-csi-node-hp1"] = _iscsi_block(
            "iqn.2000-01.com.synology:brian.pvc-c99fb3fa-8965-4757-90a8-27ec9d8440f2",
            "30", disks=[("sdab", "running")],
        )
        result = inspect_node_storage(self.plan, self.resources, self.run_cmd, self.kube_cmd)
        self.assertEqual(len(result["orphan_mounts"]), 1)
        self.assertEqual(len(result["orphan_sessions"]), 1)
        self.assertFalse(result["orphan_sessions"][0]["unmounted"])

    def test_shared_device_or_pod_mount_prevents_orphan_classification(self):
        orphan_handle = "6449b3d1-3699-40ab-b37f-612deb71f746"
        orphan_hash = hashlib.sha256(orphan_handle.encode()).hexdigest()
        mount_dir = f"/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/{orphan_hash}"
        self.node_mounts["10.0.16.133"] += (
            f"/dev/sdab {mount_dir}/globalmount ext4 rw,relatime 0 0\n"
            "/dev/sdab /var/lib/kubelet/pods/pod1/volumes/kubernetes.io~csi/pvc-data/mount ext4 rw,relatime 0 0\n"
        )
        self.vol_data[f"{mount_dir}/vol_data.json"] = json.dumps({
            "driverName": "csi.san.synology.com", "volumeHandle": orphan_handle,
        })
        self.sessions["10.0.16.133"] = ".\nsession30\n"
        self.iscsi_out["synology-csi-node-hp1"] = _iscsi_block(
            "iqn.2000-01.com.synology:brian.pvc-c99fb3fa-8965-4757-90a8-27ec9d8440f2",
            "30", disks=[("sdab", "running")],
        )
        result = inspect_node_storage(self.plan, self.resources, self.run_cmd, self.kube_cmd)
        self.assertEqual(result["orphan_mounts"], [])
        self.assertEqual(result["orphan_sessions"], [])
        self.assertTrue(any("shared by 2 mounts" in b for b in result["blockers"]))
        self.assertTrue(any("disk still mounted" in b for b in result["blockers"]))

    def test_volume_attachment_non_pvc_target_foreign_portal_and_bad_vol_data_fail_closed(self):
        orphan_handle = "8aa4d1fa-d0ef-4fa8-8f91-6cabb44330fc"
        orphan_hash = hashlib.sha256(orphan_handle.encode()).hexdigest()
        mount_dir = f"/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/{orphan_hash}"
        self.node_mounts["10.0.16.133"] += f"/dev/sdah {mount_dir}/globalmount ext4 rw,relatime 0 0\n"
        self.vol_data[f"{mount_dir}/vol_data.json"] = json.dumps({
            "driverName": "csi.san.synology.com", "volumeHandle": "wrong-handle",
        })
        self.resources["volumeattachments"] = [{
            "metadata": {"name": "csi-va-1"},
            "spec": {"attacher": "csi.san.synology.com", "source": {"persistentVolumeName": "pvc-aaaaaaaa-1111"}},
        }]
        self.sessions["10.0.16.133"] = ".\nsession1\nsession2\nsession3\n"
        self.iscsi_out["synology-csi-node-hp1"] = (
            _iscsi_block("iqn.2000-01.com.synology:brian.pvc-aaaaaaaa-1111", "1")
            + _iscsi_block("iqn.2000-01.com.synology:brian.manual-lun", "2")
            + _iscsi_block("iqn.2000-01.com.synology:brian.pvc-bbbbbbbb-2222", "3", portal="10.0.16.99:3260,1")
        )
        result = inspect_node_storage(self.plan, self.resources, self.run_cmd, self.kube_cmd)
        self.assertEqual(result["orphan_mounts"], [])
        self.assertEqual(result["orphan_sessions"], [])
        self.assertTrue(any("hash does not match" in w for w in result["warnings"]))
        self.assertEqual(len(result["blockers"]), 4)

    def test_missing_csi_node_pod_or_truncated_iscsiadm_output_fails_closed(self):
        self.sessions["10.0.16.133"] = ".\nsession30\n"
        self.resources["pods"] = []
        result = inspect_node_storage(self.plan, self.resources, self.run_cmd, self.kube_cmd)
        self.assertEqual(result["orphan_sessions"], [])
        self.assertTrue(any("no running synology-csi-node pod" in w for w in result["warnings"]))

        self.resources["pods"] = [_csi_pod("synology-csi-node-hp1", "hp1")]
        self.iscsi_out["synology-csi-node-hp1"] = "Target: iqn.2000-01.com.synology:brian.pvc-c99fb3fa\n"
        result = inspect_node_storage(self.plan, self.resources, self.run_cmd, self.kube_cmd)
        self.assertEqual(result["orphan_sessions"], [])
        self.assertTrue(any("cannot inspect via iscsiadm" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()

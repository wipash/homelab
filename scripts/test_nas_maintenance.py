"""Safety invariants for maintenance transitions, using an in-memory API adapter."""

import copy
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import nas_maintenance as maintenance


def controller(name, resource="deployments.apps", role="workload", replicas=1, selector=None):
    return {"resource": resource, "namespace": "test", "name": name, "uid": name,
            "role": role, "replicas": replicas if resource != "daemonsets.apps" else None,
            "nodeSelector": selector}


def state_for(records):
    return {"version": 1, "cluster_uid": "cluster", "context": "test", "phase": "pausing", "marker": "unique-marker",
            "plan": {"controllers": records, "cronjobs": [
                {"resource": "cronjobs.batch", "namespace": "test", "name": "enabled", "uid": "enabled", "suspend": None},
                {"resource": "cronjobs.batch", "namespace": "test", "name": "disabled", "uid": "disabled", "suspend": True},
            ], "flux_instances": [{"resource": "fluxinstances.fluxcd.controlplane.io", "namespace": "test", "name": "flux", "uid": "flux", "annotation": None}],
            "nas_hosts": ["10.0.16.16"], "nodes": [], "volumes": ["/volume3"], "nas_claims": [], "warnings": []}}


class MemoryCluster:
    """Models API object identity, JSON patches and controller-observed readiness."""

    def __init__(self, state):
        self.objects = {}
        self.saved = copy.deepcopy(state)
        self.patches = []
        self.deleted_state = False
        self.fail_name = None
        self.extra_pods = []
        self.extra_replicasets = []
        self.extra_jobs = []
        self.extra_pvs = []
        self.extra_volumeattachments = []
        self.exec_handler = None
        self.exec_calls = []
        for record in state["plan"]["controllers"]:
            spec = {"template": {"spec": {}}}
            if record["nodeSelector"] is not None:
                spec["template"]["spec"]["nodeSelector"] = copy.deepcopy(record["nodeSelector"])
            if record["replicas"] is not None:
                spec["replicas"] = record["replicas"]
            self.add(record, spec)
        for record in state["plan"]["cronjobs"]:
            self.add(record, {} if record["suspend"] is None else {"suspend": record["suspend"]})
        for record in state["plan"]["flux_instances"]:
            self.add(record, {})
            obj = self.objects[self.key(record)]
            obj["metadata"]["annotations"] = {"unrelated": "preserve-me"}
            if record["annotation"] is not None:
                obj["metadata"]["annotations"][maintenance.RECONCILE] = record["annotation"]

    @staticmethod
    def key(record):
        return record["resource"], record["namespace"], record["name"]

    def add(self, record, spec):
        self.objects[self.key(record)] = {
            "metadata": {"uid": record["uid"], "namespace": record["namespace"], "name": record["name"], "generation": 1},
            "spec": spec, "status": {"observedGeneration": 1, "readyReplicas": spec.get("replicas", 0),
                                     "desiredNumberScheduled": 2, "numberReady": 2, "updatedNumberScheduled": 2},
        }

    def get(self, resource, namespace, name, **kwargs):
        return copy.deepcopy(self.objects[(resource, namespace, name)])

    def patch(self, record, operations):
        if record["name"] == self.fail_name:
            raise RuntimeError("simulated API failure")
        obj = self.objects[self.key(record)]
        if obj["metadata"]["uid"] != record["uid"]:
            raise RuntimeError("replaced object")
        for op in operations(copy.deepcopy(obj)):
            self.patches.append((record["name"], copy.deepcopy(op)))
            path = [p.replace("~1", "/").replace("~0", "~") for p in op["path"].strip("/").split("/")]
            parent = obj
            for key in path[:-1]:
                parent = parent[key]
            if op["op"] == "remove":
                del parent[path[-1]]
            else:
                parent[path[-1]] = copy.deepcopy(op["value"])
            obj["metadata"]["generation"] += 1
            obj["status"]["observedGeneration"] = obj["metadata"]["generation"]
            if "replicas" in obj["spec"]:
                obj["status"]["readyReplicas"] = obj["spec"]["replicas"]

    def snapshot(self):
        resources = {key: [] for key in maintenance.RESOURCE_KINDS.values()}
        resources["pods"] = copy.deepcopy(self.extra_pods)
        resources["replicasets"] = copy.deepcopy(self.extra_replicasets)
        resources["jobs"] = copy.deepcopy(self.extra_jobs)
        resources["persistentvolumes"] = copy.deepcopy(self.extra_pvs)
        resources["volumeattachments"] = copy.deepcopy(self.extra_volumeattachments)
        return resources

    def save_state(self, state):
        self.saved = copy.deepcopy(state)

    def command(self, *args, **kwargs):
        if args[0] == "delete" and args[1] == "configmap":
            self.deleted_state = True
            return ""
        if self.exec_handler is not None and "exec" in args:
            self.exec_calls.append(args)
            return self.exec_handler(args)
        raise AssertionError(f"Unexpected destructive operation: {args}")


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.records = [controller("gitops", role="gitops"), controller("operator", role="operator"),
                        controller("backups", role="backup", replicas=2), controller("app", replicas=3),
                        controller("already-stopped", replicas=0), controller("database", "statefulsets.apps", replicas=2),
                        controller("importer", "daemonsets.apps", selector={"hardware": "cd-reader"})]
        self.state = state_for(self.records)
        self.cluster = MemoryCluster(self.state)
        self.storage = patch.object(maintenance, "storage_blockers", return_value=[])
        self.readiness = patch.object(maintenance, "nas_ready", return_value=[])
        self.storage.start()
        self.readiness.start()
        self.addCleanup(self.storage.stop)
        self.addCleanup(self.readiness.stop)

    def test_pause_resume_restores_original_counts_selectors_and_scheduling(self):
        original = {key: copy.deepcopy(obj["spec"]) for key, obj in self.cluster.objects.items()}
        maintenance.pause(self.cluster, self.state, timeout=1)
        self.assertEqual(self.cluster.saved["phase"], "paused")
        for record in self.records:
            obj = self.cluster.get(record["resource"], "test", record["name"])
            if record["replicas"] is not None:
                self.assertEqual(obj["spec"]["replicas"], 0)
            else:
                self.assertEqual(obj["spec"]["template"]["spec"]["nodeSelector"], {"hardware": "cd-reader", maintenance.SELECTOR: "unique-marker"})
        maintenance.resume(self.cluster, self.state, timeout=1)
        self.assertEqual({key: obj["spec"] for key, obj in self.cluster.objects.items()}, original)
        self.assertEqual(self.cluster.get("fluxinstances.fluxcd.controlplane.io", "test", "flux")["metadata"]["annotations"], {"unrelated": "preserve-me"})
        self.assertTrue(self.cluster.deleted_state)

    def test_partial_pause_can_be_repeated_without_losing_saved_originals(self):
        self.cluster.fail_name = "app"
        with self.assertRaisesRegex(RuntimeError, "simulated API failure"):
            maintenance.pause(self.cluster, self.state, timeout=1)
        self.assertEqual(self.cluster.saved["phase"], "pausing")
        self.assertFalse(self.cluster.deleted_state)
        self.cluster.fail_name = None
        maintenance.pause(self.cluster, self.state, timeout=1)
        maintenance.pause(self.cluster, self.state, timeout=1)
        maintenance.resume(self.cluster, self.state, timeout=1)
        self.assertEqual(self.cluster.get("deployments.apps", "test", "app")["spec"]["replicas"], 3)
        self.assertEqual(self.cluster.get("deployments.apps", "test", "already-stopped")["spec"]["replicas"], 0)

    def test_failed_storage_cleanup_never_reports_paused_and_remains_recoverable(self):
        with patch.object(maintenance, "storage_blockers", return_value=["hp1 still has an iSCSI session"]):
            with self.assertRaisesRegex(RuntimeError, "iSCSI session"):
                maintenance.pause(self.cluster, self.state, timeout=0)
        self.assertEqual(self.cluster.saved["phase"], "pausing")
        self.assertFalse(self.cluster.deleted_state)
        maintenance.resume(self.cluster, self.state, timeout=1)
        self.assertEqual(self.cluster.get("deployments.apps", "test", "app")["spec"]["replicas"], 3)

    def test_job_without_pod_blocks_shutdown_before_apps_stop(self):
        self.cluster.extra_jobs = [{
            "metadata": {"name": "backup-run", "namespace": "test", "uid": "backup-run"},
            "spec": {"template": {"spec": {"volumes": [{
                "name": "nas", "nfs": {"server": "10.0.16.16", "path": "/volume1/Media"},
            }]}}},
        }]
        with self.assertRaisesRegex(RuntimeError, "backup-run"):
            maintenance.pause(self.cluster, self.state, timeout=0)
        self.assertEqual(self.cluster.get("deployments.apps", "test", "app")["spec"]["replicas"], 3)
        self.assertEqual(self.cluster.saved["phase"], "pausing")
        self.cluster.extra_jobs[0]["status"] = {"conditions": [{"type": "Complete", "status": "True"}]}
        maintenance.pause(self.cluster, self.state, timeout=1)
        self.assertEqual(self.cluster.saved["phase"], "paused")

    def test_cronjob_with_indirect_host_storage_access_must_finish_too(self):
        self.cluster.extra_jobs = [{
            "metadata": {"name": "fstrim-run", "namespace": "test", "uid": "fstrim-run",
                         "ownerReferences": [{"kind": "CronJob", "uid": "enabled", "controller": True}]},
            "spec": {"template": {"spec": {"volumes": [{"name": "host", "hostPath": {"path": "/"}}]}}},
        }]
        with self.assertRaisesRegex(RuntimeError, "fstrim-run"):
            maintenance.pause(self.cluster, self.state, timeout=0)
        self.assertEqual(self.cluster.get("deployments.apps", "test", "app")["spec"]["replicas"], 3)
        self.assertFalse(self.cluster.deleted_state)

    def test_offline_nas_does_not_restart_workloads_or_discard_state(self):
        maintenance.pause(self.cluster, self.state, timeout=1)
        before = copy.deepcopy(self.cluster.objects)
        with patch.object(maintenance, "nas_ready", return_value=["/volume3 is read-only"]):
            with self.assertRaisesRegex(RuntimeError, "read-only"):
                maintenance.resume(self.cluster, self.state, timeout=0)
        self.assertEqual(self.cluster.objects, before)
        self.assertEqual(self.cluster.saved["phase"], "paused")
        self.assertFalse(self.cluster.deleted_state)

    def test_replaced_workload_blocks_resume_before_any_original_object_is_changed(self):
        maintenance.pause(self.cluster, self.state, timeout=1)
        self.cluster.objects[("deployments.apps", "test", "app")]["metadata"]["uid"] = "replacement"
        before = copy.deepcopy(self.cluster.objects)
        with self.assertRaisesRegex(RuntimeError, "replaced"):
            maintenance.resume(self.cluster, self.state, timeout=1)
        self.assertEqual(self.cluster.objects, before)
        self.assertFalse(self.cluster.deleted_state)

    def test_stateful_dependencies_start_before_apps_and_reconcilers_start_last(self):
        maintenance.pause(self.cluster, self.state, timeout=1)
        self.cluster.patches.clear()
        maintenance.resume(self.cluster, self.state, timeout=1)
        starts = [name for name, op in self.cluster.patches if op["path"] == "/spec/replicas" and op.get("value", 0) > 0]
        self.assertLess(starts.index("database"), starts.index("app"))
        self.assertLess(starts.index("app"), starts.index("operator"))
        self.assertLess(starts.index("operator"), starts.index("backups"))
        self.assertLess(starts.index("backups"), starts.index("gitops"))

    def test_resume_failure_retains_state_and_can_be_retried(self):
        maintenance.pause(self.cluster, self.state, timeout=1)
        self.cluster.fail_name = "app"
        with self.assertRaisesRegex(RuntimeError, "simulated API failure"):
            maintenance.resume(self.cluster, self.state, timeout=1)
        self.assertEqual(self.cluster.saved["phase"], "resuming")
        self.assertFalse(self.cluster.deleted_state)
        with self.assertRaisesRegex(RuntimeError, "finish cluster:resume"):
            maintenance.pause(self.cluster, self.state, timeout=1)
        self.cluster.fail_name = None
        maintenance.resume(self.cluster, self.state, timeout=1)
        self.assertEqual(self.cluster.get("deployments.apps", "test", "app")["spec"]["replicas"], 3)
        self.assertTrue(self.cluster.deleted_state)

    def test_pause_auto_cleans_orphaned_mounts_then_sessions_and_reaches_paused(self):
        self.storage.stop()
        mount_a = "/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/" + "a" * 64 + "/globalmount"
        mount_b = "/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/" + "b" * 64 + "/globalmount"
        remaining_mounts = [mount_a, mount_b]
        remaining_sessions = ["30", "66"]
        actions = []

        def fake_exec(args):
            if "umount" in args:
                target = args[-1]
                actions.append(("umount", target))
                remaining_mounts.remove(target)
                return ""
            if "/usr/local/sbin/iscsiadm" in args and "-u" in args:
                sid = args[args.index("-r") + 1]
                actions.append(("logout", sid))
                remaining_sessions.remove(sid)
                return ""
            raise AssertionError(f"unexpected exec: {args}")

        self.cluster.exec_handler = fake_exec

        def fake_blockers(_plan, _run):
            out = [f"hp1: mount {m}" for m in remaining_mounts]
            if remaining_sessions:
                out.append(f"hp1: {len(remaining_sessions)} iSCSI session(s) remain")
            return out

        def fake_inspect(_plan, _resources, _run, _kube):
            return {
                "blockers": fake_blockers(_plan, _run),
                "orphan_mounts": [
                    {"node": "hp1", "address": "10.0.16.133", "pod": "synology-csi-node-hp1",
                     "target": m, "source": "/dev/sdab", "volume_handle": "h", "description": f"hp1: orphan {m}"}
                    for m in remaining_mounts
                ],
                "orphan_sessions": [
                    {"node": "hp1", "address": "10.0.16.133", "pod": "synology-csi-node-hp1",
                     "sid": sid, "target": f"iqn.test.{sid}", "pv_name": f"pvc-{sid}",
                     "state": "FREE/IN LOGIN",
                     # session 66 is backed by mount_b until mount_b is unmounted
                     "unmounted": sid != "66" or mount_b not in remaining_mounts,
                     "description": f"hp1: orphan session{sid}"}
                    for sid in remaining_sessions
                ],
                "warnings": [],
            }

        with (
            patch.object(maintenance, "storage_blockers", side_effect=fake_blockers),
            patch.object(maintenance, "inspect_node_storage", side_effect=fake_inspect),
        ):
            maintenance.pause(self.cluster, self.state, timeout=1, orphan_stall_seconds=0)

        self.assertEqual(self.cluster.saved["phase"], "paused")
        self.assertEqual(actions, [
            ("umount", mount_a),
            ("umount", mount_b),
            ("logout", "30"),
            ("logout", "66"),
        ])

    def test_pause_waits_for_volume_attachments_before_cleaning_orphans(self):
        self.storage.stop()
        self.cluster.extra_volumeattachments = [{
            "metadata": {"name": "csi-va-active"},
            "spec": {"attacher": "csi.san.synology.com", "source": {"persistentVolumeName": "pvc-live"}},
        }]
        self.cluster.exec_handler = lambda args: (_ for _ in ()).throw(AssertionError(f"should not exec: {args}"))
        with (
            patch.object(maintenance, "storage_blockers", return_value=["hp1: 1 iSCSI session(s) remain"]),
            patch.object(maintenance, "inspect_node_storage") as inspect_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "VolumeAttachment csi-va-active"):
                maintenance.pause(self.cluster, self.state, timeout=0, orphan_stall_seconds=0)
        inspect_mock.assert_not_called()
        self.assertEqual(self.cluster.saved["phase"], "pausing")

    def test_pause_never_cleans_live_pv_blockers_and_surfaces_detailed_blocker(self):
        self.storage.stop()
        detailed = "hp1: iSCSI session12 remains for pvc-live (default/actual) (iqn.test, state=LOGGED_IN/LOGGED IN)"
        with (
            patch.object(maintenance, "storage_blockers", return_value=["hp1: 1 iSCSI session(s) remain"]),
            patch.object(maintenance, "inspect_node_storage", return_value={
                "blockers": [detailed], "orphan_mounts": [], "orphan_sessions": [], "warnings": [],
            }),
        ):
            with self.assertRaisesRegex(RuntimeError, "default/actual"):
                maintenance.pause(self.cluster, self.state, timeout=0, orphan_stall_seconds=0)
        self.assertEqual(self.cluster.exec_calls, [])
        self.assertEqual(self.cluster.saved["phase"], "pausing")

    def test_pause_cleanup_failure_fails_closed_without_marking_paused(self):
        self.storage.stop()
        mount_a = "/var/lib/kubelet/plugins/kubernetes.io/csi/csi.san.synology.com/" + "a" * 64 + "/globalmount"
        self.cluster.exec_handler = lambda args: (_ for _ in ()).throw(RuntimeError("target is busy"))
        with (
            patch.object(maintenance, "storage_blockers", return_value=[f"hp1: Synology CSI mount remains at {mount_a}"]),
            patch.object(maintenance, "inspect_node_storage", return_value={
                "blockers": [f"hp1: orphaned Synology CSI globalmount {mount_a}"],
                "orphan_mounts": [{
                    "node": "hp1", "address": "10.0.16.133", "pod": "synology-csi-node-hp1",
                    "target": mount_a, "source": "/dev/sdc", "volume_handle": "h",
                    "description": f"hp1: orphaned {mount_a}",
                }],
                "orphan_sessions": [],
                "warnings": [],
            }),
        ):
            with self.assertRaisesRegex(RuntimeError, "target is busy"):
                maintenance.pause(self.cluster, self.state, timeout=0, orphan_stall_seconds=0)
        self.assertEqual(len(self.cluster.exec_calls), 1)
        self.assertEqual(self.cluster.saved["phase"], "pausing")

    def test_pause_dry_run_reports_orphans_without_mutating(self):
        fake_cluster = self.cluster
        fake_cluster.state = lambda: None
        fake_cluster.create_state = lambda state: (_ for _ in ()).throw(AssertionError("dry-run created state"))
        orig_get = fake_cluster.get
        fake_cluster.get = lambda resource, ns, name, **kw: (
            {"metadata": {"uid": "cluster"}} if (resource, ns, name) == ("namespaces", "kube-system", "kube-system")
            else orig_get(resource, ns, name, **kw)
        )
        stdout = io.StringIO()
        with (
            patch.object(maintenance, "Cluster", return_value=fake_cluster),
            patch.object(maintenance, "run", return_value="test-context\n"),
            patch.object(maintenance, "build_plan", return_value=self.state["plan"]),
            patch.object(maintenance, "inspect_node_storage", return_value={
                "blockers": ["hp1: orphaned iSCSI session30 (no matching PV)"],
                "orphan_mounts": [],
                "orphan_sessions": [{"description": "hp1: orphaned iSCSI session30 (no matching PV)"}],
                "warnings": [],
            }),
            redirect_stdout(stdout),
        ):
            rc = maintenance.main(["pause", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("Orphaned NAS storage detected", stdout.getvalue())
        self.assertIn("session30", stdout.getvalue())
        self.assertEqual(fake_cluster.exec_calls, [])

    def test_resume_limits_concurrent_workload_restores_and_slides_window(self):
        records = [
            controller("gitops", role="gitops"),
            controller("app-1", replicas=1),
            controller("zero-app", replicas=0),
            controller("app-2", replicas=1),
            controller("app-3", replicas=1),
            controller("app-4", replicas=1),
            controller("app-5", replicas=1),
        ]
        state = state_for(records)
        cluster = MemoryCluster(state)
        maintenance.pause(cluster, state, timeout=1)

        # Simulate delayed readiness so we can observe the bounded concurrency window.
        polls_until_ready = {"app-1": 3, "app-2": 1, "app-3": 1, "app-4": 1, "app-5": 1}
        in_flight_active = set()
        max_concurrent = 0
        orig_patch = cluster.patch
        orig_get = cluster.get

        def delayed_patch(record, operations):
            nonlocal max_concurrent
            orig_patch(record, operations)
            name = record["name"]
            if name in polls_until_ready:
                obj = cluster.objects[cluster.key(record)]
                if obj["spec"].get("replicas", 0) > 0:
                    obj["status"]["readyReplicas"] = 0
                    in_flight_active.add(name)
                    max_concurrent = max(max_concurrent, len(in_flight_active))

        def stepping_get(resource, namespace, name, **kwargs):
            obj = orig_get(resource, namespace, name, **kwargs)
            return obj

        def fake_sleep(_seconds):
            for name in list(in_flight_active):
                polls_until_ready[name] -= 1
                if polls_until_ready[name] <= 0:
                    cluster.objects[("deployments.apps", "test", name)]["status"]["readyReplicas"] = 1
                    in_flight_active.remove(name)

        cluster.patch = delayed_patch
        cluster.get = stepping_get
        with patch.object(maintenance.time, "sleep", side_effect=fake_sleep):
            maintenance.resume(cluster, state, timeout=10, batch_size=2)

        self.assertEqual(max_concurrent, 2)
        self.assertTrue(cluster.deleted_state)
        for name in ("app-1", "app-2", "app-3", "app-4", "app-5"):
            self.assertEqual(cluster.objects[("deployments.apps", "test", name)]["spec"]["replicas"], 1)
        self.assertEqual(cluster.objects[("deployments.apps", "test", "zero-app")]["spec"]["replicas"], 0)

    def test_resume_advances_on_volume_mount_before_slow_readiness_and_enforces_tier_barrier(self):
        records = [
            controller("gitops", role="gitops"),
            controller("slow-app", replicas=1),
            controller("init-crash", replicas=1),
            controller("fast-app", replicas=1),
        ]
        state = state_for(records)
        cluster = MemoryCluster(state)
        maintenance.pause(cluster, state, timeout=1)

        cluster.extra_replicasets = [
            {"metadata": {"name": f"{name}-rs", "namespace": "test", "uid": f"{name}-rs",
                          "ownerReferences": [{"kind": "Deployment", "uid": name, "controller": True}]}}
            for name in ("slow-app", "init-crash", "fast-app")
        ]
        orig_patch = cluster.patch
        started = []
        tick = 0

        def tracking_patch(record, operations):
            orig_patch(record, operations)
            name = record["name"]
            if name in ("slow-app", "init-crash", "fast-app"):
                obj = cluster.objects[cluster.key(record)]
                if obj["spec"].get("replicas", 0) > 0:
                    obj["status"]["readyReplicas"] = 0
                    started.append(name)

        def fake_sleep(_seconds):
            nonlocal tick
            tick += 1
            if tick == 1:
                # slow-app mounted (Running, still not Ready); init-crash mounted (initContainer crashlooping).
                cluster.extra_pods = [
                    {"metadata": {"name": "slow-app-pod", "namespace": "test",
                                  "ownerReferences": [{"kind": "ReplicaSet", "uid": "slow-app-rs", "controller": True}]},
                     "status": {"phase": "Running", "containerStatuses": [{"state": {"running": {}}}]}},
                    {"metadata": {"name": "init-crash-pod", "namespace": "test",
                                  "ownerReferences": [{"kind": "ReplicaSet", "uid": "init-crash-rs", "controller": True}]},
                     "status": {"phase": "Pending", "initContainerStatuses": [{
                         "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                         "lastState": {"terminated": {"exitCode": 1}},
                         "restartCount": 1,
                     }]}},
                ]
            elif tick == 2:
                # fast-app should already have been started while slow-app & init-crash are still ready=0.
                self.assertIn("fast-app", started)
                # Gitops must NOT have started yet because the tier barrier waits for full readiness.
                self.assertEqual(cluster.objects[("deployments.apps", "test", "gitops")]["spec"]["replicas"], 0)
                for name in ("slow-app", "init-crash", "fast-app"):
                    cluster.objects[("deployments.apps", "test", name)]["status"]["readyReplicas"] = 1

        cluster.patch = tracking_patch
        with patch.object(maintenance.time, "sleep", side_effect=fake_sleep):
            maintenance.resume(cluster, state, timeout=10, batch_size=2)

        self.assertEqual(started, ["slow-app", "init-crash", "fast-app"])
        self.assertEqual(cluster.objects[("deployments.apps", "test", "gitops")]["spec"]["replicas"], 1)
        self.assertTrue(cluster.deleted_state)

    def test_mount_blockers_ignore_stale_failed_and_terminating_pods_and_handle_daemonsets(self):
        dep = controller("app", replicas=1)
        ds = controller("importer", resource="daemonsets.apps", selector={"hardware": "cd-reader"})
        state = state_for([controller("gitops", role="gitops"), dep, ds])
        cluster = MemoryCluster(state)
        cluster.objects[cluster.key(dep)]["status"]["readyReplicas"] = 0
        cluster.objects[cluster.key(ds)]["status"]["numberReady"] = 0
        rs = {"metadata": {"name": "app-rs", "namespace": "test", "uid": "app-rs",
                           "ownerReferences": [{"kind": "Deployment", "uid": "app", "controller": True}]}}
        resources = {
            "replicasets": [rs],
            "pods": [
                # Stale Failed pod and terminating Running pod must not count as mounted.
                {"metadata": {"name": "app-old-failed", "namespace": "test",
                              "ownerReferences": [{"kind": "ReplicaSet", "uid": "app-rs", "controller": True}]},
                 "status": {"phase": "Failed", "containerStatuses": [{"state": {"terminated": {"exitCode": 1}}}]}},
                {"metadata": {"name": "app-terminating", "namespace": "test", "deletionTimestamp": "2026-11-23T00:00:00Z",
                              "ownerReferences": [{"kind": "ReplicaSet", "uid": "app-rs", "controller": True}]},
                 "status": {"phase": "Running", "containerStatuses": [{"state": {"running": {}}}]}},
                # Live new pod still mounting volumes.
                {"metadata": {"name": "app-new", "namespace": "test",
                              "ownerReferences": [{"kind": "ReplicaSet", "uid": "app-rs", "controller": True}]},
                 "status": {"phase": "Pending", "containerStatuses": [{"state": {"waiting": {"reason": "ContainerCreating"}}}]}},
            ],
        }
        dep_blockers = maintenance.mount_blockers(cluster, dep, resources)
        self.assertEqual(dep_blockers, ["test/deployments/app waiting for volume mount (0/1 pods started)"])
        ds_blockers = maintenance.mount_blockers(cluster, ds, resources)
        self.assertEqual(ds_blockers, ["test/daemonsets/importer ready 0/2, updated 2"])


if __name__ == "__main__":
    unittest.main()

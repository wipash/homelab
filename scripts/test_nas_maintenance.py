"""Safety invariants for maintenance transitions, using an in-memory API adapter."""

import copy
import unittest
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
        self.extra_jobs = []
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
        resources["jobs"] = copy.deepcopy(self.extra_jobs)
        return resources

    def save_state(self, state):
        self.saved = copy.deepcopy(state)

    def command(self, *args, **kwargs):
        if args[0] == "delete" and args[1] == "configmap":
            self.deleted_state = True
        else:
            raise AssertionError(f"Unexpected destructive operation: {args}")
        return ""


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


if __name__ == "__main__":
    unittest.main()

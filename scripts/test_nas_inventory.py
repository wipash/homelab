"""Inventory invariants; these tests never contact Kubernetes or the NAS."""

import copy
import unittest

from nas_inventory import build_plan, nas_jobs, nas_pods


HOSTS = {"10.0.16.16", "brian.sk.mcgrath.nz"}


def obj(kind, name, namespace="apps", spec=None, owner=None):
    result = {"kind": kind, "metadata": {"name": name, "namespace": namespace,
                                        "uid": namespace + "/" + name}, "spec": spec or {}}
    if owner:
        result["metadata"]["ownerReferences"] = [owner]
    return result


def owner(kind, name, api="apps/v1"):
    return {"kind": kind, "name": name, "apiVersion": api, "controller": True}


def template(volumes):
    return {"template": {"spec": {"volumes": volumes}}}


def pvc_volume(name):
    return {"name": "data", "persistentVolumeClaim": {"claimName": name}}


def nfs_volume():
    return {"name": "media", "nfs": {"server": "brian.sk.mcgrath.nz", "path": "/volume1/Media"}}


def snapshot():
    return {
        "deployments": [obj("Deployment", name, "flux-system", {"replicas": 1})
                        for name in ("flux-operator", "kustomize-controller", "helm-controller")],
        "storageclasses": [
            {"metadata": {"name": "nas", "annotations": {"storageclass.kubernetes.io/is-default-class": "true"}},
             "provisioner": "csi.san.synology.com", "parameters": {"dsm": "10.0.16.16", "location": "/volume3", "protocol": "iscsi"}},
            {"metadata": {"name": "local"}, "provisioner": "openebs.io/local"},
        ],
        "persistentvolumes": [], "persistentvolumeclaims": [],
        "nodes": [{"metadata": {"name": "hp1"}, "status": {"addresses": [{"type": "InternalIP", "address": "10.0.16.133"}]}}],
    }


def workloads(plan):
    return {entry["name"]: entry for entry in plan["controllers"] if entry["role"] == "workload"}


class InventoryTests(unittest.TestCase):
    def test_bound_pv_is_authoritative_and_local_consumers_stay_running(self):
        resources = snapshot()
        resources["persistentvolumes"] = [
            obj("PersistentVolume", "local-pv", spec={"hostPath": {"path": "/local"}}),
            obj("PersistentVolume", "nas-pv", spec={"csi": {
                "driver": "csi.san.synology.com", "volumeAttributes": {"dsm": "10.0.16.16"}}}),
        ]
        resources["persistentvolumeclaims"] = [
            obj("PersistentVolumeClaim", "local-data", spec={"volumeName": "local-pv", "storageClassName": "nas"}),
            obj("PersistentVolumeClaim", "nas-data", spec={"volumeName": "nas-pv", "storageClassName": "local"}),
        ]
        resources["deployments"] += [
            obj("Deployment", "local-app", spec=template([pvc_volume("local-data")])),
            obj("Deployment", "nas-app", spec=template([pvc_volume("nas-data")])),
        ]
        resources["daemonsets"] = [obj("DaemonSet", "synology-csi-node", "synology-csi", template([
            {"name": "host", "hostPath": {"path": "/"}}
        ]))]
        plan = build_plan(resources, HOSTS)
        self.assertEqual(set(workloads(plan)), {"nas-app"})
        self.assertEqual(plan["nas_claims"], [{"namespace": "apps", "name": "nas-data", "pv": "nas-pv"}])

    def test_zero_replicas_and_stateful_claim_templates_are_saved(self):
        resources = snapshot()
        resources["deployments"].append(obj("Deployment", "media", spec={"replicas": 0, **template([nfs_volume()])}))
        resources["statefulsets"] = [obj("StatefulSet", "database", spec={
            "replicas": 0, "volumeClaimTemplates": [obj("PersistentVolumeClaim", "data", spec={"storageClassName": "nas"})],
            **template([]),
        })]
        plan = build_plan(resources, HOSTS)
        self.assertEqual({name: entry["replicas"] for name, entry in workloads(plan).items()}, {"database": 0, "media": 0})
        self.assertEqual(plan["volumes"], ["/volume1", "/volume3"])
        self.assertEqual(plan["nas_protocols"], ["iscsi", "nfs"])

    def test_unbound_default_and_generic_ephemeral_claims(self):
        resources = snapshot()
        resources["persistentvolumeclaims"] = [obj("PersistentVolumeClaim", "pending")]
        resources["deployments"] += [
            obj("Deployment", "pending-app", spec=template([pvc_volume("pending")])),
            obj("Deployment", "clone", spec=template([{"name": "clone", "ephemeral": {
                "volumeClaimTemplate": {"spec": {"storageClassName": "nas"}}
            }}])),
            obj("Deployment", "local-clone", spec=template([{"name": "clone", "ephemeral": {
                "volumeClaimTemplate": {"spec": {"storageClassName": "local"}}
            }}])),
        ]
        self.assertEqual(set(workloads(build_plan(resources, HOSTS))), {"clone", "pending-app"})

    def test_nfs_provisioner_identifies_unbound_cache_claim(self):
        resources = snapshot()
        resources["storageclasses"].append({"metadata": {"name": "cache"}, "provisioner": "example/nfs"})
        resources["persistentvolumeclaims"] = [obj("PersistentVolumeClaim", "cache", spec={"storageClassName": "cache"})]
        resources["deployments"] += [
            obj("Deployment", "nfs", "kube-system", {"template": {"spec": {"containers": [{"name": "provisioner", "env": [
                {"name": "NFS_SERVER", "value": "10.0.16.16"},
                {"name": "NFS_PATH", "value": "/volume3/cache"},
                {"name": "PROVISIONER_NAME", "value": "example/nfs"},
            ]}]}}}),
            obj("Deployment", "cache-consumer", spec=template([pvc_volume("cache")])),
        ]
        self.assertIn("cache-consumer", workloads(build_plan(resources, HOSTS)))

    def test_operator_owned_workloads_require_and_freeze_the_manager(self):
        for kind, api, manager, collection in (
            ("Grafana", "grafana.integreatly.org/v1beta1", "grafana-operator", "deployments"),
            ("Alertmanager", "monitoring.coreos.com/v1", "kube-prometheus-stack-operator", "statefulsets"),
        ):
            with self.subTest(kind=kind):
                resources = snapshot()
                workload_kind = "Deployment" if collection == "deployments" else "StatefulSet"
                resources.setdefault(collection, []).append(obj(workload_kind, "generated", "monitoring", {"replicas": 0, **template([nfs_volume()])}, owner(kind, "custom", api)))
                with self.assertRaisesRegex(ValueError, "Required maintenance gate"):
                    build_plan(resources, HOSTS)
                resources["deployments"].append(obj("Deployment", manager, "monitoring", {"replicas": 0}))
                plan = build_plan(resources, HOSTS)
                self.assertIn("generated", workloads(plan))
                self.assertEqual(next(c for c in plan["controllers"] if c["name"] == manager)["replicas"], 0)

    def test_unknown_custom_owner_unowned_pod_and_standalone_replicaset_fail_closed(self):
        resources = snapshot()
        resources["deployments"].append(obj("Deployment", "unknown", spec=template([nfs_volume()]), owner=owner("Unknown", "custom", "example.org/v1")))
        with self.assertRaisesRegex(ValueError, "Unsupported NAS controller owner"):
            build_plan(resources, HOSTS)
        resources = snapshot()
        resources["pods"] = [obj("Pod", "unowned", spec={"volumes": [nfs_volume()]})]
        with self.assertRaisesRegex(ValueError, "Unowned NAS Pod"):
            build_plan(resources, HOSTS)
        resources = snapshot()
        resources["replicasets"] = [obj("ReplicaSet", "standalone", spec=template([nfs_volume()]))]
        with self.assertRaisesRegex(ValueError, "no supported Deployment"):
            build_plan(resources, HOSTS)

    def test_hpa_targeting_nas_workload_is_rejected(self):
        resources = snapshot()
        resources["deployments"].append(obj("Deployment", "media", spec=template([nfs_volume()])))
        resources["horizontalpodautoscalers"] = [obj("HorizontalPodAutoscaler", "scale", spec={"scaleTargetRef": {"kind": "Deployment", "name": "media", "apiVersion": "apps/v1"}})]
        with self.assertRaisesRegex(ValueError, "HPA can recreate"):
            build_plan(resources, HOSTS)

    def test_all_cronjobs_preserve_prior_suspension_and_daemonset_selector(self):
        resources = snapshot()
        resources["cronjobs"] = [obj("CronJob", "paused", spec={"suspend": True}),
                                  obj("CronJob", "active", spec={"suspend": False}),
                                  obj("CronJob", "implicit")]
        ds = obj("DaemonSet", "nas-agent", spec=template([nfs_volume()]))
        ds["spec"]["template"]["spec"]["nodeSelector"] = {"disk": "original"}
        resources["daemonsets"] = [ds]
        plan = build_plan(resources, HOSTS)
        self.assertEqual({c["name"]: c["suspend"] for c in plan["cronjobs"]}, {"paused": True, "active": False, "implicit": None})
        self.assertEqual(workloads(plan)["nas-agent"]["nodeSelector"], {"disk": "original"})
        self.assertIsNone(workloads(plan)["nas-agent"]["replicas"])

    def test_pod_owner_chain_resolves_and_terminating_pods_remain_in_barrier(self):
        resources = snapshot()
        resources["deployments"].append(obj("Deployment", "media", spec={"replicas": 2}))
        resources["replicasets"] = [obj("ReplicaSet", "media-rs", owner=owner("Deployment", "media"))]
        live = obj("Pod", "terminating", spec={"volumes": [nfs_volume()]}, owner=owner("ReplicaSet", "media-rs"))
        live["metadata"]["deletionTimestamp"] = "2026-10-28T00:00:00Z"
        complete = copy.deepcopy(live)
        complete["metadata"]["name"] = "complete"
        complete["status"] = {"phase": "Succeeded"}
        resources["pods"] = [complete, live]
        self.assertEqual(nas_pods(resources, HOSTS), [live])
        self.assertEqual(workloads(build_plan(resources, HOSTS))["media"]["replicas"], 2)

    def test_nas_jobs_require_a_frozen_manager(self):
        resources = snapshot()
        job = obj("Job", "backup", spec=template([nfs_volume()]), owner=owner("ReplicationSource", "backup", "volsync.backube/v1alpha1"))
        resources["jobs"] = [job]
        with self.assertRaisesRegex(ValueError, "Required maintenance gate"):
            build_plan(resources, HOSTS)
        resources["deployments"].append(obj("Deployment", "volsync", "volsync"))
        self.assertEqual(build_plan(resources, HOSTS)["counts"]["active_nas_jobs"], 1)
        job["metadata"].pop("ownerReferences")
        with self.assertRaisesRegex(ValueError, "Unmanaged NAS Job"):
            build_plan(resources, HOSTS)

    def test_plan_is_deterministic_and_does_not_change_snapshot(self):
        resources = snapshot()
        resources["deployments"].append(obj("Deployment", "media", spec=template([nfs_volume()])))
        original = copy.deepcopy(resources)
        first = build_plan(resources, HOSTS)
        self.assertEqual(resources, original)
        for values in resources.values():
            values.reverse()
        self.assertEqual(first, build_plan(resources, HOSTS))

    def test_missing_flux_gate_and_changed_owner_uid_fail_closed(self):
        resources = snapshot()
        resources["deployments"].pop()
        with self.assertRaisesRegex(ValueError, "Required maintenance gate"):
            build_plan(resources, HOSTS)
        resources = snapshot()
        resources["deployments"].append(obj("Deployment", "media"))
        reference = owner("Deployment", "media")
        reference["uid"] = "replaced-uid"
        resources["replicasets"] = [obj("ReplicaSet", "media-rs", spec=template([nfs_volume()]), owner=reference)]
        with self.assertRaisesRegex(ValueError, "UID changed"):
            build_plan(resources, HOSTS)

    def test_cronjob_owned_job_is_drained_even_before_it_creates_a_pod(self):
        resources = snapshot()
        resources["cronjobs"] = [obj("CronJob", "backup", spec={
            "suspend": True, "jobTemplate": {"spec": template([nfs_volume()])}
        })]
        resources["jobs"] = [obj("Job", "backup-run", spec=template([nfs_volume()]),
                                  owner=owner("CronJob", "backup", "batch/v1"))]
        plan = build_plan(resources, HOSTS)
        self.assertEqual(plan["counts"]["active_nas_jobs"], 1)
        self.assertEqual(plan["counts"]["nas_pods"], 0)
        self.assertEqual(nas_jobs(resources, HOSTS), resources["jobs"])
        self.assertTrue(plan["cronjobs"][0]["suspend"])
        resources["jobs"][0]["status"] = {"conditions": [{"type": "Complete", "status": "True"}]}
        self.assertEqual(build_plan(resources, HOSTS)["counts"]["active_nas_jobs"], 0)
        self.assertEqual(nas_jobs(resources, HOSTS), [])

    def test_flux_instance_reconciliation_annotation_is_preserved(self):
        resources = snapshot()
        instance = obj("FluxInstance", "flux", "flux-system")
        instance["metadata"]["annotations"] = {"fluxcd.controlplane.io/reconcile": "disabled"}
        resources["fluxinstances"] = [instance]
        saved = build_plan(resources, HOSTS)["flux_instances"][0]
        self.assertEqual(saved["annotation"], "disabled")
        self.assertEqual(saved["uid"], instance["metadata"]["uid"])
        instance["metadata"].pop("annotations")
        self.assertIsNone(build_plan(resources, HOSTS)["flux_instances"][0]["annotation"])

    def test_incomplete_storage_snapshot_is_not_treated_as_local(self):
        resources = snapshot()
        resources["pods"] = [obj("Pod", "missing-claim", spec={"volumes": [pvc_volume("missing")]})]
        with self.assertRaisesRegex(ValueError, "missing PVC"):
            nas_pods(resources, HOSTS)
        resources["persistentvolumeclaims"] = [
            obj("PersistentVolumeClaim", "missing", spec={"volumeName": "missing-pv"})
        ]
        with self.assertRaisesRegex(ValueError, "missing PV"):
            build_plan(resources, HOSTS)


if __name__ == "__main__":
    unittest.main()

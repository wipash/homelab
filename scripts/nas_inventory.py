"""Read-only Kubernetes inventory for reversible NAS maintenance."""

import posixpath


CSI_DRIVER = "csi.san.synology.com"
RECONCILE_ANNOTATION = "fluxcd.controlplane.io/reconcile"
CONTROLLERS = {
    "Deployment": ("deployments", "deployments.apps"),
    "StatefulSet": ("statefulsets", "statefulsets.apps"),
    "DaemonSet": ("daemonsets", "daemonsets.apps"),
}
GATES = {
    ("flux-system", "flux-operator"): "gitops",
    ("flux-system", "kustomize-controller"): "gitops",
    ("flux-system", "helm-controller"): "gitops",
    ("monitoring", "grafana-operator"): "operator",
    ("monitoring", "kube-prometheus-stack-operator"): "operator",
    ("kube-system", "descheduler"): "operator",
    ("volsync", "volsync"): "backup",
}
CUSTOM_MANAGERS = {
    ("grafana.integreatly.org", "Grafana"): ("monitoring", "grafana-operator"),
    ("monitoring.coreos.com", "Alertmanager"): (
        "monitoring", "kube-prometheus-stack-operator"
    ),
}


def _key(obj):
    metadata = obj["metadata"]
    return metadata.get("namespace", "default"), metadata["name"]


def _owner(obj):
    owners = obj.get("metadata", {}).get("ownerReferences", [])
    controlling = [owner for owner in owners if owner.get("controller")]
    candidates = controlling or owners
    if len(candidates) > 1:
        raise ValueError("Ambiguous ownership for %s/%s" % _key(obj))
    return candidates[0] if candidates else None


def _terminal(obj):
    return obj.get("status", {}).get("phase") in ("Succeeded", "Failed")


def _finished_job(obj):
    return any(
        condition.get("type") in ("Complete", "Failed")
        and condition.get("status") == "True"
        for condition in obj.get("status", {}).get("conditions", [])
    )


class _Inventory:
    def __init__(self, resources, nas_hosts):
        self.resources = resources
        self.hosts = {str(host).lower().rstrip(".") for host in nas_hosts}
        if not self.hosts:
            raise ValueError("At least one NAS host is required")
        self.volumes = set()
        self.protocols = set()
        self.classes = {o["metadata"]["name"]: o for o in resources.get("storageclasses", [])}
        self.pvs = {o["metadata"]["name"]: o for o in resources.get("persistentvolumes", [])}
        self.claims = {_key(o): o for o in resources.get("persistentvolumeclaims", [])}
        self.objects = {}
        for kind, (collection, _) in CONTROLLERS.items():
            for obj in resources.get(collection, []):
                self.objects[(kind, *_key(obj))] = obj
        for kind, collection in (("ReplicaSet", "replicasets"), ("Job", "jobs"), ("CronJob", "cronjobs")):
            for obj in resources.get(collection, []):
                self.objects[(kind, *_key(obj))] = obj
        self.default_classes = [
            name for name, obj in self.classes.items()
            if any(obj.get("metadata", {}).get("annotations", {}).get(annotation) == "true"
                   for annotation in ("storageclass.kubernetes.io/is-default-class",
                                      "storageclass.beta.kubernetes.io/is-default-class"))
        ]
        self.nfs_provisioners = self._nfs_provisioners()
        self.nas_classes = {name: self._class_storage(obj) for name, obj in self.classes.items()}
        self.nas_pvs = {name: self._pv_storage(obj) for name, obj in self.pvs.items()}
        self.nas_claims = {key for key, obj in self.claims.items() if self._claim_storage(obj)}
        self.selected = {}
        self.active_jobs = set()

    def _is_host(self, host):
        return str(host).lower().rstrip(".") in self.hosts

    def _root(self, path):
        if not path or not path.startswith("/"):
            raise ValueError("NAS volume path must be absolute: %r" % path)
        normalized = posixpath.normpath(path)
        if normalized == "/":
            raise ValueError("Cannot infer NAS volume root from /")
        self.volumes.add("/" + normalized.lstrip("/").split("/", 1)[0])

    def _nfs_provisioners(self):
        provisioners = set()
        for kind in CONTROLLERS:
            collection = CONTROLLERS[kind][0]
            for obj in self.resources.get(collection, []):
                spec = obj.get("spec", {}).get("template", {}).get("spec", {})
                for container in spec.get("containers", []):
                    env = {entry["name"]: entry.get("value") for entry in container.get("env", [])}
                    if self._is_host(env.get("NFS_SERVER")) and env.get("PROVISIONER_NAME"):
                        provisioners.add(env["PROVISIONER_NAME"])
                        self.protocols.add("nfs")
                        self._root(env.get("NFS_PATH"))
        return provisioners

    def _class_storage(self, obj):
        provisioner = obj.get("provisioner")
        parameters = obj.get("parameters", {})
        if provisioner == CSI_DRIVER:
            if not parameters.get("dsm"):
                raise ValueError("Synology StorageClass lacks dsm: " + obj["metadata"]["name"])
            if self._is_host(parameters["dsm"]):
                self.protocols.add(parameters.get("protocol", "iscsi"))
                self._root(parameters.get("location"))
                return True
        if provisioner in self.nfs_provisioners:
            self.protocols.add("nfs")
            return True
        if self._is_host(parameters.get("server")):
            self.protocols.add("nfs")
            self._root(parameters.get("share") or parameters.get("path"))
            return True
        return False

    def _source_storage(self, source):
        nfs = source.get("nfs")
        if nfs and self._is_host(nfs.get("server")):
            self.protocols.add("nfs")
            self._root(nfs.get("path"))
            return True
        csi = source.get("csi", {})
        attributes = csi.get("volumeAttributes", {})
        if csi.get("driver") == CSI_DRIVER:
            if not attributes.get("dsm"):
                raise ValueError("Synology CSI volume lacks dsm")
            if self._is_host(attributes["dsm"]):
                self.protocols.add(attributes.get("protocol", "iscsi"))
                if attributes.get("location"):
                    self._root(attributes["location"])
                return True
        if csi.get("driver") == "nfs.csi.k8s.io" and self._is_host(attributes.get("server")):
            self.protocols.add("nfs")
            self._root(attributes.get("share"))
            return True
        return False

    def _pv_storage(self, obj):
        return self._source_storage(obj.get("spec", {}))

    def _claim_storage(self, obj):
        spec = obj.get("spec", {})
        if spec.get("volumeName"):
            pv = spec["volumeName"]
            if pv not in self.nas_pvs:
                raise ValueError("Bound PVC references missing PV: " + pv)
            return self.nas_pvs[pv]
        name = spec.get("storageClassName")
        if name is None:
            if len(self.default_classes) > 1:
                raise ValueError("Cannot choose between multiple default StorageClasses")
            name = self.default_classes[0] if self.default_classes else ""
        if name and name not in self.classes:
            raise ValueError("PVC references missing StorageClass: " + name)
        return self.nas_classes.get(name, False)

    def uses_nas(self, spec, namespace, templates=()):
        uses = False
        template_claims = {obj["metadata"]["name"]: obj for obj in templates}
        for claim in templates:
            uses = self._claim_storage(claim) or uses
        for volume in spec.get("volumes", []):
            uses = self._source_storage(volume) or uses
            if "persistentVolumeClaim" in volume:
                name = volume["persistentVolumeClaim"]["claimName"]
                key = (namespace, name)
                if key in self.claims:
                    uses = (key in self.nas_claims) or uses
                elif name in template_claims:
                    uses = self._claim_storage(template_claims[name]) or uses
                else:
                    raise ValueError("Volume references missing PVC: %s/%s" % key)
            if "ephemeral" in volume:
                template = volume["ephemeral"].get("volumeClaimTemplate")
                if template is None:
                    raise ValueError("Generic ephemeral volume lacks volumeClaimTemplate")
                uses = self._claim_storage(template) or uses
        return uses

    def _lookup(self, owner, namespace):
        key = (owner["kind"], namespace, owner["name"])
        obj = self.objects.get(key)
        if obj is None:
            raise ValueError("Missing NAS owner: %s %s/%s" % key)
        if owner.get("uid") and owner["uid"] != obj["metadata"].get("uid"):
            raise ValueError("NAS owner UID changed: %s %s/%s" % key)
        return obj

    def _gate(self, namespace, name):
        obj = self.objects.get(("Deployment", namespace, name))
        if obj is None:
            raise ValueError("Required maintenance gate is missing: %s/%s" % (namespace, name))
        self._select("Deployment", obj)

    def _manager(self, obj):
        owner = _owner(obj)
        if owner:
            namespace = _key(obj)[0]
            group = owner.get("apiVersion", "").split("/")[0]
            manager = CUSTOM_MANAGERS.get((group, owner["kind"]))
            if manager is None:
                raise ValueError("Unsupported NAS controller owner: %s %s/%s" % (owner["kind"], namespace, owner["name"]))
            self._gate(*manager)

    def _select(self, kind, obj):
        namespace, name = _key(obj)
        key = (kind, namespace, name)
        if key in self.selected:
            return
        self._manager(obj)
        metadata = obj["metadata"]
        if not metadata.get("uid"):
            raise ValueError("NAS controller lacks UID: %s/%s" % (namespace, name))
        spec = obj.get("spec", {})
        self.selected[key] = {
            "resource": CONTROLLERS[kind][1], "namespace": namespace,
            "name": name, "uid": metadata["uid"],
            "role": GATES.get((namespace, name), "workload"),
            "replicas": None if kind == "DaemonSet" else spec.get("replicas", 1),
            "nodeSelector": spec.get("template", {}).get("spec", {}).get("nodeSelector"),
        }

    def _job(self, obj):
        namespace, name = _key(obj)
        owner = _owner(obj)
        if not owner:
            raise ValueError("Unmanaged NAS Job cannot be safely paused: %s/%s" % (namespace, name))
        group = owner.get("apiVersion", "").split("/")[0]
        if owner["kind"] == "CronJob" and group == "batch":
            self._lookup(owner, namespace)
        elif group == "volsync.backube" and owner["kind"] in ("ReplicationSource", "ReplicationDestination"):
            self._gate("volsync", "volsync")
        else:
            raise ValueError("Unsupported NAS Job owner: %s %s/%s" % (owner["kind"], namespace, owner["name"]))
        self.active_jobs.add((namespace, name))

    def _replicaset(self, obj):
        owner = _owner(obj)
        if not owner or owner["kind"] != "Deployment":
            raise ValueError("NAS ReplicaSet has no supported Deployment owner: %s/%s" % _key(obj))
        self._select("Deployment", self._lookup(owner, _key(obj)[0]))

    def consumer(self, obj):
        namespace, name = _key(obj)
        owner = _owner(obj)
        if not owner:
            raise ValueError("Unowned NAS Pod cannot be safely restored: %s/%s" % (namespace, name))
        kind = owner["kind"]
        if kind == "ReplicaSet":
            self._replicaset(self._lookup(owner, namespace))
        elif kind in CONTROLLERS:
            self._select(kind, self._lookup(owner, namespace))
        elif kind == "Job":
            self._job(self._lookup(owner, namespace))
        else:
            raise ValueError("Unsupported NAS Pod owner: %s %s/%s" % (kind, namespace, owner["name"]))


def nas_pods(resources, nas_hosts):
    """Return live NAS consumers, including terminating pods, without changing state."""
    inventory = _Inventory(resources, nas_hosts)
    return sorted(
        (pod for pod in resources.get("pods", [])
         if not _terminal(pod) and inventory.uses_nas(pod.get("spec", {}), _key(pod)[0])),
        key=_key,
    )


def nas_jobs(resources, nas_hosts):
    """Return unfinished NAS Jobs, including those not yet holding a Pod."""
    inventory = _Inventory(resources, nas_hosts)
    return sorted(
        (job for job in resources.get("jobs", [])
         if not _finished_job(job)
         and inventory.uses_nas(job.get("spec", {}).get("template", {}).get("spec", {}), _key(job)[0])),
        key=_key,
    )


def build_plan(resources, nas_hosts):
    """Inventory reversible controller settings; reject consumers we cannot quiesce."""
    inventory = _Inventory(resources, nas_hosts)
    for (namespace, name), role in GATES.items():
        if role == "gitops" or ("Deployment", namespace, name) in inventory.objects:
            inventory._gate(namespace, name)
    for kind, (collection, _) in CONTROLLERS.items():
        for obj in resources.get(collection, []):
            spec = obj.get("spec", {})
            if inventory.uses_nas(spec.get("template", {}).get("spec", {}), _key(obj)[0], spec.get("volumeClaimTemplates", [])):
                inventory._select(kind, obj)
    for obj in resources.get("replicasets", []):
        if inventory.uses_nas(obj.get("spec", {}).get("template", {}).get("spec", {}), _key(obj)[0]):
            inventory._replicaset(obj)
    for obj in resources.get("jobs", []):
        if not _finished_job(obj) and inventory.uses_nas(obj.get("spec", {}).get("template", {}).get("spec", {}), _key(obj)[0]):
            inventory._job(obj)
    cronjobs = []
    for obj in resources.get("cronjobs", []):
        if inventory.uses_nas(obj.get("spec", {}).get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec", {}), _key(obj)[0]):
            inventory._manager(obj)
        metadata = obj["metadata"]
        if not metadata.get("uid"):
            raise ValueError("CronJob lacks UID: %s/%s" % _key(obj))
        cronjobs.append({"resource": "cronjobs.batch", "namespace": _key(obj)[0],
                         "name": metadata["name"], "uid": metadata["uid"],
                         "suspend": obj.get("spec", {}).get("suspend")})
    pods = [pod for pod in resources.get("pods", []) if not _terminal(pod)
            and inventory.uses_nas(pod.get("spec", {}), _key(pod)[0])]
    for pod in pods:
        inventory.consumer(pod)
    for obj in resources.get("horizontalpodautoscalers", []):
        target = obj.get("spec", {}).get("scaleTargetRef", {})
        key = (target.get("kind"), _key(obj)[0], target.get("name"))
        if key in inventory.selected:
            raise ValueError("HPA can recreate paused NAS controller: %s/%s" % _key(obj))
    nodes = []
    for obj in resources.get("nodes", []):
        addresses = [entry["address"] for entry in obj.get("status", {}).get("addresses", []) if entry.get("type") == "InternalIP"]
        if not addresses:
            raise ValueError("Node has no InternalIP: " + obj["metadata"]["name"])
        nodes.append({"name": obj["metadata"]["name"], "address": sorted(addresses)[0]})
    flux_instances = []
    for obj in resources.get("fluxinstances", []):
        metadata = obj["metadata"]
        if not metadata.get("uid"):
            raise ValueError("FluxInstance lacks UID: %s/%s" % _key(obj))
        flux_instances.append({"resource": "fluxinstances.fluxcd.controlplane.io",
                               "namespace": _key(obj)[0], "name": metadata["name"],
                               "uid": metadata["uid"], "annotation": metadata.get("annotations", {}).get(RECONCILE_ANNOTATION)})
    warnings = []
    if inventory.active_jobs:
        warnings.append("Wait for %d active NAS Job(s) to finish after freezing their managers" % len(inventory.active_jobs))
    return {
        "nas_hosts": sorted(inventory.hosts), "nodes": sorted(nodes, key=lambda o: o["name"]),
        "volumes": sorted(inventory.volumes), "nas_protocols": sorted(inventory.protocols),
        "flux_instances": sorted(flux_instances, key=lambda o: (o["namespace"], o["name"])),
        "controllers": sorted(inventory.selected.values(), key=lambda o: (o["role"], o["namespace"], o["name"], o["resource"])),
        "cronjobs": sorted(cronjobs, key=lambda o: (o["namespace"], o["name"])),
        "nas_claims": [{"namespace": namespace, "name": name,
                        "pv": inventory.claims[(namespace, name)].get("spec", {}).get("volumeName")}
                       for namespace, name in sorted(inventory.nas_claims)],
        "warnings": warnings,
        "counts": {"nas_pods": len(pods), "nas_claims": len(inventory.nas_claims),
                   "controllers": len(inventory.selected), "cronjobs": len(cronjobs),
                   "active_nas_jobs": len(inventory.active_jobs)},
    }

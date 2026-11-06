#!/usr/bin/env python3
"""Quiesce NAS consumers without shutting down the Kubernetes control plane."""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from nas_inventory import build_plan, nas_jobs, nas_pods
from nas_storage import nas_ready, storage_blockers

STATE_NAMESPACE = "kube-system"
STATE_NAME = "nas-maintenance"
RECONCILE = "fluxcd.controlplane.io/reconcile"
SELECTOR = "maintenance.mcgrath.nz/nas-paused"
NAS_HOSTS = {"10.0.16.16", "brian.sk.mcgrath.nz"}
RESOURCE_KINDS = {
    "PersistentVolume": "persistentvolumes",
    "PersistentVolumeClaim": "persistentvolumeclaims",
    "StorageClass": "storageclasses",
    "Deployment": "deployments",
    "StatefulSet": "statefulsets",
    "DaemonSet": "daemonsets",
    "ReplicaSet": "replicasets",
    "Pod": "pods",
    "CronJob": "cronjobs",
    "Job": "jobs",
    "Node": "nodes",
    "FluxInstance": "fluxinstances",
    "HorizontalPodAutoscaler": "horizontalpodautoscalers",
}


def run(argv, *, stdin=None):
    result = subprocess.run(
        argv, input=stdin, capture_output=True, text=True, timeout=45,
    )
    if result.returncode:
        raise RuntimeError(f"{argv[0]} failed: {result.stderr.strip()}")
    return result.stdout


class Cluster:
    def __init__(self, context):
        self.context = context

    def command(self, *args, stdin=None):
        return run(
            ["kubectl", "--context", self.context, "--request-timeout=30s", *args],
            stdin=stdin,
        )

    def snapshot(self):
        result = json.loads(self.command(
            "get", ",".join(RESOURCE_KINDS.values()), "-A", "-o", "json",
        ))
        resources = {key: [] for key in RESOURCE_KINDS.values()}
        for item in result["items"]:
            resources[RESOURCE_KINDS[item["kind"]]].append(item)
        return resources

    def get(self, resource, namespace, name, *, missing_ok=False):
        args = ["get", resource, name, "-n", namespace, "-o", "json"]
        if missing_ok:
            args.append("--ignore-not-found")
        value = self.command(*args)
        return json.loads(value) if value.strip() else None

    def patch(self, record, operations):
        current = self.get(record["resource"], record["namespace"], record["name"])
        if current["metadata"]["uid"] != record["uid"]:
            raise RuntimeError(f"{label(record)} was replaced; refusing to modify its replacement")
        operations = operations(current)
        if not operations:
            return
        preconditions = [
            {"op": "test", "path": "/metadata/uid", "value": record["uid"]},
            {"op": "test", "path": "/metadata/resourceVersion", "value": current["metadata"]["resourceVersion"]},
        ]
        self.command(
            "patch", record["resource"], record["name"], "-n", record["namespace"],
            "--type=json", "--field-manager=nas-maintenance", "-p", json.dumps(preconditions + operations),
        )

    def state(self):
        return self.get("configmaps", STATE_NAMESPACE, STATE_NAME, missing_ok=True)

    def create_state(self, state):
        manifest = {
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": STATE_NAME, "namespace": STATE_NAMESPACE,
                         "labels": {"app.kubernetes.io/name": STATE_NAME}},
            "data": {"state.json": json.dumps(state)},
        }
        self.command("create", "-f", "-", stdin=json.dumps(manifest))

    def save_state(self, state):
        current = self.state()
        if current is None:
            raise RuntimeError("Maintenance state disappeared; refusing to continue")
        self.patch(
            {"resource": "configmaps", "namespace": STATE_NAMESPACE,
             "name": STATE_NAME, "uid": current["metadata"]["uid"]},
            lambda _: [{"op": "replace", "path": "/data/state.json", "value": json.dumps(state)}],
        )


def label(record):
    return f"{record['namespace']}/{record['resource'].split('.')[0]}/{record['name']}"


def set_field(cluster, record, path, value):
    """None restores a previously absent field; JSON merge would retain selector keys."""
    parts = path.strip("/").split("/")

    def operations(current):
        parent = current
        for part in parts[:-1]:
            parent = parent[part]
        key = parts[-1]
        if value is None:
            return [{"op": "remove", "path": path}] if key in parent else []
        if parent.get(key) == value:
            return []
        return [{"op": "add", "path": path, "value": value}]

    cluster.patch(record, operations)


def set_flux_annotation(cluster, record, value):
    def operations(current):
        annotations = current["metadata"].get("annotations")
        path = "/metadata/annotations/" + RECONCILE.replace("/", "~1")
        if value is None:
            return [{"op": "remove", "path": path}] if annotations and RECONCILE in annotations else []
        if annotations is None:
            return [{"op": "add", "path": "/metadata/annotations", "value": {RECONCILE: value}}]
        if annotations.get(RECONCILE) == value:
            return []
        return [{"op": "add", "path": path, "value": value}]

    cluster.patch(record, operations)


def owner_uid(pod, resources, targets):
    objects = {r["metadata"]["uid"]: r for r in resources["replicasets"]}
    for ref in pod["metadata"].get("ownerReferences", []):
        if ref.get("controller"):
            if ref["uid"] in targets:
                return ref["uid"]
            if ref["uid"] in objects:
                for parent in objects[ref["uid"]]["metadata"].get("ownerReferences", []):
                    if parent.get("controller") and parent["uid"] in targets:
                        return parent["uid"]
    return None


def wait_for(description, check, timeout):
    print(description, flush=True)
    deadline = time.monotonic() + timeout
    previous = None
    while True:
        blockers = check()
        if not blockers:
            return
        message = "\n".join(sorted(set(blockers)))
        if message != previous:
            print(message, flush=True)
            previous = message
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Timed out: {description}\n{message}")
        time.sleep(min(5, max(0, deadline - time.monotonic())))


def stop_controllers(cluster, records, marker, timeout):
    if not records:
        return
    for record in records:
        print(f"Stopping {label(record)}", flush=True)
        if record["resource"] == "daemonsets.apps":
            selector = dict(record["nodeSelector"] or {})
            selector[SELECTOR] = marker
            set_field(cluster, record, "/spec/template/spec/nodeSelector", selector)
        else:
            set_field(cluster, record, "/spec/replicas", 0)
    targets = {r["uid"] for r in records}

    def stopped():
        resources = cluster.snapshot()
        blockers = []
        for record in records:
            current = cluster.get(record["resource"], record["namespace"], record["name"])
            if current["metadata"]["uid"] != record["uid"]:
                raise RuntimeError(f"{label(record)} was replaced during shutdown")
            # An in-flight reconciliation can restore replicas while its controller exits.
            if record["resource"] != "daemonsets.apps" and current["spec"].get("replicas", 1) != 0:
                set_field(cluster, record, "/spec/replicas", 0)
                blockers.append(f"Waiting for reconciliation to stop: {label(record)}")
        for pod in resources["pods"]:
            if pod["status"].get("phase") in ("Succeeded", "Failed"):
                continue
            target = owner_uid(pod, resources, targets)
            if target:
                blockers.append(f"Waiting for pod {pod['metadata']['namespace']}/{pod['metadata']['name']}")
                record = next(r for r in records if r["uid"] == target)
                if record["resource"] == "daemonsets.apps" and not pod["metadata"].get("deletionTimestamp"):
                    # OnDelete DaemonSets also need graceful deletion after scheduling is disabled.
                    cluster.command("delete", "pod", pod["metadata"]["name"], "-n", pod["metadata"]["namespace"], "--wait=false")
        return blockers

    wait_for("Waiting for controlled pods to terminate...", stopped, timeout)


def ready_blockers(cluster, records):
    blockers = []
    for record in records:
        current = cluster.get(record["resource"], record["namespace"], record["name"])
        if current["metadata"]["uid"] != record["uid"]:
            raise RuntimeError(f"{label(record)} was replaced during maintenance")
        if record["replicas"] == 0 and current["spec"].get("replicas", 1) == 0:
            continue
        status = current.get("status", {})
        if status.get("observedGeneration", 0) < current["metadata"].get("generation", 1):
            blockers.append(f"Waiting for controller to observe {label(record)}")
            continue
        if record["resource"] == "daemonsets.apps":
            desired = status.get("desiredNumberScheduled", 0)
            ready = status.get("numberReady", 0)
            updated = status.get("updatedNumberScheduled", 0)
            if ready < desired or updated < desired or status.get("numberMisscheduled", 0):
                blockers.append(f"{label(record)} ready {ready}/{desired}, updated {updated}")
        else:
            desired = record["replicas"]
            ready = status.get("readyReplicas", 0)
            if current["spec"].get("replicas", 1) != desired or ready < desired:
                blockers.append(f"{label(record)} ready {ready}/{desired}")
    return blockers


def restore_controllers(cluster, records, timeout):
    for record in records:
        print(f"Restoring {label(record)}", flush=True)
        if record["resource"] == "daemonsets.apps":
            set_field(cluster, record, "/spec/template/spec/nodeSelector", record["nodeSelector"])
        else:
            set_field(cluster, record, "/spec/replicas", record["replicas"])
    if records:
        wait_for("Waiting for restored workloads to become ready...", lambda: ready_blockers(cluster, records), timeout)


def job_blockers(resources, plan):
    """Include host-path maintenance Jobs, not just explicit NAS volume consumers."""
    jobs = {(j["metadata"]["namespace"], j["metadata"]["name"]): j
            for j in nas_jobs(resources, set(plan["nas_hosts"]))}
    cron_uids = {record["uid"] for record in plan["cronjobs"]}
    for job in resources["jobs"]:
        finished = any(c.get("type") in ("Complete", "Failed") and c.get("status") == "True"
                       for c in job.get("status", {}).get("conditions", []))
        if not finished and any(o.get("controller") and o["uid"] in cron_uids
                                for o in job["metadata"].get("ownerReferences", [])):
            jobs[(job["metadata"]["namespace"], job["metadata"]["name"])] = job
    blockers = [f"Waiting for batch/backup Job {namespace}/{name}" for namespace, name in sorted(jobs)]
    blockers.extend(
        f"Waiting for NAS job pod {p['metadata']['namespace']}/{p['metadata']['name']}"
        for p in nas_pods(resources, set(plan["nas_hosts"]))
        if any(o.get("controller") and o["kind"] == "Job" for o in p["metadata"].get("ownerReferences", []))
    )
    return blockers


def show_plan(state):
    print(f"Cluster: {state['context']}; maintenance phase: {state['phase']}")
    print(f"State: ConfigMap {STATE_NAMESPACE}/{STATE_NAME} (stored in etcd, not on the NAS)")
    for record in state["plan"]["controllers"]:
        setting = f"replicas={record['replicas']}" if record["replicas"] is not None else f"nodeSelector={record['nodeSelector']}"
        print(f"  {record['role']:8} {label(record)} ({setting})")
    print(f"CronJobs to suspend/restore: {len(state['plan']['cronjobs'])}")
    print(f"NAS PVCs: {len(state['plan']['nas_claims'])}; backing mounts: {', '.join(state['plan']['volumes'])}")
    for warning in state["plan"]["warnings"]:
        print(f"Warning: {warning}")


def pause(cluster, state, timeout):
    if state["phase"] == "resuming":
        raise RuntimeError("A resume was started; finish cluster:resume before pausing again")
    plan = state["plan"]
    for record in plan["flux_instances"]:
        set_flux_annotation(cluster, record, "disabled")
    # Stop upstream reconcilers first; the final barrier also catches in-flight writes.
    gitops = [r for r in plan["controllers"] if r["role"] == "gitops"]
    stop_controllers(cluster, gitops, state["marker"], timeout)
    stop_controllers(cluster, [r for r in plan["controllers"] if r["role"] in ("operator", "backup")], state["marker"], timeout)
    for record in plan["cronjobs"]:
        set_field(cluster, record, "/spec/suspend", True)

    wait_for(
        "Waiting for existing backup/batch jobs to finish (no forced deletion)...",
        lambda: job_blockers(cluster.snapshot(), plan), timeout,
    )
    workloads = [r for r in plan["controllers"] if r["role"] == "workload"]
    for stateful in (False, True):
        stop_controllers(cluster, [r for r in workloads if (r["resource"] == "statefulsets.apps") == stateful], state["marker"], timeout)

    def no_nas_pods():
        resources = cluster.snapshot()
        return job_blockers(resources, plan) + [
            f"NAS consumer remains: {p['metadata']['namespace']}/{p['metadata']['name']}"
            for p in nas_pods(resources, set(plan["nas_hosts"]))
        ]

    wait_for("Checking for remaining NAS consumers...", no_nas_pods, timeout)
    wait_for("Waiting for node-side NFS unmounts and iSCSI logout...", lambda: storage_blockers(plan, run), timeout)
    state["phase"] = "paused"
    cluster.save_state(state)
    print("PAUSED: NAS consumers are stopped and node storage is disconnected. The NAS can now be updated/rebooted.")
    print("Keep both cluster nodes running. Afterwards run: task cluster:resume")


def resume(cluster, state, timeout):
    plan = state["plan"]
    # Check all original identities before any restoration, including partial-pause recovery.
    for record in plan["controllers"] + plan["cronjobs"] + plan["flux_instances"]:
        current = cluster.get(record["resource"], record["namespace"], record["name"])
        if current["metadata"]["uid"] != record["uid"]:
            raise RuntimeError(f"{label(record)} was replaced; saved state retained for manual resolution")
    wait_for("Waiting for NAS SAN service, backing mounts and endpoints...", lambda: nas_ready(plan, run), timeout)
    state["phase"] = "resuming"
    cluster.save_state(state)
    workloads = [r for r in plan["controllers"] if r["role"] == "workload"]
    for resource in ("statefulsets.apps", "deployments.apps", "daemonsets.apps"):
        restore_controllers(cluster, [r for r in workloads if r["resource"] == resource], timeout)
    for role in ("operator", "backup"):
        restore_controllers(cluster, [r for r in plan["controllers"] if r["role"] == role], timeout)
    for record in plan["cronjobs"]:
        set_field(cluster, record, "/spec/suspend", record["suspend"])
    restore_controllers(cluster, [r for r in plan["controllers"] if r["role"] == "gitops"], timeout)
    for record in plan["flux_instances"]:
        set_flux_annotation(cluster, record, record["annotation"])
    cluster.command("delete", "configmap", STATE_NAME, "-n", STATE_NAMESPACE)
    print("RESUMED: saved replica counts, DaemonSet selectors, CronJob suspension and Flux annotations restored.")


@contextlib.contextmanager
def workstation_lock(cluster_uid):
    # Serializes invocations from this workstation, including different checkouts.
    path = Path(tempfile.gettempdir()) / f"homelab-nas-maintenance-{os.getuid()}-{cluster_uid}.lock"
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another NAS maintenance command is running on this workstation") from exc
        yield


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pause", "resume"))
    parser.add_argument("--dry-run", action="store_true", help="Read-only inventory and NAS readiness checks; no state or workload changes")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait per shutdown/readiness barrier (default: 900)")
    parser.add_argument("--context", help="Kubeconfig context (default: current context)")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    context = args.context or run(["kubectl", "config", "current-context"]).strip()
    cluster = Cluster(context)
    cluster_uid = cluster.get("namespaces", STATE_NAMESPACE, STATE_NAMESPACE)["metadata"]["uid"]
    with workstation_lock(cluster_uid):
        saved = cluster.state()
        if saved:
            state = json.loads(saved["data"]["state.json"])
            if state.get("version") != 1 or state.get("cluster_uid") != cluster_uid:
                raise RuntimeError("Maintenance state has an unsupported version or belongs to another cluster")
        elif args.action == "resume":
            print("No saved NAS maintenance state; nothing to resume.")
            return 0
        else:
            plan = build_plan(cluster.snapshot(), NAS_HOSTS)
            marker = uuid.uuid4().hex
            state = {"version": 1, "cluster_uid": cluster_uid, "context": context,
                     "phase": "pausing", "marker": marker, "plan": plan}
        show_plan(state)
        if args.dry_run:
            blockers = nas_ready(state["plan"], run)
            if blockers:
                print("NAS readiness blockers:\n" + "\n".join(blockers))
            print("DRY RUN: no Kubernetes or NAS resources changed.")
            return 1 if blockers else 0
        if saved is None:
            cluster.create_state(state)
        if args.action == "pause":
            pause(cluster, state, args.timeout)
        else:
            resume(cluster, state, args.timeout)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        print(f"Do not reboot the NAS unless pause reported PAUSED. Any saved state remains in {STATE_NAMESPACE}/{STATE_NAME}; use cluster:resume to recover an interrupted pause/resume.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted; maintenance state is retained. Use task cluster:resume to restore it.", file=sys.stderr)
        sys.exit(130)

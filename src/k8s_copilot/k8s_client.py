"""Kubernetes operations exposed to the LLM as tools.

Design principles:
    - One Python function per logical tool.
    - All functions return STRING output (what the LLM sees).
    - All functions truncate output to max_lines to prevent token waste.
    - All write operations (scale/delete/apply) are isolated in write_tools.py.
"""

from __future__ import annotations

from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException


class K8sClient:
    """Wraps the kubernetes-python-client with operations the LLM can call."""

    def __init__(self, kubeconfig_path: Optional[str] = None, max_lines: int = 50):
        # Load kubeconfig: explicit path → KUBECONFIG env → ~/.kube/config
        if kubeconfig_path:
            config.load_kube_config(config_file=str(kubeconfig_path))
        else:
            try:
                config.load_kube_config()
            except config.config_exception.ConfigException:
                # Try in-cluster config (works inside a pod with a service account)
                config.load_incluster_config()

        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()
        self.max_lines = max_lines

    # ------------------------------------------------------------------ #
    # READ-ONLY TOOLS — always safe to call
    # ------------------------------------------------------------------ #

    def get_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None,
        field_selector: Optional[str] = None,
    ) -> str:
        """List pods. namespace=None means all namespaces."""
        try:
            if namespace:
                resp = self.core.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=label_selector or "",
                    field_selector=field_selector or "",
                )
            else:
                resp = self.core.list_pod_for_all_namespaces(
                    label_selector=label_selector or "",
                    field_selector=field_selector or "",
                )
        except ApiException as e:
            return f"ERROR calling Kubernetes API: {e.reason} (status {e.status})"

        if not resp.items:
            return "No pods found matching the criteria."

        lines = [f"{'NAMESPACE':<20} {'NAME':<50} {'STATUS':<20} {'RESTARTS':<10} {'AGE'}"]
        for pod in resp.items:
            ns = pod.metadata.namespace
            name = pod.metadata.name
            phase = pod.status.phase or "Unknown"
            restarts = sum(
                (c.restart_count for c in (pod.status.container_statuses or [])),
                0,
            )
            age = _age_short(pod.metadata.creation_timestamp)

            # Note CrashLoopBackOff / ImagePullBackOff if present
            for cs in pod.status.container_statuses or []:
                if cs.state.waiting and cs.state.waiting.reason in (
                    "CrashLoopBackOff",
                    "ImagePullBackOff",
                    "ErrImagePull",
                    "CreateContainerConfigError",
                ):
                    phase = cs.state.waiting.reason
                    break

            lines.append(f"{ns:<20} {name:<50} {phase:<20} {restarts:<10} {age}")

        return _truncate(lines, self.max_lines)

    def describe_pod(self, name: str, namespace: str) -> str:
        """Get detailed info about a single pod."""
        try:
            pod = self.core.read_namespaced_pod(name=name, namespace=namespace)
        except ApiException as e:
            return f"ERROR: pod '{name}' in namespace '{namespace}' not found ({e.status})"

        out = []
        out.append(f"Name:         {pod.metadata.name}")
        out.append(f"Namespace:    {pod.metadata.namespace}")
        out.append(f"Node:         {pod.spec.node_name}")
        out.append(f"Status:       {pod.status.phase}")
        out.append(f"Created:      {pod.metadata.creation_timestamp}")
        if pod.metadata.labels:
            out.append(f"Labels:       {dict(pod.metadata.labels)}")
        out.append("")
        out.append("Containers:")
        for c in pod.spec.containers:
            out.append(f"  - {c.name}")
            out.append(f"      Image:    {c.image}")
            if c.resources and c.resources.requests:
                out.append(f"      Requests: {dict(c.resources.requests)}")
            if c.resources and c.resources.limits:
                out.append(f"      Limits:   {dict(c.resources.limits)}")

        out.append("")
        out.append("Container Statuses:")
        for cs in pod.status.container_statuses or []:
            out.append(f"  - {cs.name}: ready={cs.ready}, restarts={cs.restart_count}")
            if cs.state.waiting:
                out.append(
                    f"      Waiting: {cs.state.waiting.reason} — "
                    f"{cs.state.waiting.message}"
                )
            if cs.last_state and cs.last_state.terminated:
                t = cs.last_state.terminated
                out.append(
                    f"      LastTerminated: exit={t.exit_code}, reason={t.reason}"
                )

        return _truncate(out, self.max_lines)

    def get_logs(
        self,
        pod_name: str,
        namespace: str,
        container: Optional[str] = None,
        tail_lines: int = 100,
        previous: bool = False,
    ) -> str:
        """Fetch container logs (current or previous run)."""
        try:
            logs = self.core.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
                previous=previous,
            )
        except ApiException as e:
            return f"ERROR fetching logs: {e.reason} (status {e.status})"

        if not logs:
            return "(no log output)"

        log_lines = logs.split("\n")
        return _truncate(log_lines, self.max_lines)

    def get_deployments(self, namespace: Optional[str] = None) -> str:
        """List deployments with replica counts and age."""
        try:
            if namespace:
                resp = self.apps.list_namespaced_deployment(namespace=namespace)
            else:
                resp = self.apps.list_deployment_for_all_namespaces()
        except ApiException as e:
            return f"ERROR: {e.reason} (status {e.status})"

        if not resp.items:
            return "No deployments found."

        lines = [
            f"{'NAMESPACE':<20} {'NAME':<40} {'READY':<10} {'UP-TO-DATE':<12} "
            f"{'AVAILABLE':<12} {'AGE'}"
        ]
        for d in resp.items:
            ns = d.metadata.namespace
            name = d.metadata.name
            ready = f"{d.status.ready_replicas or 0}/{d.spec.replicas or 0}"
            updated = d.status.updated_replicas or 0
            available = d.status.available_replicas or 0
            age = _age_short(d.metadata.creation_timestamp)
            lines.append(
                f"{ns:<20} {name:<40} {ready:<10} {updated:<12} {available:<12} {age}"
            )

        return _truncate(lines, self.max_lines)

    def get_nodes(self) -> str:
        """List cluster nodes with status and capacity."""
        try:
            resp = self.core.list_node()
        except ApiException as e:
            return f"ERROR: {e.reason} (status {e.status})"

        lines = [
            f"{'NAME':<40} {'STATUS':<15} {'ROLES':<20} {'AGE':<10} {'VERSION'}"
        ]
        for node in resp.items:
            name = node.metadata.name
            ready = "Unknown"
            for cond in node.status.conditions or []:
                if cond.type == "Ready":
                    ready = "Ready" if cond.status == "True" else "NotReady"

            roles = ",".join(
                k.replace("node-role.kubernetes.io/", "")
                for k in (node.metadata.labels or {})
                if k.startswith("node-role.kubernetes.io/")
            ) or "<none>"

            age = _age_short(node.metadata.creation_timestamp)
            version = node.status.node_info.kubelet_version if node.status.node_info else "?"
            lines.append(f"{name:<40} {ready:<15} {roles:<20} {age:<10} {version}")

        return _truncate(lines, self.max_lines)

    # ------------------------------------------------------------------ #
    # WRITE TOOLS — only called after explicit human approval
    # ------------------------------------------------------------------ #

    def delete_pod(self, name: str, namespace: str) -> str:
        """Delete a pod. Its controller will recreate it."""
        try:
            self.core.delete_namespaced_pod(name=name, namespace=namespace)
            return f"Pod '{name}' deleted from namespace '{namespace}'. Its controller will recreate it."
        except ApiException as e:
            return f"ERROR deleting pod: {e.reason} (status {e.status})"

    def scale_deployment(self, name: str, namespace: str, replicas: int) -> str:
        """Patch a deployment's replica count."""
        try:
            body = {"spec": {"replicas": replicas}}
            self.apps.patch_namespaced_deployment_scale(
                name=name, namespace=namespace, body=body
            )
            return f"Deployment '{name}' in '{namespace}' scaled to {replicas} replica(s)."
        except ApiException as e:
            return f"ERROR scaling deployment: {e.reason} (status {e.status})"

    def rollout_restart(self, name: str, namespace: str) -> str:
        """Trigger a rolling restart by patching the pod template annotation."""
        import datetime

        restart_ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": restart_ts
                        }
                    }
                }
            }
        }
        try:
            self.apps.patch_namespaced_deployment(
                name=name, namespace=namespace, body=body
            )
            return (
                f"Rolling restart triggered for deployment '{name}' in '{namespace}'. "
                f"Pods will be replaced one by one (restartedAt={restart_ts})."
            )
        except ApiException as e:
            return f"ERROR triggering rollout restart: {e.reason} (status {e.status})"

    def get_events(
        self,
        namespace: Optional[str] = None,
        limit: int = 30,
    ) -> str:
        """Recent cluster events, newest first."""
        try:
            if namespace:
                resp = self.core.list_namespaced_event(namespace=namespace, limit=limit)
            else:
                resp = self.core.list_event_for_all_namespaces(limit=limit)
        except ApiException as e:
            return f"ERROR: {e.reason} (status {e.status})"

        events = sorted(
            resp.items,
            key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp,
            reverse=True,
        )

        if not events:
            return "No recent events found."

        lines = [f"{'TIME':<25} {'TYPE':<10} {'REASON':<25} {'OBJECT':<40} MESSAGE"]
        for e in events[:limit]:
            ts = e.last_timestamp or e.event_time or e.metadata.creation_timestamp
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else "?"
            obj = f"{e.involved_object.kind}/{e.involved_object.name}"
            msg = (e.message or "").replace("\n", " ")[:80]
            lines.append(
                f"{ts_str:<25} {e.type:<10} {e.reason:<25} {obj:<40} {msg}"
            )

        return _truncate(lines, self.max_lines)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _age_short(creation_ts) -> str:
    """Return a kubectl-style short age string (e.g. '4d2h', '15m')."""
    if not creation_ts:
        return "?"
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    delta = now - creation_ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h{m}m" if m else f"{h}h"
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    return f"{d}d{h}h" if h else f"{d}d"


def _truncate(lines: list[str], max_lines: int) -> str:
    """Truncate lines list and add a note if cut."""
    if len(lines) <= max_lines:
        return "\n".join(lines)
    kept = lines[:max_lines]
    cut = len(lines) - max_lines
    kept.append(f"... ({cut} more lines truncated; refine your query if needed)")
    return "\n".join(kept)

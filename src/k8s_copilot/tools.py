"""Tool definitions exposed to Claude via the Messages API.

These schemas tell Claude what tools are available, what parameters they accept,
and when to use them. Claude returns `tool_use` blocks that map to entries here.
"""

from typing import Any, Dict, List


# Read-only tools — always available
READ_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "kubectl_get_pods",
        "description": (
            "List pods in the cluster, optionally filtered by namespace, label, or field. "
            "Use this as the entry point for most troubleshooting workflows. "
            "Examples: 'failing pods in orders namespace' → namespace='orders', "
            "field_selector='status.phase!=Running'. "
            "Set namespace=null to list pods across ALL namespaces."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": ["string", "null"],
                    "description": "Namespace to filter by. Null = all namespaces.",
                },
                "label_selector": {
                    "type": ["string", "null"],
                    "description": (
                        "Kubernetes label selector, e.g. 'app=orders' or "
                        "'environment=production,tier=frontend'."
                    ),
                },
                "field_selector": {
                    "type": ["string", "null"],
                    "description": (
                        "Field selector, e.g. 'status.phase=Running' or "
                        "'status.phase!=Running'."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "kubectl_describe_pod",
        "description": (
            "Get detailed information about a single pod — including container statuses, "
            "restart counts, waiting reasons (CrashLoopBackOff, ImagePullBackOff), and "
            "last termination state. Use after kubectl_get_pods identifies a problem pod."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Pod name (exact).",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace the pod lives in.",
                },
            },
            "required": ["name", "namespace"],
        },
    },
    {
        "name": "kubectl_logs",
        "description": (
            "Fetch container logs from a pod. Set previous=true to get logs from the "
            "previous container instance — useful after a CrashLoopBackOff to see why "
            "the container died. Default tail_lines=100."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pod_name": {
                    "type": "string",
                    "description": "Pod name (exact).",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace the pod lives in.",
                },
                "container": {
                    "type": ["string", "null"],
                    "description": (
                        "Container name within the pod. Null = first container."
                    ),
                },
                "tail_lines": {
                    "type": "integer",
                    "description": "Number of log lines to fetch from the end.",
                    "default": 100,
                },
                "previous": {
                    "type": "boolean",
                    "description": (
                        "True = get logs from the previous (crashed) container instance."
                    ),
                    "default": False,
                },
            },
            "required": ["pod_name", "namespace"],
        },
    },
    {
        "name": "kubectl_get_deployments",
        "description": (
            "List deployments with replica counts, update status, and age. "
            "Use to check deployment health or identify stale deployments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": ["string", "null"],
                    "description": "Namespace to filter by. Null = all namespaces.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "kubectl_get_nodes",
        "description": (
            "List cluster nodes with status (Ready/NotReady), roles, age, and kubelet version. "
            "Use to investigate cluster-wide issues."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "kubectl_get_events",
        "description": (
            "Get recent Kubernetes events, sorted newest first. Events show why pods are "
            "failing to schedule, image pulls failing, probe failures, etc. Always check "
            "events when investigating an unhealthy pod."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": ["string", "null"],
                    "description": "Namespace to filter by. Null = all namespaces.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of events to return.",
                    "default": 30,
                },
            },
            "required": [],
        },
    },
]


WRITE_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "kubectl_delete_pod",
        "description": (
            "Delete a pod by name. Its controller (Deployment/StatefulSet) will recreate it. "
            "Use to force-restart a stuck or crashlooping pod. "
            "WRITE OPERATION — requires human approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact pod name."},
                "namespace": {"type": "string", "description": "Namespace the pod lives in."},
            },
            "required": ["name", "namespace"],
        },
    },
    {
        "name": "kubectl_scale_deployment",
        "description": (
            "Scale a deployment to a target number of replicas. "
            "Use to scale up for traffic or scale down to 0 to stop a misbehaving workload. "
            "WRITE OPERATION — requires human approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Deployment name."},
                "namespace": {"type": "string", "description": "Namespace."},
                "replicas": {
                    "type": "integer",
                    "description": "Target replica count. Use 0 to scale down completely.",
                },
            },
            "required": ["name", "namespace", "replicas"],
        },
    },
    {
        "name": "kubectl_rollout_restart",
        "description": (
            "Trigger a rolling restart of a deployment (equivalent to kubectl rollout restart). "
            "All pods are replaced one by one with zero downtime. "
            "Use when a deployment is stuck or you need to pick up a new ConfigMap/Secret. "
            "WRITE OPERATION — requires human approval before execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Deployment name."},
                "namespace": {"type": "string", "description": "Namespace."},
            },
            "required": ["name", "namespace"],
        },
    },
]

# Set of write tool names — used by the agent to gate on approval.
WRITE_TOOL_NAMES: set = {t["name"] for t in WRITE_TOOLS}


def command_display(tool_name: str, tool_input: Dict[str, Any]) -> str:
    """Return a human-readable kubectl equivalent for a write tool call."""
    ns = tool_input.get("namespace", "<namespace>")
    name = tool_input.get("name", "<name>")
    if tool_name == "kubectl_delete_pod":
        return f"kubectl delete pod {name} -n {ns}"
    if tool_name == "kubectl_scale_deployment":
        replicas = tool_input.get("replicas", "?")
        return f"kubectl scale deployment/{name} -n {ns} --replicas={replicas}"
    if tool_name == "kubectl_rollout_restart":
        return f"kubectl rollout restart deployment/{name} -n {ns}"
    return f"{tool_name}({tool_input})"


SYSTEM_PROMPT = """\
You are K8sCopilot, an assistant for Kubernetes operations.

You help engineers investigate and operate Kubernetes clusters through natural language.
Translate user questions into appropriate tool calls, chain multiple tool calls when needed
for multi-step investigations, and present results clearly.

Operational principles:
1. **Investigate, don't guess.** When asked "why is X failing", actually look at pods,
   describe the failing one, fetch its logs, check events. Do not speculate without data.
2. **Chain tools naturally.** A typical debugging flow is:
   kubectl_get_pods → kubectl_describe_pod (on the failing one) →
   kubectl_logs (previous=true if CrashLoopBackOff) → kubectl_get_events.
3. **Be concise in your final summary.** After tool calls complete, give the engineer
   a short diagnosis (3-5 lines) ending with the most likely root cause or next step.
4. **Don't over-call.** If a single tool answers the question, stop. Don't run extra tools
   for the sake of completeness.
5. **Acknowledge limits honestly.** If a tool returns "no pods found" or an error, say
   so directly. Don't fabricate.
6. **Write operations require explicit user intent.** Only call kubectl_delete_pod,
   kubectl_scale_deployment, or kubectl_rollout_restart when the user has clearly asked
   for a change. For ambiguous requests like "fix the crashing pod", diagnose first,
   then ask the user if they want you to act. Before calling a write tool, state in one
   sentence what you are about to do and why.
"""

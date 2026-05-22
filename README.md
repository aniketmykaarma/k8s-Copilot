# K8sCopilot

> A natural-language assistant for Kubernetes operations. Ask in plain English, get answers (and safe `kubectl` execution) from your cluster.

K8sCopilot is a Python tool that turns natural-language questions about your Kubernetes clusters into safe, structured `kubectl` operations. It uses Anthropic Claude's tool-use API to route queries to a small set of well-defined Python tools — read-only by default, with explicit approval gates for any destructive operations.

```
$ k8s-copilot "show me pods crashing in the orders namespace"

Thinking...
→ kubectl_get_pods(namespace='orders', field_selector='status.phase!=Running')

Found 2 pods not in Running state:
  • orders-api-7f8d-xyz       CrashLoopBackOff   3 restarts in last 10m
  • orders-worker-9c2-abc     ImagePullBackOff   2m ago

Want me to look deeper at orders-api-7f8d-xyz? (y/n)
```

## Why this exists

Troubleshooting Kubernetes during incidents involves repetitive command sequences:
`kubectl get pods` → find the failing one → `kubectl describe pod X` → `kubectl logs X --previous` → `kubectl get events`.

K8sCopilot automates the navigation, so engineers focus on the actual problem rather than the typing.

## Features

- **Natural-language queries** translated to safe `kubectl` operations
- **Multi-step troubleshooting workflows** — the agent chains tool calls to investigate complex problems
- **Read-only by default** — destructive operations (scale, delete, apply) require explicit confirmation, and are feature-flagged off in v1
- **Audit logging** — every executed command logged with timestamp, query, and outcome
- **Output truncation** — handles large clusters without overwhelming the model
- **CLI + Web UI** — terminal-first, with a Streamlit-based web interface in v2

## Quick start

### Prerequisites

- Python 3.10+
- A working `kubectl` configuration (`~/.kube/config`) pointed at any cluster (use [kind](https://kind.sigs.k8s.io/) for a local test cluster)
- An Anthropic API key — get one at [console.anthropic.com](https://console.anthropic.com)

### Install

```bash
git clone https://github.com/aniketchakrabarty7/k8s-copilot.git
cd k8s-copilot
pip install -e .
```

### Configure

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Optional — override defaults
export K8S_COPILOT_MODEL=claude-sonnet-4-20250514
export K8S_COPILOT_LOG_PATH=~/.k8s-copilot/audit.log
```

### Use

```bash
# Single query
k8s-copilot "show me pods using more than 1Gi of memory in default namespace"

# Interactive mode
k8s-copilot --interactive

# Web UI (v2)
k8s-copilot-web
```

## Example queries

- `"show me failing pods across all namespaces"`
- `"why is the orders service unhealthy?"`  (multi-step)
- `"which deployments haven't been updated in 30 days?"`
- `"what's consuming the most memory in the kube-system namespace?"`
- `"list nodes and their conditions"`
- `"show me recent events in the production namespace, sorted by time"`

## Architecture

```
User Query → Claude (with tool definitions) → Tool Executor → kubernetes-python-client → Cluster
                  ↑                                ↓
                  └──────── Tool Results ──────────┘
                  (loop until Claude is done)
```

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design walkthrough.

## Safety model

K8sCopilot is designed for production-adjacent use. Three layers:

1. **Tool-level read-only default.** Out of the box, only `get`, `describe`, `logs`, and `top` tools are enabled.
2. **Approval gate on destructive operations.** When write tools (`scale`, `delete`, `apply`) are enabled via config, every invocation prints the exact action and prompts for confirmation before executing.
3. **Audit log.** Every tool call (read or write) is written to a structured JSON log for review.

## Configuration

`~/.k8s-copilot/config.yaml`:

```yaml
model: claude-sonnet-4-20250514
log_path: ~/.k8s-copilot/audit.log
max_tool_calls: 10           # safety cap on tool-use loop iterations
max_output_lines: 50         # truncate kubectl output before sending to LLM
enable_write_tools: false    # turn on scale/delete/apply (requires --confirm flag too)
```

## Project status

- v0.1 ✅ — CLI with 4 read-only tools, multi-step tool-use loop
- v0.2 ✅ — Audit logging, output truncation, rich CLI output
- v0.3 ✅ — Streamlit web UI
- v0.4 (planned) — Write tools with approval gates, multi-cluster context switching
- v1.0 (planned) — kubeconfig context inference, integration tests, packaged release

## License

MIT

## Author

Aniket Chakrabarty — [LinkedIn](https://linkedin.com/in/aniket-chakrabarty) | [GitHub](https://github.com/aniketchakrabarty7)

Built because every Sev-1 I've been on involved typing the same `kubectl` sequences in the same order. The agent does the typing now.

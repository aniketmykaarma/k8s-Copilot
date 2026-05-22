# K8sCopilot — Guardrails & SRE Benefits

## Current Guardrails

### 1. Read-Only by Default
Write tools (`kubectl_delete_pod`, `kubectl_scale_deployment`, `kubectl_rollout_restart`) are
**not registered with Claude** unless you explicitly pass `--write` or set
`enable_write_tools: true` in config. Claude cannot call them if the flag is not set — the
tools are absent from the tool list entirely, not just blocked by a prompt instruction.

### 2. Human Approval Gate
When `--write` is enabled, every write operation pauses and shows the exact equivalent
`kubectl` command before prompting:

```
╭─ Write operation requested ──────────────────────────────╮
│  $ kubectl delete pod api-server-xyz -n prod-services    │
╰──────────────────────────────────────────────────────────╯
Execute this command? [y/n] (default: n):
```

The default is **n** — pressing Enter without typing `y` never executes anything.

### 3. Max Tool Call Cap
`max_tool_calls: 10` (configurable). If Claude enters an investigation loop, the agent
hard-stops and returns what it has. Prevents runaway API spend and infinite chains.

### 4. Output Truncation
`max_output_lines: 50` per tool call. Large clusters with hundreds of pods won't flood
the LLM context window or drive up token costs unexpectedly.

### 5. Append-Only Audit Log
Every tool execution — read or write — is appended to `~/.k8s-copilot/audit.log` as JSONL:

```json
{
  "ts": "2026-05-22T07:00:00Z",
  "session_id": "a3f2c1",
  "user_query": "delete the crashing pod in prod",
  "tool": "kubectl_delete_pod",
  "params": {"name": "api-server-xyz", "namespace": "prod-services"},
  "outcome": "denied",
  "duration_ms": 0
}
```

Outcomes are `success`, `error`, or `denied`. Structured for `jq`, Splunk, or any log
aggregator.

### 6. System Prompt Safety Instructions
Claude is explicitly instructed to:
- Only call write tools when the user **clearly requests a change**
- **Diagnose first** for ambiguous requests (e.g. "fix the crashing pod") and ask before acting
- Never speculate without data returned from tool calls

### 7. Limited Write Blast Radius
Write operations are deliberately scoped to three **recoverable** actions:

| Tool | Effect | Recovery |
|------|--------|----------|
| `kubectl_delete_pod` | Deletes a pod | Controller recreates it automatically |
| `kubectl_scale_deployment` | Changes replica count | Scale back manually |
| `kubectl_rollout_restart` | Rolling restart of a deployment | Zero-downtime; undo with rollout undo |

No `kubectl exec` shell access, no arbitrary manifest apply — the most dangerous operations
are out of scope by design.

### 8. Single-Cluster Scope
Operates only on the cluster in `~/.kube/config` (or `KUBECONFIG`). No cross-cluster
access. Supports in-cluster config when running as a pod, where Kubernetes RBAC limits
what the service account can see and do.

---

## Benefits for DevOps / SRE Engineers

### Incident Response Speed
- **Natural language at 3 AM** — ask "why is payment-service down in prod?" and the agent
  runs the full investigation chain: get pods → describe the failing one → fetch previous
  logs → check events. No fumbling for namespaces or flags under pressure.
- **Multi-turn context** — after "which pods are crashing in orders?", follow up with
  "check logs for the first one" and Claude knows which pod you mean. No copy-pasting
  names between commands.

### Reduced Toil
- Eliminates repetitive kubectl sequences every SRE runs during incidents — the agent
  chains them automatically.
- Junior engineers can investigate production without deep kubectl knowledge, flattening
  the on-call learning curve.

### Safe Write Operations
- The approval gate shows the exact `kubectl` command before execution — no surprises
  from an LLM interpreting your intent differently than expected.
- Audit log provides a **post-incident record** of every command run during a war room,
  useful for blameless postmortems and compliance reviews.

### Team Scalability
- The **Streamlit web UI** gives the whole team access without CLI setup — developers,
  PMs, and on-call rotation members share the same interface.
- Config file and env var support makes it easy to deploy as a shared internal tool.

### Observability
- Session IDs in the audit log let you reconstruct exactly what an on-call engineer
  queried during an incident.
- Tool call durations surface slow Kubernetes API responses.

---

## Known Gaps (Honest)

| Gap | Risk | Suggested Fix |
|-----|------|---------------|
| No auth on the web UI | Anyone on the network can query the cluster | Put behind a reverse proxy with auth (nginx, Cloudflare Access) |
| No RBAC on the tool itself | Full read access to the cluster for any user | Run with a service account scoped to read-only RBAC |
| No per-session rate limiting | Runaway queries could hit Anthropic API limits | Add a per-session token budget in `config.py` |
| `kubectl apply` not implemented | Cannot push arbitrary manifest changes — currently a gap and a guardrail | Add with a diff-preview approval step |
| API key stored in plaintext config | Key exposure if config file is readable | Use a secrets manager or environment-only injection |

---

## Future Improvements

### Security & Access Control
- **Web UI authentication** — Add SSO/OAuth (Google, GitHub, Okta) to the Streamlit app
  so only authorized engineers can access it. Short-term: put it behind Cloudflare Access
  or an nginx reverse proxy with basic auth.
- **Kubernetes RBAC service account** — Ship a `ClusterRole` manifest that grants only the
  permissions K8sCopilot actually needs (get/list pods, deployments, nodes, events, logs).
  When running in-cluster, bind this role to the pod's service account so it cannot read
  Secrets or other sensitive resources.
- **Namespace allowlist** — Config option to restrict which namespaces the agent can query.
  Prevents accidental exposure of `kube-system` internals or other sensitive namespaces in
  a multi-tenant cluster.
- **Secrets masking** — Automatically redact values from Kubernetes Secrets if they appear
  in describe/event output before sending to the LLM.

### Write Operation Safety
- **`kubectl apply` with diff preview** — Implement the missing apply tool with a mandatory
  dry-run + diff step shown to the user before the real apply, similar to `terraform plan`
  before `apply`.
- **Two-person approval** — For high-risk write operations in production namespaces, require
  a second engineer to confirm via a Slack message or a shared web UI button before
  execution.
- **Namespace-based write restrictions** — Allow writes in `staging` freely but require
  stricter approval (or block entirely) in `prod` namespaces, configured via a policy file.
- **Rollback awareness** — Before executing a scale or restart, capture the current state
  (replica count, last deployed image) and log it so the engineer has a one-command undo
  path.

### Reliability & Cost Control
- **Per-session token budget** — Add a configurable `max_tokens_per_session` cap so a
  runaway interactive session cannot spend unbounded on the Anthropic API.
- **Context window management** — Auto-summarize old turns when the conversation history
  approaches the model's context limit, so long REPL sessions don't fail silently.
- **Streaming responses** — Use the Anthropic streaming API so tool call progress and the
  final answer appear token-by-token rather than waiting for the full response, improving
  perceived speed during long investigations.
- **Caching for read tools** — Cache read-only tool results (e.g. `get_pods`) for a short
  TTL (10–30s) so repeated similar queries within a session don't hammer the Kubernetes API.

### Observability & Audit
- **Structured audit export** — Ship a script to push `audit.log` to common destinations:
  CloudWatch Logs, Datadog, Splunk, or a Postgres table for team-wide query history.
- **Session replay** — A CLI command (`k8s-copilot --replay <session_id>`) that prints the
  full tool call sequence for a past session, useful for postmortem reconstruction.
- **Metrics endpoint** — Expose a `/metrics` endpoint (Prometheus format) with counters for
  queries, tool calls, approval rates, and error rates.

### Developer Experience
- **Plugin system for custom tools** — Allow teams to register their own read-only tools
  (e.g. query an internal CMDB, fetch a Datadog dashboard URL) so the agent can pull
  context from beyond the Kubernetes API.
- **Multi-cluster support** — `--context` flag to target a specific kubeconfig context, and
  a config option to name clusters (e.g. `prod-us-east`, `staging-eu`) so the agent can
  be asked "compare pod counts between prod and staging".
- **Slack / PagerDuty integration** — Trigger K8sCopilot investigations directly from a
  Slack slash command during an incident, with results posted back to the channel.

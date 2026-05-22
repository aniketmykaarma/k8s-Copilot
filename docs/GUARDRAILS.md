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

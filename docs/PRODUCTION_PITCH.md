# K8sCopilot — Production Proposal

> Proposal to run K8sCopilot as a shared internal tool for the SRE / DevOps team.

---

## The Problem

Every Kubernetes incident follows the same pattern:

```
kubectl get pods -n <namespace>                          # find the failing pod
kubectl describe pod <name> -n <namespace>               # check why it's failing
kubectl logs <name> -n <namespace> --previous            # read the crash logs
kubectl get events -n <namespace> --sort-by=.lastTimestamp  # check recent events
```

This sequence — repeated dozens of times per incident, often at 2–3 AM — is:

- **Slow under pressure.** Engineers forget exact flags, mistype namespace names, and
  lose time on syntax rather than diagnosis.
- **Knowledge-gated.** Junior engineers on rotation cannot investigate confidently
  without senior help, creating bottlenecks during incidents.
- **Undocumented.** There is no record of what was checked, in what order, and what
  was found — making postmortems harder and root cause identification slower.

K8sCopilot solves all three.

---

## What It Does

K8sCopilot is a natural-language interface to your Kubernetes cluster. Engineers ask
questions in plain English; the tool translates them into the right `kubectl` operations,
executes them against the cluster, and synthesises the results into a clear answer.

**Example — Incident investigation:**
```
> why is the payment-service unhealthy in prod?

→ kubectl_get_pods(namespace='prod', label_selector='app=payment-service')
→ kubectl_describe_pod(name='payment-svc-7f8d-xyz', namespace='prod')
→ kubectl_logs(pod_name='payment-svc-7f8d-xyz', namespace='prod', previous=True)
→ kubectl_get_events(namespace='prod')

┌─ K8sCopilot ────────────────────────────────────────────────────────────────┐
│ payment-svc-7f8d-xyz is in CrashLoopBackOff (14 restarts in the last hour). │
│                                                                              │
│ Root cause: OOMKilled — the container is being killed by the kernel because  │
│ it exceeds its memory limit of 512Mi. Last log line before crash:            │
│   FATAL: java.lang.OutOfMemoryError: Java heap space                        │
│                                                                              │
│ Suggested fix: increase memory limit in the deployment spec, or reduce       │
│ heap usage. Current limit: 512Mi. Recommended: 1Gi based on recent usage.   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Example — Write operation with approval gate:**
```
> restart the payment-service deployment

╭─ Write operation requested ──────────────────────────────────────────────╮
│  $ kubectl rollout restart deployment/payment-svc -n prod                │
╰──────────────────────────────────────────────────────────────────────────╯
Execute this command? [y/n] (default: n): y

Executing...
Rolling restart triggered for deployment 'payment-svc' in 'prod'.
```

---

## Architecture

```
Engineer (CLI or Web UI)
        │
        ▼
  K8sCopilot Agent
  ┌─────────────────────────────────────────────┐
  │  User query → Claude (Anthropic API)        │
  │       ↓  tool_use blocks                    │
  │  Tool Dispatcher                            │
  │  ┌──────────────────────────────────────┐   │
  │  │  Read tools  →  Kubernetes API       │   │
  │  │  Write tools →  Approval Gate        │   │
  │  │                      ↓              │   │
  │  │               Kubernetes API        │   │
  │  └──────────────────────────────────────┘   │
  │       ↓  tool_result                        │
  │  Claude synthesises → Final answer          │
  └─────────────────────────────────────────────┘
        │
        ▼
  Audit Log (JSONL)
```

**Key components:**

| Component | Technology | Purpose |
|-----------|-----------|---------|
| LLM | Anthropic Claude (`claude-sonnet-4-6`) | Translates queries to tool calls, synthesises results |
| Kubernetes client | `kubernetes-python` SDK | Calls the cluster API directly — no `kubectl` binary required |
| CLI | Python + Rich | Interactive REPL and single-shot query mode |
| Web UI | Streamlit | Browser-based interface for the whole team |
| Audit log | JSONL append-only file | Records every tool execution for compliance and postmortems |

---

## Safety Model

This is the most important section for a production deployment.

### What can it do by default?

Out of the box, K8sCopilot is **entirely read-only**. It can:

- List and describe pods, deployments, nodes, services
- Fetch container logs (current and previous runs)
- Read cluster events

It **cannot** modify, delete, restart, or scale anything without explicit opt-in.

### How are write operations controlled?

Write operations are disabled at the code level unless the `--write` flag is passed or
`enable_write_tools: true` is set in config. Even then:

1. The agent only calls a write tool when the engineer explicitly asks for a change
2. Before execution, the **exact equivalent `kubectl` command** is shown
3. The engineer must type `y` — the default is `n`, so Enter alone never executes anything

Current write operations are deliberately limited to three **recoverable** actions:

| Operation | Kubernetes Effect | How to Undo |
|-----------|-----------------|-------------|
| Delete pod | Pod is removed; controller recreates it | Automatic (controller does it) |
| Scale deployment | Replica count changes | `kubectl scale` back to previous count |
| Rollout restart | Rolling restart, zero downtime | `kubectl rollout undo` |

Intentionally excluded: `kubectl exec`, `kubectl apply`, namespace deletion, and any
operation that touches Secrets or ConfigMaps.

### Audit trail

Every tool call — read or write — is logged:

```json
{
  "ts": "2026-05-22T07:00:00Z",
  "session_id": "a3f2c1b8",
  "user_query": "restart the payment-service in prod",
  "tool": "kubectl_rollout_restart",
  "params": {"name": "payment-svc", "namespace": "prod"},
  "outcome": "success",
  "duration_ms": 312
}
```

This gives you a full record for postmortems, compliance audits, and change management.

---

## Operational Requirements

### Infrastructure

| Requirement | Detail |
|-------------|--------|
| Runtime | Python 3.9+, any Linux/macOS host |
| Network | Outbound HTTPS to `api.anthropic.com` (port 443) |
| Cluster access | Read access via `~/.kube/config` or in-cluster service account |
| Disk | ~200MB for dependencies; audit log grows ~1KB per query |
| Memory | ~150MB resident |
| CPU | Negligible (I/O-bound on API calls) |

### Deployment options

**Option A — Shared VM / bastion host (recommended for first rollout)**
Install once on a bastion host; team members access via SSH or the Streamlit web UI.
One API key, one audit log, easy to manage.

**Option B — In-cluster pod**
Run as a Kubernetes Deployment with a read-only service account. Expose the web UI via
an internal `Service`. Audit logs go to stdout for your existing log aggregator.

**Option C — Local install**
Each engineer installs on their own machine. Simple, but audit logs are fragmented.

### API Cost Estimate

K8sCopilot uses `claude-sonnet-4-6`. Typical incident investigation (4–6 tool calls):

| Query type | Approx. tokens | Approx. cost |
|------------|---------------|-------------|
| Simple pod list | ~2,000 | ~$0.003 |
| Full incident investigation (5 tool calls) | ~8,000 | ~$0.012 |
| 50 investigations/day (busy on-call) | ~400,000 | ~$0.60/day |

Monthly cost for a team running 50 investigations/day: **~$18/month**.

---

## Benefits

### For on-call engineers
- Cuts mean time to diagnosis (MTTD) by eliminating repetitive command sequences
- Works for engineers who know the problem domain but not the exact `kubectl` syntax
- Multi-turn context — follow-up questions build on previous findings without re-running
  commands or re-specifying the namespace/pod name

### For the team
- Junior engineers can investigate production confidently without senior escalation
- The web UI means no local setup — anyone can query the cluster from a browser
- Consistent investigation patterns replace ad-hoc muscle memory

### For the organisation
- Full audit trail of cluster queries and changes during incidents
- Faster, better-documented postmortems — the session log shows exactly what was checked
- Reduced on-call burnout from repetitive mechanical work

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM returns incorrect diagnosis | Medium | Low (read-only by default) | All raw tool output is available in verbose mode for verification; Claude is instructed to never fabricate |
| Engineer approves a write operation by mistake | Low | Medium | Default is `n`; exact kubectl command shown before approval; all actions logged and recoverable |
| Anthropic API outage | Low | Low (tool falls back gracefully) | K8sCopilot fails safely — engineers fall back to direct `kubectl` |
| API key exposure | Low | High | Store in environment variable or secrets manager, not in config file; rotate regularly |
| Excessive API spend | Low | Low | `max_tool_calls: 10` cap per query; cost is ~$0.01/investigation |
| Cluster credential exposure | Low | High | Kubeconfig scoped to read-only service account; web UI behind internal network |

---

## Proposed Rollout Plan

### Phase 1 — Internal pilot (Week 1–2)
- Deploy on a bastion host pointed at the **staging** cluster
- On-call team uses it alongside existing tooling for 2 weeks
- Collect feedback on query accuracy, missing tools, and UX

### Phase 2 — Production read-only (Week 3–4)
- Point at the **production** cluster with read-only access
- All engineers have access via the Streamlit web UI
- Write tools remain disabled

### Phase 3 — Production with write tools (Week 5+)
- Enable write tools (`--write` flag) for senior engineers only
- Namespace allowlist restricts writes to non-critical namespaces first
- Review audit log weekly for the first month

### Success metrics
- Reduction in mean time to diagnosis (MTTD) during incidents
- Reduction in senior engineer escalations during on-call
- Audit log query volume (proxy for adoption)

---

## Known Gaps (Honest Assessment)

These are real limitations to be aware of before going to production:

- **No web UI authentication** — the Streamlit app has no login. Must be deployed behind
  an internal network, VPN, or reverse proxy with auth before production use.
- **No Kubernetes RBAC manifest** — a service account with scoped permissions is not yet
  shipped. Currently relies on whatever credentials are in `~/.kube/config`.
- **No `kubectl apply`** — cannot push manifest changes. This is intentional for safety
  but limits usefulness for deployment workflows.
- **Single cluster** — no multi-cluster support yet. One instance per cluster.

All of these are tracked in [docs/GUARDRAILS.md](docs/GUARDRAILS.md) with planned fixes.

---

## Recommendation

Deploy K8sCopilot in **read-only mode on the staging cluster** for a two-week pilot.
The risk is low (no write access, full audit log, falls back to `kubectl` if unavailable),
and the potential upside — faster incident resolution and reduced on-call cognitive load —
is immediately measurable.

The two blockers before production with write tools are:
1. Put the web UI behind authentication (1–2 hours with nginx + basic auth)
2. Create a read-only Kubernetes service account for the tool (30 minutes)

Both are small investments for a significant improvement to the on-call experience.

---

## Links

- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — Technical design walkthrough
- [docs/GUARDRAILS.md](GUARDRAILS.md) — Full guardrails, gaps, and future improvements
- [examples/SESSIONS.md](../examples/SESSIONS.md) — Example query sessions
- [GitHub Repository](https://github.com/aniketmykaarma/k8s-Copilot)

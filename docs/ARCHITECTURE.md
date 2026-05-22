# K8sCopilot — Architecture

A walkthrough of how K8sCopilot is built and why.

## High-level flow

```
┌──────────────┐   user query (text)   ┌──────────────┐
│   CLI / Web  │ ───────────────────►  │    Agent     │
│              │                        │              │
│              │ ◄───── final text ──── │              │
└──────────────┘                        └──────┬───────┘
                                               │
                                ┌──────────────┼───────────────┐
                                │                              │
                          messages.create()              tool_use blocks
                                │                              │
                                ▼                              ▼
                       ┌─────────────────┐           ┌──────────────────┐
                       │   Anthropic     │           │  Tool Dispatcher │
                       │   Claude API    │           │                  │
                       │                 │           │  audit.log()     │
                       │  + tool defs    │           │  K8sClient.foo() │
                       └─────────────────┘           └────────┬─────────┘
                                                              │
                                                              ▼
                                                    ┌──────────────────┐
                                                    │ kubernetes-py    │
                                                    │ client           │
                                                    └────────┬─────────┘
                                                              │
                                                              ▼
                                                    ┌──────────────────┐
                                                    │  Kubernetes API  │
                                                    │  Server          │
                                                    └──────────────────┘
```

## The tool-use loop in detail

```
1. messages = [{"role": "user", "content": user_query}]
2. response = claude.messages.create(messages, tools=[...])
3. If response.stop_reason != "tool_use":
       return response.text  ← we're done
4. For each tool_use block:
       result = dispatch_tool(block.name, block.input)
       audit.log(...)
       tool_results.append({"tool_use_id": block.id, "content": result})
5. messages.append({"role": "assistant", "content": response.content})
   messages.append({"role": "user", "content": tool_results})
6. Goto 2 (up to config.max_tool_calls iterations).
```

### Why this design (the interview answer)

**Q: Why have Python tools at all? Why not let Claude run kubectl directly?**

Two reasons:
1. **Security.** Shell-out to `kubectl` opens command injection vectors. Python functions with typed parameters validate inputs before any cluster call.
2. **Control.** Each tool can enforce its own rules (read-only, output truncation, namespace allowlists) independent of what the LLM "wants" to do.

**Q: Why use the kubernetes-python client instead of subprocess to kubectl?**

- No shell parsing, no quoting issues, no PATH dependencies.
- Structured exceptions (`ApiException` with `.status`, `.reason`) instead of stderr text.
- Pagination, watches, label selectors are first-class — no string manipulation.
- The downside: a few outputs (notably `describe`) are nicer from kubectl. We reimplement them in `k8s_client.py` to match the human-readable format.

**Q: How do you prevent the LLM from hallucinating a tool name?**

The tool dispatcher is a fixed dict (`tool_dispatch`). If Claude returns a `tool_use` block with a name we don't have, we return an error string. The LLM sees the error and recovers in the next turn. This is defense in depth — the tool definitions are already declared upfront, so this branch should rarely fire.

**Q: How do you handle output that's too large?**

`k8s_client._truncate(lines, max_lines)`. Default cap is 50 lines per tool call. Cuts the tail and appends a "truncated" notice. This serves three goals:
- Saves Claude tokens (a 200-row pod list is ~5K tokens).
- Prevents Claude from getting confused by noise.
- Forces the LLM to refine queries (e.g. add a label selector) if results are big.

**Q: How do you handle multi-turn debugging across tool calls?**

The agent maintains a `messages` array that gets appended on every loop iteration:
- The assistant turn (containing Claude's text + tool_use blocks).
- The user turn (containing tool_results matching each tool_use_id).

Claude sees the full history every iteration, so it can chain: "I called `get_pods`, found a CrashLoopBackOff pod, now I'll call `describe_pod` and then `logs` with previous=true." This is standard Anthropic tool-use loop pattern — nothing magical.

## Configuration precedence

```
Defaults (in Config dataclass)
        ▼
~/.k8s-copilot/config.yaml (overrides matching keys)
        ▼
Environment variables (K8S_COPILOT_*, ANTHROPIC_API_KEY)
        ▼
CLI flags (--verbose, --config)
```

## Audit log format

JSONL — one event per line, append-only. Designed for `jq`-friendly downstream parsing:

```jsonl
{"ts":"2026-05-17T14:30:01Z","session_id":"a1b2c3d4","user_query":"failing pods","tool":"kubectl_get_pods","params":{"namespace":"orders"},"outcome":"success","duration_ms":142}
{"ts":"2026-05-17T14:30:03Z","session_id":"a1b2c3d4","user_query":"failing pods","tool":"kubectl_describe_pod","params":{"name":"orders-api-7f8d","namespace":"orders"},"outcome":"success","duration_ms":89}
```

Useful queries:
```bash
# All errors in the last day
jq 'select(.outcome=="error")' ~/.k8s-copilot/audit.log

# Most-used tools
jq -r .tool ~/.k8s-copilot/audit.log | sort | uniq -c | sort -rn

# Average duration per tool
jq -s 'group_by(.tool) | map({tool:.[0].tool, avg_ms:(map(.duration_ms)|add/length)})' \
  ~/.k8s-copilot/audit.log
```

## Safety: what's already in place

| Layer | Mechanism | Status |
|---|---|---|
| Tool catalog | Only read tools registered in v0.3 | ✅ |
| Tool dispatch | Unknown tool names rejected with error | ✅ |
| Output truncation | `max_output_lines` cap | ✅ |
| Loop cap | `max_tool_calls` (default 10) | ✅ |
| Audit log | All calls written to JSONL | ✅ |
| Approval gate | Write tools (scale, delete) — feature-flagged off | 🟡 v0.4 |
| Namespace allowlist | Optional restriction to specific namespaces | 🟡 v0.4 |
| Rate limiting | Cap on tool calls per minute | 🟡 v1.0 |

## Future extensions (mention if asked "what's next")

- **Write tools with approval gates.** Add `kubectl_scale_deployment`, `kubectl_delete_pod`, `kubectl_apply_manifest`. Each prints the action and prompts for confirmation in CLI. Web UI shows a confirm dialog.
- **Multi-cluster.** Pass kubeconfig context as a parameter to the agent; let the LLM ask "which cluster?" if ambiguous.
- **Streaming responses.** Use Anthropic's streaming API so users see Claude's reasoning unfold token-by-token.
- **Built-in runbooks.** Pre-canned multi-step procedures ("investigate slow service X") the agent can invoke via tool call.
- **OpenTelemetry integration.** Emit traces from the agent so you can see token usage, tool latency, and full session timelines in your existing observability stack.
- **Local model fallback.** Add an Ollama backend so the same code works against a local model when API access isn't available.

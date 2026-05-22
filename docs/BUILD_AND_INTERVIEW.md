# K8sCopilot Build Plan + Interview Prep

This document walks you through HOW to build K8sCopilot — file by file, hour by hour — and what to say about it in interviews.

---

## Build sequence

The codebase has 12 files. Build them in this order. Each milestone is a "you could stop here and have something working" checkpoint.

### Hour 0-1: Bootstrap

**Goal: empty repo, dependencies installed, hello-world working.**

```bash
mkdir k8s-copilot && cd k8s-copilot
git init
python3 -m venv .venv && source .venv/bin/activate

# Create directory structure
mkdir -p src/k8s_copilot tests docs examples
touch README.md requirements.txt pyproject.toml .gitignore
```

Files to add now (copy from the provided code):
- `.gitignore` (Python + IDE + .env)
- `requirements.txt`
- `pyproject.toml`
- `src/k8s_copilot/__init__.py`

```bash
pip install -e .
```

✅ **Checkpoint 1:** `pip list` shows `k8s-copilot` installed.

### Hour 1-3: Foundation — Config + Audit + K8s client

**Goal: can list pods from a kind cluster (no LLM yet).**

Add:
- `src/k8s_copilot/config.py`
- `src/k8s_copilot/audit.py`
- `src/k8s_copilot/k8s_client.py`

Test it manually:
```python
# In a python REPL
from k8s_copilot.k8s_client import K8sClient
client = K8sClient()
print(client.get_pods())   # Should print pods from your kind cluster
print(client.get_nodes())  # Should print nodes
```

If you don't have a kind cluster yet, create one:
```bash
brew install kind             # macOS
# or:  go install sigs.k8s.io/kind@latest
kind create cluster --name k8scopilot-demo
```

✅ **Checkpoint 2:** You can list pods from Python, before any AI involvement.

### Hour 3-5: Agent + tool-use loop

**Goal: ask a natural-language question, get an answer that involved a real cluster call.**

Add:
- `src/k8s_copilot/tools.py`
- `src/k8s_copilot/agent.py`

Test manually:
```python
from k8s_copilot.config import load_config
from k8s_copilot.agent import Agent

cfg = load_config()
agent = Agent(cfg)
print(agent.run("how many pods are running in this cluster?"))
```

You'll need `export ANTHROPIC_API_KEY=sk-ant-...` first. Get a key at console.anthropic.com — they give you starter credits.

✅ **Checkpoint 3 (the magic moment):** The agent answered a natural-language question by calling kubectl. This is when K8sCopilot becomes real.

### Hour 5-7: CLI polish

**Goal: `k8s-copilot "your query"` works end to end with nice output.**

Add:
- `src/k8s_copilot/cli.py`

Reinstall to get the entry point:
```bash
pip install -e .
which k8s-copilot   # Should show the binary
k8s-copilot "show me all pods"
k8s-copilot --interactive
k8s-copilot --verbose "list nodes"
```

✅ **Checkpoint 4 (shippable v0.3 CLI):** README, working CLI, tested against kind cluster. **You can git commit and push to GitHub here.** Your résumé has a real project.

### Hour 7-9: Polish — tests, docs, examples

Add:
- `tests/test_smoke.py`
- `docs/ARCHITECTURE.md`
- `examples/SESSIONS.md`

```bash
pip install pytest
pytest tests/   # Should pass
```

✅ **Checkpoint 5:** Tests pass. Documentation is complete. The README has screenshots.

### Hour 9-12 (Weekend 2): Web UI

Add:
- `src/k8s_copilot/web_app.py`
- `src/k8s_copilot/web_launcher.py`

```bash
pip install 'streamlit>=1.31.0'
k8s-copilot-web
# Opens browser at http://localhost:8501
```

✅ **Checkpoint 6 (shippable v0.3 final):** Web UI works. Tag this as v0.3 in git, push.

### Hour 12-15: Demo prep

- Run through every demo in `examples/SESSIONS.md`.
- Record a 60-second screen capture using Loom or QuickTime. Pin it as a featured GIF/video in the README.
- Take screenshots, add them to README near the demo sections.

✅ **Checkpoint 7 (interview-ready):** README has visuals. You can run a clean demo end-to-end in under 90 seconds.

---

## What's intentionally NOT in v0.3

When asked "what's missing?" or "what would you build next?", these are your honest answers:

- **Write tools (scale/delete/apply) with approval gates.** Designed but not implemented. v0.4 target.
- **Multi-cluster context switching.** Currently uses default kubeconfig. v0.4.
- **Streaming responses.** Currently blocks until Claude is fully done. v0.5.
- **Conversation memory across turns in interactive mode.** Each query is independent right now. v0.5.
- **Integration tests against a real cluster.** Tests are unit-only; CI would need a kind cluster. v1.0.
- **Cost tracking.** No tracking of Claude token usage per session. v1.0.

These gaps are **deliberate v1 scope decisions, not bugs.** Frame them that way in interviews.

---

## Résumé bullet (replace your existing Claude project bullet with this)

```
K8sCopilot — Natural-Language Kubernetes Operations Assistant | Python, Anthropic SDK, kubernetes-py, Streamlit
github.com/aniketchakrabarty7/k8s-copilot
• Built a Python agent that translates natural-language Kubernetes queries into safe
  kubectl operations using Anthropic Claude's tool-use API. Implements multi-step
  troubleshooting workflows (e.g., "why is orders unhealthy?" → list pods, describe
  the failing one, check logs and events, return a diagnosis).
• Read-only by default with a defined extension path for write operations gated by
  explicit approval prompts. Structured JSONL audit logging of every tool execution.
• Shipped both a CLI (Click + Rich) and a web UI (Streamlit). Installable via
  pip install -e . with proper package structure, tests, and architecture docs.
```

---

## Interview Q&A drill — questions you WILL get about K8sCopilot

Practice these out loud with the same mirror discipline you used for myKaarma stories.

### Q1. (THE BIG ONE) Walk me through K8sCopilot.

> "K8sCopilot is a Python agent I built that lets engineers ask Kubernetes questions in plain English — 'show me failing pods in orders' or 'why is the orders service unhealthy?' — and gets answers from the cluster. It uses Anthropic Claude's tool-use API, where I expose a small set of Python functions (get_pods, describe_pod, logs, events, get_deployments, get_nodes) as tools. Claude routes the query to the right tool, executes via the kubernetes-python client, and chains multiple calls for multi-step investigations. Everything is read-only in v1. Every tool execution writes to a JSONL audit log. The whole thing is roughly 800 lines of Python, runs as a CLI or a Streamlit web UI. The motivation was real — every incident I've been on involves the same kubectl sequence — get pods, describe the failing one, check logs, check events. The agent automates the navigation so you focus on the actual problem."

That's ~60 seconds.

### Q2. Why Anthropic Claude and not OpenAI?

> "Two reasons. First, Claude's tool-use API handles multi-step chains cleanly — the message-format with explicit tool_use_id matching makes it easy to track which result belongs to which call across loop iterations. Second, I had existing experience with the SDK, so iteration was faster. Honestly, OpenAI's function calling would work just as well; this isn't a deep technical differentiator. The interesting bits are the tool design and the safety model, not which provider hosts the LLM."

### Q3. What stops Claude from running `kubectl delete` and nuking my cluster?

> "Three layers. First, the tool catalog itself — in v1 I only registered read tools (get_pods, describe_pod, logs, events, get_deployments, get_nodes). Write tools like scale, delete, apply aren't in the catalog at all, so Claude literally can't call them. Second, when those tools are added in v0.4, they'll be feature-flagged off by default in config, requiring an explicit `enable_write_tools: true`. Third, even when enabled, the dispatcher will print the exact action and require an explicit Y/N confirmation before calling the cluster. Defense in depth — the LLM is one layer, the tool wrapper is another, the user confirmation is the third."

### Q4. How do you handle huge outputs? `kubectl get pods -A` on a real cluster could be thousands of rows.

> "Output truncation in the tool layer. Every tool caps its return at max_output_lines, configurable but defaulting to 50. Cuts the tail and adds a 'truncated; refine your query' notice. Three benefits: saves tokens (a 500-row pod list is 10K+ tokens we don't need), prevents the LLM from getting confused by noise, and nudges the agent to use selectors instead of returning everything. If the user explicitly wants the full list, they can raise the cap via config."

### Q5. How does the multi-step loop work?

> "Standard Anthropic tool-use pattern. The agent maintains a messages array. Each iteration: send messages + tool definitions to Claude, get a response. If response.stop_reason is 'end_turn', we're done — return the text. If it's 'tool_use', extract every tool_use block, dispatch each one to the matching Python function, collect tool_result blocks with matching tool_use_ids, append the assistant turn AND a new user turn containing the tool_results, then loop. Capped at max_tool_calls iterations — default 10 — as a safety guard against runaway loops."

### Q6. What if a tool fails — say the cluster is unreachable?

> "Three failure modes. ApiException from the kubernetes client — caught and returned as 'ERROR: <reason> (status <code>)' string. Generic Python exception — caught one level up in the agent, returned as 'ERROR executing <tool>: <exception type>: <message>'. Anthropic API failure — propagates up and is caught in the CLI, printed to the user as an error. In all cases, audit logs record outcome='error' with the error message, so failures are visible after the fact. The LLM also sees the error text in the tool_result and can recover — e.g., if it asked for a pod that doesn't exist, it'll see the error and ask the user to clarify rather than barging on."

### Q7. Why not just use kubectl-ai or k8sgpt — those exist?

> "Yeah, those exist and they're cool. The reason to build my own: I wanted to understand the tool-use pattern deeply, control the exact safety model end-to-end, and have a project I can talk about authentically. There's also a real distinction — k8sgpt is great for diagnostic summaries on a fixed set of resources, but it isn't an interactive agent that chains arbitrary investigations. K8sCopilot is closer to having a junior SRE who can navigate the cluster for you, where k8sgpt is a one-shot 'analyze my cluster' tool. Different shapes of solution to overlapping problems."

### Q8. How do you test it without a real cluster?

> "Two levels. Unit tests in tests/test_smoke.py — they test things like output truncation, config loading, audit logging, and timer correctness. No cluster needed, runs in CI in seconds. Integration testing is manual right now — I have a kind cluster setup script in examples/SESSIONS.md that seeds a known-good + known-broken state, then I run a fixed set of queries and verify the agent's behavior. For a production deployment I'd want automated integration tests against a kind cluster in CI, plus eval suites that score the agent's diagnostic accuracy on canned scenarios. Both are on the v1.0 roadmap."

### Q9. What was the hardest part to build?

> "Honestly, getting the tool-use loop's message structure right. The pattern is straightforward once you understand it — the assistant turn contains content blocks including tool_use blocks, and the user reply has to contain matching tool_result blocks with the same tool_use_id — but the first time you implement it, you can easily get into a state where Claude is confused because the message history doesn't match what it expects. I debugged this by adding verbose logging that printed every message before sending. Once I saw the structure clearly, it clicked. The other tricky part was designing the tools themselves — choosing tool boundaries that are large enough to be useful but small enough that the LLM uses them correctly. For example, I considered a single 'kubectl' tool that accepts arbitrary commands, but that pushes too much into the LLM's hands. Splitting into specific verbs (get_pods, describe_pod, etc.) gave me cleaner control."

### Q10. If you had unlimited time, what would you build next?

> "Three things in priority order. One: write tools with proper approval gates and probably an undo mechanism — so the agent can actually fix things, not just diagnose them. Two: built-in runbooks — pre-canned multi-step procedures the agent can invoke as a single tool ('run the standard slow-service investigation'). This combines the benefits of LLM flexibility with the reliability of scripted workflows. Three: OpenTelemetry instrumentation so the agent's own behavior is observable — token usage per session, tool latency distributions, accuracy metrics if I add an eval suite. Past those: multi-cluster support, real conversation memory across turns, and possibly an alternative backend using a local model for environments where the API isn't available."

---

## Talking points by interview type

### For a senior DevOps role
Emphasize: safety design, audit log, kubernetes-python over shell-out, defense-in-depth. Walk through Q3 and Q4 carefully.

### For a platform engineering / SRE role
Emphasize: the multi-step troubleshooting pattern (the killer demo), the parallel between this agent's design and incident response work you've done at myKaarma. "I built this because I'd done the manual version of this debugging too many times."

### For an AI engineer or AI infra role
Emphasize: tool-use loop mechanics, output truncation for token efficiency, the tool boundary design tradeoff (one big tool vs many specific tools). Q5 and Q9 carry the weight here.

### For a startup wearing-many-hats role
Emphasize: full-stack ownership — CLI to web UI, packaging, docs, tests. "I shipped this end-to-end as one engineer over two weekends" is a strong signal.

---

## Common interviewer follow-ups you should be ready for

- **"Have you tried this against a really big cluster?"** Honest: "I've tested against a multi-node kind cluster. Haven't run it against thousands of pods yet — the output truncation logic is there for it, but I'd want to see how the LLM handles repeated truncation feedback in a real big-cluster session before claiming it scales."
- **"How much does this cost to run per query?"** A single-tool-call query is roughly $0.01-0.03 with Sonnet 4. A multi-step debug session might be $0.05-0.15. Cheap for occasional use, but the model choice and prompt size matter — I'd switch to Haiku for high-volume use cases.
- **"What if Anthropic changes their tool-use API?"** The Anthropic SDK abstracts most of it; minor version bumps usually require small changes. I'd add a thin internal interface between my agent and the SDK to make backend swaps easier if I were extending this further.

---

## What to push to GitHub

```bash
git add .
git commit -m "Initial v0.3 release: CLI + Web UI"
git remote add origin https://github.com/aniketchakrabarty7/k8s-copilot.git
git push -u origin main
git tag v0.3.0
git push --tags
```

In the README, pin a 30-second demo GIF (use https://www.cockos.com/licecap/ to record one). That single visual at the top makes the difference between "interesting" and "I have to try this."

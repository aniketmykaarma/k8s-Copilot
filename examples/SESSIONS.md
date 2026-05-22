# Example Sessions

These are the demo scripts you'll use in interviews. Each shows a real K8sCopilot interaction against a kind cluster.

## Setup (one-time)

```bash
# Create a kind cluster with multiple nodes
kind create cluster --name k8scopilot-demo --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
  - role: worker
EOF

# Deploy some sample workloads
kubectl create namespace orders
kubectl create namespace inventory

# A healthy deployment
kubectl create deployment orders-api --image=nginx:latest -n orders --replicas=3

# A broken deployment (image pull error — use a non-existent image)
kubectl create deployment orders-worker --image=nonexistent:fake -n orders

# Another healthy one
kubectl create deployment inventory-api --image=nginx:latest -n inventory --replicas=2

# Verify
kubectl get pods -A
```

## Demo 1: Single-shot query

```bash
$ k8s-copilot "show me all the failing pods in the cluster"
```

Expected behavior:
- Calls `kubectl_get_pods` with `field_selector="status.phase!=Running"` and no namespace.
- Returns a list including the `orders-worker-*` pod stuck in ImagePullBackOff.
- Final answer: brief summary identifying the broken pod and reason.

## Demo 2: Multi-step troubleshooting (the killer demo)

```bash
$ k8s-copilot "why is the orders-worker deployment unhealthy?"
```

Expected behavior:
1. Calls `kubectl_get_deployments` filtered to namespace=`orders`.
2. Sees `orders-worker` has 0/1 ready replicas.
3. Calls `kubectl_get_pods` for that deployment's pods.
4. Sees `orders-worker-XXX` in ImagePullBackOff.
5. Calls `kubectl_describe_pod` on that pod.
6. Calls `kubectl_get_events` namespace=`orders` for context.
7. Final answer: "The orders-worker deployment is failing because the container image `nonexistent:fake` doesn't exist in the registry. Events show repeated ErrImagePull. Fix: update the image reference in the deployment spec."

THIS IS THE SEQUENCE TO DEMO IN INTERVIEWS. The chained reasoning is what makes the project memorable.

## Demo 3: Interactive mode

```bash
$ k8s-copilot --interactive
```

Then ask:
```
> what's running in this cluster?
> show me deployments only
> any deployments unhealthy?
> investigate the unhealthy one
> exit
```

Each turn is a new query with no shared context (v0.3) — future versions add multi-turn memory.

## Demo 4: Verbose mode (for the audience to see what's happening)

```bash
$ k8s-copilot --verbose "list nodes and their status"
```

In verbose mode you see every tool call and its raw output. Good for technical-deep-dive interviews where the interviewer wants to see the mechanics.

## Demo 5: Web UI

```bash
$ k8s-copilot-web
```

Opens in browser at http://localhost:8501. Type queries in the chat box. Tool calls render in expandable boxes, final answers as markdown.

## Cleanup

```bash
kind delete cluster --name k8scopilot-demo
```

## Tips for the interview demo

- **Have the cluster pre-created and pre-seeded.** Don't waste interview time on setup.
- **Pre-run Demo 2 once before the interview to warm up your terminal scrollback.** You'll be more comfortable.
- **Lead with Demo 2.** Skip the trivial single-query one — go straight to the multi-step chain. That's what's impressive.
- **Don't over-narrate.** Run the command, let the output speak. Pause for questions instead of explaining every line.
- **Have the audit log open in a second terminal.** When asked about safety, switch terminals and show the JSONL stream — it's a great "I treated this as production tooling" moment.

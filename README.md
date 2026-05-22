# k8s-Copilot
CLI and web assistant that turns plain-English Kubernetes queries ("show me crashing pods in prod") into safe kubectl operations via an LLM with tool-use. Chains multi-step investigations — find failing pod → check logs → identify root cause. Read-only by default; write operations require explicit human approval.

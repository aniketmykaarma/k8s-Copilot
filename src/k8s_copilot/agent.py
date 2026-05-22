"""The agent core: handles the Claude tool-use loop.

The loop:
    1. Send user query + conversation history + tool definitions to Claude.
    2. Claude either responds with text (done) or with tool_use blocks.
    3. For each tool_use, dispatch to the K8sClient method, capture output.
    4. Write tools first emit an approval_required event and call on_approval;
       the operation is skipped if approval is denied.
    5. Send tool_result blocks back to Claude.
    6. Repeat until Claude returns a text-only response (or max_tool_calls is hit).

Multi-turn: callers pass in messages from the previous turn and receive the
updated list back, enabling persistent conversation context in REPL mode.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from anthropic import Anthropic
from anthropic.types import Message, ToolUseBlock

from .audit import AuditLogger, Timer
from .config import Config
from .k8s_client import K8sClient
from .tools import READ_TOOLS, WRITE_TOOLS, WRITE_TOOL_NAMES, SYSTEM_PROMPT, command_display


# on_event(event_type, payload) — called as activity happens so the UI can stream output.
# Event types: 'tool_call', 'tool_result', 'approval_required', 'text'
EventHandler = Optional[Callable[[str, Dict], None]]

# on_approval(tool_name, command_display, tool_input) → bool
# Return True to allow the write operation, False to deny it.
ApprovalHandler = Optional[Callable[[str, str, Dict], bool]]


class Agent:
    """Orchestrates the tool-use loop between Claude and the Kubernetes client."""

    def __init__(
        self,
        config: Config,
        k8s_client: Optional[K8sClient] = None,
        audit: Optional[AuditLogger] = None,
    ):
        self.config = config
        self.client = Anthropic(api_key=config.anthropic_api_key)
        self.k8s = k8s_client or K8sClient(
            kubeconfig_path=str(config.kubeconfig_path) if config.kubeconfig_path else None,
            max_lines=config.max_output_lines,
        )
        self.audit = audit or AuditLogger(config.log_path)

        self.tool_dispatch: Dict[str, Callable] = {
            "kubectl_get_pods": self.k8s.get_pods,
            "kubectl_describe_pod": self.k8s.describe_pod,
            "kubectl_logs": self.k8s.get_logs,
            "kubectl_get_deployments": self.k8s.get_deployments,
            "kubectl_get_nodes": self.k8s.get_nodes,
            "kubectl_get_events": self.k8s.get_events,
        }

        self.tools = list(READ_TOOLS)

        if config.enable_write_tools:
            self.tools = self.tools + list(WRITE_TOOLS)
            self.tool_dispatch.update({
                "kubectl_delete_pod": self.k8s.delete_pod,
                "kubectl_scale_deployment": self.k8s.scale_deployment,
                "kubectl_rollout_restart": self.k8s.rollout_restart,
            })

    def run(
        self,
        user_query: str,
        messages: Optional[List] = None,
        on_event: EventHandler = None,
        on_approval: ApprovalHandler = None,
    ) -> Tuple[str, List]:
        """
        Execute one query end-to-end. Returns (final_text, updated_messages).

        Pass messages from a previous run to maintain conversation context (REPL mode).
        on_event(event_type, payload) is called as activity happens.
        on_approval(tool_name, command, input) must return True to execute a write tool.
        """
        if messages is None:
            messages = []

        messages = messages + [{"role": "user", "content": user_query}]
        last_response: Optional[Message] = None

        for _ in range(self.config.max_tool_calls):
            last_response = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=SYSTEM_PROMPT,
                tools=self.tools,
                messages=messages,
            )

            messages = messages + [{"role": "assistant", "content": last_response.content}]

            if last_response.stop_reason != "tool_use":
                final_text = _extract_text(last_response)
                if on_event:
                    on_event("text", {"text": final_text})
                return final_text, messages

            tool_results = []
            for block in last_response.content:
                if not isinstance(block, ToolUseBlock):
                    continue

                tool_name = block.name
                tool_input = block.input or {}

                if on_event:
                    on_event("tool_call", {"tool": tool_name, "input": tool_input})

                # Write tools require explicit human approval before execution.
                if tool_name in WRITE_TOOL_NAMES:
                    cmd = command_display(tool_name, tool_input)
                    if on_event:
                        on_event("approval_required", {"tool": tool_name, "command": cmd})

                    approved = on_approval(tool_name, cmd, tool_input) if on_approval else True

                    if not approved:
                        result_text = "Operation declined by user."
                        self.audit.log(
                            user_query=user_query,
                            tool=tool_name,
                            params=tool_input,
                            outcome="denied",
                            duration_ms=0,
                        )
                        if on_event:
                            on_event("tool_result", {"tool": tool_name, "result": result_text})
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        })
                        continue

                result_text = self._dispatch_tool(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    user_query=user_query,
                )

                if on_event:
                    on_event("tool_result", {"tool": tool_name, "result": result_text})

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

            messages = messages + [{"role": "user", "content": tool_results}]

        warn = (
            f"\n\n[warning: max_tool_calls={self.config.max_tool_calls} reached; "
            "conversation may be incomplete.]"
        )
        final_text = (_extract_text(last_response) if last_response else "") + warn
        return final_text, messages

    def _dispatch_tool(
        self,
        tool_name: str,
        tool_input: Dict,
        user_query: str,
    ) -> str:
        """Invoke a tool, log it, return its text output."""
        fn = self.tool_dispatch.get(tool_name)
        if fn is None:
            err = f"Unknown tool: {tool_name}"
            self.audit.log(
                user_query=user_query,
                tool=tool_name,
                params=tool_input,
                outcome="error",
                duration_ms=0,
                error=err,
            )
            return f"ERROR: {err}"

        with Timer() as t:
            try:
                filtered = {k: v for k, v in tool_input.items() if v is not None}
                output = fn(**filtered)
                outcome = "success"
                error = None
            except Exception as e:
                output = f"ERROR executing {tool_name}: {type(e).__name__}: {e}"
                outcome = "error"
                error = str(e)

        self.audit.log(
            user_query=user_query,
            tool=tool_name,
            params=tool_input,
            outcome=outcome,
            duration_ms=t.duration_ms,
            error=error,
        )
        return output


def _extract_text(response: Message) -> str:
    """Pull text from a Claude response, joining multi-block text."""
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()

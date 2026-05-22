"""Smoke tests for K8sCopilot.

These are intentionally light — they test that our code paths don't crash,
not that they correctly interact with a real cluster. For real-cluster tests,
spin up a kind cluster and run the manual scenarios in examples/.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from k8s_copilot.audit import AuditLogger, Timer
from k8s_copilot.config import Config, load_config
from k8s_copilot.k8s_client import _age_short, _truncate


def test_truncate_short_list():
    """Lists shorter than max_lines should pass through unchanged."""
    lines = ["a", "b", "c"]
    out = _truncate(lines, max_lines=10)
    assert out == "a\nb\nc"


def test_truncate_long_list():
    """Lists longer than max_lines should be cut and annotated."""
    lines = [str(i) for i in range(100)]
    out = _truncate(lines, max_lines=10)
    assert "0" in out
    assert "9" in out
    assert "10" not in out.split("\n")[:10]
    assert "truncated" in out


def test_age_short_with_none():
    """Defensive handling of None timestamps."""
    assert _age_short(None) == "?"


def test_config_loads_defaults():
    """Config should populate sane defaults when no file/env present."""
    with patch.dict("os.environ", {}, clear=True):
        cfg = load_config()
        assert cfg.model.startswith("claude")
        assert cfg.max_tool_calls > 0
        assert cfg.enable_write_tools is False


def test_config_env_override():
    """Env vars should override defaults."""
    with patch.dict(
        "os.environ",
        {"ANTHROPIC_API_KEY": "test-key", "K8S_COPILOT_MAX_TOOL_CALLS": "5"},
    ):
        cfg = load_config()
        assert cfg.anthropic_api_key == "test-key"
        assert cfg.max_tool_calls == 5


def test_audit_logger_writes_jsonl(tmp_path: Path):
    """Audit log should be valid JSONL we can parse back."""
    log_path = tmp_path / "audit.log"
    logger = AuditLogger(log_path)

    logger.log(
        user_query="test query",
        tool="kubectl_get_pods",
        params={"namespace": "default"},
        outcome="success",
        duration_ms=42,
    )

    assert log_path.exists()
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "kubectl_get_pods"
    assert entry["params"] == {"namespace": "default"}
    assert entry["outcome"] == "success"
    assert entry["duration_ms"] == 42
    assert "ts" in entry
    assert "session_id" in entry


def test_audit_logger_records_errors(tmp_path: Path):
    """Errors should be captured with the error message."""
    log_path = tmp_path / "audit.log"
    logger = AuditLogger(log_path)

    logger.log(
        user_query="bad query",
        tool="kubectl_get_pods",
        params={},
        outcome="error",
        duration_ms=10,
        error="connection refused",
    )

    entry = json.loads(log_path.read_text().strip())
    assert entry["outcome"] == "error"
    assert entry["error"] == "connection refused"


def test_timer():
    """Timer should record some non-negative duration."""
    with Timer() as t:
        sum(range(100))
    assert t.duration_ms >= 0


# ------------------------------------------------------------------ #
# Write tools / approval gate
# ------------------------------------------------------------------ #

from k8s_copilot.tools import WRITE_TOOLS, WRITE_TOOL_NAMES, command_display


def test_write_tools_populated():
    """WRITE_TOOLS must have entries and WRITE_TOOL_NAMES must match."""
    assert len(WRITE_TOOLS) > 0
    assert WRITE_TOOL_NAMES == {t["name"] for t in WRITE_TOOLS}


def test_command_display_delete_pod():
    assert command_display("kubectl_delete_pod", {"name": "my-pod", "namespace": "prod"}) == \
        "kubectl delete pod my-pod -n prod"


def test_command_display_scale():
    assert command_display(
        "kubectl_scale_deployment",
        {"name": "api", "namespace": "staging", "replicas": 3},
    ) == "kubectl scale deployment/api -n staging --replicas=3"


def test_command_display_rollout_restart():
    assert command_display(
        "kubectl_rollout_restart",
        {"name": "worker", "namespace": "jobs"},
    ) == "kubectl rollout restart deployment/worker -n jobs"


def test_agent_registers_write_tools_when_enabled():
    """Agent should include write tools in its tool list when enable_write_tools=True."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        cfg = load_config()
        cfg.enable_write_tools = True

    from k8s_copilot.agent import Agent
    from k8s_copilot.k8s_client import K8sClient

    mock_k8s = MagicMock(spec=K8sClient)
    agent = Agent(cfg, k8s_client=mock_k8s)

    tool_names = {t["name"] for t in agent.tools}
    assert "kubectl_delete_pod" in tool_names
    assert "kubectl_scale_deployment" in tool_names
    assert "kubectl_rollout_restart" in tool_names


def test_agent_omits_write_tools_by_default():
    """Write tools must NOT be available unless explicitly enabled."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        cfg = load_config()

    from k8s_copilot.agent import Agent
    from k8s_copilot.k8s_client import K8sClient

    mock_k8s = MagicMock(spec=K8sClient)
    agent = Agent(cfg, k8s_client=mock_k8s)

    tool_names = {t["name"] for t in agent.tools}
    assert "kubectl_delete_pod" not in tool_names


def test_approval_denied_skips_execution():
    """When on_approval returns False, the tool must not be called."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        cfg = load_config()
        cfg.enable_write_tools = True

    from k8s_copilot.agent import Agent
    from k8s_copilot.k8s_client import K8sClient
    from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

    mock_k8s = MagicMock(spec=K8sClient)
    agent = Agent(cfg, k8s_client=mock_k8s)

    # First response: Claude requests a write tool
    tool_block = MagicMock(spec=ToolUseBlock)
    tool_block.type = "tool_use"
    tool_block.id = "tu_123"
    tool_block.name = "kubectl_delete_pod"
    tool_block.input = {"name": "bad-pod", "namespace": "prod"}

    # Second response: Claude acknowledges the denial
    text_block = MagicMock(spec=TextBlock)
    text_block.type = "text"
    text_block.text = "Understood, operation was declined."

    first_msg = MagicMock(spec=Message)
    first_msg.stop_reason = "tool_use"
    first_msg.content = [tool_block]

    second_msg = MagicMock(spec=Message)
    second_msg.stop_reason = "end_turn"
    second_msg.content = [text_block]

    with patch.object(agent.client.messages, "create", side_effect=[first_msg, second_msg]):
        answer, _ = agent.run(
            "delete bad-pod",
            on_approval=lambda *_: False,  # always deny
        )

    # The actual k8s delete method must never have been called
    mock_k8s.delete_pod.assert_not_called()
    assert "declined" in answer.lower() or answer  # agent responded after denial


def test_approval_approved_calls_tool():
    """When on_approval returns True, the tool should be dispatched."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        cfg = load_config()
        cfg.enable_write_tools = True

    from k8s_copilot.agent import Agent
    from k8s_copilot.k8s_client import K8sClient
    from anthropic.types import Message, TextBlock, ToolUseBlock

    mock_k8s = MagicMock(spec=K8sClient)
    mock_k8s.delete_pod.return_value = "Pod 'bad-pod' deleted."
    agent = Agent(cfg, k8s_client=mock_k8s)

    tool_block = MagicMock(spec=ToolUseBlock)
    tool_block.type = "tool_use"
    tool_block.id = "tu_456"
    tool_block.name = "kubectl_delete_pod"
    tool_block.input = {"name": "bad-pod", "namespace": "prod"}

    text_block = MagicMock(spec=TextBlock)
    text_block.type = "text"
    text_block.text = "Pod deleted successfully."

    first_msg = MagicMock(spec=Message)
    first_msg.stop_reason = "tool_use"
    first_msg.content = [tool_block]

    second_msg = MagicMock(spec=Message)
    second_msg.stop_reason = "end_turn"
    second_msg.content = [text_block]

    with patch.object(agent.client.messages, "create", side_effect=[first_msg, second_msg]):
        answer, _ = agent.run(
            "delete bad-pod",
            on_approval=lambda *_: True,  # always approve
        )

    mock_k8s.delete_pod.assert_called_once_with(name="bad-pod", namespace="prod")


def test_multi_turn_messages_accumulate():
    """Messages from a previous turn should be prepended so Claude has context."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        cfg = load_config()

    from k8s_copilot.agent import Agent
    from k8s_copilot.k8s_client import K8sClient
    from anthropic.types import Message, TextBlock

    mock_k8s = MagicMock(spec=K8sClient)
    agent = Agent(cfg, k8s_client=mock_k8s)

    text_block = MagicMock(spec=TextBlock)
    text_block.type = "text"
    text_block.text = "Here is the answer."

    response = MagicMock(spec=Message)
    response.stop_reason = "end_turn"
    response.content = [text_block]

    captured_calls = []

    def fake_create(**kwargs):
        captured_calls.append(kwargs["messages"])
        return response

    with patch.object(agent.client.messages, "create", side_effect=fake_create):
        _, messages_after_turn1 = agent.run("first question")
        assert len(captured_calls) == 1
        assert captured_calls[0][0]["content"] == "first question"

        # Second turn passes messages back in
        _, messages_after_turn2 = agent.run("follow-up question", messages=messages_after_turn1)
        assert len(captured_calls) == 2
        # The second call should include the first turn's exchange
        second_call_messages = captured_calls[1]
        contents = [m["content"] for m in second_call_messages]
        assert "first question" in contents
        assert "follow-up question" in contents

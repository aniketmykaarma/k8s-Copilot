"""Configuration management for K8sCopilot.

Loads config in this order of precedence (later overrides earlier):
    1. Built-in defaults
    2. ~/.k8s-copilot/config.yaml (if exists)
    3. Environment variables (K8S_COPILOT_*)
    4. CLI flags (handled in cli.py)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".k8s-copilot" / "config.yaml"
DEFAULT_LOG_PATH = Path.home() / ".k8s-copilot" / "audit.log"


@dataclass
class Config:
    """Runtime configuration for K8sCopilot."""

    # LLM
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    anthropic_api_key: Optional[str] = None

    # Behavior
    max_tool_calls: int = 10          # safety cap on tool-use loop
    max_output_lines: int = 50        # truncate kubectl output before sending to LLM
    enable_write_tools: bool = False  # gate destructive operations

    # Paths
    log_path: Path = field(default_factory=lambda: DEFAULT_LOG_PATH)
    kubeconfig_path: Optional[Path] = None  # None => use default ~/.kube/config

    # UX
    verbose: bool = False             # show tool calls in CLI output

    def __post_init__(self) -> None:
        # Ensure log directory exists
        self.log_path = Path(self.log_path).expanduser()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.kubeconfig_path:
            self.kubeconfig_path = Path(self.kubeconfig_path).expanduser()


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load configuration from file, env, and defaults."""
    cfg = Config()

    # Step 1: Load from YAML if present
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)

    # Step 2: Override with env vars
    env_mapping = {
        "ANTHROPIC_API_KEY": "anthropic_api_key",
        "K8S_COPILOT_MODEL": "model",
        "K8S_COPILOT_LOG_PATH": "log_path",
        "K8S_COPILOT_MAX_TOOL_CALLS": "max_tool_calls",
        "K8S_COPILOT_MAX_OUTPUT_LINES": "max_output_lines",
        "K8S_COPILOT_ENABLE_WRITE_TOOLS": "enable_write_tools",
        "KUBECONFIG": "kubeconfig_path",
    }
    for env_key, cfg_key in env_mapping.items():
        if env_key in os.environ:
            raw = os.environ[env_key]
            current = getattr(cfg, cfg_key)
            if isinstance(current, bool):
                setattr(cfg, cfg_key, raw.lower() in ("1", "true", "yes"))
            elif isinstance(current, int):
                setattr(cfg, cfg_key, int(raw))
            else:
                setattr(cfg, cfg_key, raw)

    # Trigger __post_init__ logic again after env overrides
    cfg.log_path = Path(cfg.log_path).expanduser()
    cfg.log_path.parent.mkdir(parents=True, exist_ok=True)

    return cfg


def require_api_key(cfg: Config) -> str:
    """Return API key or raise a helpful error."""
    if not cfg.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set.\n"
            "Set it via:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "or put it in ~/.k8s-copilot/config.yaml under 'anthropic_api_key:'"
        )
    return cfg.anthropic_api_key

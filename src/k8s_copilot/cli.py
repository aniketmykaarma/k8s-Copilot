"""K8sCopilot CLI.

Usage:
    k8s-copilot "show me failing pods in orders"
    k8s-copilot --interactive
    k8s-copilot --verbose "what's wrong with the orders service?"
    k8s-copilot --write "restart the api-gateway deployment in staging"
"""

import sys
from typing import List, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.text import Text

from .agent import Agent
from .config import load_config, require_api_key

console = Console()


def _print_tool_call(tool: str, params: dict, verbose: bool) -> None:
    if verbose:
        param_str = ", ".join(f"{k}={v!r}" for k, v in params.items()) or "(no args)"
        console.print(f"[dim cyan]→ {tool}({param_str})[/dim cyan]")
    else:
        console.print(f"[dim cyan]→ {tool}[/dim cyan]")


def _print_tool_result(tool: str, result: str, verbose: bool) -> None:
    if verbose:
        display = result if len(result) < 2000 else result[:2000] + "\n... [truncated for display]"
        console.print(
            Panel(
                Syntax(display, "text", theme="ansi_dark", word_wrap=False),
                title=f"output: {tool}",
                title_align="left",
                border_style="dim",
            )
        )


def _make_event_handler(verbose: bool):
    def handler(event_type: str, payload: dict) -> None:
        if event_type == "tool_call":
            _print_tool_call(payload["tool"], payload.get("input", {}), verbose)
        elif event_type == "tool_result":
            _print_tool_result(payload["tool"], payload["result"], verbose)

    return handler


def _make_approval_handler():
    """Interactive y/n prompt shown before any write operation executes."""
    def handler(tool_name: str, command: str, tool_input: dict) -> bool:
        console.print()
        console.print(
            Panel(
                f"[bold yellow]Write operation requested[/bold yellow]\n\n"
                f"  [dim]$[/dim] [cyan]{command}[/cyan]",
                border_style="yellow",
                padding=(1, 2),
            )
        )
        try:
            answer = Prompt.ask(
                "Execute this command?",
                choices=["y", "n"],
                default="n",
            )
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        console.print()
        if answer == "y":
            console.print("[dim green]Executing...[/dim green]\n")
            return True
        console.print("[dim]Operation declined.[/dim]\n")
        return False

    return handler


@click.command()
@click.argument("query", required=False)
@click.option("-i", "--interactive", is_flag=True, help="Start interactive REPL mode.")
@click.option("-v", "--verbose", is_flag=True, help="Show tool call inputs and outputs.")
@click.option(
    "-w", "--write", is_flag=True,
    help="Enable write operations (scale, delete, rollout restart). Prompts for approval.",
)
@click.option(
    "--config", "config_path", type=click.Path(), default=None,
    help="Path to YAML config file (default: ~/.k8s-copilot/config.yaml).",
)
def main(
    query: Optional[str],
    interactive: bool,
    verbose: bool,
    write: bool,
    config_path: Optional[str],
) -> None:
    """K8sCopilot — ask Kubernetes questions in plain English."""
    try:
        cfg = load_config(config_path)
        cfg.verbose = verbose
        if write:
            cfg.enable_write_tools = True
        require_api_key(cfg)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    try:
        agent = Agent(cfg)
    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {type(e).__name__}: {e}[/red]")
        console.print(
            "[yellow]Hint: check that ~/.kube/config exists and points to a "
            "reachable cluster.[/yellow]"
        )
        sys.exit(1)

    event_handler = _make_event_handler(verbose)
    approval_handler = _make_approval_handler() if cfg.enable_write_tools else None

    if interactive:
        _run_interactive(agent, event_handler, approval_handler)
    elif query:
        _run_single(agent, query, event_handler, approval_handler)
    else:
        console.print(
            "[yellow]Provide a query or use --interactive. "
            "Run with --help for usage.[/yellow]"
        )
        sys.exit(1)


def _run_single(agent: Agent, query: str, event_handler, approval_handler) -> None:
    console.print(f"[bold]Query:[/bold] {query}\n")
    with console.status("[dim]Thinking...[/dim]", spinner="dots"):
        answer, _ = agent.run(
            query,
            on_event=event_handler,
            on_approval=approval_handler,
        )
    console.print()
    console.print(Panel(Text(answer), title="K8sCopilot", border_style="green"))


def _run_interactive(agent: Agent, event_handler, approval_handler) -> None:
    """REPL: maintains conversation context across queries. Ctrl+D or 'exit' to quit."""
    write_note = " [yellow](write mode on)[/yellow]" if agent.config.enable_write_tools else ""
    console.print(
        Panel(
            f"[bold green]K8sCopilot — interactive mode[/bold green]{write_note}\n"
            "Type your question and press Enter.\n"
            "[dim]/clear[/dim] to reset context  •  [dim]/exit[/dim] or Ctrl+D to quit",
            border_style="green",
        )
    )

    messages: List = []

    while True:
        try:
            query = console.input("\n[bold cyan]>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            return

        if not query:
            continue
        if query.lower() in ("exit", "quit", "/exit", "/q", ":q"):
            console.print("[dim]Goodbye.[/dim]")
            return
        if query.lower() in ("/clear", "/reset"):
            messages = []
            console.print("[dim]Conversation context cleared.[/dim]")
            continue

        try:
            answer, messages = agent.run(
                query,
                messages=messages,
                on_event=event_handler,
                on_approval=approval_handler,
            )
            console.print()
            console.print(Panel(Text(answer), title="K8sCopilot", border_style="green"))
        except Exception as e:
            console.print(f"[red]Error: {type(e).__name__}: {e}[/red]")


if __name__ == "__main__":
    main()

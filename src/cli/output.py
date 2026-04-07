"""
Terminal output helpers for FlowCoder CLI agent.

Provides formatted output using ANSI escape codes. No external dependencies.
"""

import sys

# ANSI escape codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"


def stream_text(text: str) -> None:
    """Write streaming text to stdout without newline (for real-time streaming)."""
    sys.stdout.write(text)
    sys.stdout.flush()


def stream_end() -> None:
    """End a streaming section with newline."""
    sys.stdout.write("\n\n")
    sys.stdout.flush()


def print_system(message: str) -> None:
    """Print a system/status message (dimmed)."""
    print(f"{_DIM}{message}{_RESET}")


def print_error(message: str) -> None:
    """Print an error message (red)."""
    print(f"{_RED}{message}{_RESET}")


def print_success(message: str) -> None:
    """Print a success message (green)."""
    print(f"{_GREEN}{message}{_RESET}")


def print_user_echo(message: str) -> None:
    """Echo the user's message (blue, for slash commands)."""
    print(f"{_BLUE}{message}{_RESET}")


def print_block_status(block_name: str, block_type: str, status: str) -> None:
    """Print block execution status during flowchart execution.

    Args:
        block_name: Display name of the block
        block_type: Block type (prompt, bash, variable, etc.)
        status: One of "executing", "completed", "error"
    """
    type_label = f" ({block_type})" if block_type not in ("start", "end") else ""
    if status == "executing":
        print(f"  {_YELLOW}▶{_RESET} {block_name}{type_label}")
    elif status == "completed":
        print(f"  {_GREEN}✓{_RESET} {block_name}{type_label}")
    elif status == "error":
        print(f"  {_RED}✗{_RESET} {block_name}{type_label}")


def print_banner() -> None:
    """Print the CLI welcome banner."""
    print(f"{_BOLD}FlowCoder CLI Agent{_RESET}")
    print(f"{_DIM}Type messages to chat with Claude. Use /command to run flowcharts.{_RESET}")
    print(f"{_DIM}Commands: /help, /commands, /quit{_RESET}")
    print()


def print_help() -> None:
    """Print help text for available CLI commands."""
    print(f"\n{_BOLD}Built-in commands:{_RESET}")
    print(f"  {_CYAN}/help{_RESET}         Show this help message")
    print(f"  {_CYAN}/commands{_RESET}     List available flowchart commands")
    print(f"  {_CYAN}/quit{_RESET}         Exit the CLI agent")
    print()
    print(f"{_BOLD}Flowchart commands:{_RESET}")
    print(f"  {_CYAN}/<name>{_RESET}        Execute a flowchart command")
    print(f"  {_CYAN}/<name> args{_RESET}   Execute with arguments")
    print()
    print(f"{_BOLD}Chat:{_RESET}")
    print(f"  Type any message to send it to Claude.")
    print(f"  Press {_BOLD}Ctrl+C{_RESET} to interrupt, {_BOLD}Ctrl+D{_RESET} to quit.")
    print()

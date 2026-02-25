"""
FlowCoder - Main Entry Point

A visual flowchart builder for creating custom automated workflows with Claude Code.
Supports both a Tkinter GUI and a terminal-based CLI agent.
"""

import asyncio
import logging
import argparse


def setup_logging(debug: bool = False):
    """Configure logging for the application with security and rotation."""
    from src.utils.logging_config import configure_secure_logging

    level = logging.DEBUG if debug else logging.INFO
    configure_secure_logging(level=level)


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(description='FlowCoder - Visual Flowchart Builder')
    subparsers = parser.add_subparsers(dest='mode', help='Run mode')

    # GUI mode (also the default when no subcommand given)
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    # CLI agent mode
    cli_parser = subparsers.add_parser('cli', help='Run terminal-based CLI agent')
    cli_parser.add_argument('--cwd', default=None, help='Working directory (default: current dir)')
    cli_parser.add_argument('--service', default='claude', choices=['claude', 'codex', 'mock'],
                           help='AI service type (default: claude)')
    cli_parser.add_argument('--model', default=None, help='Model override')
    cli_prompt_group = cli_parser.add_mutually_exclusive_group()
    cli_prompt_group.add_argument('--system-prompt', default=None, help='Custom system prompt for the AI')
    cli_prompt_group.add_argument('--no-system-prompt', action='store_true',
                                  help='Use a blank system prompt instead of the built-in FlowCoder prompt')
    cli_parser.add_argument('--session-name', default='cli-session', help='Session name')
    cli_parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    if args.mode == 'cli':
        # CLI agent mode
        setup_logging(args.debug)
        logger = logging.getLogger(__name__)
        logger.info("Starting FlowCoder CLI agent...")

        from src.cli import CLIAgent

        # --no-system-prompt → blank prompt; --system-prompt → custom; neither → DEFAULT_SYSTEM_PROMPT
        system_prompt = args.system_prompt
        if args.no_system_prompt:
            system_prompt = ""

        agent = CLIAgent(
            cwd=args.cwd,
            service_type=args.service,
            model=args.model,
            system_prompt=system_prompt,
            session_name=args.session_name,
            debug=args.debug,
        )
        asyncio.run(agent.run())
    else:
        # GUI mode (default)
        setup_logging(args.debug)
        logger = logging.getLogger(__name__)
        logger.info("Starting FlowCoder...")

        from src.views import MainWindow

        window = MainWindow(title="FlowCoder - Visual Flowchart Builder")
        logger.info("Main window created")
        window.run()


def main_cli():
    """Shortcut entry point for CLI mode (flowcoder-cli command)."""
    import sys
    sys.argv.insert(1, 'cli')
    main()


if __name__ == "__main__":
    main()

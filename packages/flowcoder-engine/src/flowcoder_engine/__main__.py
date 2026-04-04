"""Main entry point for the flowcoder-engine binary."""

from __future__ import annotations

import asyncio
import json
import signal
import sys

import flowcoder_flowchart as fc_lib

from .cli import build_variables, parse_args
from .claude_discovery import find_claude
from .protocol import ProtocolHandler
from .resolver import CommandNotFoundError, resolve_command
from .session import Session
from .walker import ExecutionError, GraphWalker


async def _run_flowchart(
    session: Session,
    flowchart: fc_lib.Flowchart,
    variables: dict,
    protocol: ProtocolHandler,
    args: object,
) -> None:
    """Execute a single flowchart and emit its result."""
    walker = GraphWalker(
        flowchart, session, variables, protocol,
        max_blocks=args.max_blocks,
        search_paths=args.search_paths or [],
    )

    protocol.busy = True
    try:
        result = await walker.run()
        protocol.emit_result(
            json.dumps(result.variables),
            is_error=result.status != "completed",
            duration_ms=result.duration_ms,
            num_turns=len(result.log),
            total_cost_usd=session.total_cost,
        )
    except ExecutionError as e:
        protocol.emit_result(str(e), is_error=True)
    except Exception as e:
        protocol.emit_result(f"Unexpected error: {e}", is_error=True)
    finally:
        protocol.busy = False


async def main() -> None:
    args = parse_args()
    protocol = ProtocolHandler()

    # Find claude binary
    try:
        claude_path = args.claude_path or find_claude()
    except FileNotFoundError as e:
        protocol.emit_result(str(e), is_error=True)
        sys.exit(1)

    # Set up signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(signum: int, frame: object) -> None:
        protocol.log(f"Received signal {signum}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Start protocol handler (stdin reader)
    await protocol.start()

    # Build default session options
    session_opts: dict = {}

    # Create and start the main session
    session = Session("main", claude_path, session_opts, protocol=protocol)
    await session.start()
    protocol.log("Main session started")

    try:
        # Execute initial command/flowchart if provided on CLI
        if args.command or args.flowchart:
            try:
                if args.command:
                    command = resolve_command(args.command, args.search_paths)
                    flowchart = command.flowchart
                    declared_args = command.arguments
                    protocol.log(f"Resolved command: {args.command}")
                else:
                    flowchart = fc_lib.load(args.flowchart)
                    declared_args = flowchart.arguments
                    protocol.log(f"Loaded flowchart: {args.flowchart}")
            except (CommandNotFoundError, FileNotFoundError, Exception) as e:
                protocol.emit_result(str(e), is_error=True)
                return

            # Validate
            validation = fc_lib.validate(flowchart)
            if not validation.valid:
                protocol.emit_result(
                    f"Flowchart validation failed: {validation.errors}",
                    is_error=True,
                )
                return
            for warning in validation.warnings:
                protocol.log(f"Validation warning: {warning}")

            # Build variables from arguments
            try:
                variables = build_variables(args.args, args.extra, declared_args)
            except ValueError as e:
                protocol.emit_result(str(e), is_error=True)
                return

            await _run_flowchart(session, flowchart, variables, protocol, args)

        # Message loop — stay alive until shutdown or stdin EOF
        protocol.log("Entering message loop")
        while not shutdown_event.is_set():
            try:
                msg = await protocol.read_message()
            except asyncio.CancelledError:
                break

            msg_type = msg.get("type", "")

            if msg_type == "shutdown":
                protocol.log("Shutdown requested")
                break

            elif msg_type == "user":
                content = msg.get("message", {}).get("content", "")
                if content:
                    await session.query(
                        content, block_id="", block_name="direct",
                    )

            elif msg_type == "command":
                cmd_name = msg.get("name", "")
                cmd_args = msg.get("args", "")
                try:
                    cmd = resolve_command(cmd_name, args.search_paths)
                    variables = build_variables(
                        cmd_args, {}, cmd.arguments,
                    )
                    await _run_flowchart(
                        session, cmd.flowchart, variables, protocol, args,
                    )
                except (CommandNotFoundError, ValueError) as e:
                    protocol.emit_result(str(e), is_error=True)
                except Exception as e:
                    protocol.emit_result(f"Unexpected error: {e}", is_error=True)

    finally:
        await session.stop()
        await protocol.stop()


def main_sync() -> None:
    """Synchronous entry point for the console script."""
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()

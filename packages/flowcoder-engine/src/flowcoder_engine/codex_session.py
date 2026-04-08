"""CodexSession — wraps the OpenAI Codex TypeScript SDK via Node.js subprocess.

Speaks a simple JSON-line protocol on stdin/stdout with a bundled wrapper
script that uses @openai/codex-sdk.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .session import BaseSession, QueryResult

log = logging.getLogger(__name__)

# The Node.js wrapper script that bridges stdin/stdout JSON ↔ Codex SDK.
_WRAPPER_SCRIPT = r"""
import { Codex } from '@openai/codex-sdk';
import * as readline from 'readline';

const codex = new Codex();
let thread = null;

async function initThread() {
    try {
        thread = await codex.startThread({
            skipGitRepoCheck: true,
            sandboxMode: 'danger-full-access',
            networkAccessEnabled: true
        });
        console.log(JSON.stringify({
            type: 'ready',
            threadId: 'codex-session-active'
        }));
    } catch (error) {
        console.log(JSON.stringify({
            type: 'error',
            error: error.message
        }));
        process.exit(1);
    }
}

function extractText(result) {
    if (typeof result === 'string') return result;
    if (result && result.finalResponse !== undefined && result.finalResponse !== null) {
        return String(result.finalResponse);
    }
    return JSON.stringify(result, null, 2);
}

async function processCommand(cmd) {
    try {
        if (cmd.type === 'run') {
            const result = await thread.run(cmd.prompt);
            console.log(JSON.stringify({
                type: 'response',
                commandId: cmd.commandId,
                success: true,
                response: extractText(result)
            }));
        } else {
            console.log(JSON.stringify({
                type: 'error',
                commandId: cmd.commandId,
                error: 'Unknown command type: ' + cmd.type
            }));
        }
    } catch (error) {
        console.log(JSON.stringify({
            type: 'error',
            commandId: cmd.commandId,
            error: error.message
        }));
    }
}

async function main() {
    await initThread();
    const rl = readline.createInterface({ input: process.stdin, terminal: false });
    rl.on('line', async (line) => {
        try {
            const cmd = JSON.parse(line);
            await processCommand(cmd);
        } catch (error) {
            console.log(JSON.stringify({
                type: 'error',
                error: 'Invalid JSON: ' + error.message
            }));
        }
    });
}

main();
"""


def _find_node() -> str:
    """Find the node binary on PATH."""
    path = shutil.which("node")
    if path:
        return path
    raise FileNotFoundError(
        "Could not find 'node' on PATH. "
        "Node.js v18+ is required for the Codex backend."
    )


def _ensure_wrapper_script(project_root: str) -> Path:
    """Write the wrapper script to a stable location (reused across sessions)."""
    wrapper_dir = Path(project_root) / ".flowcoder"
    wrapper_dir.mkdir(exist_ok=True)
    script_path = wrapper_dir / "codex_wrapper.mjs"
    if not script_path.exists():
        script_path.write_text(_WRAPPER_SCRIPT)
        log.debug("Created Codex wrapper script at %s", script_path)
    return script_path


class CodexSession(BaseSession):
    """A Codex SDK session running in a Node.js subprocess."""

    def __init__(
        self,
        name: str,
        cwd: str | None = None,
        node_path: str | None = None,
    ) -> None:
        self._name = name
        self._session_id: str | None = None
        self._total_cost: float = 0.0
        self._cwd = cwd or os.getcwd()
        self._node_path = node_path or _find_node()
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._command_id = 0

    # -- BaseSession properties --

    @property
    def name(self) -> str:
        return self._name

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    # -- BaseSession methods --

    def clone(self, name: str) -> CodexSession:
        return CodexSession(
            name=name,
            cwd=self._cwd,
            node_path=self._node_path,
        )

    def with_model(self, model: str) -> CodexSession:
        # Codex SDK doesn't support model selection — return a clone.
        return self.clone(self._name)

    async def start(self) -> None:
        """Spawn the Node.js wrapper subprocess and wait for ready."""
        script = _ensure_wrapper_script(self._cwd)

        self._process = await asyncio.create_subprocess_exec(
            self._node_path,
            str(script),
            cwd=self._cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._stderr_task = asyncio.create_task(self._forward_stderr())

        # Wait for the "ready" message
        ready_line = await asyncio.wait_for(
            self._process.stdout.readline(),  # type: ignore[union-attr]
            timeout=30,
        )
        if not ready_line:
            raise RuntimeError("Codex wrapper process exited before sending ready")

        msg = json.loads(ready_line.decode())
        if msg.get("type") == "error":
            raise RuntimeError(f"Codex wrapper startup error: {msg.get('error')}")
        if msg.get("type") != "ready":
            raise RuntimeError(f"Unexpected startup message: {msg}")

        self._session_id = msg.get("threadId")
        log.info("CodexSession '%s' started (thread=%s)", self._name, self._session_id)

    async def query(
        self,
        prompt: str,
        block_id: str = "",
        block_name: str = "",
    ) -> QueryResult:
        """Send a prompt to the Codex thread and return the result."""
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None

        self._command_id += 1
        cmd_id = self._command_id

        command = {
            "type": "run",
            "commandId": cmd_id,
            "prompt": prompt,
        }
        self._process.stdin.write((json.dumps(command) + "\n").encode())
        await self._process.stdin.drain()

        # Read until we get our response
        while True:
            line = await self._process.stdout.readline()
            if not line:
                return QueryResult(response_text="[Codex process exited unexpectedly]")

            data = json.loads(line.decode())

            if data.get("type") == "error":
                if data.get("commandId") == cmd_id:
                    return QueryResult(
                        response_text=f"[Codex error: {data.get('error', 'unknown')}]"
                    )
                continue

            if data.get("type") == "response" and data.get("commandId") == cmd_id:
                return QueryResult(
                    response_text=data.get("response", ""),
                )

    async def clear(self) -> None:
        """Restart the Codex subprocess to clear conversation."""
        await self.stop()
        await self.start()

    async def stop(self) -> None:
        """Terminate the Node.js subprocess."""
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None

        if self._process:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (ProcessLookupError, TimeoutError):
                if self._process.returncode is None:
                    self._process.kill()
            finally:
                self._process = None

    # -- Internal --

    async def _forward_stderr(self) -> None:
        """Read stderr and log it."""
        assert self._process is not None
        assert self._process.stderr is not None
        while True:
            line_bytes = await self._process.stderr.readline()
            if not line_bytes:
                break
            log.debug("[%s codex-stderr] %s", self._name, line_bytes.decode().rstrip())

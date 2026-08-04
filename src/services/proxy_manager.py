"""Lifecycle manager for the anthropic-proxy subprocess.

The Codex service routes claude CLI requests through anthropic-proxy-rs to
OpenAI. This module spawns that proxy lazily (on first Codex session) and
shuts it down with the GUI.

If the port is already occupied (e.g. axi runs its own systemd-managed proxy
on the same port), spawn is skipped — we use whatever is already there.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROXY_BINARY = "anthropic-proxy-codex"
DEFAULT_PORT = 3000
HEALTH_CHECK_PATH = "/v1/models"
HEALTH_CHECK_TIMEOUT = 10.0
HEALTH_CHECK_INTERVAL = 0.2


class ProxyStartupError(Exception):
    """Raised when the proxy subprocess fails to start.

    Messages are user-readable — they surface in GUI dialogs.
    """


class ProxyManager:
    """Lifecycle manager for the anthropic-proxy subprocess.

    - ensure_started() is idempotent: subsequent calls after a successful
      start are no-ops.
    - stop() is idempotent: safe to call when nothing is running.
    - If the port is already healthy when ensure_started() runs, no
      subprocess is spawned (we treat the existing listener as ours).
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        log_dir: Optional[Path] = None,
    ) -> None:
        self._port = port
        self._log_dir = log_dir or Path.cwd() / "logs" / "proxy"
        self._process: Optional[subprocess.Popen] = None
        self._external = False
        self._lock = threading.Lock()

    @property
    def port(self) -> int:
        return self._port

    def is_running(self) -> bool:
        if self._external:
            return True
        return self._process is not None and self._process.poll() is None

    def ensure_started(self) -> None:
        with self._lock:
            if self.is_running():
                return
            if self._health_check():
                logger.info(
                    "anthropic-proxy already responding on port %d "
                    "(external) — skipping spawn",
                    self._port,
                )
                self._external = True
                return
            self._spawn()

    def stop(self) -> None:
        with self._lock:
            if self._external:
                logger.info("Proxy was external — not stopping")
                self._external = False
                return
            if self._process is None:
                return
            self._kill_process_group()
            self._process = None

    def _health_check(self) -> bool:
        url = f"http://127.0.0.1:{self._port}{HEALTH_CHECK_PATH}"
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                return 200 <= resp.status < 500
        except (urllib.error.URLError, OSError):
            return False

    def _spawn(self) -> None:
        binary = shutil.which(PROXY_BINARY)
        if not binary:
            raise ProxyStartupError(
                f"Proxy binary '{PROXY_BINARY}' not found on PATH. "
                "Codex sessions require this binary. See "
                "scripts/anthropic-codex-proxy/install.sh in the "
                "personal-assistant repo for installation."
            )

        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / "anthropic-proxy.log"
        log_file = open(log_path, "ab")

        # The wrapper script invokes inner binaries by name: `anthropic-proxy`
        # (cargo-installed under ~/.cargo/bin) and the shim/normalizer (under
        # ~/.local/bin). Interactive shells often don't include ~/.cargo/bin,
        # so prepend both so the wrapper can find its dependencies regardless
        # of the launching shell's PATH.
        home = os.path.expanduser("~")
        extra_paths = [f"{home}/.cargo/bin", f"{home}/.local/bin"]
        augmented_path = os.pathsep.join(
            [*extra_paths, os.environ.get("PATH", "")]
        )
        env = {
            **os.environ,
            "PORT": str(self._port),
            "PATH": augmented_path,
        }

        logger.info(
            "Starting %s on port %d (logs: %s)", binary, self._port, log_path
        )
        try:
            self._process = subprocess.Popen(
                [binary],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e:
            log_file.close()
            raise ProxyStartupError(
                f"Failed to spawn {binary}: {e}"
            ) from e

        deadline = time.monotonic() + HEALTH_CHECK_TIMEOUT
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                returncode = self._process.returncode
                self._process = None
                raise ProxyStartupError(
                    f"Proxy exited during startup (code {returncode}). "
                    f"Check logs: {log_path}"
                )
            if self._health_check():
                logger.info(
                    "anthropic-proxy is healthy on port %d", self._port
                )
                return
            time.sleep(HEALTH_CHECK_INTERVAL)

        logger.error(
            "Proxy did not become healthy within %ss", HEALTH_CHECK_TIMEOUT
        )
        self._kill_process_group()
        self._process = None
        raise ProxyStartupError(
            f"Proxy did not respond on port {self._port} within "
            f"{HEALTH_CHECK_TIMEOUT}s. Check logs: {log_path}"
        )

    def _kill_process_group(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        try:
            pgid = os.getpgid(self._process.pid)
        except ProcessLookupError:
            return
        logger.info("Killing proxy process group %d (SIGTERM)", pgid)
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self._process.wait(timeout=3)
            logger.info("Proxy exited cleanly")
            return
        except subprocess.TimeoutExpired:
            pass
        logger.warning("Proxy did not exit on SIGTERM — sending SIGKILL")
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            logger.error("Proxy still alive after SIGKILL — giving up")


_singleton_lock = threading.Lock()
_singleton: Optional[ProxyManager] = None


def get_proxy_manager() -> ProxyManager:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = ProxyManager()
        return _singleton


def reset_proxy_manager() -> None:
    """Stop and clear the singleton (test helper)."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.stop()
        _singleton = None

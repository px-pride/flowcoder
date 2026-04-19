"""Regression tests for SessionManager.failed_loads behavior.

Saved sessions whose AI service fails to initialize (e.g. Codex with
unreachable proxy) used to silently get ``agent_service = None``. The user
got no feedback and only discovered the problem when trying to use the
session. We now collect those failures into ``SessionManager.failed_loads``
so the UI can surface them with a dialog after init.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, "packages/flowcoder-engine/src")
sys.path.insert(0, "packages/flowcoder-flowchart/src")
sys.path.insert(0, ".")


def _build_codex_sessions_file(tmp_path: Path, name: str = "broken-codex") -> Path:
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({
        "active_session": name,
        "sessions": {
            name: {
                "name": name,
                "working_directory": str(tmp_path),
                "system_prompt": "",
                "service_type": "codex",
                "created_at": "2026-04-19T00:00:00",
                "state": "idle",
                "chat_history": [],
                "execution_history": [],
                "git_repo_url": "",
                "git_branch": "",
                "git_auto_push": False,
                "config_name": "",
                "sound_on_prompt_complete": None,
                "sound_on_block_complete": None,
                "sound_on_command_pop": None,
            },
        },
    }))
    return sessions_file


def _make_manager_with_sessions_file(sessions_file: Path):
    """Construct a SessionManager bypassing the singleton, pointed at sessions_file."""
    from src.services.session_manager import SessionManager

    SessionManager._instance = None
    mgr = SessionManager.__new__(SessionManager)
    mgr._initialized = False
    mgr.sessions = {}
    mgr.active_session_name = None
    mgr.failed_loads = []
    mgr._session_change_callbacks = []
    mgr.sessions_file = sessions_file
    mgr._ensure_sessions_directory = lambda: None
    return mgr


class TestFailedLoads:
    def test_codex_proxy_failure_recorded(self, tmp_path):
        sessions_file = _build_codex_sessions_file(tmp_path)
        mgr = _make_manager_with_sessions_file(sessions_file)

        from src.services import service_factory

        def fake_create(service_type, **kwargs):
            raise service_factory.ServiceFactoryError(
                "proxy unreachable: connection refused"
            )

        with patch.object(service_factory.ServiceFactory, "create_service", staticmethod(fake_create)):
            mgr.load_sessions()

        assert len(mgr.failed_loads) == 1
        name, err = mgr.failed_loads[0]
        assert name == "broken-codex"
        assert "codex" in err
        assert "proxy unreachable" in err

    def test_session_loaded_with_no_agent_service_when_factory_fails(self, tmp_path):
        sessions_file = _build_codex_sessions_file(tmp_path)
        mgr = _make_manager_with_sessions_file(sessions_file)

        from src.services import service_factory

        with patch.object(
            service_factory.ServiceFactory,
            "create_service",
            staticmethod(lambda service_type, **kwargs: (_ for _ in ()).throw(
                service_factory.ServiceFactoryError("boom")
            )),
        ):
            mgr.load_sessions()

        assert "broken-codex" in mgr.sessions
        assert mgr.sessions["broken-codex"].agent_service is None

    def test_failed_loads_empty_on_successful_load(self, tmp_path):
        sessions_file = _build_codex_sessions_file(tmp_path, name="working-codex")
        mgr = _make_manager_with_sessions_file(sessions_file)

        from src.services import service_factory
        from src.services.mock_service import MockClaudeService

        with patch.object(
            service_factory.ServiceFactory,
            "create_service",
            staticmethod(lambda service_type, **kwargs: MockClaudeService(cwd=kwargs.get("cwd", "."))),
        ):
            mgr.load_sessions()

        assert mgr.failed_loads == []
        assert mgr.sessions["working-codex"].agent_service is not None

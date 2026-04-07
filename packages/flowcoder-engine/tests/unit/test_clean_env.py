"""Tests for _clean_env() — environment preparation for inner Claude CLI."""

import os
from unittest.mock import patch

from flowcoder_engine.session import _clean_env


class TestCleanEnv:
    """Verify _clean_env strips CLAUDECODE but preserves SDK vars."""

    def test_strips_claudecode(self):
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=False):
            env = _clean_env()
        assert "CLAUDECODE" not in env

    def test_preserves_existing_sdk_version(self):
        with patch.dict(
            os.environ,
            {"CLAUDE_AGENT_SDK_VERSION": "custom-ver"},
            clear=False,
        ):
            env = _clean_env()
        assert env["CLAUDE_AGENT_SDK_VERSION"] == "custom-ver"

    def test_preserves_existing_entrypoint(self):
        with patch.dict(
            os.environ,
            {"CLAUDE_CODE_ENTRYPOINT": "custom-entry"},
            clear=False,
        ):
            env = _clean_env()
        assert env["CLAUDE_CODE_ENTRYPOINT"] == "custom-entry"

    def test_sets_default_sdk_version_when_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_AGENT_SDK_VERSION", None)
            env = _clean_env()
        assert env["CLAUDE_AGENT_SDK_VERSION"] == "flowcoder-engine"

    def test_sets_default_entrypoint_when_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)
            env = _clean_env()
        assert env["CLAUDE_CODE_ENTRYPOINT"] == "sdk-py"

    def test_does_not_modify_real_environ(self):
        original = os.environ.copy()
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=False):
            _clean_env()
            assert os.environ.get("CLAUDECODE") == "1"

    def test_passes_through_unrelated_vars(self):
        with patch.dict(os.environ, {"MY_CUSTOM_VAR": "hello"}, clear=False):
            env = _clean_env()
        assert env.get("MY_CUSTOM_VAR") == "hello"

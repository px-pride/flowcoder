"""
Config Service for FlowCoder

Handles persistence and management of agent configuration files.

Single config format (`.claudeconfig`) drives both Claude Code and Codex
sessions. A config with `proxy_url` set is treated as a Codex config — when
the session starts, those env vars are injected into the claude subprocess so
it routes through anthropic-proxy-rs (translating Anthropic API → OpenAI).
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Base exception for config operations."""
    pass


class ConfigNotFoundError(ConfigError):
    """Raised when a config file is not found."""
    pass


class ConfigAlreadyExistsError(ConfigError):
    """Raised when trying to create a config that already exists."""
    pass


class CorruptedConfigError(ConfigError):
    """Raised when a config file is corrupted or invalid."""
    pass


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClaudeConfig:
    """Configuration for an agent session.

    A "Codex" session is just a ClaudeConfig with `proxy_url` set — the
    session spawns the claude CLI with `ANTHROPIC_BASE_URL=proxy_url` and
    `ANTHROPIC_MODEL=proxy_model` so requests route through the local
    anthropic-proxy translator to OpenAI.
    """

    name: str
    model: str = "claude-opus-4-5"
    permission_mode: str = "bypassPermissions"
    thinking: Dict[str, Any] = field(default_factory=lambda: {"type": "adaptive"})
    max_output_tokens: int = 64000
    system_prompt: Optional[str] = None
    proxy_url: Optional[str] = None
    proxy_model: Optional[str] = None

    @property
    def is_codex(self) -> bool:
        """True if this config routes through the anthropic-proxy."""
        return bool(self.proxy_url)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary suitable for JSON."""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClaudeConfig":
        """Deserialize from a dictionary."""
        return cls(
            name=data["name"],
            model=data.get("model", "claude-opus-4-5"),
            permission_mode=data.get("permission_mode", "bypassPermissions"),
            thinking=data.get("thinking", {"type": "adaptive"}),
            max_output_tokens=data.get("max_output_tokens", 64000),
            system_prompt=data.get("system_prompt"),
            proxy_url=data.get("proxy_url"),
            proxy_model=data.get("proxy_model"),
        )


# ---------------------------------------------------------------------------
# File-extension helpers
# ---------------------------------------------------------------------------

_CONFIG_EXT = ".claudeconfig"


# ---------------------------------------------------------------------------
# Default configs
# ---------------------------------------------------------------------------

_DEFAULT_CONFIGS: List[ClaudeConfig] = [
    ClaudeConfig(
        name="claude-max",
        model="claude-opus-4-5",
        permission_mode="bypassPermissions",
        thinking={"type": "adaptive"},
        max_output_tokens=64000,
    ),
    ClaudeConfig(
        name="claude-min",
        model="claude-haiku-3-5",
        permission_mode="plan",
        thinking={"type": "disabled"},
        max_output_tokens=16000,
    ),
    ClaudeConfig(
        name="codex-max",
        model="claude-opus-4-5",
        permission_mode="bypassPermissions",
        thinking={"type": "adaptive"},
        max_output_tokens=64000,
        proxy_url="http://127.0.0.1:3000",
        proxy_model="gpt-5.4",
    ),
    ClaudeConfig(
        name="codex-min",
        model="claude-opus-4-5",
        permission_mode="bypassPermissions",
        thinking={"type": "adaptive"},
        max_output_tokens=64000,
        proxy_url="http://127.0.0.1:3000",
        proxy_model="gpt-5.4-mini",
    ),
]


# ---------------------------------------------------------------------------
# ConfigService
# ---------------------------------------------------------------------------

class ConfigService:
    """Service for saving, loading, and managing agent config files."""

    def __init__(self, configs_dir: str = "./configs"):
        """
        Initialize the config service.

        Args:
            configs_dir: Directory where config files are stored.
        """
        self.configs_dir = Path(configs_dir)
        self._ensure_configs_directory()

    # ------------------------------------------------------------------
    # Directory helpers
    # ------------------------------------------------------------------

    def _ensure_configs_directory(self) -> None:
        """Ensure the configs directory exists."""
        try:
            self.configs_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Configs directory ready: {self.configs_dir}")
        except Exception as e:
            logger.error(f"Failed to create configs directory: {e}")
            raise ConfigError(f"Could not create configs directory: {e}")

    def _get_config_file_path(self, name: str) -> Path:
        """Build the full path for a config file."""
        safe_name = name.replace(" ", "_")
        return self.configs_dir / f"{safe_name}{_CONFIG_EXT}"

    def _resolve_config_path(self, name: str) -> Path:
        """
        Find the on-disk path for *name*.

        Args:
            name: Config name.

        Returns:
            Path if found.

        Raises:
            ConfigNotFoundError: If no matching file exists.
        """
        path = self._get_config_file_path(name)
        if path.exists():
            return path
        raise ConfigNotFoundError(f"Config '{name}' not found")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_config(self, config: ClaudeConfig, overwrite: bool = True) -> None:
        """
        Save a config to disk.

        Args:
            config: A ``ClaudeConfig`` instance.
            overwrite: If *False*, raise an error when the file already exists.

        Raises:
            ConfigAlreadyExistsError: If the config exists and *overwrite* is False.
            ConfigError: On I/O failures.
        """
        if not isinstance(config, ClaudeConfig):
            raise ConfigError(f"Unsupported config type: {type(config).__name__}")

        file_path = self._get_config_file_path(config.name)

        if file_path.exists() and not overwrite:
            raise ConfigAlreadyExistsError(
                f"Config '{config.name}' already exists"
            )

        try:
            data = config.to_dict()
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved config '{config.name}' to {file_path}")

        except Exception as e:
            logger.error(f"Failed to save config '{config.name}': {e}")
            raise ConfigError(f"Could not save config: {e}")

    def load_config(self, name: str) -> ClaudeConfig:
        """
        Load a config from disk.

        Args:
            name: Config name (without extension).

        Returns:
            A ``ClaudeConfig`` instance.

        Raises:
            ConfigNotFoundError: If no matching file exists.
            CorruptedConfigError: If the file cannot be parsed.
            ConfigError: On other I/O failures.
        """
        file_path = self._resolve_config_path(name)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            config = ClaudeConfig.from_dict(data)
            logger.info(f"Loaded config '{name}' from {file_path}")
            return config

        except json.JSONDecodeError as e:
            logger.error(f"Corrupted config file '{name}': {e}")
            raise CorruptedConfigError(f"Config file is corrupted: {e}")
        except KeyError as e:
            logger.error(f"Invalid config file '{name}': missing {e}")
            raise CorruptedConfigError(
                f"Config file is missing required field: {e}"
            )
        except (ConfigNotFoundError, CorruptedConfigError):
            raise
        except Exception as e:
            logger.error(f"Failed to load config '{name}': {e}")
            raise ConfigError(f"Could not load config: {e}")

    def list_configs(self) -> List[Dict[str, Any]]:
        """
        List all available configs with metadata.

        Returns:
            A list of dictionaries, each containing:
            - ``name``:        Config name.
            - ``config_type``: ``'claude'`` or ``'codex'`` (based on whether proxy_url set).
            - ``model``:       Model identifier.
            - ``proxy_model``: Proxy model identifier (codex configs only).
            - ``file_path``:   Full path to the config file.
            - ``permission_mode``, ``max_output_tokens``: standard fields.

        Raises:
            ConfigError: On I/O failures.
        """
        configs: List[Dict[str, Any]] = []

        try:
            for file_path in self.configs_dir.glob(f"*{_CONFIG_EXT}"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    proxy_url = data.get("proxy_url")
                    metadata: Dict[str, Any] = {
                        "name": data.get("name", file_path.stem),
                        "config_type": "codex" if proxy_url else "claude",
                        "model": data.get("model", ""),
                        "file_path": str(file_path),
                        "permission_mode": data.get("permission_mode", ""),
                        "max_output_tokens": data.get("max_output_tokens", 0),
                    }
                    if proxy_url:
                        metadata["proxy_url"] = proxy_url
                        metadata["proxy_model"] = data.get("proxy_model", "")

                    configs.append(metadata)

                except json.JSONDecodeError:
                    logger.warning(
                        f"Skipping corrupted config file: {file_path}"
                    )
                    continue
                except Exception as e:
                    logger.warning(f"Error reading {file_path}: {e}")
                    continue

            configs.sort(key=lambda c: c["name"])
            logger.info(f"Found {len(configs)} configs")
            return configs

        except Exception as e:
            logger.error(f"Failed to list configs: {e}")
            raise ConfigError(f"Could not list configs: {e}")

    def delete_config(self, name: str) -> None:
        """
        Delete a config from disk.

        Args:
            name: Config name.

        Raises:
            ConfigNotFoundError: If no matching file exists.
            ConfigError: On I/O failures.
        """
        file_path = self._resolve_config_path(name)

        try:
            file_path.unlink()
            logger.info(f"Deleted config '{name}'")
        except Exception as e:
            logger.error(f"Failed to delete config '{name}': {e}")
            raise ConfigError(f"Could not delete config: {e}")

    def config_exists(self, name: str) -> bool:
        """
        Check whether a config with the given name exists on disk.

        Args:
            name: Config name.

        Returns:
            ``True`` if a ``.claudeconfig`` file exists.
        """
        return self._get_config_file_path(name).exists()

    def ensure_defaults(self) -> None:
        """
        Create the four default configs if they do not already exist.

        Existing configs with matching names are never overwritten.
        """
        for config in _DEFAULT_CONFIGS:
            if not self.config_exists(config.name):
                try:
                    self.save_config(config, overwrite=False)
                    logger.info(f"Created default config: {config.name}")
                except ConfigAlreadyExistsError:
                    pass
                except Exception as e:
                    logger.error(
                        f"Failed to create default config '{config.name}': {e}"
                    )

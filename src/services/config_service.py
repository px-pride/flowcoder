"""
Config Service for FlowCoder

Handles persistence and management of agent configuration files.
Supports both Claude Code (.claudeconfig) and Codex (.codexconfig) formats.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Union


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
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ClaudeConfig:
    """Configuration for a Claude Code agent."""

    name: str
    model: str = "claude-opus-4-5"
    permission_mode: str = "bypassPermissions"
    thinking: Dict[str, Any] = field(default_factory=lambda: {"type": "adaptive"})
    max_output_tokens: int = 64000
    system_prompt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary suitable for JSON."""
        data = asdict(self)
        # Strip None values to keep the file clean
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
        )


@dataclass
class CodexConfig:
    """Configuration for a Codex agent."""

    name: str
    model: str = "o4-mini"
    approval_mode: str = "full-auto"
    system_prompt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary suitable for JSON."""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodexConfig":
        """Deserialize from a dictionary."""
        return cls(
            name=data["name"],
            model=data.get("model", "o4-mini"),
            approval_mode=data.get("approval_mode", "full-auto"),
            system_prompt=data.get("system_prompt"),
        )


# ---------------------------------------------------------------------------
# File-extension helpers
# ---------------------------------------------------------------------------

_CLAUDE_EXT = ".claudeconfig"
_CODEX_EXT = ".codexconfig"
_ALL_EXTENSIONS = (_CLAUDE_EXT, _CODEX_EXT)


def _config_type_for_path(path: Path) -> str:
    """Return 'claude' or 'codex' based on the file extension."""
    if path.suffix == _CLAUDE_EXT:
        return "claude"
    if path.suffix == _CODEX_EXT:
        return "codex"
    raise ConfigError(f"Unrecognised config extension: {path.suffix}")


# ---------------------------------------------------------------------------
# Default configs
# ---------------------------------------------------------------------------

_DEFAULT_CONFIGS: List[Union[ClaudeConfig, CodexConfig]] = [
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
    CodexConfig(
        name="codex-max",
        model="o4-mini",
        approval_mode="full-auto",
    ),
    CodexConfig(
        name="codex-min",
        model="o4-mini",
        approval_mode="suggest",
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

    def _get_config_file_path(
        self, name: str, config_type: str = "claude"
    ) -> Path:
        """
        Build the full path for a config file.

        Args:
            name: Config name (used as the filename stem).
            config_type: Either ``'claude'`` or ``'codex'``.

        Returns:
            Absolute path to the config file.
        """
        safe_name = name.replace(" ", "_")
        ext = _CLAUDE_EXT if config_type == "claude" else _CODEX_EXT
        return self.configs_dir / f"{safe_name}{ext}"

    def _resolve_config_path(self, name: str) -> Path:
        """
        Find the on-disk path for *name*, trying both extensions.

        Args:
            name: Config name.

        Returns:
            Path if found.

        Raises:
            ConfigNotFoundError: If no matching file exists.
        """
        safe_name = name.replace(" ", "_")
        for ext in _ALL_EXTENSIONS:
            path = self.configs_dir / f"{safe_name}{ext}"
            if path.exists():
                return path
        raise ConfigNotFoundError(f"Config '{name}' not found")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_config(
        self, config: Union[ClaudeConfig, CodexConfig], overwrite: bool = True
    ) -> None:
        """
        Save a config to disk.

        Args:
            config: A ``ClaudeConfig`` or ``CodexConfig`` instance.
            overwrite: If *False*, raise an error when the file already exists.

        Raises:
            ConfigAlreadyExistsError: If the config exists and *overwrite* is False.
            ConfigError: On I/O failures.
        """
        if isinstance(config, ClaudeConfig):
            config_type = "claude"
        elif isinstance(config, CodexConfig):
            config_type = "codex"
        else:
            raise ConfigError(
                f"Unsupported config type: {type(config).__name__}"
            )

        file_path = self._get_config_file_path(config.name, config_type)

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

    def load_config(self, name: str) -> Union[ClaudeConfig, CodexConfig]:
        """
        Load a config from disk.

        The method determines whether the config is a Claude or Codex config
        based on its file extension.

        Args:
            name: Config name (without extension).

        Returns:
            A ``ClaudeConfig`` or ``CodexConfig`` instance.

        Raises:
            ConfigNotFoundError: If no matching file exists.
            CorruptedConfigError: If the file cannot be parsed.
            ConfigError: On other I/O failures.
        """
        file_path = self._resolve_config_path(name)
        config_type = _config_type_for_path(file_path)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if config_type == "claude":
                config = ClaudeConfig.from_dict(data)
            else:
                config = CodexConfig.from_dict(data)

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
            - ``config_type``: ``'claude'`` or ``'codex'``.
            - ``model``:       Model identifier.
            - ``file_path``:   Full path to the config file.

        Raises:
            ConfigError: On I/O failures.
        """
        configs: List[Dict[str, Any]] = []

        try:
            for ext in _ALL_EXTENSIONS:
                for file_path in self.configs_dir.glob(f"*{ext}"):
                    try:
                        config_type = _config_type_for_path(file_path)

                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)

                        metadata: Dict[str, Any] = {
                            "name": data.get("name", file_path.stem),
                            "config_type": config_type,
                            "model": data.get("model", ""),
                            "file_path": str(file_path),
                        }

                        # Include type-specific fields in metadata
                        if config_type == "claude":
                            metadata["permission_mode"] = data.get(
                                "permission_mode", ""
                            )
                            metadata["max_output_tokens"] = data.get(
                                "max_output_tokens", 0
                            )
                        else:
                            metadata["approval_mode"] = data.get(
                                "approval_mode", ""
                            )

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
            ``True`` if a ``.claudeconfig`` or ``.codexconfig`` file exists.
        """
        safe_name = name.replace(" ", "_")
        for ext in _ALL_EXTENSIONS:
            if (self.configs_dir / f"{safe_name}{ext}").exists():
                return True
        return False

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
                    # Race-condition guard; another process may have created
                    # the file between the exists-check and the save call.
                    pass
                except Exception as e:
                    logger.error(
                        f"Failed to create default config '{config.name}': {e}"
                    )

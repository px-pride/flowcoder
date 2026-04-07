"""Core models for flowchart workflows.

Defines Connection, Argument, SessionConfig, Flowchart, and helper models.

Extended with:
- VariableEntry: for tracking variable state across execution
- WaitEntry: for tracking spawned session wait results
"""

from __future__ import annotations

from typing import Any, Self
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from .blocks import Block


class Connection(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str = Field(
        validation_alias=AliasChoices("source_id", "source_block_id"),
    )
    target_id: str = Field(
        validation_alias=AliasChoices("target_id", "target_block_id"),
    )
    label: str | None = None
    is_true_path: bool | None = None


class Argument(BaseModel):
    name: str
    description: str = ""
    required: bool = True
    default: str | None = None

    @model_validator(mode="after")
    def check_required_default(self) -> Self:
        if self.required and self.default is not None:
            raise ValueError("Argument cannot be both required and have a default")
        return self


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None


class Flowchart(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blocks: dict[str, Block]
    connections: list[Connection] = Field(default_factory=list)
    sessions: dict[str, SessionConfig] = Field(default_factory=dict)
    name: str = ""
    description: str = ""
    arguments: list[Argument] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def sync_block_ids(self) -> Self:
        """Ensure each block's id matches its dict key."""
        for key, block in self.blocks.items():
            if block.id != key:
                block.id = key
        return self


# ── Helper models for execution tracking ────────────────────────────


class VariableEntry(BaseModel):
    """Tracks a variable's value and which block set it."""
    name: str
    value: Any = None
    set_by_block_id: str | None = None


class WaitEntry(BaseModel):
    """Tracks results from a spawned session wait."""
    agent_name: str
    exit_code: int = 0
    output: str = ""
    completed: bool = False

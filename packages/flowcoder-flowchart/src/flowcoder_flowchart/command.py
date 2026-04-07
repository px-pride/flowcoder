"""Command model — a named wrapper around a flowchart."""

from __future__ import annotations

import shlex
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .models import Argument, Flowchart  # noqa: TC001


class CommandMetadata(BaseModel):
    created: datetime = Field(default_factory=datetime.now)
    modified: datetime = Field(default_factory=datetime.now)
    version: str = "1.0"
    author: str | None = None
    tags: list[str] = Field(default_factory=list)


class Command(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    flowchart: Flowchart
    metadata: CommandMetadata = Field(default_factory=CommandMetadata)
    arguments: list[Argument] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or " " in v or not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Command name must be non-empty, no spaces, "
                "alphanumeric/hyphens/underscores only"
            )
        return v

    def parse_arguments(self, args: list[str] | str) -> dict[str, str]:
        """Parse arguments into positional ($1, $2) and named keys.

        Accepts either a pre-split list or a raw string (parsed with shlex).
        """
        if isinstance(args, str):
            parts = shlex.split(args) if args.strip() else []
        else:
            parts = list(args)

        result: dict[str, str] = {}

        # Map to declared arguments
        for i, arg_def in enumerate(self.arguments):
            pos = i + 1
            key = f"${pos}"

            if i < len(parts):
                value = parts[i]
            elif arg_def.default is not None:
                value = arg_def.default
            elif arg_def.required:
                raise ValueError(
                    f"Missing required argument: {arg_def.name} (position {pos})"
                )
            else:
                continue

            result[key] = value
            result[arg_def.name] = value

        # Extra positional args beyond declared ones
        for i in range(len(self.arguments), len(parts)):
            result[f"${i + 1}"] = parts[i]

        return result

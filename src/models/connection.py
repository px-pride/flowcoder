"""
Connection Model for FlowCoder

Represents connections (arrows) between blocks in a flowchart.
"""

from dataclasses import dataclass
from typing import Optional
import uuid


@dataclass
class Connection:
    """Connection between two blocks in a flowchart.

    Ports: 'top', 'left', 'bottom', 'right'
    - Any port can be input or output
    - is_true_path: True for normal flow (black), False for false path (blue)
    """
    id: str
    source_block_id: str
    target_block_id: str
    source_port: str = "bottom"  # Which port on source block
    target_port: str = "top"  # Which port on target block
    is_true_path: bool = True  # True = black arrow, False = blue arrow
    condition: Optional[str] = None  # Deprecated
    label: Optional[str] = None  # Deprecated

    def __post_init__(self):
        """Validate connection after initialization."""
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.source_block_id:
            raise ValueError("source_block_id is required")
        if not self.target_block_id:
            raise ValueError("target_block_id is required")

        # Validate ports
        valid_ports = {'top', 'left', 'bottom', 'right'}
        if self.source_port not in valid_ports:
            self.source_port = "bottom"
        if self.target_port not in valid_ports:
            self.target_port = "top"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "source_block_id": self.source_block_id,
            "target_block_id": self.target_block_id,
            "source_port": self.source_port,
            "target_port": self.target_port,
            "is_true_path": self.is_true_path,
            "condition": self.condition,
            "label": self.label
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Connection':
        """Create Connection from dictionary."""
        return cls(
            id=data["id"],
            source_block_id=data["source_block_id"],
            target_block_id=data["target_block_id"],
            source_port=data.get("source_port", "bottom"),
            target_port=data.get("target_port", "top"),
            is_true_path=data.get("is_true_path", True),
            condition=data.get("condition"),
            label=data.get("label")
        )

    def __repr__(self) -> str:
        """String representation of connection."""
        label_str = f" [{self.label}]" if self.label else ""
        condition_str = f" if {self.condition}" if self.condition else ""
        return f"Connection({self.source_block_id} -> {self.target_block_id}{label_str}{condition_str})"

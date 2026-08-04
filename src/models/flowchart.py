"""
Flowchart Model for FlowCoder

Represents a complete flowchart with blocks and connections.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from .blocks import Block, BlockType, StartBlock
from .connection import Connection


@dataclass
class ValidationResult:
    """Result of flowchart validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Allow using ValidationResult in boolean context."""
        return self.valid


@dataclass
class Flowchart:
    """A flowchart containing blocks and connections."""
    blocks: Dict[str, Block] = field(default_factory=dict)
    connections: List[Connection] = field(default_factory=list)
    start_block_id: Optional[str] = None

    def __post_init__(self):
        """Initialize flowchart with a start block if empty."""
        if not self.blocks:
            start_block = StartBlock()
            self.blocks[start_block.id] = start_block
            self.start_block_id = start_block.id

    def add_block(self, block: Block) -> None:
        """Add a block to the flowchart."""
        if block.id in self.blocks:
            raise ValueError(f"Block with id {block.id} already exists")

        self.blocks[block.id] = block

        # If this is a start block, set it as the start
        if block.type == BlockType.START:
            if self.start_block_id and self.start_block_id != block.id:
                raise ValueError("Flowchart already has a start block")
            self.start_block_id = block.id

    def remove_block(self, block_id: str) -> None:
        """Remove a block and all its connections."""
        if block_id not in self.blocks:
            raise ValueError(f"Block {block_id} not found")

        block = self.blocks[block_id]

        # Prevent removing start block
        if block.type == BlockType.START:
            raise ValueError("Cannot remove start block")

        # Remove all connections involving this block
        self.connections = [
            conn for conn in self.connections
            if conn.source_block_id != block_id and conn.target_block_id != block_id
        ]

        # Remove the block
        del self.blocks[block_id]

    def add_connection(self, connection: Connection) -> None:
        """Add a connection between blocks."""
        # Validate that blocks exist
        if connection.source_block_id not in self.blocks:
            raise ValueError(f"Source block {connection.source_block_id} not found")
        if connection.target_block_id not in self.blocks:
            raise ValueError(f"Target block {connection.target_block_id} not found")

        # Check for duplicate connections
        for conn in self.connections:
            if (conn.source_block_id == connection.source_block_id and
                conn.target_block_id == connection.target_block_id):
                raise ValueError(
                    f"Connection from {connection.source_block_id} to "
                    f"{connection.target_block_id} already exists"
                )

        self.connections.append(connection)

    def remove_connection(self, connection_id: str) -> None:
        """Remove a connection by its ID."""
        self.connections = [
            conn for conn in self.connections if conn.id != connection_id
        ]

    def get_connections_from(self, block_id: str) -> List[Connection]:
        """Get all connections originating from a block."""
        return [
            conn for conn in self.connections
            if conn.source_block_id == block_id
        ]

    def get_connections_to(self, block_id: str) -> List[Connection]:
        """Get all connections targeting a block."""
        return [
            conn for conn in self.connections
            if conn.target_block_id == block_id
        ]

    def get_start_block(self) -> Optional[Block]:
        """Get the start block."""
        if self.start_block_id:
            return self.blocks.get(self.start_block_id)
        return None

    def get_next_block(self, current_block_id: str) -> Optional[Block]:
        """Get the next block in linear flow (first connection)."""
        connections = self.get_connections_from(current_block_id)
        if connections:
            return self.blocks.get(connections[0].target_block_id)
        return None

    def validate(self) -> ValidationResult:
        """Validate the flowchart for common errors."""
        errors = []
        warnings = []

        # 1. Must have exactly one start block
        start_blocks = [b for b in self.blocks.values() if b.type == BlockType.START]
        if len(start_blocks) == 0:
            errors.append(
                "Flowchart must have a Start block. "
                "Add a Start block from the Block Palette to begin your flowchart."
            )
        elif len(start_blocks) > 1:
            errors.append(
                f"Flowchart must have only one Start block (found {len(start_blocks)}). "
                "Remove extra Start blocks to fix this error."
            )

        # 2. Should have at least one end block
        end_blocks = [b for b in self.blocks.values() if b.type == BlockType.END]
        if len(end_blocks) == 0:
            warnings.append(
                "Flowchart should have at least one End block. "
                "Add an End block to properly terminate execution paths."
            )

        # 3. All blocks should be reachable from start
        if start_blocks:
            reachable = self._get_reachable_blocks(start_blocks[0].id)
            unreachable_blocks = []
            for block in self.blocks.values():
                if block.id not in reachable:
                    unreachable_blocks.append(block.name)

            if unreachable_blocks:
                warnings.append(
                    f"Blocks unreachable from Start: {', '.join(unreachable_blocks)}. "
                    "Connect these blocks to the main flow or remove them."
                )

        # 4. Prompt blocks must have non-empty prompts
        for block in self.blocks.values():
            if block.type == BlockType.PROMPT:
                from .blocks import PromptBlock
                prompt_block = block
                if isinstance(prompt_block, PromptBlock) and not prompt_block.prompt.strip():
                    errors.append(
                        f"Prompt block '{block.name}' has an empty prompt. "
                        "Double-click the block to add a prompt in the configuration panel."
                    )

        # 5. Branch blocks must have a condition and at least one outgoing connection
        for block in self.blocks.values():
            if block.type == BlockType.BRANCH:
                from .blocks import BranchBlock
                branch_block = block
                if isinstance(branch_block, BranchBlock):
                    # Check if branch has a condition
                    if not branch_block.condition or not branch_block.condition.strip():
                        errors.append(
                            f"Branch block '{block.name}' has no condition. "
                            "Double-click the block to configure the branch condition (e.g., 'count > 5')."
                        )

                    # Check if branch has outgoing connections
                    outgoing_connections = [
                        conn for conn in self.connections
                        if conn.source_block_id == block.id
                    ]
                    if not outgoing_connections:
                        errors.append(
                            f"Branch block '{block.name}' has no outgoing connections. "
                            "Create True path (drag) and False path (Ctrl+drag) connections."
                        )
                    elif len(outgoing_connections) == 1:
                        # Warn if only one path exists
                        existing_path = "True" if outgoing_connections[0].is_true_path else "False"
                        missing_path = "False" if outgoing_connections[0].is_true_path else "True"
                        errors.append(
                            f"Branch block '{block.name}' only has a {existing_path} path connection. "
                            f"Add a {missing_path} path using {'Ctrl+drag' if existing_path == 'True' else 'normal drag'}."
                        )

        # 5.5. Variable blocks must have non-empty variable names
        for block in self.blocks.values():
            if block.type == BlockType.VARIABLE:
                from .blocks import VariableBlock
                variable_block = block
                if isinstance(variable_block, VariableBlock):
                    # Call the block's own validate method
                    block_errors = variable_block.validate()
                    for error in block_errors:
                        errors.append(f"Variable block '{block.name}': {error}")

        # 5.6. Bash blocks must have non-empty commands
        for block in self.blocks.values():
            if block.type == BlockType.BASH:
                from .blocks import BashBlock
                bash_block = block
                if isinstance(bash_block, BashBlock):
                    # Call the block's own validate method
                    block_errors = bash_block.validate()
                    for error in block_errors:
                        errors.append(f"Bash block '{block.name}': {error}")

        # 6. Validate connections
        for conn in self.connections:
            if conn.source_block_id not in self.blocks:
                errors.append(f"Connection references non-existent source block: {conn.source_block_id}")
            if conn.target_block_id not in self.blocks:
                errors.append(f"Connection references non-existent target block: {conn.target_block_id}")

        # 7. Detect disconnected blocks (no incoming or outgoing connections)
        for block in self.blocks.values():
            # Skip Start and End blocks from disconnected check
            if block.type in [BlockType.START, BlockType.END]:
                continue

            # Check if block has any connections
            has_incoming = any(conn.target_block_id == block.id for conn in self.connections)
            has_outgoing = any(conn.source_block_id == block.id for conn in self.connections)

            if not has_incoming and not has_outgoing:
                warnings.append(
                    f"Block '{block.name}' is completely disconnected (no incoming or outgoing connections). "
                    f"Consider connecting it to the flowchart or removing it."
                )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def _get_reachable_blocks(self, start_block_id: str) -> Set[str]:
        """Get all block IDs reachable from a starting block (BFS)."""
        visited = set()
        queue = [start_block_id]

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue

            visited.add(current_id)

            # Add all connected blocks to queue
            for conn in self.get_connections_from(current_id):
                if conn.target_block_id not in visited:
                    queue.append(conn.target_block_id)

        return visited

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "blocks": {
                block_id: block.to_dict()
                for block_id, block in self.blocks.items()
            },
            "connections": [conn.to_dict() for conn in self.connections],
            "start_block_id": self.start_block_id
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Flowchart':
        """Create Flowchart from dictionary."""
        flowchart = cls()

        # Clear default start block
        flowchart.blocks.clear()

        # Load blocks
        for block_id, block_data in data.get("blocks", {}).items():
            block = Block.from_dict(block_data)
            flowchart.blocks[block_id] = block

        # Load connections
        flowchart.connections = [
            Connection.from_dict(conn_data)
            for conn_data in data.get("connections", [])
        ]

        # Set start block
        flowchart.start_block_id = data.get("start_block_id")

        return flowchart

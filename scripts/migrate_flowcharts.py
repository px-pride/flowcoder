#!/usr/bin/env python3
"""
Migrate existing .flowchart JSON files to Pydantic-compatible format.

Handles field renames:
- source_block_id -> source_id
- target_block_id -> target_id

And structural changes:
- Variable block entries -> single variable
- Branch condition object -> string
- Port fields preserved for GUI but not required by engine

Usage:
    python scripts/migrate_flowcharts.py [--dry-run] [--dir COMMANDS_DIR]
"""

import argparse
import json
import sys
from pathlib import Path


def migrate_flowchart(data: dict) -> tuple[dict, list[str]]:
    """Migrate a single flowchart dict. Returns (migrated_data, changes)."""
    changes: list[str] = []

    # Migrate connections
    for conn in data.get("connections", []):
        if "source_block_id" in conn and "source_id" not in conn:
            conn["source_id"] = conn["source_block_id"]
            changes.append(f"  connection {conn.get('id', '?')}: added source_id")
        if "target_block_id" in conn and "target_id" not in conn:
            conn["target_id"] = conn["target_block_id"]
            changes.append(f"  connection {conn.get('id', '?')}: added target_id")

    # Migrate blocks
    blocks = data.get("blocks", {})
    if isinstance(blocks, list):
        # Convert list to dict
        blocks_dict = {}
        for b in blocks:
            blocks_dict[b["id"]] = b
        data["blocks"] = blocks_dict
        blocks = blocks_dict
        changes.append("  converted blocks from list to dict")

    for bid, block in blocks.items():
        btype = block.get("type", "")

        # Variable blocks: ensure single-variable fields exist
        if btype == "variable":
            entries = block.get("entries", [])
            if entries and "variable_name" not in block:
                first = entries[0]
                block["variable_name"] = first.get("variable_name", "")
                block["variable_value"] = first.get("variable_value", "")
                block["variable_type"] = first.get("variable_type", "string")
                changes.append(f"  block {bid}: extracted variable from entries")

        # Branch blocks: ensure condition is string
        if btype == "branch":
            cond = block.get("condition")
            if isinstance(cond, dict):
                block["condition"] = cond.get("variable", "")
                changes.append(f"  block {bid}: converted condition dict to string")

    return data, changes


def migrate_command(data: dict) -> tuple[dict, list[str]]:
    """Migrate a command JSON dict."""
    changes: list[str] = []

    if "flowchart" in data:
        fc_data, fc_changes = migrate_flowchart(data["flowchart"])
        data["flowchart"] = fc_data
        changes.extend(fc_changes)

    return data, changes


def main():
    parser = argparse.ArgumentParser(description="Migrate flowchart JSON files")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--dir", default=None, help="Commands directory to migrate")
    args = parser.parse_args()

    # Find commands directory
    if args.dir:
        commands_dir = Path(args.dir)
    else:
        # Default locations
        home = Path.home()
        candidates = [
            home / ".flowcoder" / "commands",
            Path.cwd() / "commands",
        ]
        commands_dir = None
        for c in candidates:
            if c.exists():
                commands_dir = c
                break

        if not commands_dir:
            print("No commands directory found. Use --dir to specify one.")
            sys.exit(1)

    print(f"Scanning: {commands_dir}")

    json_files = list(commands_dir.glob("**/*.json"))
    if not json_files:
        print("No JSON files found.")
        return

    total_changes = 0
    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text())
        except json.JSONDecodeError:
            print(f"  SKIP (invalid JSON): {json_file}")
            continue

        # Determine if this is a command or a bare flowchart
        if "flowchart" in data:
            migrated, changes = migrate_command(data)
        elif "blocks" in data:
            migrated, changes = migrate_flowchart(data)
        else:
            continue

        if changes:
            print(f"\n{json_file.name}:")
            for change in changes:
                print(change)
            total_changes += len(changes)

            if not args.dry_run:
                json_file.write_text(json.dumps(migrated, indent=2))
                print(f"  -> Written")

    print(f"\nTotal changes: {total_changes}")
    if args.dry_run and total_changes > 0:
        print("(dry-run mode — no files were modified)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
select-next-batch.py

Deterministic feature selection for DAG-based development.
Optimized for large DAGs with O(N+E) total complexity.

Modes:
  --select (default): Select next batch of features to implement
  --complete <file>:  Mark features in file as complete, update ready set
  --rebuild:          Force regeneration of DAG_STATE.json from CSV

Algorithm:
1. Load DAG_STATE.json (pre-computed features and effective values)
2. Select features from ready set that share the highest effective value
3. Write to CURRENT_BATCH.md
4. Output batch size as integer

Backwards compatible: Falls back to CSV parsing if DAG_STATE.json doesn't exist.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Optional


@dataclass
class Feature:
    """Represents a feature in the DAG."""
    tag: str
    description: str
    parents: List[str]
    children: List[str]
    vertical_score: int
    effective_value: int


@dataclass
class DAGState:
    """Complete DAG state."""
    source_hash: str
    features: Dict[str, Feature]
    completed: Set[str]
    ready: Set[str]
    batch_number: int = 0  # Current batch number (0 = no batches started yet)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "source_hash": self.source_hash,
            "features": {
                tag: {
                    "description": f.description,
                    "parents": f.parents,
                    "children": f.children,
                    "vertical_score": f.vertical_score,
                    "effective_value": f.effective_value
                }
                for tag, f in self.features.items()
            },
            "completed": sorted(self.completed),
            "ready": sorted(self.ready),
            "batch_number": self.batch_number
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DAGState':
        """Load from JSON dict."""
        features = {}
        for tag, f in data["features"].items():
            features[tag] = Feature(
                tag=tag,
                description=f["description"],
                parents=f["parents"],
                children=f["children"],
                vertical_score=f["vertical_score"],
                effective_value=f["effective_value"]
            )
        return cls(
            source_hash=data["source_hash"],
            features=features,
            completed=set(data["completed"]),
            ready=set(data["ready"]),
            batch_number=data.get("batch_number", 0)
        )


class DAGSelector:
    """Selects the next batch of features to implement."""

    def __init__(self, dag_file="FEATURE_DAG.md", state_file="DAG_STATE.json",
                 batch_file="CURRENT_BATCH.md"):
        self.dag_file = Path(dag_file)
        self.state_file = Path(state_file)
        self.batch_file = Path(batch_file)
        self.state: Optional[DAGState] = None

    def compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file contents."""
        if not file_path.exists():
            return ""
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    def load_state(self) -> bool:
        """
        Load DAG state from JSON file.

        Returns True if state was loaded, False if rebuild needed.
        """
        if not self.state_file.exists():
            return False

        with open(self.state_file, 'r') as f:
            data = json.load(f)

        self.state = DAGState.from_dict(data)

        # Check if source markdown changed
        if self.dag_file.exists():
            current_hash = self.compute_file_hash(self.dag_file)
            if current_hash != self.state.source_hash:
                print(f"WARNING: {self.dag_file} has changed since state was built", file=sys.stderr)
                print(f"  Run with --rebuild to regenerate state", file=sys.stderr)
                # Continue with existing state but warn

        return True

    def save_state(self) -> None:
        """Save DAG state to JSON file."""
        if self.state is None:
            return
        with open(self.state_file, 'w') as f:
            json.dump(self.state.to_dict(), f, indent=2)
            f.write('\n')

    def parse_feature_dag(self) -> Dict[str, Feature]:
        """
        Parse FEATURE_DAG.csv into Feature objects.
        Used for backwards compatibility when DAG_STATE.json doesn't exist.
        """
        if not self.dag_file.exists():
            raise FileNotFoundError(f"{self.dag_file} does not exist")

        features: Dict[str, Feature] = {}

        with open(self.dag_file, 'r', newline='') as f:
            reader = csv.DictReader(f)

            for row in reader:
                tag = row.get('Feature Tag', '').strip()
                if not tag:
                    continue

                description = row.get('Description', '').strip()
                parents_str = row.get('Parents', '').strip()
                score_str = row.get('Vertical Score', '').strip()

                # Parse parents (comma-separated list)
                if parents_str:
                    parents = [p.strip() for p in parents_str.split(',') if p.strip()]
                else:
                    parents = []

                # Parse score
                try:
                    score = int(score_str) if score_str else 5
                except ValueError:
                    score = 5

                features[tag] = Feature(
                    tag=tag,
                    description=description,
                    parents=parents,
                    children=[],
                    vertical_score=score,
                    effective_value=0
                )

        # Build children
        for tag, feature in features.items():
            for parent_tag in feature.parents:
                if parent_tag in features:
                    features[parent_tag].children.append(tag)

        return features

    def calculate_effective_values(self, features: Dict[str, Feature]) -> None:
        """Calculate effective values for all features."""
        calculated: Set[str] = set()

        def calculate(tag: str, visited: Set[str]) -> int:
            if tag in calculated:
                return features[tag].effective_value
            if tag in visited:
                return features[tag].vertical_score

            visited.add(tag)
            feature = features[tag]

            if not feature.children:
                feature.effective_value = feature.vertical_score
            else:
                child_values = [
                    calculate(child, visited)
                    for child in feature.children
                    if child in features
                ]
                max_child = max(child_values) if child_values else 0
                feature.effective_value = max(feature.vertical_score, max_child)

            visited.remove(tag)
            calculated.add(tag)
            return feature.effective_value

        for tag in features:
            if tag not in calculated:
                calculate(tag, set())

    def build_state_from_markdown(self) -> None:
        """Build state from markdown (backwards compatibility / rebuild)."""
        print(f"Building state from {self.dag_file}...", file=sys.stderr)

        features = self.parse_feature_dag()
        self.calculate_effective_values(features)

        # Compute ready set (features with no incomplete parents)
        ready = {
            tag for tag, f in features.items()
            if all(p not in features or False for p in f.parents)  # No parents = ready
        }
        # Actually: ready = features with no parents OR all parents complete
        # Since completed is empty on fresh build, only no-parent features are ready
        ready = {tag for tag, f in features.items() if not f.parents}

        self.state = DAGState(
            source_hash=self.compute_file_hash(self.dag_file),
            features=features,
            completed=set(),
            ready=ready
        )

        self.save_state()
        print(f"  Created {self.state_file} with {len(features)} features", file=sys.stderr)

    def select_batch(self, batch_size: int = 5) -> List[str]:
        """
        Select the next batch of features from the ready set.

        Only includes features that share the highest effective score.
        This ensures all features in a batch have equal priority.

        Complexity: O(|ready| log |ready|) - just sort the ready set
        """
        if self.state is None:
            return []

        # Sort ready set by priority
        candidates = sorted(
            self.state.ready,
            key=lambda tag: (
                -self.state.features[tag].effective_value,
                -self.state.features[tag].vertical_score,
                tag
            )
        )

        if not candidates:
            return []

        # Get the highest effective score
        top_effective_score = self.state.features[candidates[0]].effective_value

        # Only include features that match the top effective score
        batch = [
            tag for tag in candidates
            if self.state.features[tag].effective_value == top_effective_score
        ]

        # Cap at batch_size (in case many features tie at top score)
        return batch[:batch_size]

    def mark_completed(self, tags: List[str]) -> None:
        """
        Mark features as completed and update ready set incrementally.

        Complexity: O(|tags| × avg_children)
        """
        if self.state is None:
            return

        for tag in tags:
            if tag not in self.state.features:
                print(f"WARNING: Unknown feature tag: {tag}", file=sys.stderr)
                continue

            self.state.completed.add(tag)
            self.state.ready.discard(tag)

            # Check if any children became ready
            feature = self.state.features[tag]
            for child in feature.children:
                if child in self.state.completed:
                    continue
                if child not in self.state.features:
                    continue

                child_feature = self.state.features[child]
                all_parents_complete = all(
                    p in self.state.completed
                    for p in child_feature.parents
                )
                if all_parents_complete:
                    self.state.ready.add(child)

        self.save_state()

    def write_current_batch(self, batch: List[str]) -> None:
        """Write selected batch to CURRENT_BATCH.md."""
        batch_num = self.state.batch_number if self.state else 0
        with open(self.batch_file, 'w') as f:
            f.write("# Current Batch\n\n")
            f.write(f"Batch Number: {batch_num:03d}\n")
            f.write(f"Research Directory: ./research-docs/batch-{batch_num:03d}/\n\n")
            f.write("## Features\n\n")
            for tag in batch:
                f.write(f"[{tag}]\n")

    def run_select(self, batch_size: int = 5) -> int:
        """Select next batch and write to file."""
        import os

        # Try to load existing state
        if not self.load_state():
            # Fall back to building from CSV
            if self.dag_file.exists():
                self.build_state_from_markdown()
            else:
                print(f"ERROR: Neither {self.state_file} nor {self.dag_file} exists", file=sys.stderr)
                return -1

        batch = self.select_batch(batch_size)

        if batch:
            # Increment batch number
            self.state.batch_number += 1
            batch_num = self.state.batch_number

            # Create batch directory for research docs
            batch_dir = Path(f"research-docs/batch-{batch_num:03d}")
            batch_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created {batch_dir}", file=sys.stderr)

            # Save state with updated batch number
            self.save_state()

        self.write_current_batch(batch)

        return len(batch)

    def run_complete(self, tags_file: str) -> int:
        """Mark features from file as complete."""
        if not self.load_state():
            print(f"ERROR: {self.state_file} does not exist. Run --rebuild first.", file=sys.stderr)
            return -1

        # Parse tags from file
        tags_path = Path(tags_file)
        if not tags_path.exists():
            print(f"ERROR: {tags_file} does not exist", file=sys.stderr)
            return -1

        tags = []
        with open(tags_path, 'r') as f:
            for line in f:
                match = re.match(r'^\[([a-z0-9-]+)\]$', line.strip())
                if match:
                    tags.append(match.group(1))

        if not tags:
            print("WARNING: No feature tags found in file", file=sys.stderr)
            return 0

        self.mark_completed(tags)
        print(f"Marked {len(tags)} features complete", file=sys.stderr)

        return len(tags)

    def run_rebuild(self) -> int:
        """Force rebuild state from markdown."""
        if not self.dag_file.exists():
            print(f"ERROR: {self.dag_file} does not exist", file=sys.stderr)
            return -1

        # Preserve completed set if state exists
        preserved_completed: Set[str] = set()
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    old_data = json.load(f)
                preserved_completed = set(old_data.get("completed", []))
                print(f"Preserving {len(preserved_completed)} completed features", file=sys.stderr)
            except (json.JSONDecodeError, KeyError):
                pass

        self.build_state_from_markdown()

        # Restore completed and recompute ready
        if preserved_completed and self.state:
            # Filter to features that still exist
            valid_completed = preserved_completed & set(self.state.features.keys())
            self.state.completed = valid_completed

            # Recompute ready set
            self.state.ready = set()
            for tag, feature in self.state.features.items():
                if tag in self.state.completed:
                    continue
                if all(p in self.state.completed for p in feature.parents):
                    self.state.ready.add(tag)

            self.save_state()
            print(f"Restored {len(valid_completed)} completed, {len(self.state.ready)} ready", file=sys.stderr)

        return len(self.state.features) if self.state else 0


def main():
    parser = argparse.ArgumentParser(
        description='Deterministic feature selection for DAG-based development'
    )
    parser.add_argument(
        '--select',
        action='store_true',
        default=True,
        help='Select next batch (default mode)'
    )
    parser.add_argument(
        '--complete',
        metavar='FILE',
        help='Mark features in FILE as complete'
    )
    parser.add_argument(
        '--rebuild',
        action='store_true',
        help='Force rebuild DAG_STATE.json from FEATURE_DAG.md'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=5,
        help='Number of features to select (default: 5)'
    )
    parser.add_argument(
        '--dag-file',
        default='FEATURE_DAG.csv',
        help='Path to FEATURE_DAG.csv'
    )
    parser.add_argument(
        '--state-file',
        default='DAG_STATE.json',
        help='Path to DAG_STATE.json'
    )
    parser.add_argument(
        '--batch-file',
        default='CURRENT_BATCH.md',
        help='Path to CURRENT_BATCH.md'
    )

    args = parser.parse_args()

    selector = DAGSelector(
        dag_file=args.dag_file,
        state_file=args.state_file,
        batch_file=args.batch_file
    )

    try:
        if args.rebuild:
            result = selector.run_rebuild()
        elif args.complete:
            result = selector.run_complete(args.complete)
        else:
            result = selector.run_select(args.batch_size)

        if result < 0:
            return 1

        # Output result for flowchart integration
        print(result)
        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

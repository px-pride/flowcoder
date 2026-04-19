#!/usr/bin/env python3
"""
init-dag-state.py

Initialize DAG_STATE.json from FEATURE_DAG.csv for optimized DAG operations.

This script:
1. Parses FEATURE_DAG.csv to extract features, parents, and vertical scores
2. Builds bidirectional parent-child relationships
3. Calculates effective values (one time, O(N+E))
4. Initializes ready set (features with all parents complete)
5. Optionally imports completed features from FEATURE_COMPLETION.md
6. Computes source hash for change detection
7. Writes DAG_STATE.json

Usage:
    ./init-dag-state.py                    # Initialize from CSV
    ./init-dag-state.py --import-completion # Also import existing completion status
    ./init-dag-state.py --force            # Overwrite existing state
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Set, Optional


@dataclass
class FeatureData:
    """Feature data for JSON serialization."""
    description: str
    parents: List[str]
    children: List[str]
    vertical_score: int
    effective_value: int


@dataclass
class DAGState:
    """Complete DAG state for persistence."""
    source_hash: str
    features: Dict[str, FeatureData]
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
            features[tag] = FeatureData(
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


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file contents."""
    if not file_path.exists():
        return ""
    with open(file_path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def parse_feature_dag(dag_file: Path) -> Dict[str, FeatureData]:
    """
    Parse FEATURE_DAG.csv into FeatureData objects.

    Expected CSV format:
    Feature Tag,Description,Parents,Vertical Score,Effective Score
    hello-world,Hello World proof of concept,,10,
    feature-one,First feature description,,9,
    feature-two,Second feature description,feature-one,8,
    feature-three,Third feature,"feature-one,feature-two",7,
    """
    if not dag_file.exists():
        raise FileNotFoundError(f"{dag_file} does not exist")

    features: Dict[str, FeatureData] = {}

    with open(dag_file, 'r', newline='') as f:
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

            features[tag] = FeatureData(
                description=description,
                parents=parents,
                children=[],
                vertical_score=score,
                effective_value=0  # Will be calculated
            )

    return features


def build_children(features: Dict[str, FeatureData]) -> None:
    """Build bidirectional children relationships from parents."""
    for tag, feature in features.items():
        for parent_tag in feature.parents:
            if parent_tag in features:
                features[parent_tag].children.append(tag)


def calculate_effective_values(features: Dict[str, FeatureData]) -> None:
    """
    Calculate effective values for all features.

    Effective value = max(vertical_score, max(children's effective_values))
    """
    calculated: Set[str] = set()

    def calculate(tag: str, visited: Set[str]) -> int:
        if tag in calculated:
            return features[tag].effective_value

        if tag in visited:
            # Cycle detected - should not happen with valid DAG
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


def parse_completions(completion_file: Path) -> Set[str]:
    """Parse FEATURE_COMPLETION.md to get completed feature tags."""
    if not completion_file.exists():
        return set()

    completed = set()
    with open(completion_file, 'r') as f:
        for line in f:
            match = re.match(r'^\[([a-z0-9-]+)\]$', line.strip())
            if match:
                completed.add(match.group(1))

    return completed


def compute_ready_set(features: Dict[str, FeatureData], completed: Set[str]) -> Set[str]:
    """Compute features that are ready to implement (all parents complete)."""
    ready = set()
    for tag, feature in features.items():
        if tag in completed:
            continue
        if all(parent in completed for parent in feature.parents):
            ready.add(tag)
    return ready


def save_state(state: DAGState, state_file: Path) -> None:
    """Save DAG state to JSON file."""
    with open(state_file, 'w') as f:
        json.dump(state.to_dict(), f, indent=2)
        f.write('\n')


def main():
    parser = argparse.ArgumentParser(
        description='Initialize DAG_STATE.json from FEATURE_DAG.csv'
    )
    parser.add_argument(
        '--dag-file',
        default='FEATURE_DAG.csv',
        help='Path to FEATURE_DAG.csv (default: FEATURE_DAG.csv)'
    )
    parser.add_argument(
        '--state-file',
        default='DAG_STATE.json',
        help='Path to output DAG_STATE.json (default: DAG_STATE.json)'
    )
    parser.add_argument(
        '--import-completion',
        action='store_true',
        help='Import completed features from FEATURE_COMPLETION.md'
    )
    parser.add_argument(
        '--completion-file',
        default='FEATURE_COMPLETION.md',
        help='Path to FEATURE_COMPLETION.md (default: FEATURE_COMPLETION.md)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite existing DAG_STATE.json'
    )

    args = parser.parse_args()

    dag_file = Path(args.dag_file)
    state_file = Path(args.state_file)
    completion_file = Path(args.completion_file)

    # Check if state file exists
    if state_file.exists() and not args.force:
        print(f"ERROR: {state_file} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    # Parse DAG
    print(f"Parsing {dag_file}...", file=sys.stderr)
    try:
        features = parse_feature_dag(dag_file)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"  Found {len(features)} features", file=sys.stderr)

    # Build children relationships
    build_children(features)
    edge_count = sum(len(f.children) for f in features.values())
    print(f"  Built {edge_count} parent-child edges", file=sys.stderr)

    # Calculate effective values
    calculate_effective_values(features)
    print("  Calculated effective values", file=sys.stderr)

    # Import completions if requested
    completed: Set[str] = set()
    if args.import_completion:
        completed = parse_completions(completion_file)
        # Filter to only features that exist in DAG
        completed = completed & set(features.keys())
        print(f"  Imported {len(completed)} completed features from {completion_file}", file=sys.stderr)

    # Compute ready set
    ready = compute_ready_set(features, completed)
    print(f"  {len(ready)} features ready to implement", file=sys.stderr)

    # Compute source hash
    source_hash = compute_file_hash(dag_file)

    # Create state
    state = DAGState(
        source_hash=source_hash,
        features=features,
        completed=completed,
        ready=ready
    )

    # Save state
    save_state(state, state_file)
    print(f"Wrote {state_file}", file=sys.stderr)

    # Output summary
    print(len(features))  # For flowchart integration

    return 0


if __name__ == "__main__":
    sys.exit(main())

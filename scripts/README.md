# DAG Feature Selection Scripts

This directory contains deterministic, script-based feature selection for the DAG-based autonomous development system.

## Purpose

These scripts replace the LLM-based feature selection in `commands/iterate-dag.json` with a purely algorithmic approach, providing:

- **Deterministic results** - Same input always produces same output
- **Faster execution** - No LLM API calls required
- **Lower cost** - No token usage for selection
- **Easier debugging** - Standard programming tools work
- **Testability** - Can write unit tests and verify behavior
- **O(N+E) complexity** - Optimized for large DAGs with incremental state updates

## Architecture

The system uses a JSON state file (`DAG_STATE.json`) for efficient operation:

```
FEATURE_DAG.md (source)
       │
       ▼ (init-dag-state.py, one-time)
DAG_STATE.json (optimized state)
       │
       ▼ (select-next-batch.py, per iteration)
CURRENT_BATCH.md (output)
```

**State contains:**
- Pre-parsed features with parent/child relationships
- Pre-calculated effective values (never recalculated)
- Completed set (updated incrementally)
- Ready set (maintained incrementally)

## Files

### `init-dag-state.py`

Initializes `DAG_STATE.json` from `FEATURE_DAG.md`. Run once after DAG creation.

**Operations:**
1. Parse FEATURE_DAG.md
2. Build bidirectional parent-child relationships
3. Calculate effective values (O(N+E))
4. Initialize ready set (features with no parents)
5. Compute source hash for change detection
6. Write DAG_STATE.json

**Usage:**
```bash
# Initialize from markdown
./scripts/init-dag-state.py

# Import existing completion status
./scripts/init-dag-state.py --import-completion

# Force overwrite existing state
./scripts/init-dag-state.py --force
```

### `select-next-batch.py`

Core Python script with three modes of operation.

**Select mode (default):**
```bash
./scripts/select-next-batch.py
```
- Loads DAG_STATE.json
- Selects top 5 from ready set
- Writes CURRENT_BATCH.md
- Outputs batch size to stdout

**Complete mode:**
```bash
./scripts/select-next-batch.py --complete CURRENT_BATCH.md
```
- Marks features as completed
- Updates ready set incrementally (O(B × avg_children))
- Saves state

**Rebuild mode:**
```bash
./scripts/select-next-batch.py --rebuild
```
- Regenerates state from FEATURE_DAG.md
- Preserves completed features
- Recomputes ready set

### `select-next-batch.sh`

Bash wrapper for integration with the flowchart system.

**Usage:**
```bash
./scripts/select-next-batch.sh                    # Select next batch
./scripts/select-next-batch.sh --complete FILE    # Mark batch complete
./scripts/select-next-batch.sh --rebuild          # Force rebuild
```

## State File Format

### DAG_STATE.json

```json
{
  "source_hash": "sha256 of FEATURE_DAG.md",
  "features": {
    "feature-tag": {
      "description": "Feature description",
      "parents": ["parent1", "parent2"],
      "children": ["child1", "child2"],
      "vertical_score": 8,
      "effective_value": 9
    }
  },
  "completed": ["tag1", "tag2"],
  "ready": ["tag3", "tag4", "tag5"]
}
```

## Input File Formats

### FEATURE_DAG.md

```markdown
# Hello World

[hello-world] Minimal proof-of-concept

# Feature DAG

## [feature-tag]
Description: Full description of the feature
Parents: none
Vertical Score: 8

## [another-feature]
Description: Another feature
Parents: [feature-tag], [hello-world]
Vertical Score: 5
```

**Format rules:**
- Feature tags: `[a-z0-9-]+`
- Parents: `Parents: none` or `Parents: [tag1], [tag2], ...`
- Vertical Score: Integer 1-10

## Output File Formats

### CURRENT_BATCH.md

```markdown
# Current Batch

[feature-tag-1]
[feature-tag-2]
[feature-tag-3]
```

### stdout

Batch size as integer (for flowchart integration):
```
3
```

## Complexity Analysis

| Operation | Complexity | Notes |
|-----------|------------|-------|
| Initialization | O(N + E) | One-time, parses markdown and calculates effective values |
| Select batch | O(\|ready\| log \|ready\|) | Just sorts the pre-maintained ready set |
| Mark complete | O(B × avg_children) | Only updates affected children |
| **Total for N features** | **O(N + E)** | Was O(N²) before optimization |

For a DAG with 1000 features:
- **Before:** ~800,000 line parses, ~200,000 effective value calculations
- **After:** ~4,000 line parses (once), ~1,000 effective value calculations (once)

## Effective Value Calculation

The effective value ensures that features which unlock high-value children are themselves prioritized.

**Formula:** `effective_value = max(vertical_score, max(children's effective_values))`

**Example:**

```
[user-auth] (vertical=10, children: profile, dashboard, notifications)
  ├─ [user-profile] (vertical=7, children: avatar, settings)
  │   ├─ [profile-avatar] (vertical=4)
  │   └─ [settings] (vertical=3)
  ├─ [dashboard] (vertical=9, children: analytics)
  │   └─ [analytics] (vertical=6)
  └─ [notifications] (vertical=5)
```

**Calculated effective values:**
- `profile-avatar`: max(4) = 4 (leaf)
- `settings`: max(3) = 3 (leaf)
- `analytics`: max(6) = 6 (leaf)
- `notifications`: max(5) = 5 (leaf)
- `user-profile`: max(7, max(4, 3)) = **7**
- `dashboard`: max(9, 6) = **9**
- `user-auth`: max(10, max(7, 9, 5)) = **10**

## Hash-Based Invalidation

When `FEATURE_DAG.md` is modified:
1. On next select, hash mismatch is detected
2. Warning is printed to stderr
3. Run `--rebuild` to regenerate state (preserves completed features)

## Integration with Flowchart

### create-dag.json

After validation passes, initializes DAG_STATE.json:
```json
{
  "type": "bash",
  "command": "./scripts/init-dag-state.py --force"
}
```

### iterate-dag.json

Select batch:
```json
{
  "type": "bash",
  "command": "./scripts/select-next-batch.sh",
  "capture_output": true,
  "output_variable": "batchSize",
  "output_type": "int"
}
```

Mark complete:
```json
{
  "type": "bash",
  "command": "./scripts/select-next-batch.sh --complete CURRENT_BATCH.md"
}
```

## Testing

Test suite is located in `test-data/`:

```bash
./test-data/test-selector.sh
```

**Test coverage:**
- Empty completion (first batch selection)
- Partial completion (dependency-aware selection)
- Effective value propagation
- Parent dependency checking
- Incremental ready-set updates
- Rebuild with completion preservation

## Dependencies

- Python 3.x (standard library only, no external packages)
- Bash

## Troubleshooting

**Script fails with FileNotFoundError:**
- For first run: Ensure `FEATURE_DAG.md` exists
- For subsequent runs: Either `DAG_STATE.json` or `FEATURE_DAG.md` must exist

**"DAG_STATE.json not found" in iterate-dag:**
- Run `create-dag` first, or
- Run `./scripts/select-next-batch.sh --rebuild`

**WARNING: FEATURE_DAG.md has changed:**
- The markdown source was modified after state was built
- Run `./scripts/select-next-batch.sh --rebuild` to regenerate

**No features selected when features remain:**
- Verify parent dependencies are satisfied
- Check `DAG_STATE.json` for the `ready` set

**Wrong features selected:**
- Check effective values in `DAG_STATE.json`
- Verify completion status in `completed` array

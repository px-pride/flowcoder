# FlowCoder

A visual flowchart builder for creating custom automated workflows with Claude Code and Codex.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
uv sync
```

## Run

```bash
uv run python -m src.main
```

## Creating Commands

Commands are reusable workflows built from connected blocks in a flowchart. To create a command:

1. Click **New Command** in the Commands tab
2. Give your command a name (alphanumeric, hyphens, and underscores only)
3. Drag blocks from the **Block Palette** onto the canvas
4. Connect blocks by dragging from one block's output port to another's input port (branching special case below)
5. Configure each block by clicking on it and editing its properties

### Block Types

| Block | Purpose |
|-------|---------|
| **Start** | Entry point (required) |
| **Prompt** | Send a prompt to Claude and capture structured output |
| **Bash** | Execute shell commands |
| **Variable** | Set a variable to a value |
| **Branch** | Conditional branching based on variable values |
| **Command** | Invoke another command |
| **Refresh** | Restart the Claude session |
| **Cast** | Convert variable types |
| **End** | Exit point |

### Branch Blocks

Branch blocks evaluate a condition and follow either the **True path** (black arrow) or **False path** (blue arrow).

**Creating connections:**
- **True path**: Drag from a port to create a black arrow
- **False path**: Ctrl+Drag from a port to create a blue arrow

**Condition syntax:**

| Format | Example | Description |
|--------|---------|-------------|
| `field == value` | `status == "done"` | Equality check |
| `field != value` | `count != 0` | Inequality check |
| `field > value` | `score > 80` | Greater than |
| `field < value` | `attempts < 3` | Less than |
| `field >= value` | `progress >= 100` | Greater than or equal |
| `field <= value` | `errors <= 5` | Less than or equal |
| `field` | `isComplete` | Boolean field (truthy check) |
| `!field` | `!hasErrors` | Negated boolean field |

### Variable Substitution

Blocks can reference variables from previous blocks:
- `$1`, `$2`, etc. - Positional arguments passed to the command
- `{{variable_name}}` - Variables set by previous blocks

## Sessions

Sessions are isolated execution environments with their own working directory and Claude instance.
(Multiple sessions at once is currently disabled due to an architectural issue leading to memory leaks.)

### Creating a Session

1. Go to the **Agents** tab
2. Click **New Session**
3. Enter a session name and working directory
4. Optionally configure git remote settings

### How Sessions Work

- Each session has its own working directory where Bash blocks execute
- Sessions maintain separate chat and execution history
- Commands run in the context of the active session
- Session data persists to `~/.flowcoder/sessions.json`

### Executing Commands

1. Select a session to make it active
2. Go to the **Commands** tab
3. Select a command and click **Run** (or use the play button)
4. Watch execution progress in the flowchart canvas
5. View results in the chat panel

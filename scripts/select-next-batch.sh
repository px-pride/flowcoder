#!/bin/bash
#
# select-next-batch.sh
#
# Bash wrapper for select-next-batch.py
# Calls Python script to perform deterministic feature selection for DAG-based development
#
# Usage:
#   ./select-next-batch.sh                    # Select next batch (default)
#   ./select-next-batch.sh --complete FILE    # Mark features in FILE as complete
#   ./select-next-batch.sh --rebuild          # Force rebuild from markdown
#

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Call the Python script with all arguments
python3 "$SCRIPT_DIR/select-next-batch.py" "$@"

#!/usr/bin/env bash
# Stress test runner for the flowcoder engine.
# Runs each stress-test flowchart through the engine and reports pass/fail.
# To exercise the codex/proxy path, export ANTHROPIC_BASE_URL and
# ANTHROPIC_MODEL before running this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENGINE_DIR="$(cd "$SCRIPT_DIR/../../packages/flowcoder-engine" && pwd)"
SEARCH_PATH="$SCRIPT_DIR"
PYTHON="${REPO_DIR}/.venv/bin/python"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0
RESULTS=()

run_test() {
    local test_name="$1"
    local expected_status="${2:-completed}"
    local timeout_secs="${3:-120}"

    echo -e "\n${YELLOW}=== Running: $test_name ===${NC}"

    # Build the JSON user message
    local user_msg='{"type":"user","message":{"content":"/'$test_name'"}}'
    local shutdown_msg='{"type":"shutdown"}'

    # Run engine with timeout, capture all output
    local output
    if output=$(printf '%s\n%s\n' "$user_msg" "$shutdown_msg" | \
        timeout "$timeout_secs" \
        "$PYTHON" -m flowcoder_engine --search-path "$SEARCH_PATH" 2>/dev/null); then
        :
    else
        local rc=$?
        if [ $rc -eq 124 ]; then
            echo -e "${RED}TIMEOUT after ${timeout_secs}s${NC}"
            RESULTS+=("$test_name: TIMEOUT")
            ((FAIL++))
            return
        fi
    fi

    # Extract the result line
    local result_line
    result_line=$(echo "$output" | grep '"type":"result"' | tail -1 || true)
    local flowchart_complete
    flowchart_complete=$(echo "$output" | grep '"flowchart_complete"' | tail -1 || true)

    if [ -z "$result_line" ]; then
        echo -e "${RED}FAIL - no result event found${NC}"
        echo "Raw output (last 20 lines):"
        echo "$output" | tail -20
        RESULTS+=("$test_name: NO_RESULT")
        ((FAIL++))
        return
    fi

    # Check status from flowchart_complete event
    local status
    status=$(echo "$flowchart_complete" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")

    # Check is_error from result
    local is_error
    is_error=$(echo "$result_line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('is_error', False))" 2>/dev/null || echo "unknown")

    # Extract result content
    local result_content
    result_content=$(echo "$result_line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result','')[:200])" 2>/dev/null || echo "")

    echo "Status: $status | is_error: $is_error"
    echo "Result: $result_content"

    if [ "$status" = "$expected_status" ] && [ "$is_error" = "False" ]; then
        echo -e "${GREEN}PASS${NC}"
        RESULTS+=("$test_name: PASS")
        ((PASS++))
    elif [ "$expected_status" = "exited" ] && [ "$status" = "exited" ]; then
        # Exit tests are expected to have is_error=True but status=exited
        echo -e "${GREEN}PASS (exit test)${NC}"
        RESULTS+=("$test_name: PASS")
        ((PASS++))
    else
        echo -e "${RED}FAIL (expected status=$expected_status, got status=$status, is_error=$is_error)${NC}"
        echo "Full output:"
        echo "$output" | tail -30
        RESULTS+=("$test_name: FAIL")
        ((FAIL++))
    fi
}

echo "======================================"
echo " Engine Stress Tests"
echo "======================================"
echo "Search path: $SEARCH_PATH"
echo "Engine dir: $ENGINE_DIR"

# Test 1: Bash blocks (no LLM calls needed)
run_test "stress-bash" "completed"

# Test 2: Exit block
run_test "stress-exit" "exited"

# Test 3: Variables + prompt + branch (needs LLM)
run_test "stress-variables" "completed"

# Test 4: Multi-prompt conversation continuity (needs LLM)
run_test "stress-multi-prompt" "completed"

# Test 5: Refresh / clear session (needs LLM)
run_test "stress-refresh" "completed"

# Test 6: Loop with prompt (needs LLM, 3 iterations)
run_test "stress-loop" "completed" 180

# Test 7: Command composition (needs LLM)
run_test "stress-command" "completed"

# Test 8: Spawn + wait with 2 agents (needs 2 LLM sessions)
run_test "stress-spawn-wait" "completed" 180

echo ""
echo "======================================"
echo " RESULTS SUMMARY"
echo "======================================"
for r in "${RESULTS[@]}"; do
    if [[ "$r" == *"PASS"* ]]; then
        echo -e "  ${GREEN}$r${NC}"
    else
        echo -e "  ${RED}$r${NC}"
    fi
done
echo ""
echo -e "Total: $((PASS + FAIL)) | ${GREEN}Pass: $PASS${NC} | ${RED}Fail: $FAIL${NC}"
echo "======================================"

if [ $FAIL -gt 0 ]; then
    exit 1
fi

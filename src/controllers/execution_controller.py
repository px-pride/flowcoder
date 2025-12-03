"""
Execution Controller for FlowCoder

Executes flowcharts by running blocks sequentially, handling branching,
and managing execution state.
"""

import asyncio
import inspect
import logging
import os
import re
import signal
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Union
from jsonpath_ng import parse as jsonpath_parse

from src.models import (
    Command,
    Flowchart,
    Block,
    BlockType,
    StartBlock,
    PromptBlock,
    VariableBlock,
    BashBlock,
    BranchBlock,
    EndBlock
)
from src.models.blocks import CommandBlock
from src.models.execution import (
    ExecutionContext,
    ExecutionLogEntry,
    ExecutionStatus,
    BlockExecutionStatus,
    BlockResult
)
from src.services import (
    ClaudeServiceError,
    StorageService
)
from src.services.command_block_executor import (
    CommandBlockExecutor,
    CommandBlockExecutorError
)
from src.utils.variable_substitution import VariableSubstitution


logger = logging.getLogger(__name__)


class ExecutionControllerError(Exception):
    """Base exception for execution controller errors."""
    pass


class ExecutionController:
    """
    Controller for executing flowcharts with Claude.

    Handles:
    - Sequential block execution
    - Branching based on structured output
    - Loop detection and prevention
    - Halt mechanism
    - Execution logging
    - Event callbacks
    """

    # Configuration
    # MAX_LOOP_ITERATIONS = 10   # Removed - infinite loops are allowed
    # LOOP_WARNING_THRESHOLD = 8 # Removed - no loop iteration warnings
    MAX_TOTAL_BLOCKS = 1000    # Safety limit for total blocks executed
    MAX_SCHEMA_RETRIES = 5     # Maximum attempts to get valid schema from Claude

    def __init__(
        self,
        agent_service,
        storage_service: Optional[StorageService] = None,
        on_execution_start: Optional[Callable[[str, ExecutionContext], None]] = None,
        on_block_start: Optional[Callable[[Block, ExecutionContext], None]] = None,
        on_block_complete: Optional[Callable[[Block, BlockResult, ExecutionContext], None]] = None,
        on_execution_complete: Optional[Callable[[ExecutionContext], None]] = None,
        on_prompt_stream: Optional[Callable[[str, str], None]] = None,
        on_block_complete_async: Optional[Callable[[Block, BlockResult, ExecutionContext], Any]] = None
    ):
        """
        Initialize execution controller.

        Args:
            agent_service: AI agent service instance (ClaudeAgentService, CodexService, or MockClaudeService)
            storage_service: Storage service for loading commands (required for command blocks)
            on_execution_start: Callback fired when command execution starts (command_name, context)
            on_block_start: Callback fired when block execution starts
            on_block_complete: Callback fired when block execution completes (sync, for UI updates)
            on_execution_complete: Callback fired when entire execution completes
            on_prompt_stream: Callback fired with streaming chunks during prompt execution (prompt_text, chunk)
            on_block_complete_async: Async callback awaited after block completes (for git workflow, etc.)
        """
        self.agent_service = agent_service
        self.on_refresh_requested: Optional[Union[Callable[[], None], Callable[[], Any]]] = None
        self.storage_service = storage_service
        self.on_execution_start = on_execution_start
        self.on_block_start = on_block_start
        self.on_block_complete = on_block_complete
        self.on_block_complete_async = on_block_complete_async
        self.on_execution_complete = on_execution_complete
        self.on_prompt_stream = on_prompt_stream
        self.current_context: Optional[ExecutionContext] = None

        # Track running bash processes for cleanup
        self.running_processes = []

        # Initialize command block executor if storage service is available
        if self.storage_service:
            self.command_block_executor = CommandBlockExecutor(
                storage_service=self.storage_service,
                execution_controller=self
            )
        else:
            self.command_block_executor = None

        logger.info("ExecutionController initialized")

    def halt(self) -> None:
        """
        Request that the current execution be halted gracefully.

        The execution will complete the current block and then stop
        before executing the next block.
        """
        if self.current_context:
            self.current_context.request_halt()
            logger.info("Halt requested for current execution")
        else:
            logger.warning("No active execution to halt")

    async def cleanup_processes(self) -> None:
        """
        Terminate all running bash processes.

        This should be called when the application is shutting down
        or when execution is being halted.
        """
        if not self.running_processes:
            logger.debug("No running processes to clean up")
            return

        logger.info(f"Cleaning up {len(self.running_processes)} running bash processes")

        for process in self.running_processes[:]:  # Iterate over a copy
            try:
                if process.returncode is None:  # Process is still running
                    pid = process.pid
                    logger.info(f"Terminating bash process group (PID: {pid})")

                    # Kill the entire process group (includes all child processes)
                    try:
                        os.killpg(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        logger.debug(f"Process group {pid} already gone")
                        continue

                    # Give it a moment to terminate gracefully
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                        logger.debug(f"Process group {pid} terminated gracefully")
                    except asyncio.TimeoutError:
                        # Force kill if it doesn't terminate
                        logger.warning(f"Process group {pid} didn't terminate, sending SIGKILL")
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass  # Already gone
                        await process.wait()

            except Exception as e:
                logger.error(f"Error terminating process: {e}")

        # Clear the list
        self.running_processes.clear()
        logger.info("All bash processes cleaned up")

    async def execute(
        self,
        command: Command,
        arguments: Optional[Dict[str, str]] = None,
        flowchart: Optional[Flowchart] = None,
        context: Optional[ExecutionContext] = None
    ) -> ExecutionContext:
        """
        Execute a command's flowchart.

        Args:
            command: The command to execute
            arguments: Optional command arguments dict ($1, $2, etc.) for variable substitution
            flowchart: Optional flowchart to execute (if None, uses command.flowchart).
                      This allows executing a copy of the flowchart without modifying the original.
            context: Optional execution context (if None, creates new one).
                    Used for command blocks to pass child context.

        Returns:
            ExecutionContext with complete execution history

        Raises:
            ExecutionControllerError: If execution fails critically
        """
        # Use provided flowchart or default to command's flowchart
        exec_flowchart = flowchart if flowchart is not None else command.flowchart

        # Use provided context or create new one
        if context is None:
            now = datetime.now()
            context = ExecutionContext(
                command_id=command.id,
                command_name=command.name,
                start_time=now,
                status=ExecutionStatus.RUNNING
            )
            # Initialize context.variables with command arguments
            if arguments:
                context.variables.update(arguments)
                logger.info(f"Initialized context with arguments: {arguments}")

        # Track current context for halt functionality
        self.current_context = context

        logger.info(f"Starting execution of command: {command.name} ({command.id})")
        if flowchart is not None:
            logger.debug("Using provided flowchart copy for execution")

        # Fire execution start callback
        if self.on_execution_start:
            self.on_execution_start(command.name, context)

        try:
            # Validate flowchart
            validation_result = exec_flowchart.validate()
            if not validation_result.valid:
                raise ExecutionControllerError(
                    f"Flowchart validation failed: {', '.join(validation_result.errors)}"
                )

            # Find start block
            start_block = None
            for block in exec_flowchart.blocks.values():
                if block.type == BlockType.START:
                    start_block = block
                    break

            if not start_block:
                raise ExecutionControllerError("No start block found in flowchart")

            # Execute flowchart starting from start block
            current_block = start_block
            blocks_executed = 0

            while current_block and not context.is_halted():
                # Safety check: prevent infinite execution
                blocks_executed += 1
                if blocks_executed > self.MAX_TOTAL_BLOCKS:
                    context.complete(ExecutionStatus.ERROR)
                    raise ExecutionControllerError(
                        f"Exceeded maximum block execution limit ({self.MAX_TOTAL_BLOCKS})"
                    )

                # Update context with current block
                context.current_block_id = current_block.id

                # Fire callback
                if self.on_block_start:
                    self.on_block_start(current_block, context)

                logger.debug(f"Executing block: {current_block.name} ({current_block.id})")

                # Execute the block
                result = await self._execute_block(current_block, exec_flowchart, context)

                # Log execution
                log_entry = ExecutionLogEntry(
                    block_id=current_block.id,
                    block_name=current_block.name,
                    timestamp=datetime.now(),
                    status=BlockExecutionStatus.SUCCESS if result.success else BlockExecutionStatus.ERROR,
                    output=result.output,
                    raw_response=result.raw_response,
                    error=result.error,
                    duration_ms=result.duration_ms
                )
                context.add_log_entry(log_entry)

                # If block has structured output, merge into context.variables
                # This makes variables available for {{varname}} substitution in later blocks
                # Note: Command blocks handle their own merging via merge_output flag, so skip them here
                if result.success and result.output and isinstance(result.output, dict):
                    if current_block.type != BlockType.COMMAND:
                        context.variables.update(result.output)
                        logger.debug(f"Merged structured output into context.variables: {list(result.output.keys())}")
                    else:
                        logger.debug(f"Skipped merge for command block (merge_output flag controls merging)")

                # Fire sync callback (for UI updates)
                if self.on_block_complete:
                    self.on_block_complete(current_block, result, context)

                # Fire async callback and await it (for git workflow, etc.)
                if self.on_block_complete_async:
                    try:
                        coro = self.on_block_complete_async(current_block, result, context)
                        if coro is not None:
                            await coro
                    except Exception as e:
                        logger.error(f"Async block complete callback failed: {e}")

                # Check for errors
                if not result.success:
                    logger.error(f"Block execution failed: {result.error}")
                    context.complete(ExecutionStatus.ERROR)
                    break

                # Get next block
                if current_block.type == BlockType.END:
                    logger.info("Reached end block, execution complete")
                    current_block = None
                elif current_block.type == BlockType.BRANCH:
                    # Branching handled in _execute_block, it returns next_block_id in output
                    next_block_id = result.output.get("next_block_id") if result.output else None
                    if next_block_id:
                        current_block = self._get_block_by_id(exec_flowchart, next_block_id)
                        if not current_block:
                            raise ExecutionControllerError(f"Next block not found: {next_block_id}")
                    else:
                        logger.warning("Branch block did not specify next block, ending execution")
                        current_block = None
                else:
                    # Get next block from connections
                    prev_block_name = current_block.name
                    current_block = exec_flowchart.get_next_block(current_block.id)
                    if not current_block:
                        logger.warning(f"No next block found after {prev_block_name}")

            # Mark execution as complete
            if context.status == ExecutionStatus.RUNNING:
                if context.is_halted():
                    context.complete(ExecutionStatus.HALTED)
                    logger.info("Execution halted by user")
                else:
                    context.complete(ExecutionStatus.COMPLETED)
                    logger.info(f"Execution completed successfully in {context.get_duration_ms()}ms")

        except Exception as e:
            logger.error(f"Execution failed with exception: {e}")
            context.complete(ExecutionStatus.ERROR)
            # Add error to last log entry if exists
            if context.execution_log:
                context.execution_log[-1].error = str(e)
            raise

        finally:
            # Clear current context
            self.current_context = None

            # Fire completion callback
            if self.on_execution_complete:
                self.on_execution_complete(context)

        return context

    async def resume(
        self,
        command: Command,
        context: ExecutionContext,
        flowchart: Optional[Flowchart] = None
    ) -> ExecutionContext:
        """
        Resume execution from a halted state.

        Args:
            command: The command that was halted
            context: The execution context from halt point
            flowchart: Optional flowchart (if None, uses command.flowchart)

        Returns:
            ExecutionContext with complete execution history

        Raises:
            ExecutionControllerError: If resume fails
        """
        logger.info(f"Resuming execution from block: {context.current_block_id}")

        # Use provided flowchart or get from command
        exec_flowchart = flowchart if flowchart else command.flowchart

        # Set current context
        self.current_context = context

        try:
            # Find the block where we halted
            current_block = self._get_block_by_id(exec_flowchart, context.current_block_id)
            if not current_block:
                raise ExecutionControllerError(f"Cannot find halted block: {context.current_block_id}")

            # Get next block (the one after where we halted)
            if current_block.type == BlockType.END:
                # We halted on END block - just complete
                logger.info("Halted on END block - execution complete")
                context.complete(ExecutionStatus.COMPLETED)
                return context
            elif current_block.type == BlockType.BRANCH:
                # For branch blocks, we need the next_block_id from output
                # But if we halted, we might not have executed this block yet
                # In that case, execute it now
                logger.warning("Resuming on BRANCH block - may need to re-evaluate")
                next_block = None
            else:
                # Get next block from connections
                next_block = exec_flowchart.get_next_block(current_block.id)

            if next_block:
                # Continue execution from next block
                logger.info(f"Continuing execution from: {next_block.name}")
                return await self._continue_execution(next_block, exec_flowchart, context)
            else:
                # No next block - execution complete
                logger.info("No next block after halt point - execution complete")
                context.complete(ExecutionStatus.COMPLETED)
                return context

        except Exception as e:
            logger.error(f"Resume failed with exception: {e}")
            context.complete(ExecutionStatus.ERROR)
            if context.execution_log:
                context.execution_log[-1].error = str(e)
            raise

        finally:
            # Clear current context
            self.current_context = None

            # Fire completion callback
            if self.on_execution_complete:
                self.on_execution_complete(context)

    async def _continue_execution(
        self,
        start_block: Block,
        flowchart: Flowchart,
        context: ExecutionContext
    ) -> ExecutionContext:
        """
        Continue execution from a specific block with existing context.

        This is similar to execute() but uses an existing context instead of creating a new one.

        Args:
            start_block: Block to start execution from
            flowchart: Flowchart being executed
            context: Existing execution context

        Returns:
            ExecutionContext with updated execution history
        """
        logger.debug(f"Continuing execution from block: {start_block.name}")

        current_block = start_block
        blocks_executed = len(context.execution_log)  # Continue counting from where we left off

        # Execution loop (same as execute() but with existing context)
        while current_block and not context.is_halted():
            # Safety check: prevent infinite execution
            blocks_executed += 1
            if blocks_executed > self.MAX_TOTAL_BLOCKS:
                context.complete(ExecutionStatus.ERROR)
                raise ExecutionControllerError(
                    f"Exceeded maximum block execution limit ({self.MAX_TOTAL_BLOCKS})"
                )

            # Update context with current block
            context.current_block_id = current_block.id

            # Fire callback
            if self.on_block_start:
                self.on_block_start(current_block, context)

            logger.debug(f"Executing block: {current_block.name} ({current_block.id})")

            # Execute the block
            result = await self._execute_block(current_block, flowchart, context)

            # Log execution
            log_entry = ExecutionLogEntry(
                block_id=current_block.id,
                block_name=current_block.name,
                timestamp=datetime.now(),
                status=BlockExecutionStatus.SUCCESS if result.success else BlockExecutionStatus.ERROR,
                output=result.output,
                raw_response=result.raw_response,
                error=result.error,
                duration_ms=result.duration_ms
            )
            context.add_log_entry(log_entry)

            # If block has structured output, merge into context.variables
            if result.success and result.output and isinstance(result.output, dict):
                context.variables.update(result.output)
                logger.debug(f"Merged structured output into context.variables: {list(result.output.keys())}")

            # Fire callback
            if self.on_block_complete:
                self.on_block_complete(current_block, result, context)

            # Check for errors
            if not result.success:
                logger.error(f"Block execution failed: {result.error}")
                context.complete(ExecutionStatus.ERROR)
                break

            # Get next block
            if current_block.type == BlockType.END:
                logger.info("Reached end block, execution complete")
                current_block = None
            elif current_block.type == BlockType.BRANCH:
                # Branching handled in _execute_block, it returns next_block_id in output
                next_block_id = result.output.get("next_block_id") if result.output else None
                if next_block_id:
                    current_block = self._get_block_by_id(flowchart, next_block_id)
                    if not current_block:
                        raise ExecutionControllerError(f"Next block not found: {next_block_id}")
                else:
                    logger.warning("Branch block did not specify next block, ending execution")
                    current_block = None
            else:
                # Get next block from connections
                prev_block_name = current_block.name
                current_block = flowchart.get_next_block(current_block.id)
                if not current_block:
                    logger.warning(f"No next block found after {prev_block_name}")

        # Mark execution as complete
        if context.status == ExecutionStatus.RUNNING:
            if context.is_halted():
                context.complete(ExecutionStatus.HALTED)
                logger.info("Execution halted by user (during resume)")
            else:
                context.complete(ExecutionStatus.COMPLETED)
                logger.info("Resumed execution completed successfully")

        return context

    async def _execute_block(
        self,
        block: Block,
        flowchart: Flowchart,
        context: ExecutionContext
    ) -> BlockResult:
        """
        Execute a single block.

        Args:
            block: The block to execute
            flowchart: The flowchart containing the block
            context: Execution context

        Returns:
            BlockResult with execution results
        """
        if block.type == BlockType.START:
            return await self._execute_start_block(block, context)
        elif block.type == BlockType.PROMPT:
            return await self._execute_prompt_block(block, context)
        elif block.type == BlockType.VARIABLE:
            return await self._execute_variable_block(block, context)
        elif block.type == BlockType.BASH:
            return await self._execute_bash_block(block, context)
        elif block.type == BlockType.BRANCH:
            return await self._execute_branch_block(block, flowchart, context)
        elif block.type == BlockType.COMMAND:
            return await self._execute_command_block(block, context)
        elif block.type == BlockType.END:
            return await self._execute_end_block(block, context)
        elif block.type == BlockType.REFRESH:
            return await self._execute_refresh_block(context)
        else:
            return BlockResult.error_result(f"Unknown block type: {block.type}")

    async def _execute_start_block(
        self,
        block: StartBlock,
        context: ExecutionContext
    ) -> BlockResult:
        """Execute start block (just passes through)."""
        logger.debug("Executing start block")
        return BlockResult.success_result(
            raw_response="Execution started",
            duration_ms=0
        )

    async def _execute_variable_block(
        self,
        block: VariableBlock,
        context: ExecutionContext
    ) -> BlockResult:
        """
        Execute variable block - sets a variable to a value.

        Args:
            block: The VariableBlock to execute
            context: Execution context

        Returns:
            BlockResult with execution results
        """
        start_time = datetime.now()
        logger.debug(f"Executing variable block: {block.variable_name} = {block.variable_value}")

        try:
            # Substitute variables in the variable_value
            # This allows setting variables based on other variables or command arguments
            value_str = VariableSubstitution.substitute_all(
                block.variable_value,
                arguments=context.variables,
                variables=context.variables
            )

            # Parse value according to type (NEW - Issue #2)
            try:
                if block.variable_type == "int":
                    value = int(value_str)
                elif block.variable_type == "float":
                    value = float(value_str)
                elif block.variable_type == "boolean":
                    # Accept: true/false, True/False, 1/0, yes/no
                    value_lower = value_str.lower().strip()
                    if value_lower in ("true", "1", "yes"):
                        value = True
                    elif value_lower in ("false", "0", "no"):
                        value = False
                    else:
                        return BlockResult.error_result(
                            f"Cannot convert '{value_str}' to boolean. "
                            f"Use: true/false, 1/0, yes/no"
                        )
                else:  # string (default)
                    value = value_str
            except (ValueError, TypeError) as e:
                return BlockResult.error_result(
                    f"Cannot convert '{value_str}' to {block.variable_type}: {e}"
                )

            # Set the variable with typed value in the execution context
            context.variables[block.variable_name] = value

            # Calculate duration
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            logger.info(
                f"Variable set: {block.variable_name} = {value} "
                f"(type: {block.variable_type}, actual: {type(value).__name__})"
            )

            return BlockResult.success_result(
                output={block.variable_name: value},
                raw_response=f"Variable '{block.variable_name}' set to '{value}' ({block.variable_type})",
                duration_ms=duration_ms
            )

        except Exception as e:
            logger.error(f"Error executing variable block: {e}", exc_info=True)
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            return BlockResult.error_result(
                f"Error setting variable '{block.variable_name}': {str(e)}",
                duration_ms=duration_ms
            )

    async def _execute_bash_block(
        self,
        block: BashBlock,
        context: ExecutionContext
    ) -> BlockResult:
        """
        Execute bash block - runs a bash command asynchronously.

        Args:
            block: The BashBlock to execute
            context: Execution context

        Returns:
            BlockResult with execution results
        """
        import asyncio
        import os
        from src.utils.bash_security import BashSecurityValidator

        start_time = datetime.now()
        logger.debug(f"Executing bash block: {block.command[:50]}...")

        # Store original command for error messages in case substitution fails
        substituted_command = block.command

        try:
            # Substitute variables in the command
            # This allows using command arguments and structured output variables in bash commands
            substituted_command = VariableSubstitution.substitute_all(
                block.command,
                arguments=context.variables,
                variables=context.variables
            )

            logger.info(f"Bash command after substitution: {substituted_command}")

            # Security validation
            is_safe, warnings = BashSecurityValidator.validate_command(substituted_command)

            if warnings:
                # Log all warnings
                for warning in warnings:
                    logger.warning(f"Bash security: {warning}")

            if not is_safe:
                # Command is dangerous - fail execution
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                error_msg = f"Dangerous bash command detected.\nCommand: {substituted_command}\nSecurity warnings:\n" + "\n".join(warnings)
                logger.error(error_msg)
                return BlockResult.error_result(
                    error_msg,
                    duration_ms=duration_ms
                )

            # Determine working directory
            # Default to session's working directory
            working_dir = str(self.agent_service.cwd)

            if block.working_directory:
                # Override with block's working directory if specified
                # Substitute variables in working directory path
                working_dir = VariableSubstitution.substitute_all(
                    block.working_directory,
                    arguments=context.variables,
                    variables=context.variables
                )

                # Validate that directory exists
                if not os.path.isdir(working_dir):
                    duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                    return BlockResult.error_result(
                        f"Working directory does not exist: {working_dir}\nCommand: {substituted_command}",
                        duration_ms=duration_ms
                    )
                logger.debug(f"Using custom working directory: {working_dir}")
            else:
                logger.debug(f"Using session working directory: {working_dir}")

            # Execute the command asynchronously
            logger.info(f"Executing bash command asynchronously: {substituted_command}")

            # Create async subprocess with proper stdout/stderr handling
            # start_new_session=True creates a new process group so we can kill all children
            if block.capture_output:
                process = await asyncio.create_subprocess_shell(
                    substituted_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir,
                    start_new_session=True
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    substituted_command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    cwd=working_dir,
                    start_new_session=True
                )

            # Track this process for cleanup
            self.running_processes.append(process)
            logger.debug(f"Tracking bash process (PID: {process.pid})")

            # Wait for process with timeout (5 minutes)
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=300.0  # 5 minute timeout for safety
                )
            except asyncio.TimeoutError:
                # Kill the process if it times out
                process.kill()
                await process.wait()
                # Remove from tracking
                if process in self.running_processes:
                    self.running_processes.remove(process)
                logger.error("Bash command timed out after 5 minutes")
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000

                # Check continue_on_error flag (consistent with normal error handling)
                if not block.continue_on_error:
                    logger.error("Bash command timed out and continue_on_error=False, returning error")
                    return BlockResult.error_result(
                        f"Bash command timed out after 5 minutes\nCommand: {substituted_command}",
                        duration_ms=duration_ms
                    )
                else:
                    logger.info("Bash command timed out but continue_on_error=True, continuing workflow")
                    # Store timeout exit code in variable if specified
                    output_dict = {}
                    if block.exit_code_variable:
                        timeout_exit_code = -1  # Use -1 to indicate timeout
                        context.variables[block.exit_code_variable] = timeout_exit_code
                        output_dict[block.exit_code_variable] = timeout_exit_code
                        logger.info(f"Stored timeout exit code {timeout_exit_code} in variable: {block.exit_code_variable}")

                    return BlockResult.success_result(
                        output=output_dict if output_dict else None,
                        raw_response=f"Bash command timed out after 5 minutes (continue_on_error enabled)\nCommand: {substituted_command}",
                        duration_ms=duration_ms
                    )
            finally:
                # Remove from tracking list when done
                if process in self.running_processes:
                    self.running_processes.remove(process)
                    logger.debug(f"Removed bash process from tracking (PID: {process.pid})")

            # Calculate duration
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Get exit code
            returncode = process.returncode

            # Prepare output
            output_dict = {}

            # Store exit code in variable if specified
            if block.exit_code_variable:
                context.variables[block.exit_code_variable] = returncode
                output_dict[block.exit_code_variable] = returncode
                logger.info(f"Stored exit code {returncode} in variable: {block.exit_code_variable}")

            # Capture stdout/stderr if enabled
            if block.capture_output:
                stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
                stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""

                # Store output in variable if specified
                if block.output_variable:
                    # Convert output to specified type
                    typed_output = self._convert_bash_output(stdout.strip(), block.output_type)
                    context.variables[block.output_variable] = typed_output
                    output_dict[block.output_variable] = typed_output
                    logger.info(f"Stored bash output ({block.output_type}) in variable: {block.output_variable}")

            # Check exit code and determine if we should fail
            if returncode != 0:
                error_msg = f"Bash command failed with exit code {returncode}\nCommand: {substituted_command}"
                if block.capture_output and stderr_bytes:
                    stderr = stderr_bytes.decode('utf-8', errors='replace')
                    error_msg += f"\nStderr: {stderr}"

                logger.warning(error_msg)

                # Only return error if continue_on_error is False
                if not block.continue_on_error:
                    logger.error("Bash command failed and continue_on_error=False, returning error")
                    return BlockResult.error_result(
                        error_msg,
                        duration_ms=duration_ms
                    )
                else:
                    logger.info("Bash command failed but continue_on_error=True, continuing workflow")
                    # Include the error info in raw_response but return success
                    raw_response = f"Bash command: {substituted_command}\nExit code: {returncode}\n"
                    if block.capture_output:
                        raw_response += f"Output: {stdout if stdout else '(no output)'}\n"
                        if stderr:
                            raw_response += f"Stderr: {stderr}"
                    else:
                        raw_response += "Command executed (continue_on_error enabled)"

                    return BlockResult.success_result(
                        output=output_dict if output_dict else None,
                        raw_response=raw_response,
                        duration_ms=duration_ms
                    )

            # Success case (exit code 0)
            raw_response = f"Bash command: {substituted_command}\nExit code: 0\n"
            if block.capture_output:
                stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
                raw_response += f"Output: {stdout if stdout else '(no output)'}"
            else:
                raw_response += "Command executed successfully"

            logger.info(f"Bash command completed successfully in {duration_ms}ms")

            return BlockResult.success_result(
                output=output_dict if output_dict else None,
                raw_response=raw_response,
                duration_ms=duration_ms
            )

        except Exception as e:
            logger.error(f"Error executing bash block: {e}", exc_info=True)
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            return BlockResult.error_result(
                f"Error executing bash command: {str(e)}\nCommand: {substituted_command}",
                duration_ms=duration_ms
            )

    def _convert_bash_output(self, value: str, target_type: str) -> Any:
        """
        Convert bash output string to the specified type.

        Args:
            value: The string value from bash output
            target_type: Target type (string, int, float, boolean)

        Returns:
            Converted value

        Raises:
            ValueError: If conversion fails
        """
        if target_type == "string":
            return value
        elif target_type == "int":
            return int(value)
        elif target_type == "float":
            return float(value)
        elif target_type == "boolean":
            value_lower = value.lower().strip()
            if value_lower in ("true", "1", "yes", "y"):
                return True
            elif value_lower in ("false", "0", "no", "n", ""):
                return False
            else:
                raise ValueError(
                    f"Cannot convert '{value}' to boolean. Use: true/false, 1/0, yes/no"
                )
        else:
            raise ValueError(f"Unknown target type: {target_type}")

    def _extract_text_from_sdk_message(self, message_str: str) -> str:
        """
        Extract actual text content from SDK message string representation.

        Handles three formats:
        1. Claude AssistantMessage with TextBlock (legacy)
        2. Claude StreamEvent format (new SDK)
        3. Codex plain text chunks

        Args:
            message_str: String representation of SDK message

        Returns:
            Extracted text content, or empty string if not an assistant message
        """

        # 1. Check for Claude StreamEvent format (new SDK)
        if "StreamEvent" in message_str and "event=" in message_str:
            try:
                # Extract text from content_block_delta events using regex
                # This is more robust than ast.literal_eval which fails on escaped newlines
                # Use flexible string matching to handle both escaped and unescaped quotes
                if "content_block_delta" in message_str and "text_delta" in message_str:
                    # Extract the text value using regex
                    # Match various quote combinations to handle Python's repr() escaping
                    import re

                    # Try different patterns (repr() uses different quote combinations)
                    patterns = [
                        r"'text':\s*'((?:[^'\\]|\\.)*)'",      # 'text': '...'
                        r'"text":\s*"((?:[^"\\]|\\.)*)"',      # "text": "..."
                        r"\\'text\\':\s*\"((?:[^\"\\]|\\.)*?)\"",  # \'text\': "..." (escaped key, double value)
                        r"'text':\s*\"((?:[^\"\\]|\\.)*?)\"",  # 'text': "..." (unescaped key, double value)
                    ]

                    text_match = None
                    for pattern in patterns:
                        text_match = re.search(pattern, message_str)
                        if text_match:
                            break

                    if text_match:
                        # Extract the text and unescape it
                        text_content = text_match.group(1)
                        # Unescape common escape sequences
                        text_content = text_content.replace('\\n', '\n')
                        text_content = text_content.replace('\\t', '\t')
                        text_content = text_content.replace('\\r', '\r')
                        text_content = text_content.replace("\\'", "'")
                        text_content = text_content.replace('\\"', '"')
                        text_content = text_content.replace('\\\\', '\\')
                        return text_content
            except Exception as e:
                logger.debug(f"Failed to parse StreamEvent: {e}")

        # 2. Check for Claude AssistantMessage with TextBlock (legacy)
        if "AssistantMessage" in message_str:
            # Extract text from TextBlock - try double quotes first
            start = message_str.find('TextBlock(text="')
            if start != -1:
                start += len('TextBlock(text="')
                end = message_str.find('")', start)
                if end != -1:
                    text_content = message_str[start:end]
                    return text_content.replace('\\n', '\n')

            # Try single quotes (slash commands use single quotes)
            start = message_str.find("TextBlock(text='")
            if start != -1:
                start += len("TextBlock(text='")
                end = message_str.find("')", start)
                if end != -1:
                    text_content = message_str[start:end]
                    return text_content.replace('\\n', '\n')

            return ""

        # 3. Codex plain text chunks - return as-is if not a structured message
        # Codex sends plain text strings (50 char chunks)
        # IMPORTANT: Don't return SDK message representations as text!
        if message_str.strip():
            # Check if this looks like an SDK message representation
            # These should NOT be treated as plain text
            sdk_message_types = [
                'StreamEvent(',
                'AssistantMessage(',
                'UserMessage(',
                'SystemMessage(',
                'ResultMessage(',
                'ToolUseBlock(',
                'ToolResultBlock(',
                'TextBlock('
            ]

            # Only return if it doesn't look like an SDK message
            if not any(msg_type in message_str for msg_type in sdk_message_types):
                return message_str

        return ""

    async def _execute_prompt_block(
        self,
        block: PromptBlock,
        context: ExecutionContext
    ) -> BlockResult:
        """
        Execute prompt block by calling Claude with streaming.

        Args:
            block: The prompt block to execute
            context: Execution context

        Returns:
            BlockResult with Claude's response
        """
        if not block.prompt:
            return BlockResult.error_result("Prompt block has no prompt text")

        logger.debug(f"Executing prompt block with prompt: {block.prompt[:50]}...")

        try:
            start_time = datetime.now()

            # Substitute variables in prompt ($1, $2, {{varname}}, etc.)
            # Uses context.variables which contains both command arguments and structured outputs
            try:
                substituted_prompt = VariableSubstitution.substitute_all(
                    block.prompt,
                    arguments=context.variables,  # Contains $1, $2, etc. from command args
                    variables=context.variables   # Contains {{varname}} from structured outputs
                )
                logger.debug(f"Variable substitution: '{block.prompt[:50]}...' -> '{substituted_prompt[:50]}...'")
            except ValueError as e:
                return BlockResult.error_result(f"Variable substitution error: {str(e)}")

            # Build final prompt with schema instructions if needed
            final_prompt = substituted_prompt
            if block.output_schema:
                import json
                schema_json = json.dumps(block.output_schema, indent=2)
                final_prompt = f"{substituted_prompt}\n\nProvide your final answer in this output JSON schema:\n{schema_json}"

            # Notify callback that we're sending a prompt (if callback exists)
            if self.on_prompt_stream:
                self.on_prompt_stream(final_prompt, "")  # Empty string = start of prompt

            # Ensure agent session is active (handles case where Refresh Block created new service)
            await self.agent_service.ensure_session()

            # Stream response from agent
            full_response = ""
            chunk_count = 0
            text_chunks_captured = 0
            async for chunk in self.agent_service.stream_prompt(final_prompt):
                chunk_str = str(chunk)
                chunk_count += 1

                # Extract actual text content from SDK message
                text_content = self._extract_text_from_sdk_message(chunk_str)
                if text_content:
                    # Check for suspicious content that looks like SDK messages (BUG DETECTION)
                    if any(x in text_content for x in ['StreamEvent(', 'AssistantMessage(', 'ToolUseBlock(', 'ToolResultBlock(']):
                        logger.warning(
                            f"[CHUNK DEBUG] Suspicious text extracted (may be SDK message leak): "
                            f"{repr(text_content[:100])}"
                        )

                    text_chunks_captured += 1
                    # Append text directly - SDK handles text flow correctly
                    full_response += text_content
                    logger.debug(f"[STREAM DEBUG] Chunk {chunk_count}: Captured text ({len(text_content)} chars): {repr(text_content[:50])}")
                else:
                    logger.debug(f"[STREAM DEBUG] Chunk {chunk_count}: No text extracted from: {chunk_str[:100]}")

                # Call streaming callback with raw chunk (callback does its own parsing)
                if self.on_prompt_stream:
                    self.on_prompt_stream(final_prompt, chunk_str)

            logger.debug(f"[STREAM DEBUG] Streaming complete: {chunk_count} total chunks, {text_chunks_captured} text chunks captured")

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.debug(f"Prompt execution complete: {len(full_response)} chars")

            # Parse structured output if schema provided (with automatic retry)
            structured_output = None
            if block.output_schema:
                import json
                schema_json = json.dumps(block.output_schema, indent=2)

                # Try to parse, with automatic retry on failure
                for attempt in range(1, self.MAX_SCHEMA_RETRIES + 1):
                    try:
                        # DEBUG: Log the actual response before parsing
                        logger.debug(f"[PARSE DEBUG] Attempt {attempt}: Response length={len(full_response)}")
                        logger.debug(f"[PARSE DEBUG] Response repr: {repr(full_response[:200])}...{repr(full_response[-200:]) if len(full_response) > 200 else ''}")
                        logger.debug(f"[PARSE DEBUG] Response starts with: {full_response[:50] if full_response else '(empty)'}")
                        logger.debug(f"[PARSE DEBUG] Response ends with: {full_response[-50:] if full_response else '(empty)'}")

                        structured_output = self.agent_service._parse_structured_output(
                            full_response,
                            block.output_schema
                        )
                        # Success! Break out of retry loop
                        if attempt > 1:
                            logger.info(f"Schema parsing succeeded on attempt {attempt}")
                        break
                    except Exception as e:
                        logger.warning(f"Schema parsing failed (attempt {attempt}/{self.MAX_SCHEMA_RETRIES}): {e}")

                        # If this was the last attempt, give up
                        if attempt >= self.MAX_SCHEMA_RETRIES:
                            return BlockResult.error_result(
                                error=f"Failed to parse structured output after {self.MAX_SCHEMA_RETRIES} attempts. Last error: {e}",
                                duration_ms=duration_ms
                            )

                        # Send retry prompt to Claude
                        retry_prompt = f"Your previous response could not be parsed. Please provide your answer in the exact JSON schema format required:\n\n{schema_json}\n\nEnsure your response contains ONLY valid JSON matching this schema."

                        # Notify callback that we're retrying (user will see this in chat)
                        if self.on_prompt_stream:
                            self.on_prompt_stream(retry_prompt, "")  # Start of retry

                        # Get retry response
                        full_response = ""
                        chunk_count = 0
                        text_chunks_captured = 0
                        async for chunk in self.agent_service.stream_prompt(retry_prompt):
                            chunk_str = str(chunk)
                            chunk_count += 1
                            text_content = self._extract_text_from_sdk_message(chunk_str)
                            if text_content:
                                text_chunks_captured += 1
                                # Append text directly - SDK handles text flow correctly
                                full_response += text_content
                                logger.debug(f"[RETRY STREAM DEBUG] Chunk {chunk_count}: Captured text ({len(text_content)} chars): {repr(text_content[:50])}")
                            else:
                                logger.debug(f"[RETRY STREAM DEBUG] Chunk {chunk_count}: No text extracted from: {chunk_str[:100]}")
                            if self.on_prompt_stream:
                                self.on_prompt_stream(retry_prompt, chunk_str)

                        logger.debug(f"[RETRY STREAM DEBUG] Retry streaming complete: {chunk_count} total chunks, {text_chunks_captured} text chunks captured")

                        # Loop will retry parsing with the new response

            return BlockResult.success_result(
                output=structured_output,
                raw_response=full_response,
                duration_ms=duration_ms
            )

        except ClaudeServiceError as e:
            logger.error(f"Claude service error: {e}")
            return BlockResult.error_result(str(e))

    async def _execute_branch_block(
        self,
        block: BranchBlock,
        flowchart: Flowchart,
        context: ExecutionContext
    ) -> BlockResult:
        """
        Execute branch block by evaluating conditions.

        Args:
            block: The branch block to execute
            flowchart: The flowchart containing the block
            context: Execution context

        Returns:
            BlockResult with next_block_id in output
        """
        logger.debug(f"Executing branch block: {block.name}")

        # Get all accumulated variables from context (not just last block's output)
        source_output = context.variables

        if not source_output:
            # If no variables available, use empty dict for condition evaluation
            logger.warning("No variables available for branching, using empty context")
            source_output = {}

        # Track loop iteration count (for debugging/monitoring)
        loop_key = f"branch_{block.id}"
        loop_count = context.increment_loop_counter(loop_key)

        # Get outgoing connections from this branch block
        outgoing_connections = [
            conn for conn in flowchart.connections
            if conn.source_block_id == block.id
        ]

        if not outgoing_connections:
            return BlockResult.error_result(
                f"Branch block '{block.name}' has no outgoing connections. "
                f"Create connections using drag (True path) and Ctrl+drag (False path)."
            )

        # NOW evaluate the branch condition (with iteration variable set)
        condition_result = self._evaluate_condition(block.condition, source_output)

        logger.debug(f"Branch condition '{block.condition}' evaluated to: {condition_result}")

        # Find the connection that matches the condition result
        # True path: is_true_path=True (black arrow)
        # False path: is_true_path=False (blue arrow)
        target_connection = None
        for conn in outgoing_connections:
            if conn.is_true_path == condition_result:
                target_connection = conn
                break

        if target_connection:
            path_type = "True" if condition_result else "False"
            logger.debug(
                f"Branch condition '{block.condition}' -> {path_type} path, "
                f"target: {target_connection.target_block_id} (loop iteration {loop_count})"
            )
            return BlockResult.success_result(
                output={
                    "next_block_id": target_connection.target_block_id,
                    "condition": block.condition,
                    "result": condition_result,
                    "loop_count": loop_count
                },
                raw_response=f"Branch condition '{block.condition}' = {path_type} (iteration {loop_count})",
                duration_ms=0
            )

        # No matching path found
        path_type = "True" if condition_result else "False"
        return BlockResult.error_result(
            f"Branch condition evaluated to {path_type}, but no {path_type} path connection exists. "
            f"Create a {path_type} path using {'normal drag' if condition_result else 'Ctrl+drag'}."
        )

    async def _execute_command_block(
        self,
        block: CommandBlock,
        context: ExecutionContext
    ) -> BlockResult:
        """
        Execute command block by invoking another command.

        Args:
            block: The command block to execute
            context: Execution context

        Returns:
            BlockResult with child command outputs
        """
        if not self.command_block_executor:
            return BlockResult.error_result(
                "Command blocks require storage_service to be provided to ExecutionController"
            )

        logger.debug(f"Executing command block: {block.command_name}")

        try:
            start_time = datetime.now()

            # Execute child command
            child_outputs = await self.command_block_executor.execute_command_block(
                block=block,
                parent_context=context
            )

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            logger.debug(
                f"Command block execution complete: {block.command_name} "
                f"({len(child_outputs)} variables returned)"
            )

            return BlockResult.success_result(
                output=child_outputs,
                raw_response=f"Executed command: {block.command_name}",
                duration_ms=duration_ms
            )

        except CommandBlockExecutorError as e:
            logger.error(f"Command block execution error: {e}")
            return BlockResult.error_result(str(e))

    async def _execute_end_block(
        self,
        block: EndBlock,
        context: ExecutionContext
    ) -> BlockResult:
        """Execute end block (marks completion)."""
        logger.debug("Executing end block")
        return BlockResult.success_result(
            raw_response="Execution completed",
            duration_ms=0
        )

    async def _execute_refresh_block(
        self,
        context: ExecutionContext
    ) -> BlockResult:
        """Execute refresh block by triggering external refresh callback."""
        logger.debug("Executing refresh block")

        if not getattr(self, 'on_refresh_requested', None):
            return BlockResult.error_result("Refresh block not supported in this context")

        try:
            # Check if callback is async and await it if needed
            if inspect.iscoroutinefunction(self.on_refresh_requested):
                await self.on_refresh_requested()
            else:
                self.on_refresh_requested()

            return BlockResult.success_result(
                raw_response="Agent refresh triggered",
                duration_ms=0
            )
        except Exception as exc:
            logger.error(f"Refresh block failed: {exc}", exc_info=True)
            return BlockResult.error_result(str(exc))

    def _evaluate_condition(self, condition: str, data: Dict[str, Any]) -> bool:
        """
        Evaluate a branch condition against data.

        Supports simple conditions like:
        - "field == value"
        - "field > 5"
        - "field < 10"
        - "field >= 5"
        - "field <= 10"
        - "field != value"

        Also supports JSONPath conditions:
        - "$.data.hasErrors == true"
        - "$.result.count > 5"
        - "$.items[0].name == 'tofu'"

        Also supports boolean field lookups (no operator):
        - "specComplete" (returns value of specComplete field)
        - "isValid" (returns value of isValid field)
        - "!specComplete" (returns negation of specComplete field)

        Args:
            condition: Condition string
            data: Data to evaluate against

        Returns:
            True if condition matches, False otherwise
        """
        try:
            # Parse condition
            # Support: field/jsonpath operator value
            # IMPORTANT: Match >= and <= before > and < to avoid partial matches
            match = re.match(r'^(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$', condition.strip())
            if not match:
                # No operator found - treat as simple boolean field lookup
                field_name = condition.strip()

                # Check for negation prefix
                negate = False
                if field_name.startswith('!'):
                    negate = True
                    field_name = field_name[1:].strip()

                # Check if it's a JSONPath expression
                if field_name.startswith('$'):
                    try:
                        jsonpath_expr = jsonpath_parse(field_name)
                        matches = jsonpath_expr.find(data)
                        if not matches:
                            logger.debug(f"JSONPath '{field_name}' found no matches in data")
                            return False
                        field_value = matches[0].value
                        result = bool(field_value)
                        if negate:
                            result = not result
                        logger.debug(f"Boolean field '{'!' if negate else ''}{field_name}' = {result}")
                        return result
                    except Exception as e:
                        logger.warning(f"Error parsing JSONPath '{field_name}': {e}")
                        return False
                else:
                    # Simple field lookup
                    if field_name not in data:
                        logger.debug(f"Boolean field '{field_name}' not found in data")
                        return False
                    field_value = data[field_name]
                    result = bool(field_value)
                    if negate:
                        result = not result
                    logger.debug(f"Boolean field '{'!' if negate else ''}{field_name}' = {result}")
                    return result

            field_expr, operator, value_str = match.groups()
            field_expr = field_expr.strip()

            # Get field value from data
            # Check if it's a JSONPath expression (starts with $)
            if field_expr.startswith('$'):
                # Use JSONPath to extract value
                try:
                    jsonpath_expr = jsonpath_parse(field_expr)
                    matches = jsonpath_expr.find(data)
                    if not matches:
                        logger.debug(f"JSONPath '{field_expr}' found no matches in data")
                        return False
                    # Use the first match
                    field_value = matches[0].value
                    logger.debug(f"JSONPath '{field_expr}' extracted value: {field_value}")
                except Exception as e:
                    logger.warning(f"Error parsing JSONPath '{field_expr}': {e}")
                    return False
            else:
                # Simple field lookup (backward compatibility)
                if field_expr not in data:
                    logger.debug(f"Field '{field_expr}' not in data")
                    return False
                field_value = data[field_expr]

            # Parse expected value
            expected_value = self._parse_value(value_str.strip())

            # Compare based on operator with type mismatch detection
            try:
                if operator == "==":
                    result = field_value == expected_value
                elif operator == "!=":
                    result = field_value != expected_value
                elif operator == ">":
                    result = field_value > expected_value
                elif operator == "<":
                    result = field_value < expected_value
                elif operator == ">=":
                    result = field_value >= expected_value
                elif operator == "<=":
                    result = field_value <= expected_value
                else:
                    logger.warning(f"Unknown operator: {operator}")
                    return False

                logger.debug(f"Condition '{condition}' evaluated to {result} ({field_value} {operator} {expected_value})")
                return result

            except TypeError as type_err:
                # Type mismatch in comparison
                field_type = type(field_value).__name__
                expected_type = type(expected_value).__name__
                error_msg = (
                    f"Type mismatch in condition '{condition}': "
                    f"Cannot compare {field_type} ({repr(field_value)}) with {expected_type} ({repr(expected_value)}). "
                    f"Use a VariableBlock to convert '{field_expr}' to {expected_type} before this branch, "
                    f"or change the comparison value to match the {field_type} type."
                )
                logger.error(error_msg)
                raise ValueError(error_msg) from type_err

        except Exception as e:
            logger.error(f"Error evaluating condition '{condition}': {e}")
            return False

    def _parse_value(self, value_str: str) -> Any:
        """
        Parse a value string to its appropriate type.

        Handles:
        - Booleans: true/false
        - Numbers: integers and floats
        - Strings: quoted strings only
        - Unquoted non-keyword identifiers: ERROR (suggest quoting)

        Args:
            value_str: String representation of value

        Returns:
            Parsed value

        Raises:
            ValueError: If unquoted non-keyword identifier is used
        """
        value_str = value_str.strip()

        # Boolean keywords
        if value_str.lower() == "true":
            return True
        if value_str.lower() == "false":
            return False

        # Number (integer or float)
        try:
            if "." in value_str:
                return float(value_str)
            else:
                return int(value_str)
        except ValueError:
            pass

        # Quoted string (remove quotes)
        if (value_str.startswith('"') and value_str.endswith('"')) or \
           (value_str.startswith("'") and value_str.endswith("'")):
            return value_str[1:-1]

        # Unquoted non-keyword identifier - ERROR
        # This catches cases like: status == success (should be status == "success")
        raise ValueError(
            f"No variable named '{value_str}', did you mean \"{value_str}\" as a string? "
            f"Literals in conditions must be quoted (strings), boolean keywords (true/false), or numbers."
        )

    def _get_block_by_id(self, flowchart: Flowchart, block_id: str) -> Optional[Block]:
        """Get a block from the flowchart by ID."""
        return flowchart.blocks.get(block_id)

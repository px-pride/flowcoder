"""
Agents Tab - Multi-session Claude Code execution interface.

This tab contains:
- Sessions list (left) - showing all sessions
- Session sub-tabs (right) - showing selected session's content
  - Chat panel
  - Execution history
  - Execution flowchart view
- Control buttons at top (New Session, Halt, Terminate)

Phase 3.2 implementation - multi-session support with session sub-tabs.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
import threading
import asyncio
from typing import Dict, Optional, List, Callable

from ..services.session_manager import SessionManager
from ..models import Session, SessionState, ExecutionStatus
from ..widgets import SessionsListWidget, SessionTabWidget, NewSessionDialog


logger = logging.getLogger(__name__)


class AgentsTab(ttk.Frame):
    """
    Agents tab for multi-session execution and management.

    Phase 3.2: Multi-session execution with session sub-tabs
    """

    def __init__(self, parent, main_window, session_manager=None):
        """
        Initialize the Agents tab.

        Args:
            parent: Parent widget (notebook)
            main_window: Reference to MainWindow instance
            session_manager: Shared SessionManager instance (optional, creates new if None)
        """
        super().__init__(parent)
        self.main_window = main_window
        self.session_manager = session_manager if session_manager else SessionManager()

        # Map session name -> SessionTabWidget
        self.session_widgets: Dict[str, SessionTabWidget] = {}

        # Currently displayed session widget
        self.current_session_widget: Optional[SessionTabWidget] = None

        # Track async tasks for cleanup
        self._async_tasks: List[asyncio.Task] = []

        # Track callback unregister function for cleanup
        self._unregister_session_callback: Optional[Callable] = None

        # Create the UI
        self._create_ui()

        # Load existing sessions
        self._load_existing_sessions()

        # Register callback to refresh when sessions change (store unregister function)
        self._unregister_session_callback = self.session_manager.add_session_change_callback(
            self._on_sessions_changed
        )

        logger.debug("AgentsTab initialized with multi-session support")

    def _on_sessions_changed(self):
        """Called when sessions are created or closed in any tab."""
        logger.debug("Sessions changed notification received in AgentsTab")
        # Refresh the sessions list
        self.sessions_list.refresh()

    def _track_task(self, coro) -> asyncio.Task:
        """
        Create and track an async task for proper cleanup.

        Args:
            coro: Coroutine to run as a task

        Returns:
            The created task
        """
        task = asyncio.ensure_future(coro)
        self._async_tasks.append(task)

        # Remove from list when done
        def on_done(t):
            if t in self._async_tasks:
                self._async_tasks.remove(t)

        task.add_done_callback(on_done)
        return task

    async def cleanup(self):
        """
        Clean up resources when tab is destroyed.

        Cancels all pending async tasks and unregisters callbacks.
        """
        logger.debug("AgentsTab cleanup started")

        # Unregister session change callback
        if self._unregister_session_callback:
            self._unregister_session_callback()
            self._unregister_session_callback = None
            logger.debug("Unregistered session change callback")

        # Cancel all pending tasks
        for task in self._async_tasks[:]:  # Copy list to avoid modification during iteration
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._async_tasks.clear()
        logger.debug("Cancelled all pending async tasks")

    def destroy(self):
        """Override destroy to ensure cleanup."""
        # Schedule cleanup in event loop if running
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.cleanup())
            else:
                loop.run_until_complete(self.cleanup())
        except RuntimeError:
            # No event loop, just do sync cleanup
            if self._unregister_session_callback:
                self._unregister_session_callback()
                self._unregister_session_callback = None

        super().destroy()

    def _create_ui(self):
        """Create the Agents tab layout."""
        # Control buttons at top
        self._create_control_buttons()

        # Create 2-pane layout
        content_frame = ttk.Frame(self)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Left: Sessions list (fixed width)
        self.sessions_list = SessionsListWidget(
            content_frame,
            on_session_selected=self.on_session_selected
        )
        self.sessions_list.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 0), pady=5)
        self.sessions_list.config(width=300)  # Fixed width for sessions list

        # Right: Container for current session widget (no sub-tabs)
        self.session_container = ttk.Frame(content_frame)
        self.session_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        logger.debug("AgentsTab layout created (no sub-tabs)")

    def _create_control_buttons(self):
        """Create control buttons at top."""
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        # New Session button
        ttk.Button(
            btn_frame,
            text="➕ New Session",
            command=self.on_new_session
        ).pack(side=tk.LEFT, padx=2)

        # Start Session button
        self.start_btn = ttk.Button(
            btn_frame,
            text="▶ Start Session",
            command=self._on_start_session,
            state=tk.DISABLED
        )
        self.start_btn.pack(side=tk.LEFT, padx=2)

        # Halt button
        self.halt_btn = ttk.Button(
            btn_frame,
            text="⏸ Halt",
            command=self._on_halt,
            state=tk.DISABLED
        )
        self.halt_btn.pack(side=tk.LEFT, padx=2)

        # Resume button
        self.resume_btn = ttk.Button(
            btn_frame,
            text="▶ Resume",
            command=self._on_resume,
            state=tk.DISABLED
        )
        self.resume_btn.pack(side=tk.LEFT, padx=2)

        # Stop button (waits for current block to finish)
        self.stop_btn = ttk.Button(
            btn_frame,
            text="⏹ Stop",
            command=self._on_stop,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        # Force Stop button (immediate)
        self.force_stop_btn = ttk.Button(
            btn_frame,
            text="⏹ Force Stop",
            command=self._on_force_stop,
            state=tk.DISABLED
        )
        self.force_stop_btn.pack(side=tk.LEFT, padx=2)

        # Refresh button (stop then start agent)
        self.refresh_btn = ttk.Button(
            btn_frame,
            text="🔄 Refresh",
            command=self._on_refresh,
            state=tk.DISABLED
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=2)

        # Status label
        self.status_label = ttk.Label(btn_frame, text="")
        self.status_label.pack(side=tk.LEFT, padx=10)

        logger.debug("Control buttons created")

    def _load_existing_sessions(self):
        """Load existing sessions from SessionManager."""
        sessions = self.session_manager.list_sessions()
        logger.info(f"Loading {len(sessions)} existing sessions")

        for session in sessions:
            self._create_session_widget(session)

        # Select first session if any exist
        if sessions:
            first_session = sessions[0]
            self.sessions_list._select_session_by_name(first_session.name)
            logger.debug(f"Selected first session: {first_session.name}")

    def _create_session_widget(self, session: Session):
        """
        Create SessionTabWidget for session (not added to UI yet).

        Args:
            session: Session to create widget for
        """
        # Create widget with close callback and storage service
        widget = SessionTabWidget(
            self.session_container,
            session,
            storage_service=self.main_window.storage_service,
            on_close_callback=self._on_session_close,
            session_manager=self.session_manager
        )

        # Store in map (but don't pack yet)
        self.session_widgets[session.name] = widget

        logger.debug(f"Created widget for session: {session.name}")

    def on_session_selected(self, session_name: str):
        """
        Called when user selects session in list.

        Args:
            session_name: Name of selected session
        """
        # Hide current widget if any
        if self.current_session_widget:
            self.current_session_widget.pack_forget()

        # Show selected session's widget
        if session_name in self.session_widgets:
            widget = self.session_widgets[session_name]
            widget.pack(fill=tk.BOTH, expand=True)
            self.current_session_widget = widget
            logger.debug(f"Switched to session: {session_name}")
        else:
            logger.warning(f"No widget found for session: {session_name}")
            self.current_session_widget = None

        # Update control buttons state
        self._update_control_buttons()

    def on_new_session(self):
        """Handle New Session button - show dialog to create new session."""
        logger.info("New Session button clicked")

        # Check if multiple sessions are disabled
        existing_count = len(self.session_manager.list_sessions())
        if existing_count >= self.session_manager.MAX_CONCURRENT_SESSIONS:
            messagebox.showinfo(
                "Multiple Sessions Disabled",
                "Multiple sessions are currently disabled. This feature is still in development.\n\n"
                "Please close the existing session before creating a new one."
            )
            logger.info("Session creation blocked - multiple sessions disabled")
            return

        try:
            # Show dialog and get result
            new_session = NewSessionDialog.show(self, self.session_manager)

            if new_session:
                # Session was created - add to UI
                logger.info(f"New session created: {new_session.name}")

                # Refresh sessions list
                self.sessions_list.refresh()

                # Create widget for new session
                self._create_session_widget(new_session)

                # Select the new session (will display it)
                self.sessions_list._select_session_by_name(new_session.name)
            else:
                logger.info("New session dialog cancelled")
        except Exception as e:
            logger.error(f"Error showing new session dialog: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to create new session: {e}")

    def _get_current_session(self) -> Optional[Session]:
        """
        Get the currently selected session.

        Returns:
            Currently selected session, or None if no session selected
        """
        if self.current_session_widget:
            return self.current_session_widget.session
        return None

    def _update_control_buttons(self):
        """Update control button states based on current session."""
        session = self._get_current_session()

        if not session:
            self.start_btn.config(state=tk.DISABLED)
            self.halt_btn.config(state=tk.DISABLED)
            self.resume_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.DISABLED)
            self.force_stop_btn.config(state=tk.DISABLED)
            self.refresh_btn.config(state=tk.DISABLED)
            self.status_label.config(text="")
            return

        # Check if agent session is active
        is_session_active = hasattr(session, 'agent_service') and \
                           session.agent_service and \
                           session.agent_service._session_active

        # Update Start Session button
        if is_session_active:
            self.start_btn.config(state=tk.DISABLED, text="✓ Connected")
        else:
            self.start_btn.config(state=tk.NORMAL, text="▶ Start Session")

        # Enable/disable based on session state
        if session.state == SessionState.EXECUTING:
            self.halt_btn.config(state=tk.NORMAL)
            self.resume_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.force_stop_btn.config(state=tk.NORMAL)
            self.refresh_btn.config(state=tk.NORMAL)
            self.status_label.config(text="🔵 Executing")
        elif session.state == SessionState.HALTED:
            self.halt_btn.config(state=tk.DISABLED)
            self.resume_btn.config(state=tk.NORMAL)  # Enable Resume when halted
            self.stop_btn.config(state=tk.NORMAL)
            self.force_stop_btn.config(state=tk.NORMAL)
            self.refresh_btn.config(state=tk.NORMAL)
            self.status_label.config(text="🟡 Halted")
        elif session.state == SessionState.ERROR:
            self.halt_btn.config(state=tk.DISABLED)
            self.resume_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.force_stop_btn.config(state=tk.NORMAL)
            self.refresh_btn.config(state=tk.NORMAL)
            self.status_label.config(text="🔴 Error")
        else:  # IDLE
            self.halt_btn.config(state=tk.DISABLED)
            self.resume_btn.config(state=tk.DISABLED)
            # Stop/Force Stop/Refresh only enabled if agent is running
            if is_session_active:
                self.stop_btn.config(state=tk.NORMAL)
                self.force_stop_btn.config(state=tk.NORMAL)
                self.refresh_btn.config(state=tk.NORMAL)
                self.status_label.config(text="🟢 Ready")
            else:
                self.stop_btn.config(state=tk.DISABLED)
                self.force_stop_btn.config(state=tk.DISABLED)
                self.refresh_btn.config(state=tk.DISABLED)
                self.status_label.config(text="⚪ Not Connected")

    def _on_start_session(self):
        """Handle Start Session button click."""
        session = self._get_current_session()
        if not session:
            logger.warning("Start session requested but no session selected")
            return

        # Check if already active
        if session.agent_service and session.agent_service._session_active:
            logger.debug("Session already active")
            return

        # Update UI to show starting
        self.start_btn.config(state=tk.DISABLED, text="⏳ Starting...")
        self.status_label.config(text="⏳ Starting session...")

        logger.info(f"Starting Claude session for: {session.name}")

        # Start session asynchronously
        async def start_session_async():
            try:
                await session.agent_service.ensure_session()
                logger.info(f"Session started successfully: {session.name}")

                # Update UI on success
                self.start_btn.config(state=tk.DISABLED, text="✓ Connected")
                self.status_label.config(text="🟢 Ready")

                messagebox.showinfo(
                    "Session Started",
                    f"Claude session for '{session.name}' is now active.",
                    parent=self
                )

            except Exception as e:
                logger.error(f"Failed to start session: {e}", exc_info=True)

                # Update UI on error
                self.start_btn.config(state=tk.NORMAL, text="▶ Start Session")
                self.status_label.config(text="🔴 Failed to start")

                messagebox.showerror(
                    "Session Start Failed",
                    f"Failed to start Claude session:\n\n{str(e)}",
                    parent=self
                )

            finally:
                # Refresh button states
                self._update_control_buttons()

        # Schedule async task (tracked for cleanup)
        self._track_task(start_session_async())

    def _on_halt(self):
        """Handle Halt button click."""
        session = self._get_current_session()
        if not session or session.state != SessionState.EXECUTING:
            logger.warning("Halt requested but no executing session")
            return

        # Check if execution controller exists
        if not session.execution_controller:
            logger.error("No execution controller for session")
            messagebox.showerror(
                "Cannot Halt",
                "Session does not have an active execution controller.",
                parent=self
            )
            return

        # Update status
        self.status_label.config(text="⏳ Waiting for current block...")
        self.halt_btn.config(state=tk.DISABLED)

        logger.info(f"Halt requested for session: {session.name}")

        # Request halt (sets flag)
        session.execution_controller.halt()

        # Schedule async task to wait for halt completion (tracked for cleanup)
        self._track_task(self._wait_for_halt_completion(session))

    async def _wait_for_halt_completion(self, session):
        """
        Wait for execution to actually halt, then update UI.

        Polls session state until execution stops (no timeout - waits forever).
        """
        logger.info(f"Waiting for halt completion: {session.name}")

        try:
            # Poll until execution stops (check every 500ms)
            while session.state == SessionState.EXECUTING:
                await asyncio.sleep(0.5)

            # Execution has stopped - update UI on main thread
            logger.info(f"Halt completed for session: {session.name}")
            self.after(0, self._on_halt_completed, session)

        except Exception as e:
            logger.error(f"Error waiting for halt: {e}", exc_info=True)
            self.after(0, self._on_halt_error, session, str(e))

    def _on_halt_completed(self, session):
        """Handle halt completion on main thread (called after block finishes)."""
        # Store halted state for resume
        if session.execution_controller and session.execution_controller.current_context:
            session.halted_context = session.execution_controller.current_context
            session.halted_command = getattr(session.execution_controller.current_context, 'command', None)
            session.halted_flowchart = session.current_flowchart
            logger.debug(f"Stored halted state for session: {session.name}")

        # Update session state
        session.halt_execution()

        # Update UI
        self._update_control_buttons()
        self.status_label.config(text="🟡 Halted")

        # Show success message
        messagebox.showinfo(
            "Execution Halted",
            f"Session '{session.name}' has been halted.\n"
            "Execution stopped after current block completed.\n\n"
            "Click Resume to continue from where you left off.",
            parent=self
        )

        logger.info(f"Session {session.name} halted successfully")

    def _on_halt_error(self, session, error_msg):
        """Handle halt error on main thread."""
        logger.error(f"Halt error for session {session.name}: {error_msg}")

        # Update UI
        self.status_label.config(text="🔴 Halt error")
        self._update_control_buttons()

        messagebox.showerror(
            "Halt Error",
            f"Error during halt:\n\n{error_msg}",
            parent=self
        )

    def _on_resume(self):
        """Handle Resume button click."""
        session = self._get_current_session()
        if not session or session.state != SessionState.HALTED:
            logger.warning("Resume requested but session not halted")
            return

        # Check if we have halted state
        if not session.halted_context or not session.halted_command:
            logger.error("No halted execution to resume")
            messagebox.showerror(
                "Cannot Resume",
                "No halted execution found for this session.",
                parent=self
            )
            return

        # Update UI
        self.status_label.config(text="▶ Resuming...")
        self.resume_btn.config(state=tk.DISABLED)

        logger.info(f"Resuming execution for session: {session.name}")

        # Schedule async resume (tracked for cleanup)
        self._track_task(self._resume_execution_async(session))

    async def _resume_execution_async(self, session):
        """Resume execution from halted state."""
        try:
            # Get stored state
            context = session.halted_context
            command = session.halted_command
            flowchart = session.halted_flowchart

            logger.debug(f"Resuming from block: {context.current_block_id}")

            # Clear halt flag in context
            context.halt_requested = False
            context.status = ExecutionStatus.RUNNING

            # Update session state
            session.start_execution(command.name)

            # Update UI
            self.after(0, self._update_control_buttons)
            self.after(0, lambda: self.status_label.config(text="🔵 Executing"))

            # Ensure Claude service is active
            await session.agent_service.ensure_session()

            # Resume execution with stored context
            result_context = await session.execution_controller.resume(
                command=command,
                context=context,
                flowchart=flowchart
            )

            # Execution completed
            logger.info(f"Resume completed for session: {session.name}")

            # Clear halted state
            session.clear_halted_state()

            # Update UI
            self.after(0, self._update_control_buttons)
            self.after(0, lambda: self.status_label.config(text="🟢 Ready"))

        except Exception as e:
            logger.error(f"Error resuming execution: {e}", exc_info=True)

            # Update session state to error
            session.state = SessionState.ERROR

            # Update UI
            self.after(0, lambda: messagebox.showerror(
                "Resume Error",
                f"Failed to resume execution:\n\n{str(e)}",
                parent=self
            ))
            self.after(0, self._update_control_buttons)
            self.after(0, lambda: self.status_label.config(text="🔴 Error"))

    def _on_stop(self):
        """Handle Stop button click (waits for current block to finish)."""
        session = self._get_current_session()
        if not session:
            logger.warning("Stop requested but no session selected")
            return

        # Update status
        if session.state == SessionState.EXECUTING:
            self.status_label.config(text="⏳ Waiting for current block...")
            self.stop_btn.config(state=tk.DISABLED)
            self.force_stop_btn.config(state=tk.DISABLED)

            logger.info(f"Stop requested for session: {session.name}")

            # Request halt (sets flag)
            session.execution_controller.halt()

            # Schedule async task to wait for halt completion, then stop (tracked for cleanup)
            self._track_task(self._wait_for_stop_completion(session))
        else:
            # Not executing - stop immediately
            self.status_label.config(text="⏳ Stopping...")
            self.stop_btn.config(state=tk.DISABLED)
            self.force_stop_btn.config(state=tk.DISABLED)
            self._track_task(self._stop_agent(session))

    async def _wait_for_stop_completion(self, session):
        """
        Wait for execution to halt, then stop the agent.

        Polls session state until execution stops (no timeout - waits forever).
        """
        logger.info(f"Waiting for stop completion: {session.name}")

        try:
            # Poll until execution stops (check every 500ms)
            while session.state == SessionState.EXECUTING:
                await asyncio.sleep(0.5)

            # Execution has stopped - now stop the agent
            logger.info(f"Block completed, stopping agent for session: {session.name}")
            await self._stop_agent(session)

        except Exception as e:
            logger.error(f"Error waiting for stop: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror(
                "Stop Error",
                f"Error during stop:\n\n{str(e)}",
                parent=self
            ))
            self.after(0, self._update_control_buttons)

    async def _stop_agent(self, session):
        """
        Stop the agent process but keep the session.

        Args:
            session: Session to stop
        """
        try:
            session_name = session.name

            # Clean up running bash processes FIRST
            if session.execution_controller:
                logger.debug(f"Cleaning up bash processes for: {session_name}")
                await session.execution_controller.cleanup_processes()

            # Then end the agent session
            if session.agent_service:
                logger.debug(f"Ending agent session for: {session_name}")
                await session.agent_service.end_session()

            # Update session state to IDLE
            session.state = SessionState.IDLE

            # Clear halted state if any
            session.clear_halted_state()

            # Update UI on main thread
            self.after(0, self._update_control_buttons)
            self.after(0, lambda: self.status_label.config(text="⚪ Not Connected"))

            # Show success message
            self.after(0, lambda: messagebox.showinfo(
                "Agent Stopped",
                f"Agent for session '{session_name}' has been stopped.\n\n"
                "The session remains in the list.\n"
                "Click 'Start Session' to restart the agent.",
                parent=self
            ))

            logger.info(f"Agent stopped successfully for session: {session_name}")

        except Exception as e:
            logger.error(f"Error stopping agent for {session.name}: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror(
                "Stop Error",
                f"Failed to stop agent:\n\n{str(e)}",
                parent=self
            ))
            self.after(0, self._update_control_buttons)

    def _on_force_stop(self):
        """Handle Force Stop button click (immediate, doesn't wait)."""
        session = self._get_current_session()
        if not session:
            logger.warning("Force Stop requested but no session selected")
            return

        # Show confirmation for executing sessions
        if session.state == SessionState.EXECUTING:
            result = messagebox.askyesno(
                "⚠️ Force Stop Agent?",
                f"Session '{session.name}' is currently executing.\n\n"
                "Force Stop will:\n"
                "• Immediately stop the agent (doesn't wait for current block)\n"
                "• The session will remain in the list\n\n"
                "⚠️ The current block execution may be interrupted.\n\n"
                "Are you sure you want to force-stop the agent?",
                icon="warning",
                parent=self
            )

            if not result:
                logger.debug(f"User cancelled force stop of session: {session.name}")
                return

        # Update status
        self.status_label.config(text="⏳ Force stopping...")
        self.stop_btn.config(state=tk.DISABLED)
        self.force_stop_btn.config(state=tk.DISABLED)

        logger.info(f"Force stop requested for session: {session.name}")

        # Stop immediately (tracked for cleanup)
        self._track_task(self._stop_agent(session))

    def _on_refresh(self):
        """Handle Refresh button click (stop then start agent)."""
        session = self._get_current_session()
        if not session:
            logger.warning("Refresh requested but no session selected")
            return

        # Update status
        if session.state == SessionState.EXECUTING:
            self.status_label.config(text="⏳ Refreshing (waiting for block)...")
            self.refresh_btn.config(state=tk.DISABLED)

            logger.info(f"Refresh requested for session: {session.name} (executing)")

            # Request halt (sets flag)
            session.execution_controller.halt()

            # Schedule async task to wait for halt completion, then refresh (tracked for cleanup)
            self._track_task(self._wait_for_refresh_completion(session))
        else:
            # Not executing - refresh immediately
            self.status_label.config(text="⏳ Refreshing...")
            self.refresh_btn.config(state=tk.DISABLED)

            logger.info(f"Refresh requested for session: {session.name}")
            self._track_task(self._refresh_agent(session))

    async def _wait_for_refresh_completion(self, session):
        """
        Wait for execution to halt, then refresh the agent.

        Polls session state until execution stops (no timeout - waits forever).
        """
        logger.info(f"Waiting for refresh completion: {session.name}")

        try:
            # Poll until execution stops (check every 500ms)
            while session.state == SessionState.EXECUTING:
                await asyncio.sleep(0.5)

            # Execution has stopped - now refresh the agent
            logger.info(f"Block completed, refreshing agent for session: {session.name}")
            await self._refresh_agent(session)

        except Exception as e:
            logger.error(f"Error waiting for refresh: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror(
                "Refresh Error",
                f"Error during refresh:\n\n{str(e)}",
                parent=self
            ))
            self.after(0, self._update_control_buttons)

    async def _refresh_agent(self, session):
        """
        Refresh the agent (stop then start).

        Args:
            session: Session to refresh
        """
        try:
            session_name = session.name

            # Stop the agent first
            if session.agent_service and session.agent_service._session_active:
                logger.debug(f"Stopping agent for refresh: {session_name}")
                await session.agent_service.end_session()

            # Update session state to IDLE
            session.state = SessionState.IDLE

            # Clear halted state if any
            session.clear_halted_state()

            # Small delay before restart
            await asyncio.sleep(0.5)

            # Start the agent again
            logger.debug(f"Starting agent after refresh: {session_name}")
            self.after(0, lambda: self.status_label.config(text="⏳ Starting..."))

            await session.agent_service.ensure_session()

            # Update UI on main thread
            self.after(0, self._update_control_buttons)
            self.after(0, lambda: self.status_label.config(text="🟢 Ready"))

            # Show success message
            self.after(0, lambda: messagebox.showinfo(
                "Agent Refreshed",
                f"Agent for session '{session_name}' has been refreshed.\n\n"
                "The agent has been restarted with a clean state.",
                parent=self
            ))

            logger.info(f"Agent refreshed successfully for session: {session_name}")

        except Exception as e:
            logger.error(f"Error refreshing agent for {session.name}: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror(
                "Refresh Error",
                f"Failed to refresh agent:\n\n{str(e)}",
                parent=self
            ))
            self.after(0, self._update_control_buttons)

    def _terminate_session(self, session: Session):
        """
        Terminate a session.

        Args:
            session: Session to terminate
        """
        session_name = session.name

        # Update status
        self.status_label.config(text="⏳ Terminating...")

        def terminate():
            """Run termination in background thread."""
            try:
                # Halt if executing
                if session.state == SessionState.EXECUTING and session.execution_controller:
                    logger.debug(f"Halting execution for session: {session_name}")
                    session.execution_controller.halt()
                    session.halt_execution()

                # Close session via SessionManager (handles Claude SDK cleanup)
                logger.debug(f"Closing session via SessionManager: {session_name}")
                self.session_manager.close_session(session_name)

                # Update UI on main thread
                self.after(0, self._remove_session_widget, session_name)
                self.after(0, self.sessions_list.refresh)
                self.after(0, self._update_control_buttons)

                logger.info(f"Session {session_name} terminated successfully")

            except Exception as e:
                logger.error(f"Error terminating session {session_name}: {e}")
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "Termination Error",
                        f"Failed to terminate session: {e}",
                        parent=self
                    )
                )
                self.after(0, self._update_control_buttons)

        # Run in background thread
        thread = threading.Thread(target=terminate, daemon=True)
        thread.start()

    def _remove_session_widget(self, session_name: str):
        """
        Remove session widget from UI.

        Args:
            session_name: Name of session to remove
        """
        # If this is the current widget, hide it
        if self.current_session_widget and self.current_session_widget.session.name == session_name:
            self.current_session_widget.pack_forget()
            self.current_session_widget = None
            logger.debug(f"Hid current widget for session: {session_name}")

        # Remove from session_widgets map and destroy widget
        if session_name in self.session_widgets:
            widget = self.session_widgets[session_name]
            widget.destroy()
            del self.session_widgets[session_name]
            logger.debug(f"Removed and destroyed widget for session: {session_name}")

    def _on_session_close(self, session: Session):
        """
        Handle session close button click.

        Shows appropriate confirmation dialog based on session state,
        then terminates the session if confirmed.

        Args:
            session: Session being closed
        """
        logger.info(f"Close button clicked for session: {session.name}")

        # Show appropriate confirmation dialog based on session state
        if session.state == SessionState.EXECUTING:
            # Danger warning for executing sessions
            result = messagebox.askyesno(
                "⚠️ Close Executing Session?",
                f"Session '{session.name}' is currently executing.\n\n"
                "⚠️ WARNING: Execution in progress!\n\n"
                "Closing this session will:\n"
                "• Interrupt the current command execution\n"
                "• Lose any work in progress\n"
                "• Close the Claude Code session\n\n"
                "Are you sure you want to force-close this session?",
                icon="warning",
                parent=self
            )
        elif session.state == SessionState.HALTED:
            # Warning for halted sessions
            result = messagebox.askyesno(
                "Close Halted Session?",
                f"Session '{session.name}' is halted.\n\n"
                "Closing will permanently end this session.\n"
                "Any halted execution will be lost.\n\n"
                "Are you sure you want to close this session?",
                parent=self
            )
        else:
            # Basic confirmation for idle/error sessions
            result = messagebox.askyesno(
                "Close Session?",
                f"Are you sure you want to close session '{session.name}'?",
                parent=self
            )

        if not result:
            logger.debug(f"User cancelled close for session: {session.name}")
            return

        # User confirmed - terminate the session
        logger.info(f"User confirmed close for session: {session.name}")
        self._terminate_session(session)

    # Legacy methods for backward compatibility
    def on_halt(self):
        """Handle Halt button (legacy - calls new implementation)."""
        self._on_halt()

    def on_terminate(self):
        """Handle Terminate button (legacy - calls new implementation)."""
        self._on_terminate()

    # Legacy methods for backward compatibility with Phase 1.3
    # These will be removed in later phases

    def get_chat_panel(self):
        """Get the chat panel (legacy - returns first session's chat)."""
        if self.session_widgets:
            first_widget = next(iter(self.session_widgets.values()))
            return first_widget.chat_panel  # Return actual ChatPanel, not SessionTabWidget
        return None

    def get_history_panel(self):
        """Get the execution history panel (legacy)."""
        if self.session_widgets:
            first_widget = next(iter(self.session_widgets.values()))
            return first_widget.execution_history_panel  # Return actual ExecutionHistoryPanel
        return None

    def get_execution_view(self):
        """Get the execution flowchart view (legacy)."""
        if self.session_widgets:
            first_widget = next(iter(self.session_widgets.values()))
            return first_widget.execution_flowchart
        return None

    def get_run_btn(self):
        """Get the run button (legacy - not available in Phase 3.2)."""
        return None

    def get_halt_btn(self):
        """Get the halt button (legacy - returns new halt button)."""
        return None

"""Smoke test: the real application window launches, renders, and does not crash.

This is the only test in the repo that constructs a Tk window. Every other test
exercises adapters, controllers and models in isolation, so the whole suite can
pass while `python -m src.main` fails outright — an import error in a view, a
constructor that raises, a tab that never builds. This closes that gap.

The window is built in a **subprocess** (tests/_gui_launch_child.py) rather than
in-process. That is not incidental:

- `MainWindow` schedules `_show_failed_loads_dialog` via `after()`, which calls
  `messagebox.showwarning` and blocks until a human clicks OK. One saved session
  that fails to load is enough to trigger it.
- An in-process `SIGALRM` watchdog does **not** rescue that case. The block
  happens inside Tcl's C event loop, and CPython defers signal handlers until
  control returns to the bytecode interpreter, so the alarm never fires. This
  was verified by writing that version first and watching it hang anyway.

Killing a child process is the only reliable escape, so a hang becomes a normal
red test instead of a stalled run.

There is deliberately no skip guard. A skipped test produces zero evidence, so
this fails with an actionable message when no display is reachable. On headless
machines it starts Xvfb itself; install `xvfb` and it runs.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHILD = REPO_ROOT / "tests" / "_gui_launch_child.py"
REPORT_PREFIX = "GUI_REPORT:"
LAUNCH_TIMEOUT = 120


# -- Display --


def _spawn_xvfb():
    """Start an Xvfb server on a free display. Returns (proc, display) or None."""
    if not shutil.which("Xvfb"):
        return None
    for n in range(99, 110):
        name = f":{n}"
        proc = subprocess.Popen(
            ["Xvfb", name, "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(20):
            time.sleep(0.1)
            if proc.poll() is not None:
                break
        else:
            return proc, name
        proc.wait(timeout=5)
    return None


@pytest.fixture(scope="module")
def display():
    """Yield a usable X display, starting Xvfb if the environment has none."""
    if os.environ.get("DISPLAY"):
        yield os.environ["DISPLAY"]
        return

    spawned = _spawn_xvfb()
    if spawned is None:
        pytest.fail(
            "No X display available and Xvfb could not be started, so the GUI "
            "cannot be launched. This is a real gap in coverage, not a reason "
            "to skip: install xvfb (or run with DISPLAY set) so this test can "
            "actually execute."
        )
    proc, name = spawned
    os.environ["DISPLAY"] = name
    try:
        yield name
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        os.environ.pop("DISPLAY", None)


def launch(display_name, *, stub_dialogs=True, force_modal=False,
           timeout=LAUNCH_TIMEOUT):
    """Run the child, return (report_or_None, completed_process_or_None).

    A return of (None, None) means the child had to be killed — it hung.
    """
    env = dict(os.environ)
    env["DISPLAY"] = display_name
    env["GUI_LAUNCH_STUB_DIALOGS"] = "1" if stub_dialogs else "0"
    env["GUI_LAUNCH_FORCE_MODAL"] = "1" if force_modal else "0"
    env["PYTHONWARNINGS"] = "ignore"

    try:
        proc = subprocess.run(
            [sys.executable, "-u", str(CHILD)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, None

    for line in proc.stdout.splitlines():
        if line.startswith(REPORT_PREFIX):
            return json.loads(line[len(REPORT_PREFIX):]), proc
    return None, proc


@pytest.fixture(scope="module")
def report(display):
    """Launch the real GUI once and share the resulting facts."""
    data, proc = launch(display)

    if data is None and proc is None:
        pytest.fail(
            f"GUI launch did not finish within {LAUNCH_TIMEOUT}s — it is hung, "
            "not merely slow. A modal dialog or another blocking call is "
            "waiting on input that will never arrive."
        )
    if data is None:
        pytest.fail(
            "GUI child produced no report.\n"
            f"exit={proc.returncode}\n--- stdout ---\n{proc.stdout[-3000:]}\n"
            f"--- stderr ---\n{proc.stderr[-3000:]}"
        )
    if not data.get("ok"):
        pytest.fail("GUI failed to launch:\n" + data.get("traceback", "<none>"))
    return data


# -- Tests --


class TestGuiLaunches:
    def test_window_exists_and_is_mapped(self, report):
        assert report["exists"], "Tk root was destroyed during startup"
        assert report["mapped"], "window was created but never mapped"

    def test_window_has_real_geometry(self, report):
        # MainWindow asks for 1200x800. A 1x1 window means the geometry call
        # was dropped or the window never rendered.
        assert report["width"] > 1, f"window width was {report['width']}"
        assert report["height"] > 1, f"window height was {report['height']}"

    def test_window_title(self, report):
        assert report["title"] == "FlowCoder - Visual Flowchart Builder"

    def test_tabs_are_present(self, report):
        tabs = report["tabs"]
        assert tabs, "no ttk.Notebook found — the tab strip did not build"
        for expected in ("Commands", "Agents", "Files"):
            assert expected in tabs, f"missing tab {expected!r}; found {tabs}"

    def test_core_widgets_built(self, report):
        widgets = report["widgets"]
        assert "Notebook" in widgets, f"no Notebook in widget tree: {widgets}"
        assert "StatusBar" in widgets, f"no StatusBar in widget tree: {widgets}"

    def test_survives_event_loop_pumps(self, report):
        assert report["exists_after_pumps"], (
            "window died while dispatching queued callbacks"
        )

    def test_runs_against_the_pinned_engine(self, report):
        # The GUI drives flowcoder_engine through the protocol bridge. Assert
        # the pinned packages are the ones actually loaded, not a stray
        # sibling checkout on sys.path.
        for key in ("engine_path", "flowchart_path"):
            path = report[key]
            assert path, f"{key} was empty"
            assert "site-packages" in path, (
                f"{key} resolved outside the venv: {path}"
            )

    def test_startup_dialogs_are_recorded_not_fatal(self, report):
        # Startup may legitimately warn (e.g. a saved session whose backing
        # service is unreachable). Whether one fires depends on local state, so
        # assert only that any dialog is a known kind and the window survived.
        allowed = {
            "showwarning",
            "showinfo",
            "showerror",
            "askyesno",
            "askokcancel",
            "askretrycancel",
        }
        for name, title in report["dialogs"]:
            assert name in allowed, f"unexpected dialog {name!r} ({title!r})"
        assert report["exists"]


class TestHangDetection:
    """The watchdog itself must be known to work.

    A hang guard nobody has watched fire is an assumption, not a guard — so this
    reproduces the real deadlock and asserts it is caught rather than stalling.
    """

    def test_live_modal_dialog_is_caught_as_a_failure(self, display):
        # Force a real, undismissable messagebox so the deadlock is
        # deterministic rather than dependent on whether a saved session
        # happens to fail loading on this machine.
        data, proc = launch(
            display, stub_dialogs=False, force_modal=True, timeout=25
        )

        assert (data, proc) == (None, None), (
            "an undismissable modal dialog did NOT hang the child, so this "
            "test is no longer exercising the deadlock it exists to catch. "
            f"Got report={data!r}."
        )

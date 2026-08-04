"""Child process for tests/test_gui_launch.py — builds the real window, reports facts.

Run as a subprocess so that a blocking modal dialog is killable. A `SIGALRM`
watchdog cannot rescue the parent here: `messagebox.showwarning` blocks inside
Tcl's C event loop, and CPython defers signal handlers until control returns to
the bytecode interpreter, so the alarm never gets a chance to raise. Killing a
child is the only reliable escape.

Prints one line of JSON to stdout, prefixed with GUI_REPORT:, then exits 0.
Any exception is reported as JSON with "ok": false and a traceback.

Not named test_* so pytest does not collect it.
"""

import faulthandler
import json
import os
import sys
import traceback

sys.path.insert(0, os.getcwd())

# If this process wedges anyway, dump every thread's stack before dying.
# faulthandler's timer runs on its own thread in C, so it fires even while
# blocked inside Tcl.
faulthandler.dump_traceback_later(45, exit=True)

REPORT_PREFIX = "GUI_REPORT:"


def collect_tabs(root):
    from tkinter import ttk

    tabs = []

    def scan(widget):
        if isinstance(widget, ttk.Notebook):
            tabs.extend(widget.tab(i, "text") for i in widget.tabs())
        for child in widget.winfo_children():
            scan(child)

    scan(root)
    return tabs


def widget_tree(widget, depth=0, out=None, max_depth=2):
    out = out if out is not None else []
    out.append(widget.__class__.__name__)
    if depth < max_depth:
        for child in widget.winfo_children():
            widget_tree(child, depth + 1, out, max_depth)
    return out


def main():
    dialogs = []

    if os.environ.get("GUI_LAUNCH_STUB_DIALOGS", "1") == "1":
        # Startup schedules _show_failed_loads_dialog via after(), which calls
        # messagebox.showwarning and blocks until a human clicks OK. Record
        # instead of blocking. The env var exists so the test suite can verify
        # that leaving dialogs live really does hang — a watchdog nobody has
        # seen fire is not a watchdog.
        from tkinter import messagebox

        for name, default in (
            ("showwarning", "ok"),
            ("showerror", "ok"),
            ("showinfo", "ok"),
            ("askyesno", False),
            ("askokcancel", False),
            ("askretrycancel", False),
        ):
            def stub(*args, _name=name, _default=default, **kwargs):
                dialogs.append([_name, args[0] if args else None])
                return _default

            setattr(messagebox, name, stub)

    from src.views import MainWindow

    win = MainWindow(title="FlowCoder - Visual Flowchart Builder")
    root = win.root
    root.update_idletasks()
    root.update()

    if os.environ.get("GUI_LAUNCH_FORCE_MODAL") == "1":
        # Deliberately deadlock so the parent's hang detection is exercised on
        # every run, rather than only when local state happens to produce a
        # failed session load. Nothing dismisses this dialog; the parent kills
        # the process. Reached only from TestHangDetection, which sets
        # GUI_LAUNCH_STUB_DIALOGS=0 so this is the genuine blocking call.
        from tkinter import messagebox

        messagebox.showwarning("Deliberate deadlock", "blocks until killed")

    report = {
        "ok": True,
        "exists": bool(root.winfo_exists()),
        "mapped": bool(root.winfo_ismapped()),
        "width": root.winfo_width(),
        "height": root.winfo_height(),
        "title": root.title(),
        "tabs": collect_tabs(root),
        "widgets": widget_tree(root),
        "dialogs": dialogs,
    }

    # Dispatch queued callbacks — some blow up only once actually delivered.
    for _ in range(25):
        root.update()

    report["exists_after_pumps"] = bool(root.winfo_exists())

    import flowcoder_engine
    import flowcoder_flowchart

    report["engine_path"] = flowcoder_engine.__file__
    report["flowchart_path"] = flowcoder_flowchart.__file__

    root.destroy()

    faulthandler.cancel_dump_traceback_later()
    print(REPORT_PREFIX + json.dumps(report))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        faulthandler.cancel_dump_traceback_later()
        print(
            REPORT_PREFIX
            + json.dumps({"ok": False, "traceback": traceback.format_exc()})
        )
        sys.exit(1)

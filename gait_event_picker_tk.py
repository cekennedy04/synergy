"""The gait-event picker as a modal window inside the clinician GUI.

Built 2026-09-03. Same picker as `gait_event_picker_ui.show_picker_window` --
literally the same drawing and the same `EventPickerModel`, via
`build_picker_view` -- differing only in how it is shown and what it blocks on.

**Why a separate way of showing it.** The standalone window ends in
`plt.show()`, which starts a Tk mainloop of its own. The clinician GUI is
already running one, and two mainloops in a process is the deadlock the whole
Phase 2.1 fallback was chosen to avoid. `FigureCanvasTkAgg` in a `Toplevel`
plus `wait_window` is Tk's own way to be modal: it runs a nested event loop
inside the mainloop that already exists, so the GUI stays responsive and this
still blocks its caller until the operator is finished.

**This must run on the main thread.** Measured 2026-09-03: creating a
matplotlib window from the GUI's pipeline worker thread deadlocks -- the
worker never returns, and matplotlib warns "Starting a Matplotlib GUI outside
of the main thread will likely fail" on the way in. The worker therefore does
not call this. It posts a `ManualEventRequest` onto the pipeline queue and
waits; `clinician_gui` picks the request up in its `root.after` poll, which is
the main thread, and calls this there. See `clinician_gui.answer_manual_event_request`.

**Closing the window is a decline, not a failure.** `segment_walking` reads an
empty picker as the operator declining and falls back to the auto-trim rung.
The standalone provider treats an empty-and-not-cancelled picker as "the
window never opened", because under a non-interactive backend `plt.show()`
returns instantly and would otherwise look like a considered answer. Here the
window demonstrably opened -- we built it -- so the X button is wired to the
same `model.cancel()` the Cancel button uses, and the ambiguity never arises.
"""

TITLE = "Pick gait events"

# Enough room for two stacked panels plus the button column at 100 dpi. Smaller
# and the legend covers the peaks an operator is trying to click.
FIGURE_SIZE = (13, 7.5)
FIGURE_DPI = 100


def show_picker_in_tk(model, parent):  # pragma: no cover - needs a display
    """Open the picker as a modal Toplevel over `parent` and block until the
    operator is done. Returns the PickerWindow.

    `parent` is the clinician GUI's root. It is required rather than optional:
    a Toplevel with no master creates its own root, which is the second
    mainloop this exists to avoid.
    """
    import tkinter as tk
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                                   NavigationToolbar2Tk)

    from gait_event_picker_ui import build_picker_view

    toplevel = tk.Toplevel(parent)
    toplevel.title("%s - %s" % (TITLE, model.picker.motion.name or "trial"))
    toplevel.transient(parent)

    figure = Figure(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)
    canvas = FigureCanvasTkAgg(figure, master=toplevel)
    # Built before build_picker_view so canvas.toolbar exists: the click
    # handler reads it to tell a real pick from a zoom-rectangle drag, and
    # without a toolbar every zoom would deposit a spurious gait event.
    toolbar = NavigationToolbar2Tk(canvas, toplevel)
    toolbar.update()
    canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    window = build_picker_view(model, figure)

    def close():
        # grab_release before destroy: an interpreter that loses the toplevel
        # while it still holds the grab leaves the GUI unclickable.
        try:
            toplevel.grab_release()
        except tk.TclError:                       # already gone
            pass
        toplevel.destroy()

    window.close = close
    # The X button means the same thing as Cancel. Without this the operator
    # closing the window would leave an empty picker that nothing had marked
    # as a decision.
    toplevel.protocol("WM_DELETE_WINDOW", lambda: (model.cancel(), close()))

    canvas.draw()
    # Modal: the clinician must not start a second run, or close the session,
    # while the pipeline thread is blocked waiting for this answer.
    toplevel.grab_set()
    parent.wait_window(toplevel)
    return window

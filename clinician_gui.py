"""
clinician_gui.py

U1 of the clinician trial report GUI plan: the tkinter window where a
clinician selects an existing OpenCap session directory and a new Xsens
.mvnx trial file, with the Run control enabled only once both inputs are
valid, and a visible reason shown when they aren't.

KTD6: the API_TOKEN placeholder below MUST be the very first thing this
module does, before any other import. utils.py calls get_token() at module
import time (see utils.py:41 / utilsAuthentication.py), which otherwise
fires an interactive OpenCap login prompt -- fine in a terminal, fatal in a
GUI with no terminal for the prompt to appear in. Setting a placeholder here
means that if anything imported later (this unit or a future one) transitively
imports utils.py, the login prompt never fires.
"""
import os

os.environ.setdefault("API_TOKEN", "clinician-gui-placeholder-token")

# Every other import must come after the os.environ.setdefault call above.
import importlib.util
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_XSENS_TO_OPENSIM_PATH = os.path.join(REPO_ROOT, "xsens_to_opensim.py")


def _load_xsens_to_opensim():
    """Load xsens_to_opensim.py by absolute path, matching this repo's own
    test-loading convention (see tests/test_xsens_to_opensim_session_paths.py)
    rather than a normal `import xsens_to_opensim`, so this module works
    regardless of how/where it's launched from."""
    spec = importlib.util.spec_from_file_location(
        "xsens_to_opensim_for_clinician_gui", _XSENS_TO_OPENSIM_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_inputs(session_dir, mvnx_path):
    """Pure validation function, no Tk dependency -- importable and testable
    standalone (plan U1 requirement).

    Given a session directory path and an .mvnx path, returns (ready, reason):
      - ready=True, reason="" only when the session directory resolves to
        exactly one .osim model (via xsens_to_opensim.py's
        resolve_session_output_paths -- not reimplemented here) AND the
        .mvnx path exists on disk.
      - ready=False with a human-readable reason otherwise. When
        resolve_session_output_paths raises (zero or multiple .osim files),
        its own message is surfaced verbatim as the reason.
    """
    if not session_dir:
        return False, "Select an existing OpenCap session directory."
    if not mvnx_path:
        return False, "Select an .mvnx trial file."

    xsens_to_opensim = _load_xsens_to_opensim()
    # trial_name doesn't affect model auto-discovery/raising -- any
    # placeholder derived from the .mvnx filename is fine here since this
    # function only cares about resolving the .osim model.
    trial_name = Path(mvnx_path).stem or "trial"
    try:
        xsens_to_opensim.resolve_session_output_paths(session_dir, trial_name)
    except ValueError as exc:
        return False, str(exc)

    mvnx_file = Path(mvnx_path)
    if not mvnx_file.exists():
        return False, f".mvnx file not found: {mvnx_path}"

    return True, ""


class ClinicianGUI:
    """The persistent tkinter main window. Construction builds real Tk
    widgets, so tests must not instantiate this class -- they exercise
    validate_inputs() directly instead (see tests/test_clinician_gui_inputs.py
    and the plan's note that Tk widget rendering is a manual smoke check,
    not a unit test)."""

    def __init__(self, root=None):
        self.root = root or tk.Tk()
        self.root.title("Clinician Trial Report")

        self.session_dir = ""
        self.mvnx_path = ""

        self._build_widgets()
        self._revalidate()

    def _build_widgets(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="OpenCap session directory:").grid(
            row=0, column=0, sticky="w"
        )
        self.session_dir_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.session_dir_var, width=50, state="readonly").grid(
            row=1, column=0, sticky="we"
        )
        ttk.Button(frame, text="Browse...", command=self._pick_session_dir).grid(
            row=1, column=1, padx=(6, 0)
        )

        ttk.Label(frame, text="Xsens .mvnx trial file:").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        self.mvnx_path_var = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.mvnx_path_var, width=50, state="readonly").grid(
            row=3, column=0, sticky="we"
        )
        ttk.Button(frame, text="Browse...", command=self._pick_mvnx_file).grid(
            row=3, column=1, padx=(6, 0)
        )

        self.reason_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.reason_var, foreground="red", wraplength=400).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        self.run_button = ttk.Button(frame, text="Run", state="disabled")
        self.run_button.grid(row=5, column=0, columnspan=2, pady=(10, 0))

    def _pick_session_dir(self):
        # Mirrors Examples/gaitAnalysis-UCM.py's
        # _select_extracted_folder_interactively picker pattern.
        selected = filedialog.askdirectory(parent=self.root)
        if selected:
            self.session_dir = selected
            self.session_dir_var.set(selected)
            self._revalidate()

    def _pick_mvnx_file(self):
        # Mirrors Examples/gaitAnalysis-UCM.py's _select_zip_interactively
        # picker pattern.
        selected = filedialog.askopenfilename(
            parent=self.root, filetypes=[("Xsens MVNX", "*.mvnx"), ("All files", "*.*")]
        )
        if selected:
            self.mvnx_path = selected
            self.mvnx_path_var.set(selected)
            self._revalidate()

    def _revalidate(self):
        ready, reason = validate_inputs(self.session_dir, self.mvnx_path)
        self.run_button.configure(state="normal" if ready else "disabled")
        self.reason_var.set(reason)
        return ready, reason


def main():
    app = ClinicianGUI()
    app.root.mainloop()


if __name__ == "__main__":
    main()

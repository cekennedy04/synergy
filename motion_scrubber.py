"""Scrub an OpenSim motion frame by frame, and read back where you are.

Built 2026-08-30. Phase 2.1 of
`docs/plans/2026-08-27-001-feat-rerun-visualizer-joint-reduction-plan.md`.
The foundation for the manual gait-event picker (Phase 2.2), which is the
third rung of the fallback chain after prominence escalation and auto-trim.

**Why the existing approach could not be extended.**
`replay-os-small.py` ends with `osim.VisualizerUtilities.showMotion(model,
motion)`. That is a static C++ helper which runs its own playback loop to
completion: no frame callback, no pause, no way to ask where it is. That, and
not any missing API, is the reason behind the note "can load motion in but no
access to change the gui". The loop is simply not yours while it owns it.

The alternative is to drive the state yourself, one frame at a time:

    coordinate.setValue(state, value)   # per coordinate, radians or degrees
    model.realizePosition(state)
    visualizer.report(state)            # getVisualizer().getSimbodyVisualizer()

which is what the supervisor's OpenSim scripting document demonstrates from a
Tk slider callback. No `Vec3` is constructed anywhere on this path --
coordinate values are plain floats -- so the "proprietary array" problem does
not arise outside camera transforms.

**Row index is the coordinate system, not time.**
A picked gait event must round-trip exactly, and `.mot` sample times are NOT
uniform: a real file from this pipeline starts `-0.01667, 0, 0.017, 0.033,
0.05`, mixing an npose frame with inconsistent rounding. Reconstructing time
as `start + row * dt` drifts against the file. So the slider's domain is the
integer row, time is *read* from the file's own independent column, and an
event is stored as a row index and converted only at the boundary --
`segment_walking` works in indices into `markerDict['time']` anyway.

**The data layer does not need OpenSim.** `.mot` is a text table; parsing it
here rather than through `osim.TimeSeriesTable` keeps every row/time/value
question testable in an environment without OpenSim, and leaves only the 3D
rendering behind the optional import.
"""
import os
import re
import shutil
import sys
from pathlib import Path

HEADER_END = "endheader"

# A .mot may be in degrees or radians; OpenSim's Coordinate.setValue always
# takes radians. Getting this backwards is a silent 57x error that still
# renders a pose, so the file's own declaration is honoured rather than assumed.
_DEGREES_KEY = "inDegrees"

# Translations are metres in every .mot regardless of inDegrees, so they must
# never be converted. Matching OpenSim's own convention for these names.
_TRANSLATION_SUFFIXES = ("_tx", "_ty", "_tz")


class MotionParseError(ValueError):
    """The .mot could not be read as a motion table, with the reason."""


def _is_translation(name):
    return name.endswith(_TRANSLATION_SUFFIXES)


class MotionSource:
    """One motion table: column names, sample times, and per-row values.

    Deliberately dumb. Everything the scrubber needs to answer about "where
    am I and what is the pose here" is answerable from this without a model,
    a visualizer, or OpenSim being installed.
    """

    def __init__(self, column_names, times, rows, in_degrees=True, name=""):
        if len(times) != len(rows):
            raise MotionParseError(
                f"{len(times)} sample times but {len(rows)} data rows.")
        if not rows:
            raise MotionParseError("motion has no data rows.")
        widths = {len(row) for row in rows}
        if widths != {len(column_names)}:
            raise MotionParseError(
                f"{len(column_names)} coordinate columns but rows of width "
                f"{sorted(widths)}; the table is ragged.")
        self.column_names = list(column_names)
        self.times = list(times)
        self.rows = rows
        self.in_degrees = in_degrees
        self.name = name

    @property
    def n_rows(self):
        return len(self.rows)

    def time_at(self, row):
        """The file's own time for a row. Never reconstructed arithmetically."""
        if not 0 <= row < self.n_rows:
            raise IndexError(
                f"row {row} out of range for a motion with {self.n_rows} rows.")
        return self.times[row]

    def values_at(self, row):
        """Coordinate name -> value, in the file's own units."""
        if not 0 <= row < self.n_rows:
            raise IndexError(
                f"row {row} out of range for a motion with {self.n_rows} rows.")
        return dict(zip(self.column_names, self.rows[row]))

    def radians_at(self, row):
        """Coordinate name -> value in the units Coordinate.setValue wants.

        Angles become radians when the file declares degrees; translations
        are metres either way and are passed through untouched.
        """
        import math
        values = self.values_at(row)
        if not self.in_degrees:
            return values
        return {name: (value if _is_translation(name) else math.radians(value))
                for name, value in values.items()}

    def nearest_row(self, time):
        """The row whose recorded time is closest to `time`.

        A linear scan, not a bisect: sample times are monotonic in every file
        seen, but a motion assembled from concatenated segments would not be,
        and a bisect would return a confidently wrong row for it.
        """
        best, best_gap = 0, abs(self.times[0] - time)
        for row, value in enumerate(self.times):
            gap = abs(value - time)
            if gap < best_gap:
                best, best_gap = row, gap
        return best


def parse_mot(path):
    """Read a .mot into a MotionSource. Pure Python; no OpenSim required."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    header_end = None
    in_degrees = True
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() == HEADER_END:
            header_end = index
            break
        match = re.match(rf"\s*{_DEGREES_KEY}\s*=\s*(\w+)", stripped, re.I)
        if match:
            in_degrees = match.group(1).strip().lower() in ("yes", "true", "1")
    if header_end is None:
        raise MotionParseError(
            f"{path} has no '{HEADER_END}' line, so where the header stops and "
            "the data starts cannot be determined. It may not be a .mot.")

    body = [line for line in lines[header_end + 1:] if line.strip()]
    if not body:
        raise MotionParseError(f"{path} has a header but no data rows.")

    header = body[0].split("\t") if "\t" in body[0] else body[0].split()
    header = [column.strip() for column in header if column.strip()]
    if not header or header[0].lower() != "time":
        raise MotionParseError(
            f"{path}'s first data column is {header[:1]}, expected 'time'. "
            "Row-to-time mapping depends on it.")

    times, rows = [], []
    for number, line in enumerate(body[1:], start=1):
        parts = line.split("\t") if "\t" in line else line.split()
        parts = [p for p in parts if p.strip()]
        if len(parts) != len(header):
            raise MotionParseError(
                f"{path} line {number}: {len(parts)} values for "
                f"{len(header)} columns.")
        try:
            values = [float(p) for p in parts]
        except ValueError as exc:
            raise MotionParseError(f"{path} line {number}: {exc}") from exc
        times.append(values[0])
        rows.append(values[1:])

    return MotionSource(header[1:], times, rows, in_degrees=in_degrees,
                        name=path.stem)


VISUALIZER_EXE = "simbody-visualizer.exe" if os.name == "nt" else "simbody-visualizer"


def ensure_visualizer_on_path():
    """Make Simbody's viewer executable findable, or say why it is not.

    OpenSim launches `simbody-visualizer` as a separate process located via
    PATH. Running the interpreter directly -- `envs/opencap-processing/
    python.exe script.py`, which is how every batch job here runs -- does NOT
    put the environment's `Library/bin` on PATH the way `conda activate`
    does, so the launch fails with Simbody's "Required condition
    'status == 0' was not met" and a PATH dump that names nothing useful.

    Returns the directory added, or None if it was already findable.
    """
    if shutil.which(VISUALIZER_EXE):
        return None
    candidate = Path(sys.executable).parent / "Library" / "bin"
    if (candidate / VISUALIZER_EXE).is_file():
        os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
        return candidate
    raise FileNotFoundError(
        f"{VISUALIZER_EXE} is not on PATH and is not at {candidate}. OpenSim "
        "runs the visualizer as a separate process, so without it a model can "
        "be loaded but never shown."
    )


class ModelView:
    """Renders one pose into a live Simbody visualizer window.

    Isolated behind this class so everything above stays importable and
    testable without OpenSim, and so the GUI can be exercised against a fake.

    **Do not drive this from a Tk callback.** Measured 2026-08-30: a Tk
    mainloop and the Simbody visualizer in one process deadlock. The identical
    frame sequence driven from a plain Python loop opens the window in 2.0s
    and renders six frames in 1.4s; wrapped in `root.after()` under
    `mainloop()` it hangs indefinitely with no output and no error, and the
    visualizer process alive. Simbody talks to its viewer over a pipe and
    blocks on it, which Tk's loop does not yield for.

    So the Phase 2.2 picker cannot be a Tk window driving this class in-process.
    The options are a picker with no 3D view (matplotlib over the joint-angle
    curves, which the plan already names as the fallback), or the visualizer in
    a separate process driven over IPC. Nothing here should grow a Tk import.
    """

    def __init__(self, model_path, opensim=None):
        if opensim is None:
            ensure_visualizer_on_path()
        osim = opensim if opensim is not None else __import__("opensim")
        self._osim = osim
        self.model = osim.Model(str(model_path))
        self.model.setUseVisualizer(True)
        self.state = self.model.initSystem()

        # Muscle dynamics off. Without this OpenSim tries to solve the muscles
        # for every reported frame and fails -- replay-os-small.py does the
        # same thing for the same reason.
        muscles = self.model.getForceSet().getMuscles()
        for index in range(muscles.getSize()):
            muscle = muscles.get(index)
            muscle.set_ignore_activation_dynamics(True)
            muscle.set_ignore_tendon_compliance(True)

        self._coordinates = {}
        coordinate_set = self.model.getCoordinateSet()
        for index in range(coordinate_set.getSize()):
            coordinate = coordinate_set.get(index)
            self._coordinates[coordinate.getName()] = coordinate

        self.visualizer = self.model.getVisualizer().getSimbodyVisualizer()
        self.model.getVisualizer().show(self.state)

    @property
    def coordinate_names(self):
        return set(self._coordinates)

    def unmatched(self, motion):
        """Motion columns this model has no coordinate for.

        Reported rather than raised: a .mot routinely carries columns the
        model does not use, and refusing to render over that would make the
        viewer useless. Silently dropping them, though, hides a real mismatch.
        """
        return [name for name in motion.column_names
                if name not in self._coordinates]

    def show_row(self, motion, row):
        """Set every matching coordinate to this row's pose and render it."""
        for name, value in motion.radians_at(row).items():
            coordinate = self._coordinates.get(name)
            if coordinate is not None:
                coordinate.setValue(self.state, value, False)
        # enforceConstraints=False above, then assemble once here: setting
        # coordinates one at a time with constraint enforcement on re-solves
        # the whole system per coordinate, which is both slow and order-
        # dependent.
        self.model.assemble(self.state)
        self.model.realizePosition(self.state)
        self.visualizer.report(self.state)

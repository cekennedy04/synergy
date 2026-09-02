"""Tests for motion_scrubber.py.

The data layer is pure Python by design, so all of it is exercised here
without OpenSim. ModelView is driven against a fake `opensim` module, which
pins the call sequence the Simbody visualizer requires without needing it
installed.
"""
import importlib.util
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "motion_scrubber_under_test", REPO_ROOT / "motion_scrubber.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_mot(path, in_degrees="yes", rows=None, columns=("pelvis_tilt", "pelvis_tx")):
    rows = rows or [(-0.01666666666666667, 1.0, 0.93),
                    (0.0, 2.0, 0.93),
                    (0.017, 3.0, 0.93),
                    (0.033, 4.0, 0.93)]
    header = "\r\n".join([
        f"inDegrees={in_degrees}", f"name={path.name}", "DataType=double",
        "version=3", "endheader",
        "\t".join(("time",) + tuple(columns)),
    ])
    body = "\r\n".join("\t".join(repr(v) for v in row) for row in rows)
    path.write_text(header + "\r\n" + body + "\r\n", encoding="utf-8")
    return path


# -- parsing ---------------------------------------------------------------


def test_a_real_shaped_mot_parses(mod, tmp_path):
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot"))

    assert motion.column_names == ["pelvis_tilt", "pelvis_tx"]
    assert motion.n_rows == 4
    assert motion.in_degrees is True
    assert motion.name == "T1"


def test_radians_declaration_is_honoured(mod, tmp_path):
    """inDegrees is read, not assumed. Getting it backwards is a silent 57x
    error that still renders a plausible pose."""
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot", in_degrees="no"))

    assert motion.in_degrees is False
    assert motion.radians_at(1)["pelvis_tilt"] == pytest.approx(2.0)


def test_degrees_are_converted_but_translations_are_not(mod, tmp_path):
    """Translations are metres in every .mot regardless of inDegrees."""
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot", in_degrees="yes"))

    converted = motion.radians_at(1)

    assert converted["pelvis_tilt"] == pytest.approx(math.radians(2.0))
    assert converted["pelvis_tx"] == pytest.approx(0.93)


def test_a_file_without_endheader_says_so(mod, tmp_path):
    path = tmp_path / "bad.mot"
    path.write_text("time\tpelvis_tilt\r\n0\t1\r\n", encoding="utf-8")

    with pytest.raises(mod.MotionParseError, match="endheader"):
        mod.parse_mot(path)


def test_a_first_column_that_is_not_time_is_rejected(mod, tmp_path):
    path = tmp_path / "bad.mot"
    path.write_text("endheader\r\nframe\tpelvis_tilt\r\n0\t1\r\n", encoding="utf-8")

    with pytest.raises(mod.MotionParseError, match="expected 'time'"):
        mod.parse_mot(path)


def test_a_ragged_row_is_rejected_rather_than_padded(mod, tmp_path):
    path = tmp_path / "bad.mot"
    path.write_text("endheader\r\ntime\ta\tb\r\n0\t1\t2\r\n0.1\t3\r\n",
                    encoding="utf-8")

    with pytest.raises(mod.MotionParseError, match="values for"):
        mod.parse_mot(path)


def test_a_header_with_no_data_is_rejected(mod, tmp_path):
    path = tmp_path / "bad.mot"
    path.write_text("endheader\r\n", encoding="utf-8")

    with pytest.raises(mod.MotionParseError, match="no data"):
        mod.parse_mot(path)


# -- the row/time contract -------------------------------------------------
# The whole reason the slider's domain is the row index. A picked gait event
# must round-trip exactly, and .mot sample times are not uniform.


def test_time_is_read_from_the_file_not_reconstructed(mod, tmp_path):
    """A real file from this pipeline starts -0.01667, 0, 0.017, 0.033 --
    an npose frame plus inconsistent rounding. start + row*dt drifts."""
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot"))

    assert motion.time_at(0) == pytest.approx(-0.01666666666666667)
    assert motion.time_at(1) == pytest.approx(0.0)
    assert motion.time_at(2) == pytest.approx(0.017)
    # what a uniform reconstruction from row 1 would have produced
    assert motion.time_at(3) != pytest.approx(0.0 + 3 * 0.017)


def test_a_row_round_trips_through_its_own_time(mod, tmp_path):
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot"))

    for row in range(motion.n_rows):
        assert motion.nearest_row(motion.time_at(row)) == row


def test_nearest_row_handles_a_time_between_samples(mod, tmp_path):
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot"))

    assert motion.nearest_row(0.0166) == 2   # closer to 0.017 than to 0.0


def test_an_out_of_range_row_is_an_error_not_a_clamp(mod, tmp_path):
    """A clamped row would silently mark an event at the wrong frame."""
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot"))

    with pytest.raises(IndexError):
        motion.time_at(motion.n_rows)
    with pytest.raises(IndexError):
        motion.values_at(-1)


# -- the visualizer executable ---------------------------------------------


def test_the_visualizer_is_found_next_to_the_interpreter(mod, tmp_path,
                                                         monkeypatch):
    """OpenSim runs simbody-visualizer as a separate process located via PATH.
    Invoking the interpreter directly -- which is how every batch job here
    runs -- does not put the environment's Library/bin on PATH the way
    `conda activate` does, and the failure names nothing useful."""
    fake_env = tmp_path / "env"
    (fake_env / "Library" / "bin").mkdir(parents=True)
    (fake_env / "Library" / "bin" / mod.VISUALIZER_EXE).write_text("")
    monkeypatch.setattr(mod.sys, "executable", str(fake_env / "python.exe"))
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setenv("PATH", "")

    added = mod.ensure_visualizer_on_path()

    assert added == fake_env / "Library" / "bin"
    assert str(added) in mod.os.environ["PATH"]


def test_an_absent_visualizer_says_what_is_missing(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    with pytest.raises(FileNotFoundError, match=mod.VISUALIZER_EXE):
        mod.ensure_visualizer_on_path()


def test_an_already_findable_visualizer_is_left_alone(mod, monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/" + name)

    assert mod.ensure_visualizer_on_path() is None


def test_the_module_does_not_import_tk(mod):
    """Measured 2026-08-30: a Tk mainloop and the Simbody visualizer deadlock
    in one process. The same frame sequence renders in 1.4s from a plain
    Python loop and hangs indefinitely under root.after()/mainloop(). Nothing
    here may grow a Tk dependency."""
    source = (REPO_ROOT / "motion_scrubber.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("#"))

    assert "import tkinter" not in code
    assert "import ttkbootstrap" not in code


# -- rendering -------------------------------------------------------------


class _FakeCoordinate:
    def __init__(self, name):
        self.name, self.value = name, None

    def getName(self):
        return self.name

    def setValue(self, state, value, enforce=True):
        self.value = value


class _FakeSet:
    def __init__(self, items):
        self._items = items

    def getSize(self):
        return len(self._items)

    def get(self, index):
        return self._items[index]


class _FakeMuscle:
    def __init__(self):
        self.ignored = []

    def set_ignore_activation_dynamics(self, flag):
        self.ignored.append(("activation", flag))

    def set_ignore_tendon_compliance(self, flag):
        self.ignored.append(("tendon", flag))


def _fake_opensim(coordinate_names=("pelvis_tilt", "pelvis_tx"), n_muscles=2):
    calls = []
    coordinates = [_FakeCoordinate(n) for n in coordinate_names]
    muscles = [_FakeMuscle() for _ in range(n_muscles)]

    class _FakeVisualizer:
        def report(self, state):
            calls.append("report")

    class _FakeModelVisualizer:
        def getSimbodyVisualizer(self):
            return _FakeVisualizer()

        def show(self, state):
            calls.append("show")

    class _FakeModel:
        def __init__(self, path):
            calls.append(("Model", path))

        def setUseVisualizer(self, flag):
            calls.append(("setUseVisualizer", flag))

        def initSystem(self):
            return "state"

        def getForceSet(self):
            return type("FS", (), {"getMuscles": lambda _self: _FakeSet(muscles)})()

        def getCoordinateSet(self):
            return _FakeSet(coordinates)

        def getVisualizer(self):
            return _FakeModelVisualizer()

        def assemble(self, state):
            calls.append("assemble")

        def realizePosition(self, state):
            calls.append("realizePosition")

    return type("osim", (), {"Model": _FakeModel}), calls, coordinates, muscles


def test_muscle_dynamics_are_disabled_on_load(mod):
    """Without this OpenSim tries to solve the muscles per rendered frame and
    fails -- replay-os-small.py disables them for the same reason."""
    osim, _calls, _coords, muscles = _fake_opensim()

    mod.ModelView("model.osim", opensim=osim)

    for muscle in muscles:
        assert ("activation", True) in muscle.ignored
        assert ("tendon", True) in muscle.ignored


def test_showing_a_row_sets_realises_then_reports_in_that_order(mod, tmp_path):
    """The sequence the Simbody visualizer requires. Reporting before
    realizing renders the previous pose."""
    osim, calls, coordinates, _ = _fake_opensim()
    view = mod.ModelView("model.osim", opensim=osim)
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot"))
    calls.clear()

    view.show_row(motion, 1)

    assert calls == ["assemble", "realizePosition", "report"]
    tilt = next(c for c in coordinates if c.name == "pelvis_tilt")
    assert tilt.value == pytest.approx(math.radians(2.0))


def test_a_translation_is_set_in_metres_not_radians(mod, tmp_path):
    osim, _calls, coordinates, _ = _fake_opensim()
    view = mod.ModelView("model.osim", opensim=osim)
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot"))

    view.show_row(motion, 1)

    tx = next(c for c in coordinates if c.name == "pelvis_tx")
    assert tx.value == pytest.approx(0.93)


def test_columns_the_model_lacks_are_reported_not_silently_dropped(mod, tmp_path):
    """A .mot routinely carries columns a model does not use, so refusing
    would make the viewer useless -- but hiding a real mismatch is worse."""
    osim, _calls, _coords, _ = _fake_opensim(coordinate_names=("pelvis_tilt",))
    view = mod.ModelView("model.osim", opensim=osim)
    motion = mod.parse_mot(_write_mot(tmp_path / "T1.mot"))

    assert view.unmatched(motion) == ["pelvis_tx"]
    view.show_row(motion, 1)  # still renders what it can

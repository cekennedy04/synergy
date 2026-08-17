"""
Tests build_orientations_sto's source='segment' vs source='sensor' logic
(added 2026-08-17 after inspecting real data: context/S01-001.xlsx confirmed
which of the 23 segments have real sensors vs Xsens-interpolated zeros, and
context/0_Bed_to_ShowerChair_M.mvnx confirmed its tpose/npose calibration
frame has NO <sensorOrientation> data at all -- source='sensor' can't
calibrate against this file and must fail loudly, not silently degrade to
an uncalibrated first-motion-frame pose).

opensim IS now installed on this machine (2026-08-17 evening, opencap-processing conda env,
OpenSim 4.5) -- but these tests still stub it, for two reasons: (1) they need to run in whatever
environment `pytest` is invoked from, which may not be the one with opensim installed, and (2) the
fake classes below double as a regression check on the exact real API shape, which running this
script for real against 0_Bed_to_ShowerChair_M.mvnx exposed to be different from what was
originally assumed -- RowVectorQuaternion has no __setitem__/.set(col, quat); the only way to
populate a row is `row.updElt(0, col)` (confirmed to return a live reference) then
`Quaternion.set(component_index, value)` four times. The fakes here mirror that real shape, not
the wrong one this file used before. Same monkeypatch.setitem-based cleanup pattern as
test_utilsKinematics_UCM_modelpath.py (see that file for why writing sys.modules directly without
cleanup is a real bug, not a style nit).
"""
import importlib.util
import os
import sys
import textwrap
import types

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'xsens_to_opensim.py')


class _FakeQuaternion:
    """Mirrors the real opensim.Quaternion's actual API: constructible with
    4 components, but mutated one component at a time via set(i, value) --
    confirmed against real OpenSim 4.5, not the set-all-4-at-once shape
    originally assumed."""
    def __init__(self, w=0.0, x=0.0, y=0.0, z=0.0):
        self._components = [w, x, y, z]

    def set(self, i, value):
        self._components[i] = value

    @property
    def wxyz(self):
        return tuple(self._components)


class _FakeRowVectorQuaternion:
    """Mirrors the real opensim.RowVectorQuaternion: no __setitem__, no
    .set(col, quat) -- only updElt(0, col), which returns a reference whose
    mutations propagate back into the row (confirmed against real OpenSim
    4.5)."""
    def __init__(self, n):
        self._elements = [_FakeQuaternion() for _ in range(n)]

    def updElt(self, row, col):
        assert row == 0, "only row 0 exists on a row vector"
        return self._elements[col]

    def __iter__(self):
        return iter(self._elements)


class _FakeTimeSeriesTableQuaternion:
    def __init__(self):
        self.column_labels = None
        self.rows = []  # list of (time, [ (w,x,y,z), ... ])

    def setColumnLabels(self, labels):
        self.column_labels = list(labels)

    def appendRow(self, t, row):
        self.rows.append((t, [q.wxyz for q in row]))


class _FakeSTOFileAdapterQuaternion:
    written = []  # (table, path) pairs, captured for assertions

    @staticmethod
    def write(table, path):
        _FakeSTOFileAdapterQuaternion.written.append((table, path))


def _install_stub_opensim(monkeypatch):
    fake_opensim = types.ModuleType('opensim')
    fake_opensim.TimeSeriesTableQuaternion = _FakeTimeSeriesTableQuaternion
    fake_opensim.RowVectorQuaternion = _FakeRowVectorQuaternion
    fake_opensim.Quaternion = _FakeQuaternion
    fake_opensim.STOFileAdapterQuaternion = _FakeSTOFileAdapterQuaternion
    monkeypatch.setitem(sys.modules, 'opensim', fake_opensim)


def _load_module(monkeypatch):
    _install_stub_opensim(monkeypatch)
    spec = importlib.util.spec_from_file_location('xsens_to_opensim_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 3 segments: Pelvis (has a sensor), L5 (no sensor, per real data), T8 (has a
# sensor). Motion frames have sensorOrientation for Pelvis/T8 only (L5's
# would be all-zero in a real export, but it's simplest to just omit it from
# this synthetic sensor payload entirely and rely on SENSOR_EQUIPPED_SEGMENTS
# to keep L5 out of any source='sensor' request). The tpose calibration frame
# has orientation but deliberately NO sensorOrientation, matching the real
# file's structure that motivated the ValueError this test checks for.
FIXTURE_MVNX = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <frames segmentCount="3" jointCount="2">
      <frame type="tpose" index="-2" time="0">
        <orientation>1 0 0 0  1 0 0 0  1 0 0 0</orientation>
      </frame>
      <frame type="normal" index="0" time="0">
        <orientation>0.9 0.1 0 0  0.8 0.2 0 0  0.7 0.3 0 0</orientation>
        <sensorOrientation>0.95 0.05 0 0  0.75 0.25 0 0</sensorOrientation>
      </frame>
      <frame type="normal" index="1" time="17">
        <orientation>0.85 0.15 0 0  0.75 0.25 0 0  0.65 0.35 0 0</orientation>
        <sensorOrientation>0.9 0.1 0 0  0.7 0.3 0 0</sensorOrientation>
      </frame>
    </frames>
    """)


@pytest.fixture
def fixture_mvnx_path(tmp_path):
    path = tmp_path / "fixture.mvnx"
    path.write_text(FIXTURE_MVNX)
    return str(path)


@pytest.fixture
def xsens_module(monkeypatch):
    module = _load_module(monkeypatch)
    # Point the module's segment-availability constants at this fixture's
    # 3-segment world instead of the real 23/17, so the tests are self
    # contained rather than depending on the module's real (23-segment)
    # constants matching a 3-segment fixture. STANDARD_23_SEGMENT_ORDER also
    # has to match, since this fixture uses the "frames-only" shape (root IS
    # <frames>, no <segments> label list) that parse_mvnx falls back to that
    # constant for.
    monkeypatch.setattr(module, 'STANDARD_23_SEGMENT_ORDER', ['Pelvis', 'L5', 'T8'])
    monkeypatch.setattr(module, 'SENSOR_EQUIPPED_SEGMENTS', ['Pelvis', 'T8'])
    return module


def test_source_segment_writes_all_requested_segments(xsens_module, fixture_mvnx_path, tmp_path):
    _FakeSTOFileAdapterQuaternion.written.clear()
    mapping = {"Pelvis": "pelvis_imu", "L5": "l5_imu"}  # L5 has no sensor, but
    # 'segment' mode doesn't care -- Xsens provides a segment orientation for
    # every segment regardless of physical sensor coverage.
    sto_path = str(tmp_path / "out.sto")

    xsens_module.build_orientations_sto(fixture_mvnx_path, sto_path, mapping, source="segment")

    table, written_path = _FakeSTOFileAdapterQuaternion.written[-1]
    assert written_path == sto_path
    assert table.column_labels == ["pelvis_imu", "l5_imu"]
    # 1 calibration row (tpose) + 2 motion rows.
    assert len(table.rows) == 3
    # Calibration row (tpose, identity quats) comes first.
    assert table.rows[0][1] == [(1.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)]
    # First real motion row: Pelvis=(0.9,0.1,0,0), L5=(0.8,0.2,0,0).
    assert table.rows[1][1] == [(0.9, 0.1, 0.0, 0.0), (0.8, 0.2, 0.0, 0.0)]


def test_source_sensor_rejects_segment_without_a_physical_sensor(xsens_module, fixture_mvnx_path, tmp_path):
    mapping = {"Pelvis": "pelvis_imu", "L5": "l5_imu"}  # L5 has no sensor.
    sto_path = str(tmp_path / "out.sto")

    with pytest.raises(ValueError, match="L5"):
        xsens_module.build_orientations_sto(fixture_mvnx_path, sto_path, mapping, source="sensor")


def test_source_sensor_fails_loudly_when_calibration_frame_lacks_sensor_data(
    xsens_module, fixture_mvnx_path, tmp_path
):
    """The core regression this file exists to guard: source='sensor' must
    refuse to run rather than silently calibrate off the first motion frame
    when the tpose/npose frame has no <sensorOrientation> -- exactly what
    the real 0_Bed_to_ShowerChair_M.mvnx does."""
    mapping = {"Pelvis": "pelvis_imu", "T8": "t8_imu"}  # both sensor-equipped
    sto_path = str(tmp_path / "out.sto")

    with pytest.raises(ValueError, match="no <sensorOrientation> data"):
        xsens_module.build_orientations_sto(fixture_mvnx_path, sto_path, mapping, source="sensor")


def test_invalid_source_value_rejected(xsens_module, fixture_mvnx_path, tmp_path):
    with pytest.raises(ValueError, match="source must be"):
        xsens_module.build_orientations_sto(
            fixture_mvnx_path, str(tmp_path / "out.sto"), {"Pelvis": "pelvis_imu"}, source="bogus"
        )

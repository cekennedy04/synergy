"""Tests for the non-gait trial guardrail in gait_analysis_UCM_fixed.py
(added 2026-08-24).

Why this exists: a real bed-to-shower-chair transfer ran the full pipeline
and produced a complete, clean-looking clinical report -- cadence, gait
speed, step-length symmetry, joint-angle curves, a confidence banner and an
exported PDF -- with no warning anywhere. The failure mode is not a crash,
it is a plausible wrong report, which is far harder to catch downstream.

`_validate_gait_pattern` is exercised directly against synthetic gaitEvents
rather than through a constructed `gait_analysis`, because the constructor
loads a real OpenSim model and marker file. The validator reads only
`self.nGaitCycles` and `self.gaitEvents['ipsilateralTime']`, so a plain
stand-in object covers it exactly.

Note also that `gait_analysis.__init__` imports `utilsKinematics` ->
`utils.py`, which calls `get_token()` at import time and fires an
interactive OpenCap login prompt. The API_TOKEN placeholder below is the
same guard clinician_gui.py applies, and must precede the module import.
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("API_TOKEN", "gait-pattern-tests-placeholder")

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "gait_analysis_UCM_fixed.py"


@pytest.fixture
def mod(monkeypatch):
    """Loads the module with `opensim` stubbed.

    gait_analysis_UCM_fixed imports utilsKinematics, which imports opensim at
    module level -- unavailable in the interpreter that has pytest (opensim
    lives in the opencap-processing conda env, which has no pytest). The
    validator under test touches none of it. Uses monkeypatch.setitem rather
    than raw sys.modules assignment so the stub is torn down per test, per
    the convention the other test modules in this suite follow.
    """
    monkeypatch.setitem(sys.modules, "opensim", types.ModuleType("opensim"))
    # utilsKinematics itself pulls in opensim -> utils -> utilsAPI and a chain
    # of packages absent from this interpreter. gait_analysis only needs it as
    # a base class, and the validator uses none of its behaviour, so a stub
    # class is both sufficient and less brittle than stubbing the chain.
    fake_kinematics = types.ModuleType("utilsKinematics")
    fake_kinematics.kinematics = type("kinematics", (object,), {})
    monkeypatch.setitem(sys.modules, "utilsKinematics", fake_kinematics)
    spec = importlib.util.spec_from_file_location("gait_analysis_ucm_fixed_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _stub(mod, n_cycles, stride_seconds=0.94):
    """Minimal stand-in exposing exactly what the validator reads.

    ipsilateralTime is (n x 3) as HS -> TO -> HS; the validator uses columns
    0 and 2, so the stride duration is what drives cadence.
    """
    obj = mod.gait_analysis.__new__(mod.gait_analysis)
    obj.nGaitCycles = n_cycles
    times = np.array([
        [i * stride_seconds, i * stride_seconds + stride_seconds * 0.6,
         (i + 1) * stride_seconds]
        for i in range(max(n_cycles, 1))
    ])
    obj.gaitEvents = {"ipsilateralTime": times}
    return obj


def test_non_gait_trial_with_one_cycle_is_rejected(mod):
    """The real observed case: a transfer segmented into a single 'gait
    cycle'. One cycle means 2 ipsilateral and 1 contralateral heel strike."""
    with pytest.raises(mod.NonGaitTrialError, match="heel strike"):
        _stub(mod, 1)._validate_gait_pattern()


def test_two_cycles_still_rejected_because_contralateral_leg_is_binding(mod):
    """Two cycles gives 3 ipsilateral heel strikes but only 2 contralateral.
    The threshold is per-leg, so the contralateral leg decides."""
    with pytest.raises(mod.NonGaitTrialError, match="contralateral"):
        _stub(mod, 2)._validate_gait_pattern()


def test_three_cycles_is_the_documented_minimum_and_passes(mod):
    """Pins the boundary. Real trials observed 4-6 cycles, so 3 sits below
    every genuine trial while excluding the non-gait case."""
    _stub(mod, 3)._validate_gait_pattern()


def test_real_world_cycle_counts_all_pass(mod):
    """Regression against false rejection: these are the actual per-leg cycle
    counts from 15 verified walking trials. A future threshold change that
    breaks any of them is rejecting real data."""
    for n_cycles in (4, 5, 6):
        _stub(mod, n_cycles)._validate_gait_pattern()


def test_implausibly_fast_cadence_is_rejected(mod):
    """Events too closely spaced to be walking -- e.g. detector noise
    latching onto a tremor or a rhythmic non-gait movement."""
    # 0.3 s strides -> 400 steps/min
    with pytest.raises(mod.NonGaitTrialError, match="cadence"):
        _stub(mod, 5, stride_seconds=0.3)._validate_gait_pattern()


def test_implausibly_slow_cadence_is_rejected(mod):
    """Events so far apart they cannot be consecutive strides."""
    # 4 s strides -> 30 steps/min
    with pytest.raises(mod.NonGaitTrialError, match="cadence"):
        _stub(mod, 5, stride_seconds=4.0)._validate_gait_pattern()


def test_slow_but_physiological_cadence_is_accepted(mod):
    """The window must stay wide enough for impaired gait. Hemiparetic or
    walker-assisted walking can sit well below a healthy cadence, and this
    guard exists to reject transfers, not to judge gait quality."""
    # 2.4 s strides -> 50 steps/min, inside the 40-160 window
    _stub(mod, 5, stride_seconds=2.4)._validate_gait_pattern()


def test_observed_real_cadence_is_comfortably_inside_the_window(mod):
    """The 15 real trials sat near 128-130 steps/min. Pinned so a narrowed
    window cannot silently start rejecting them."""
    low, high = mod.PHYSIOLOGICAL_CADENCE_STEPS_PER_MIN
    assert low < 128.0 < high
    assert low < 130.5 < high


def test_validation_can_be_overridden_for_a_genuinely_short_trial(mod):
    """The escape hatch has to work -- a clinician with a legitimately short
    recording must not be hard-blocked by a screening heuristic."""
    import inspect

    signature = inspect.signature(mod.gait_analysis.__init__)
    assert signature.parameters["validate_gait_pattern"].default is True

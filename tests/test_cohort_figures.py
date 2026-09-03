"""Tests for cohort_figures.py -- the cohort report's six panels.

Two kinds here, and the split is deliberate.

The pure helpers decide what a reader sees: which participant is which colour,
what order the rows come in, and whether two converging labels stay legible.
Those are pinned properly, because a wrong answer there is silent -- a figure
with two labels on top of each other still renders, and a participant whose
colour moved between figure 1 and figure 2 still looks like a valid chart.

The six `figure_*` functions are smoke-tested only. What they draw is a design
question that a test cannot referee; what a test can catch is the thing that
actually breaks them, which is a missing key or a degenerate input reaching
matplotlib. Each is run over a fixture shaped like `cohort_scores.py`'s real
output and asserted to produce a non-empty file.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def figs():
    spec = importlib.util.spec_from_file_location(
        "cohort_figures_under_test", REPO_ROOT / "cohort_figures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(participant, side, gdi, delta_v=1.0):
    """One leg, shaped like cohort_scores.py's rows."""
    return {
        "participant": participant, "side": side, "gdi": gdi, "gdi_sd": 3.0,
        "n_strides": 40, "n_trials": 5, "delta_v": delta_v, "delta_v_z": 0.5,
        "v_ucm": 2.0, "v_ort": 1.0, "phases_with_synergy": 3, "n_phases": 4,
    }


@pytest.fixture
def rows():
    return [
        _row("AA", "right", 92.0, 1.4), _row("AA", "left", 90.0, 1.2),
        _row("BB", "right", 85.0, 1.0), _row("BB", "left", 83.0, 0.9),
        _row("CC", "right", 78.0, 0.7), _row("CC", "left", 76.0, 0.6),
    ]


@pytest.fixture
def order(figs, rows):
    return figs.participant_order(rows)


# -- participant_order ------------------------------------------------------


def test_participants_are_ordered_by_cohort_gdi_best_first(figs, rows):
    assert figs.participant_order(rows) == ["AA", "BB", "CC"]


def test_a_participants_limbs_are_averaged_into_one_rank(figs):
    """One row per participant, not per leg. A participant with one strong limb
    and one weak one must rank on the pair, or the order silently depends on
    which leg was listed first."""
    rows = [_row("HIGH", "right", 100.0), _row("HIGH", "left", 40.0),
            _row("MID", "right", 71.0), _row("MID", "left", 71.0)]

    # HIGH averages 70.0, below MID's 71.0, despite owning the best single leg.
    assert figs.participant_order(rows) == ["MID", "HIGH"]


def test_the_order_is_stable_across_figures(figs, rows):
    """Every panel shares one order so a reader comparing two figures is
    comparing the same rows in the same places."""
    shuffled = list(reversed(rows))

    assert figs.participant_order(rows) == figs.participant_order(shuffled)


# -- colours_for ------------------------------------------------------------


def test_each_participant_gets_a_distinct_palette_slot(figs):
    colours = figs.colours_for(["AA", "BB", "CC"])

    assert len(set(colours.values())) == 3
    assert all(c in figs.SERIES for c in colours.values())


def test_colour_follows_rank_not_name(figs):
    """Assigned by cohort rank, so the same participant keeps its colour across
    every figure built from one order."""
    assert figs.colours_for(["AA", "BB"])["AA"] == figs.SERIES[0]
    assert figs.colours_for(["BB", "AA"])["AA"] == figs.SERIES[1]


def test_a_seventh_participant_wraps_rather_than_inventing_a_hue(figs):
    """The palette is validated at six. Wrapping is a visible collision a
    reader can notice; a generated seventh hue is an invisible one that may sit
    anywhere in colour space."""
    order = [f"P{i}" for i in range(7)]

    colours = figs.colours_for(order)

    assert colours["P6"] == colours["P0"]
    assert len(set(colours.values())) == 6


# -- _nudge_labels ----------------------------------------------------------


def test_labels_that_already_clear_the_gap_are_left_alone(figs):
    assert figs._nudge_labels([0.0, 10.0, 20.0], 5.0) == [0.0, 10.0, 20.0]


def test_overlapping_labels_are_pushed_to_the_minimum_gap(figs):
    result = figs._nudge_labels([0.0, 1.0, 2.0], 5.0)

    gaps = np.diff(sorted(result))
    assert all(gap >= 5.0 - 1e-9 for gap in gaps)


def test_nudging_preserves_which_label_is_above_which(figs):
    """The label has to stay next to its own line. Reordering while spreading
    would attach a name to a neighbour's curve, which is worse than overlap
    because it is not visibly wrong."""
    positions = [3.0, 1.0, 2.0]

    result = figs._nudge_labels(positions, 10.0)

    # Ranking of the inputs must survive into the outputs.
    assert np.argsort(positions).tolist() == np.argsort(result).tolist()


def test_identical_positions_are_still_separated(figs):
    result = figs._nudge_labels([5.0, 5.0, 5.0], 2.0)

    assert sorted(result) == pytest.approx([5.0, 7.0, 9.0])


# -- _label_offset ----------------------------------------------------------


def test_a_single_point_falls_back_to_up_and_right(figs):
    assert figs._label_offset([_row("AA", "right", 90.0)]) == (11, 6)


def test_coincident_limbs_fall_back_rather_than_dividing_by_zero(figs):
    """Two limbs at the same coordinates give a zero-length line with no
    normal. The fallback is what stops a nan reaching the annotation."""
    pair = [_row("AA", "right", 90.0, 1.0), _row("AA", "left", 90.0, 1.0)]

    assert figs._label_offset(pair) == (11, 6)


def test_the_offset_is_perpendicular_to_the_line_joining_the_limbs(figs):
    """Offsetting along that line would land the label on one of the two
    points it is naming."""
    pair = [_row("AA", "right", 80.0, 1.0), _row("AA", "left", 100.0, 1.0)]

    dx, dy = figs._label_offset(pair)

    # The limbs differ in GDI only, so the joining line is horizontal and the
    # offset must be vertical.
    assert dx == pytest.approx(0.0, abs=1e-9)
    assert abs(dy) == pytest.approx(15.0)


def test_the_offset_keeps_its_requested_length(figs):
    pair = [_row("AA", "right", 80.0, 0.8), _row("AA", "left", 95.0, 1.3)]

    dx, dy = figs._label_offset(pair, distance=25.0)

    assert float(np.hypot(dx, dy)) == pytest.approx(25.0)


# -- the six panels ---------------------------------------------------------


def _sessions(order):
    """Shaped like cohort_scores.py's per-session payload."""
    return [
        {
            "participant": name,
            "synergy": {
                side: {"per_phase": {"delta_v": list(np.linspace(0.2, 1.4, 101))}}
                for side in ("right", "left")
            },
            "by_trial": {
                side: {f"T-{i:03d}": 88.0 + i for i in range(1, 6)}
                for side in ("right", "left")
            },
        }
        for name in order
    ]


@pytest.fixture
def summary():
    return {
        "gdi_vs_delta_v": {"r": 0.62, "p": 0.04, "rho": 0.58, "rho_p": 0.06,
                           "n": 6},
        "gdi_vs_delta_v_participant": {"r": 0.71, "p": 0.11, "rho": 0.70,
                                       "rho_p": 0.12, "n": 3},
    }


def test_every_panel_renders_from_a_realistic_payload(figs, rows, order,
                                                      summary, tmp_path):
    """One assertion per panel: it runs to a file over data shaped the way
    cohort_scores.py emits it. A KeyError here is the failure mode that
    actually happens when the scoring payload changes shape."""
    sessions = _sessions(order)
    built = {
        "gdi": lambda p: figs.figure_gdi(rows, order, p),
        "synergy": lambda p: figs.figure_synergy(rows, order, p),
        "comparison": lambda p: figs.figure_comparison(rows, order, summary, p),
        "cycle": lambda p: figs.figure_cycle(sessions, order, p),
        "trial_order": lambda p: figs.figure_trial_order(sessions, order, p),
        "variance": lambda p: figs.figure_variance(rows, order, p),
    }

    for name, build in built.items():
        path = tmp_path / f"{name}.png"
        build(path)
        assert path.exists() and path.stat().st_size > 0, (
            f"figure_{name} produced no output"
        )


def test_a_panel_survives_a_participant_with_no_synergy_index(figs, order,
                                                              tmp_path):
    """A session whose OpenSim model would not load has GDI but no index. The
    cohort figure must draw the rest rather than fail the whole report."""
    sessions = _sessions(order)
    sessions[0]["synergy"] = {}

    path = tmp_path / "cycle.png"
    figs.figure_cycle(sessions, order, path)

    assert path.exists() and path.stat().st_size > 0


def test_a_panel_survives_a_leg_with_no_delta_v(figs, rows, order, tmp_path):
    """`delta_v` is None whenever the index could not be computed. It reaches
    the synergy panel directly."""
    rows = [dict(row) for row in rows]
    rows[0]["delta_v"] = None

    path = tmp_path / "synergy.png"
    figs.figure_synergy(rows, order, path)

    assert path.exists() and path.stat().st_size > 0

"""Tests figure_theme.py, and the cross-surface agreement it exists to enforce.

The defect this module was built for was not a shade being slightly off. It
was that `gait_event_picker_ui.py` drew the right leg warm and the left leg
cool, while `cohort_figures.py` drew the right side blue and the left side
orange -- so blue meant *left* in the window where a clinician picks gait
events and *right* in the figures those events end up in. Four files each
owning a private palette is what made that possible, and no test could have
caught it while the four palettes shared no code.

So the tests that matter here are the agreement ones: the same limb is the
same colour everywhere, and the hues that mean a limb are not reused to mean
something else. The rest -- that a hex string is a hex string -- is cheap and
included, but it is not what this file is for.

Loads modules by path per this repo's convention (see
tests/test_report_export.py).
"""
import importlib.util
import os
import re

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(REPO_ROOT, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def theme():
    return _load("figure_theme_under_test", "figure_theme.py")


@pytest.fixture(scope="module")
def picker_ui():
    # Imports its siblings by plain name, so the repo root has to be
    # importable -- the same thing clinician_gui._ensure_repo_root_importable
    # does before loading it.
    import sys
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    return _load("picker_ui_for_theme_test", "gait_event_picker_ui.py")


@pytest.fixture(scope="module")
def cohort():
    return _load("cohort_figures_for_theme_test", "cohort_figures.py")


# ---------------------------------------------------------------------------
# The agreement the module exists to enforce.
# ---------------------------------------------------------------------------

def test_a_limb_is_the_same_colour_in_the_picker_and_the_cohort_figures(
        theme, picker_ui, cohort):
    """The regression. Before 2026-09-04 blue meant left in one and right in
    the other."""
    assert cohort.SIDE_COLOUR["right"] == theme.LIMB["right"]
    assert cohort.SIDE_COLOUR["left"] == theme.LIMB["left"]

    # The picker encodes limb in the hue and event kind in the marker, so the
    # heel-strike colour is the limb colour outright.
    assert picker_ui.EVENT_STYLE["rHS"]["color"] == theme.LIMB["right"]
    assert picker_ui.EVENT_STYLE["lHS"]["color"] == theme.LIMB["left"]


def test_every_figure_module_reads_the_same_palette_object(
        theme, picker_ui, cohort):
    """Not merely equal values -- the same source. Two files that happen to
    agree today are exactly what drifted apart before."""
    assert picker_ui.EVENT_STYLE is not None
    assert picker_ui.figure_theme.LIMB == theme.LIMB
    assert list(cohort.SERIES) == list(theme.SERIES)


def test_the_subspace_colours_are_not_limb_colours(theme):
    """A hue that means 'right limb' in five figures must not mean
    'uncontrolled manifold' in the sixth -- cohort_figures.py's argument, and
    the reason a limb cannot be violet."""
    assert theme.V_UCM not in theme.LIMB.values()
    assert theme.V_ORT not in theme.LIMB.values()
    assert theme.V_UCM != theme.V_ORT


def test_limb_is_never_distinguishable_by_colour_alone(theme):
    """Blue and orange separate well, but the rule is redundant encoding, so
    linestyle and marker must differ too."""
    right = theme.limb_style("right")
    left = theme.limb_style("left")
    assert right["color"] != left["color"]
    assert right["linestyle"] != left["linestyle"]
    assert right["marker"] != left["marker"]


def test_event_kinds_share_the_limb_family_and_differ_by_marker(picker_ui):
    """Hue is the limb, marker is the event. A heel strike and a toe off on
    one leg are the same family and different shapes -- which is the
    relationship they actually have, and which four unrelated hues did not
    encode at all."""
    style = picker_ui.EVENT_STYLE
    assert style["rHS"]["marker"] != style["rTO"]["marker"]
    assert style["lHS"]["marker"] != style["lTO"]["marker"]
    # The heel strike of one leg must not be confusable with the other leg's.
    assert style["rHS"]["color"] != style["lHS"]["color"]
    assert style["rTO"]["color"] != style["lTO"]["color"]


def test_the_normative_band_uses_the_semantic_tiers_not_its_own_greens(theme):
    """A GDI band is a confidence statement in the same language as the
    per-segment tiers, so it is drawn in those tokens rather than a fifth
    green invented for one figure."""
    colours = [band["color"] for band in theme.NORMATIVE_BAND]
    assert theme.TIER["high"]["bg"] in colours
    assert theme.TIER["medium"]["bg"] in colours
    assert theme.NORMATIVE_MEAN_LINE == theme.TIER["high"]["fg"]


def test_the_tiers_match_the_gui_widget_colours(theme):
    """clinician_gui.TIER_COLORS and this table are two readers of one
    DESIGN.md row. A chip in the window and a band in the PDF that disagree
    would be the same class of defect as the limb inversion."""
    gui = _load("clinician_gui_for_theme_test", "clinician_gui.py")
    for tier, values in theme.TIER.items():
        matching = [v for v in gui.TIER_COLORS.values()
                    if v.get("bg") == values["bg"]]
        assert matching, f"tier {tier} bg {values['bg']} is not in the GUI's table"


# ---------------------------------------------------------------------------
# Shape and defensiveness.
# ---------------------------------------------------------------------------

def test_every_declared_colour_is_a_hex_triplet(theme):
    singles = [theme.ACCENT, theme.ACCENT_DARK, theme.BACKGROUND,
               theme.SURFACE, theme.SURFACE_2, theme.BORDER, theme.INK,
               theme.INK_2, theme.GRID, theme.BASELINE, theme.ZERO_LINE,
               theme.V_UCM, theme.V_ORT, theme.NORMATIVE_MEAN_LINE]
    groups = (list(theme.SERIES) + list(theme.LIMB.values())
              + list(theme.LIMB_TINT.values())
              + [band["color"] for band in theme.NORMATIVE_BAND]
              + [v for tier in theme.TIER.values() for v in tier.values()]
              + [style["color"] for style in theme.EVENT_STYLE.values()])
    for value in singles + groups:
        assert HEX.match(value), f"{value!r} is not a #rrggbb triplet"


def test_series_colours_are_distinct(theme):
    assert len(set(theme.SERIES)) == len(theme.SERIES)


def test_limb_style_accepts_both_spellings_this_repo_uses(theme):
    """'right'/'left' in the reports, 'r'/'l' in the gait code. A KeyError on
    the short one would be a needless trap."""
    assert theme.limb_style("r") == theme.limb_style("right")
    assert theme.limb_style("l") == theme.limb_style("left")


def test_limb_style_refuses_an_unknown_limb_by_name(theme):
    with pytest.raises(ValueError, match="unknown limb"):
        theme.limb_style("middle")


def test_limb_style_overrides_do_not_mutate_the_shared_table(theme):
    """It returns a copy: a caller passing marker='x' must not repaint every
    other figure in the process."""
    before = dict(theme.LIMB_STYLE["right"])
    theme.limb_style("right", marker="x", color="#000000")
    assert theme.LIMB_STYLE["right"] == before


def test_series_color_wraps_rather_than_raising(theme):
    assert theme.series_color(0) == theme.SERIES[0]
    assert theme.series_color(len(theme.SERIES)) == theme.SERIES[0]


def test_style_axis_leaves_the_axis_usable_and_below_the_data(theme):
    from matplotlib.figure import Figure
    axis = Figure().add_subplot(111)
    returned = theme.style_axis(axis)

    assert returned is axis
    assert axis.get_axisbelow() is True
    assert not axis.spines["top"].get_visible()
    assert not axis.spines["right"].get_visible()


def test_background_traces_never_borrow_a_limb_hue(theme):
    """The picker draws two curves per panel. While they used matplotlib's
    default cycle they were C0 blue and C1 orange -- so the left leg's own
    panel carried a curve in the colour that means "right limb" everywhere
    else. Traces are what an operator picks *against*; colour belongs to the
    marks being placed."""
    limb_hues = set(theme.LIMB.values()) | set(theme.LIMB_TINT.values())
    for trace in theme.TRACE:
        assert trace["color"] not in limb_hues
    # And the two traces on one panel are told apart without colour alone.
    assert theme.TRACE[0]["linestyle"] != theme.TRACE[1]["linestyle"]


def test_the_picker_actually_applies_the_neutral_traces(picker_ui, theme):
    """The rule is only worth having if the drawing code follows it."""
    import math
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from gait_event_picker import GaitEventPicker

    n = 120

    class _Motion:
        n_rows = n
        name = "trace_colour_trial"
        signals = {name: [math.sin(i / 9.0) for i in range(n)]
                   for name in ("r_calc", "r_toe", "l_calc", "l_toe")}

        def time_at(self, frame):
            return frame / 60.0

    model = picker_ui.EventPickerModel(GaitEventPicker(_Motion()))
    figure = Figure(figsize=(8, 5), dpi=72)
    FigureCanvasAgg(figure)
    window = picker_ui.build_picker_view(model, figure)

    limb_hues = set(theme.LIMB.values()) | set(theme.LIMB_TINT.values())
    trace_colours = {t["color"] for t in theme.TRACE}
    for axis in window.axes:
        # Two signal traces per panel, drawn before the marker artists.
        for line in axis.lines[:2]:
            colour = line.get_color()
            assert colour not in limb_hues, (
                f"a background trace is drawn in {colour}, which means a limb")
            assert colour in trace_colours

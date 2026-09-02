"""Tests for gdi_reference.py -- regenerating a GDI normative reference.

Cohort data is synthetic. What these pin is that the construction is
self-consistent, that the checks distinguish an arithmetic identity from a
real validation, and that a written reference is loadable by gdi.py.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ref():
    return _load("gdi_reference_under_test", "gdi_reference.py")


@pytest.fixture(scope="module")
def gdi():
    return _load("gdi_for_reference_tests", "gdi.py")


@pytest.fixture
def cohort():
    """A synthetic control cohort: 459 canonical rows, 80 gait cycles.

    Deliberately low-rank plus small noise, because that is what real gait
    data is -- 15 components capture 98.7% of the real pooled control matrix.
    A cohort of pure isotropic noise behaves completely differently under
    held-out validation (see the overfitting test below), so a realistic
    structure matters here rather than being cosmetic.
    """
    rng = np.random.default_rng(7)
    loadings = rng.normal(size=(459, 6))
    scores = rng.normal(size=(6, 80))
    return 50.0 + loadings @ scores * 5.0 + rng.normal(size=(459, 80)) * 0.2


# -- the self-check is an identity, not a validation -----------------------


def test_the_defining_cohort_scores_exactly_100_and_10(ref, cohort):
    """By construction: the constants are that cohort's own log-distance mean
    and SD. Worth asserting as arithmetic."""
    reference = ref.build_reference(cohort, n_components=10)

    check = ref.self_consistency(reference, cohort)

    assert check["mean"] == pytest.approx(100.0)
    assert check["sd"] == pytest.approx(10.0)


def test_the_self_check_passes_even_for_a_meaningless_basis(ref, cohort):
    """The point of the docstring's warning, pinned. A random orthonormal
    basis also scores its own cohort at exactly 100/10, so this check cannot
    tell a good reference from a worthless one."""
    rng = np.random.default_rng(0)
    random_basis = np.linalg.qr(rng.normal(size=(459, 10)))[0]
    reference = ref.build_reference(cohort, n_components=10)
    reference["basis"] = random_basis
    projected = random_basis.T @ cohort
    reference["control_mean"] = projected.mean(axis=1)
    distances = np.log(np.linalg.norm(
        projected - reference["control_mean"][:, None], axis=0))
    reference["ln_control_mean"] = float(distances.mean())
    reference["ln_control_sd"] = float(distances.std(ddof=0))

    check = ref.self_consistency(reference, cohort)

    assert check["mean"] == pytest.approx(100.0)
    assert check["sd"] == pytest.approx(10.0)


def test_held_out_controls_land_near_100(ref, cohort):
    """The real check: build on part of the cohort, score the rest. On data
    with genuine low-rank structure, unseen controls still land near 100 --
    which is what the real pooled cohort does (held-out mean 100.18)."""
    report = ref.held_out_report(cohort, n_components=10, folds=5)

    assert report["n_held_out"] == cohort.shape[1]
    assert report["mean"] == pytest.approx(100.0, abs=5.0)
    assert report["sd"] == pytest.approx(10.0, abs=5.0)


def test_held_out_validation_detects_an_overfit_reference(ref):
    """The check has teeth. A cohort with no shared structure gives a basis
    that describes only the cycles that built it; held-out cycles then project
    much closer to the mean and score far above 100. The self-check would
    still report a flawless 100/10 on the same reference."""
    rng = np.random.default_rng(3)
    noise_cohort = rng.normal(size=(459, 80))

    report = ref.held_out_report(noise_cohort, n_components=10, folds=5)
    reference = ref.build_reference(noise_cohort, n_components=10)
    self_check = ref.self_consistency(reference, noise_cohort)

    assert report["mean"] > 120.0            # nowhere near 100
    assert self_check["mean"] == pytest.approx(100.0)   # yet this still passes


def test_held_out_needs_enough_cycles_to_split(ref):
    with pytest.raises(ValueError, match="folds"):
        ref.held_out_report(np.ones((459, 4)), n_components=2, folds=5)


# -- component selection is explicit ---------------------------------------


def test_component_count_must_be_chosen_not_defaulted(ref):
    """The archived matrices kept 14, 15, 26, 27, 28, 30, 31 and 34 across
    variants, so this was tuned. Neither silently defaulting nor accepting
    both criteria at once is acceptable."""
    singular = np.array([10.0, 5.0, 1.0])

    with pytest.raises(ValueError, match="exactly one"):
        ref.choose_components(singular)
    with pytest.raises(ValueError, match="exactly one"):
        ref.choose_components(singular, n_components=2, variance=0.9)


def test_variance_criterion_returns_the_count_that_reaches_it(ref):
    singular = np.array([10.0, 1.0, 1.0])  # energies 100, 1, 1

    n, captured = ref.choose_components(singular, variance=0.98)

    assert n == 1
    assert captured == pytest.approx(100 / 102)


def test_captured_variance_is_always_reported(ref, cohort):
    reference = ref.build_reference(cohort, n_components=10)

    assert 0.0 < reference["variance_captured"] <= 1.0
    assert reference["n_components"] == 10


# -- input validation ------------------------------------------------------


def test_a_matrix_with_reduced_rows_is_rejected(ref, tmp_path, gdi):
    """A 306-row file cannot be used as a cohort input: which variables were
    dropped is not recoverable from the row count."""
    path = tmp_path / "pooled.csv"
    np.savetxt(path, np.ones((306, 20)), delimiter=",")

    with pytest.raises(ValueError, match="459"):
        ref.load_pooled_matrix(path, gdi)


def test_non_finite_cohort_values_are_rejected(ref, tmp_path, gdi):
    """An SVD over NaNs yields a basis of NaNs that fails silently later."""
    data = np.ones((459, 20))
    data[0, 0] = np.nan
    path = tmp_path / "pooled.csv"
    np.savetxt(path, data, delimiter=",")

    with pytest.raises(ValueError, match="non-finite"):
        ref.load_pooled_matrix(path, gdi)


def test_rows_are_selected_for_a_reduced_feature_set(ref, tmp_path, gdi):
    path = tmp_path / "pooled.csv"
    np.savetxt(path, np.arange(459 * 6).reshape(459, 6).astype(float),
               delimiter=",")

    selected = ref.load_pooled_matrix(path, gdi, gdi.REDUCED6)

    assert selected.shape == (306, 6)


def test_a_single_cycle_cohort_cannot_define_a_norm(ref):
    with pytest.raises(ValueError, match="undefined"):
        ref.build_reference(np.ones((459, 1)), n_components=1)


# -- what gets written -----------------------------------------------------


def test_the_written_reference_loads_back_through_gdi(ref, gdi, cohort, tmp_path):
    """The round trip that matters: what this writes must be what
    gdi.load_gdi_reference expects, under the filenames it looks for."""
    selected = cohort[gdi.canonical_row_indices(gdi.REDUCED6), :]
    reference = ref.build_reference(selected, n_components=12)

    ref.write_reference(reference, tmp_path, gdi.REDUCED6, gdi)
    # check_digest=False: a reference regenerated at a different component
    # count is deliberately not the one REDUCED6's shipped constants belong
    # to, and load_gdi_reference refuses that pairing by design. The round
    # trip under test is the file layout, not the calibration.
    loaded = gdi.load_gdi_reference(tmp_path, gdi.REDUCED6, check_digest=False)

    assert loaded["matrix"].shape == (12, 306)
    assert loaded["control_mean"].shape == (12,)
    assert np.allclose(loaded["matrix"], reference["basis"].T)


def test_the_sidecar_records_what_the_archived_files_could_not(ref, gdi, cohort,
                                                              tmp_path):
    """A bare matrix on disk carries no record of cohort, component count or
    constants -- which is how 4.443685139 ended up attached to nothing."""
    selected = cohort[gdi.canonical_row_indices(gdi.REDUCED6), :]
    reference = ref.build_reference(selected, n_components=12)

    _, _, sidecar = ref.write_reference(reference, tmp_path, gdi.REDUCED6, gdi)
    recorded = json.loads(sidecar.read_text(encoding="utf-8"))

    assert recorded["feature_set"] == "reduced6"
    assert recorded["n_components"] == 12
    assert recorded["n_control_cycles"] == cohort.shape[1]
    assert recorded["ln_control_mean"] == pytest.approx(
        reference["ln_control_mean"])
    assert "not comparable" in recorded["note"]


def test_a_reference_cannot_be_written_under_the_wrong_feature_set(ref, gdi,
                                                                  cohort,
                                                                  tmp_path):
    """The mismatch that broke GDI in the first place, refused at write time
    rather than discovered at score time."""
    selected = cohort[gdi.canonical_row_indices(gdi.REDUCED6), :]
    reference = ref.build_reference(selected, n_components=12)

    with pytest.raises(ValueError, match="306"):
        ref.write_reference(reference, tmp_path, gdi.REDUCED5, gdi)


# -- the score path agrees with gdi.py -------------------------------------


def test_scores_match_gdi_compute_for_the_same_reference(ref, gdi, cohort,
                                                         tmp_path):
    """score_against exists so the builder can validate without a round trip;
    it must not drift from the real scoring code."""
    selected = cohort[gdi.canonical_row_indices(gdi.REDUCED6), :]
    built = ref.build_reference(selected, n_components=12)
    ref.write_reference(built, tmp_path, gdi.REDUCED6, gdi)

    scoring_set = gdi.GdiFeatureSet(
        name="reduced6_scored", features=gdi.REDUCED6.features,
        matrix_filename=gdi.REDUCED6.matrix_filename,
        control_filename=gdi.REDUCED6.control_filename,
        ln_control_mean=built["ln_control_mean"],
        ln_control_sd=built["ln_control_sd"],
    )
    loaded = gdi.load_gdi_reference(tmp_path, scoring_set)

    ours = ref.score_against(built, selected[:, :3])
    theirs = [gdi.compute_gdi(selected[:, i], loaded, scoring_set)
              for i in range(3)]

    assert ours == pytest.approx(theirs)

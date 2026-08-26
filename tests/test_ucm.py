"""Tests for ucm.py -- UCM (uncontrolled manifold) variance decomposition.

Built test-first. Every case here is analytically checkable by construction,
because on real gait data a subtly wrong decomposition produces Delta-V values
indistinguishable from correct ones.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "ucm.py"


@pytest.fixture(scope="module")
def ucm():
    spec = importlib.util.spec_from_file_location("ucm_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_nullspace_dimension_is_dof_minus_task_rank(ucm):
    """The uncontrolled manifold is null(J): 18 joint DOFs constrained by a
    3-dimensional task leaves 15 directions the task is blind to."""
    jacobian = np.zeros((3, 18))
    jacobian[0, 0] = jacobian[1, 1] = jacobian[2, 2] = 1.0

    basis = ucm.nullspace_basis(jacobian)

    assert basis.shape == (18, 15)


def test_nullspace_basis_is_orthonormal_and_annihilates_the_jacobian(ucm):
    """Projection onto the manifold is only meaningful if the basis is
    orthonormal; if J@basis were non-zero the 'uncontrolled' directions would
    still move the task variable."""
    rng = np.random.default_rng(0)
    jacobian = rng.normal(size=(3, 10))

    basis = ucm.nullspace_basis(jacobian)

    assert np.allclose(basis.T @ basis, np.eye(basis.shape[1]), atol=1e-10)
    assert np.allclose(jacobian @ basis, 0.0, atol=1e-10)


def test_rank_deficient_jacobian_yields_a_larger_manifold(ucm):
    """A phase where the task loses sensitivity to a direction. Assuming full
    rank instead of measuring it would mis-split the subspaces here."""
    jacobian = np.zeros((3, 10))
    jacobian[0, 0] = 1.0
    jacobian[1, 1] = 1.0
    jacobian[2] = jacobian[0] * 2.0          # linearly dependent on row 0

    basis = ucm.nullspace_basis(jacobian)

    assert basis.shape[1] == 8               # 10 DOF - rank 2


def _jacobian_first_three(n_dof=18):
    """Task variable depends only on DOFs 0,1,2 -- so those span ORT and the
    remaining DOFs span the uncontrolled manifold."""
    jacobian = np.zeros((3, n_dof))
    jacobian[0, 0] = jacobian[1, 1] = jacobian[2, 2] = 1.0
    return jacobian


def test_variance_only_in_manifold_directions_gives_zero_orthogonal_variance(ucm):
    """Strides differing solely in a DOF the task is blind to: all variance
    lies in the UCM, none of it moves the task variable."""
    deviations = np.zeros((6, 18))
    deviations[:, 5] = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5]   # DOF 5 is in null(J)

    result = ucm.decompose_deviations(deviations, _jacobian_first_three())

    assert result["v_ort"] == pytest.approx(0.0, abs=1e-12)
    assert result["v_ucm"] > 0


def test_variance_only_in_constrained_directions_gives_zero_manifold_variance(ucm):
    """The mirror case: strides differing solely in a DOF the task fully
    constrains. Every bit of variation moves the task variable."""
    deviations = np.zeros((6, 18))
    deviations[:, 0] = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5]   # DOF 0 is in ORT

    result = ucm.decompose_deviations(deviations, _jacobian_first_three())

    assert result["v_ucm"] == pytest.approx(0.0, abs=1e-12)
    assert result["v_ort"] > 0


def test_components_partition_the_total_variance_exactly(ucm):
    """UCM and ORT must account for all of it -- taking the orthogonal part as
    a remainder rather than projecting twice is what guarantees this."""
    rng = np.random.default_rng(3)
    deviations = rng.normal(size=(20, 12))

    r = ucm.decompose_deviations(deviations, rng.normal(size=(3, 12)))
    summed = r["v_ucm"] * r["dim_ucm"] + r["v_ort"] * r["dim_ort"]

    assert summed == pytest.approx(r["v_tot"] * (r["dim_ucm"] + r["dim_ort"]))


def test_variance_is_normalised_per_degree_of_freedom(ucm):
    """Without per-DOF normalisation the larger subspace wins on dimension
    alone. Dimensions must be UNEQUAL for this to discriminate: with 15 UCM
    directions against 3 orthogonal ones, isotropic noise puts ~5x the raw sum
    of squares in the UCM, and only the per-DOF division makes them match.
    (An earlier version of this test used 3 and 3, where dropping the
    normalisation divides both sides identically and goes undetected.)"""
    rng = np.random.default_rng(7)
    deviations = rng.normal(size=(4000, 18))

    r = ucm.decompose_deviations(deviations, _jacobian_first_three(n_dof=18))

    assert r["dim_ucm"] == 15 and r["dim_ort"] == 3
    assert r["v_ucm"] == pytest.approx(r["v_ort"], rel=0.10)


def test_a_single_stride_is_rejected(ucm):
    """One stride carries no across-stride variance. Dividing by n-1 = 0 would
    otherwise produce inf or nan and look like a computed result."""
    with pytest.raises(ValueError, match="at least 2 strides"):
        ucm.decompose_deviations(np.zeros((1, 18)), _jacobian_first_three())


def test_a_task_constraining_every_dof_reports_an_empty_manifold(ucm):
    """If the task fixes all DOFs there is nothing uncontrolled, so there is no
    synergy to measure. That has to be said, not returned as zero."""
    with pytest.raises(ValueError, match="uncontrolled manifold is empty"):
        ucm.decompose_deviations(np.zeros((5, 4)), np.eye(4))


def test_synergy_index_is_positive_when_manifold_variance_dominates(ucm):
    """Delta-V > 0 is the definition of a synergy: more variance per DOF
    inside the uncontrolled manifold than outside it."""
    assert ucm.synergy_index(v_ucm=3.0, v_ort=1.0, v_tot=2.0) > 0


def test_synergy_index_is_negative_when_orthogonal_variance_dominates(ucm):
    assert ucm.synergy_index(v_ucm=1.0, v_ort=3.0, v_tot=2.0) < 0


def test_synergy_index_follows_the_stated_formula(ucm):
    """Conventions vary across the literature, so the exact one used here is
    pinned: (V_UCM - V_ORT) / V_TOT, all per-DOF normalised."""
    assert ucm.synergy_index(v_ucm=3.0, v_ort=1.0, v_tot=2.0) == pytest.approx(1.0)


def test_zero_total_variance_gives_nan_not_a_fake_zero(ucm):
    """Identical strides say nothing about synergy. Returning 0.0 would read
    as 'measured, and there is none'."""
    assert np.isnan(ucm.synergy_index(v_ucm=0.0, v_ort=0.0, v_tot=0.0))


def test_z_transform_is_zero_at_zero_and_monotonic(ucm):
    """Delta-V is bounded, so averaging it raw across gait phases compresses
    values near the bounds and biases the mean. The z-transform fixes that and
    must preserve sign and ordering."""
    assert ucm.synergy_index_z(0.0, dim_ucm=15, dim_ort=3) == pytest.approx(0.0)
    assert ucm.synergy_index_z(0.5, 15, 3) < ucm.synergy_index_z(1.0, 15, 3)
    assert ucm.synergy_index_z(-0.5, 15, 3) < 0


def test_z_transform_stays_finite_at_the_bounds(ucm):
    """Delta-V can legitimately sit at its theoretical bound; returning inf
    there would poison every downstream average of the cycle."""
    bound = (15 + 3) / 15
    assert np.isfinite(ucm.synergy_index_z(bound, 15, 3))
    assert np.isfinite(ucm.synergy_index_z(-bound, 15, 3))


def test_finite_difference_matches_a_known_analytic_jacobian(ucm):
    """The task function reaches this code through a physics engine, so the
    Jacobian is numerical. Pin it against a case with a hand-computable
    answer."""
    def task(q):
        return np.array([q[0] ** 2 + q[1], 3.0 * q[2]])

    point = np.array([2.0, -1.0, 0.5])
    expected = np.array([[2 * point[0], 1.0, 0.0],
                         [0.0, 0.0, 3.0]])

    jacobian = ucm.finite_difference_jacobian(task, point, step=1e-5)

    assert jacobian.shape == (2, 3)
    assert np.allclose(jacobian, expected, atol=1e-6)


def test_finite_difference_is_central_not_forward(ucm):
    """Central differences are exact for a quadratic; forward differences carry
    an O(h) error. This distinguishes the two, which matters because the task
    function's own numerical noise makes the O(h^2) error worth having."""
    def task(q):
        return np.array([q[0] ** 2])

    jacobian = ucm.finite_difference_jacobian(task, np.array([1.0]), step=1e-3)

    assert jacobian[0, 0] == pytest.approx(2.0, abs=1e-9)


def test_analyse_phase_centres_the_data_itself(ucm):
    """Callers pass raw joint angles, not deviations. Adding a constant offset
    to every stride must not change the answer -- if it does, the mean is not
    being removed."""
    rng = np.random.default_rng(5)
    raw = rng.normal(size=(10, 18))
    jacobian = _jacobian_first_three()

    a = ucm.analyse_phase(raw, jacobian)
    b = ucm.analyse_phase(raw + 100.0, jacobian)

    assert a["v_ucm"] == pytest.approx(b["v_ucm"])
    assert a["delta_v"] == pytest.approx(b["delta_v"])


def test_analyse_cycle_requests_a_jacobian_for_every_phase(ucm):
    """The Jacobian linearises the task about that phase's mean joint
    configuration. Reusing one across the cycle would be wrong everywhere the
    configuration moves -- which in gait is everywhere."""
    seen = []

    def jacobian_fn(mean_configuration, phase_index):
        seen.append(phase_index)
        return _jacobian_first_three(n_dof=mean_configuration.size)

    rng = np.random.default_rng(1)
    cycles = rng.normal(size=(5, 8, 18))       # 5 phases, 8 strides, 18 DOF

    phases = ucm.analyse_cycle(cycles, jacobian_fn)

    assert seen == [0, 1, 2, 3, 4]
    assert len(phases) == 5
    assert all(p["dim_ucm"] == 15 for p in phases)


def test_analyse_cycle_rejects_a_two_dimensional_array(ucm):
    """A (strides, dof) array silently interpreted as (phases, strides) would
    decompose nonsense."""
    with pytest.raises(ValueError, match=r"n_phases, n_strides, n_dof"):
        ucm.analyse_cycle(np.zeros((5, 18)), lambda q, i: _jacobian_first_three())


def test_summary_averages_delta_v_in_z_space(ucm):
    """Averaging bounded Delta-V directly biases the mean; the summary must
    average the z-transformed values."""
    rng = np.random.default_rng(11)
    phases = ucm.analyse_cycle(rng.normal(size=(4, 10, 18)),
                               lambda q, i: _jacobian_first_three())

    summary = ucm.summarise_cycle(phases)

    assert summary["n_phases"] == 4
    assert summary["n_strides"] == 10
    assert summary["dim_ucm"] == 15 and summary["dim_ort"] == 3
    assert np.isfinite(summary["mean_delta_v_z"])
    expected = np.mean([p["delta_v_z"] for p in phases])
    assert summary["mean_delta_v_z"] == pytest.approx(expected)

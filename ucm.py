"""Uncontrolled Manifold (UCM) variance decomposition.

Built test-first 2026-08-25. Nothing of this kind existed in this repository
or its history -- see VENDORING.md. **The formulation is a documented default
chosen here, not a reproduction of any prior analysis.** Treat the output as
"a synergy index", not "the lab's synergy index", until the intended task
variable is confirmed.

Method (Scholz & Schoner 1999). At each phase of the normalised gait cycle:
take the mean joint configuration, linearise the task function there, split
joint space into the nullspace of that Jacobian (the uncontrolled manifold --
directions the task is blind to) and its complement, project each stride's
deviation into both, and compare variance PER DEGREE OF FREEDOM. More variance
per DOF inside the manifold than outside means the joints co-vary to stabilise
the task variable: a synergy.

The projection math here knows nothing about OpenSim, gait, or centre of mass.
The task function enters only through `analyse_cycle`'s `jacobian_fn`
callable, so switching from pelvis-relative COM to foot placement or anything
else is a one-argument change with no edit to the nullspace or variance code.
That seam is deliberate: the task variable is an open domain question.

Intended default formulation:

  * q -- the 18 clean DOFs: pelvis orientation, lumbar, and both legs.
    Excludes the pinned root translations, the toe joints (frozen in BOTH
    methodologies), and the upper limb (saturated against its joint bounds in
    the IMU pipeline). See VENDORING.md's batch-inspection section.
  * x -- centre of mass relative to the pelvis. Chosen over global COM
    precisely so the two methodologies stay comparable: global COM exists for
    the OpenCap pipeline but NOT for the IMU one, whose root translation is
    pinned. Picking it would make the comparison this work exists to support
    impossible.

Units are the export's own -- angles in degrees, COM in metres -- so the
Jacobian is m/deg and variances are deg^2 per DOF. Consistent within an
analysis, but not comparable to a study working in radians; convert before
quoting alongside published values.
"""
import numpy as np


def nullspace_basis(jacobian, rcond=1e-10):
    """Orthonormal basis for null(J) -- the uncontrolled manifold."""
    jacobian = np.atleast_2d(np.asarray(jacobian, dtype=float))
    _u, singular, vh = np.linalg.svd(jacobian)
    tolerance = rcond * (singular[0] if singular.size else 0.0)
    rank = int(np.sum(singular > tolerance))
    return vh[rank:].T


def decompose_deviations(deviations, jacobian, rcond=1e-10):
    """Split mean-centred stride deviations into UCM and orthogonal parts.

    Variances are normalised per degree of freedom: the two subspaces almost
    always have different dimensions, so raw sums of squares would favour
    whichever is larger regardless of any real structure.
    """
    deviations = np.atleast_2d(np.asarray(deviations, dtype=float))
    n_strides, n_dof = deviations.shape
    if n_strides < 2:
        raise ValueError(
            "UCM needs at least 2 strides to have any variance to decompose; "
            f"got {n_strides}."
        )

    basis = nullspace_basis(jacobian, rcond=rcond)
    dim_ucm = basis.shape[1]
    dim_ort = n_dof - dim_ucm
    if dim_ucm == 0:
        raise ValueError(
            "The task Jacobian constrains every one of the "
            f"{n_dof} joint DOFs, so the uncontrolled manifold is empty and "
            "there is no synergy to measure."
        )

    # Project onto the UCM, then take the remainder rather than building a
    # second basis -- guarantees the parts sum to the total exactly.
    parallel = deviations @ basis @ basis.T
    orthogonal = deviations - parallel

    denominator = n_strides - 1
    ss_ucm = float(np.sum(parallel ** 2))
    ss_ort = float(np.sum(orthogonal ** 2))
    return {
        "v_ucm": ss_ucm / (dim_ucm * denominator),
        "v_ort": ss_ort / (dim_ort * denominator) if dim_ort > 0 else 0.0,
        "v_tot": (ss_ucm + ss_ort) / (n_dof * denominator),
        "dim_ucm": dim_ucm,
        "dim_ort": dim_ort,
        "n_strides": n_strides,
    }


def synergy_index(v_ucm, v_ort, v_tot):
    """Delta-V = (V_UCM - V_ORT) / V_TOT, all per-DOF normalised.

    Positive means joint variation is channelled into directions that leave
    the task variable alone -- a synergy. Negative means it is pushing the
    task variable around. Conventions differ in the literature over the
    denominator and the normalisation, so this one is stated explicitly rather
    than assumed, and can be checked against whatever prior analysis exists.
    """
    if v_tot <= 1e-12:
        return float("nan")
    return (v_ucm - v_ort) / v_tot


def synergy_index_z(delta_v, dim_ucm, dim_ort):
    """Fisher-style z-transform of Delta-V, so phases can be averaged.

    The bounds follow from the per-DOF normalisation: Delta-V is largest when
    all variance sits in the UCM and smallest when all of it is orthogonal.
    Values are clipped just inside the bound so a legitimately extremal phase
    yields a large finite number rather than an infinity that would propagate
    through every subsequent average.
    """
    n_dof = dim_ucm + dim_ort
    upper = n_dof / dim_ucm
    lower = n_dof / dim_ort if dim_ort > 0 else np.inf
    bound = min(upper, lower)
    clipped = float(np.clip(delta_v, -bound * (1 - 1e-9), bound * (1 - 1e-9)))
    return 0.5 * float(np.log((bound + clipped) / (bound - clipped)))


def finite_difference_jacobian(task_fn, configuration, step=1e-4):
    """Central-difference Jacobian of an arbitrary task function f(q).

    Central rather than forward: the error is O(step^2) instead of O(step),
    which matters because these task functions are evaluated through a physics
    engine whose output carries its own numerical noise.
    """
    configuration = np.asarray(configuration, dtype=float)
    baseline = np.asarray(task_fn(configuration), dtype=float)
    jacobian = np.zeros((baseline.size, configuration.size))
    for index in range(configuration.size):
        forward = configuration.copy()
        backward = configuration.copy()
        forward[index] += step
        backward[index] -= step
        jacobian[:, index] = (
            np.asarray(task_fn(forward), dtype=float)
            - np.asarray(task_fn(backward), dtype=float)
        ) / (2.0 * step)
    return jacobian


def analyse_phase(joint_matrix, jacobian, rcond=1e-10):
    """Full decomposition at one phase of the cycle.

    `joint_matrix` is (n_strides, n_dof) of RAW joint angles -- the mean is
    removed here so callers never have to centre their own data.
    """
    joint_matrix = np.atleast_2d(np.asarray(joint_matrix, dtype=float))
    mean_configuration = joint_matrix.mean(axis=0)
    result = decompose_deviations(
        joint_matrix - mean_configuration, jacobian, rcond=rcond
    )
    result["delta_v"] = synergy_index(
        result["v_ucm"], result["v_ort"], result["v_tot"]
    )
    result["delta_v_z"] = synergy_index_z(
        result["delta_v"], result["dim_ucm"], result["dim_ort"]
    )
    result["mean_configuration"] = mean_configuration
    return result


def analyse_cycle(joint_cycles, jacobian_fn, rcond=1e-10):
    """Decompose every phase of the normalised gait cycle.

    `joint_cycles` is (n_phases, n_strides, n_dof).
    `jacobian_fn(mean_configuration, phase_index) -> (task_dim, n_dof)`.

    The Jacobian is requested per phase because it is a linearisation about
    that phase's mean configuration. This callable is the single seam where
    the task function f(q) is defined -- swapping pelvis-relative COM for foot
    placement, or anything else, changes nothing else in this module.
    """
    joint_cycles = np.asarray(joint_cycles, dtype=float)
    if joint_cycles.ndim != 3:
        raise ValueError(
            "joint_cycles must be (n_phases, n_strides, n_dof); got shape "
            f"{joint_cycles.shape}."
        )
    phases = []
    for phase_index in range(joint_cycles.shape[0]):
        matrix = joint_cycles[phase_index]
        jacobian = jacobian_fn(matrix.mean(axis=0), phase_index)
        phases.append(analyse_phase(matrix, jacobian, rcond=rcond))
    return phases


def summarise_cycle(phases):
    """Cycle-level summary.

    Delta-V is averaged in z-space, because it is bounded and averaging it
    directly compresses extremal phases and biases the mean.
    """
    if not phases:
        raise ValueError("no phases to summarise")
    z_values = np.array([p["delta_v_z"] for p in phases], dtype=float)
    finite = z_values[np.isfinite(z_values)]
    return {
        "n_phases": len(phases),
        "n_strides": phases[0]["n_strides"],
        "dim_ucm": phases[0]["dim_ucm"],
        "dim_ort": phases[0]["dim_ort"],
        "mean_v_ucm": float(np.mean([p["v_ucm"] for p in phases])),
        "mean_v_ort": float(np.mean([p["v_ort"] for p in phases])),
        "mean_delta_v": float(np.mean([p["delta_v"] for p in phases])),
        "mean_delta_v_z": float(np.mean(finite)) if finite.size else float("nan"),
        "phases_with_synergy": int(np.sum([p["delta_v"] > 0 for p in phases])),
    }

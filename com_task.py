"""Pelvis-relative centre-of-mass task function for the UCM decomposition.

This is the seam ucm.analyse_cycle's `jacobian_fn` plugs into. Swapping the
task variable -- to foot placement, or anything else -- means writing another
class with the same two methods and changing nothing in ucm.py.

The model is injected rather than constructed here, so the maths is testable
without OpenSim (which lives in the opencap-processing env and has no pytest)
and so a different backend can be substituted.
"""
import numpy as np

# Zeroed on every evaluation so the COM is expressed relative to the pelvis
# rather than in global space. This matches what the curve export computes
# (com minus the matching pelvis translation) and, more importantly, keeps the
# task variable computable by BOTH methodologies: global COM exists for the
# OpenCap pipeline but not for the IMU one, whose root translation is pinned.
PELVIS_TRANSLATIONS = ("pelvis_tx", "pelvis_ty", "pelvis_tz")


class PelvisRelativeComTask:
    """x = f(q): centre of mass relative to the pelvis, from a joint pose."""

    def __init__(self, model, coordinate_names, step_degrees=1e-3):
        self.model = model
        self.coordinate_names = list(coordinate_names)
        self.step_degrees = step_degrees

    def evaluate(self, joint_angles_degrees):
        """Set the pose and read the COM.

        Curve exports are in degrees; OpenSim coordinates are radians. The
        conversion happens here, once -- getting it wrong scales every
        Jacobian entry by 57.3 while leaving the output entirely plausible.
        """
        angles = np.asarray(joint_angles_degrees, dtype=float).ravel()
        if angles.size != len(self.coordinate_names):
            raise ValueError(
                f"expected {len(self.coordinate_names)} coordinate values to match "
                f"{self.coordinate_names[:3]}...; got {angles.size}. Zipping a "
                "short vector would set only the leading coordinates and leave "
                "the rest stale -- a wrong pose with a plausible COM."
            )
        for name, value in zip(self.coordinate_names, angles):
            self.model.set_coordinate(name, np.deg2rad(value))
        for name in PELVIS_TRANSLATIONS:
            self.model.set_coordinate(name, 0.0)
        return np.asarray(self.model.center_of_mass(), dtype=float)

    def jacobian(self, joint_angles_degrees):
        """d(COM)/d(q), shape (3, n_dof), by central differences in degrees."""
        import ucm  # local import: keeps this module usable standalone
        return ucm.finite_difference_jacobian(
            self.evaluate, joint_angles_degrees, step=self.step_degrees
        )

    def as_jacobian_fn(self):
        """Adapter to ucm.analyse_cycle's expected callable signature."""
        return lambda mean_configuration, phase_index: self.jacobian(mean_configuration)


class OpenSimModel:
    """Adapter exposing an OpenSim model through the two methods
    PelvisRelativeComTask needs.

    Deliberately thin, and deliberately NOT unit-tested: `opensim` lives in the
    opencap-processing conda env, which has no pytest, so it cannot be
    imported by the suite. All the logic that can be tested -- unit
    conversion, pelvis zeroing, the finite-difference Jacobian -- lives in
    PelvisRelativeComTask and is covered against an injected fake. What
    remains here is API plumbing, verified by running it against the real
    model rather than by assertion.
    """

    def __init__(self, model_path):
        import opensim  # local: never importable in the test interpreter

        self.opensim = opensim
        self.model = opensim.Model(str(model_path))
        self.state = self.model.initSystem()
        self._coordinates = {
            self.model.getCoordinateSet().get(i).getName():
                self.model.getCoordinateSet().get(i)
            for i in range(self.model.getCoordinateSet().getSize())
        }

    def coordinate_names(self):
        return list(self._coordinates)

    def set_coordinate(self, name, value_radians):
        coordinate = self._coordinates.get(name)
        if coordinate is None:
            # Silently ignoring an unknown name would hold that DOF at its
            # default while the caller believed it was being driven.
            raise KeyError(
                f"{name!r} is not a coordinate of this model. Available include: "
                f"{sorted(self._coordinates)[:6]}..."
            )
        # enforceContraints=False: assembly on every one of the ~114 evaluations
        # a single Jacobian needs would dominate the runtime, and the poses come
        # from an IK solution that already satisfies the constraints.
        coordinate.setValue(self.state, float(value_radians), False)

    def center_of_mass(self):
        self.model.realizePosition(self.state)
        position = self.model.calcMassCenterPosition(self.state)
        return np.array([position.get(0), position.get(1), position.get(2)])

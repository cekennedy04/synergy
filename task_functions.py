"""Task variables x = f(q) for the UCM decomposition.

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


class _PelvisRelativeTask:
    """Shared machinery: set the pose, zero the pelvis, read something.

    Subclasses differ only in `_read`. Everything risky -- the degrees to
    radians conversion, the pelvis zeroing, the length check -- lives here
    once, so a new task variable cannot reintroduce those bugs.
    """

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
        return self._to_pelvis_frame(np.asarray(self._read(), dtype=float))

    def _to_pelvis_frame(self, position):
        """Express a ground-frame position in the pelvis's own frame.

        Zeroing pelvis_tx/ty/tz removes the root TRANSLATION but not its
        ORIENTATION, and until 2026-09-03 that was the whole of "pelvis
        relative": the task read the global centre of mass and called it done.
        So rotating the root moved the task variable. Measured on the real
        model, sweeping pelvis_rotation from 0 to 180 degrees with every
        relative joint held fixed moved x by 0.166 m, and pelvis_rotation
        carried the 4th-largest Jacobian column of the 18 coordinates.

        For a pelvis-relative task that dependence must be exactly zero: a
        rigid whole-body rotation cannot change where the centre of mass sits
        relative to the pelvis. It is an invariance, not an approximation, so
        it has to hold at every configuration rather than near a mean.

        What it cost: absolute lab-frame heading became a real input to the
        task variable, so pooling strides across trials that pointed in
        slightly different directions injected heading differences into the
        UCM decomposition. See VENDORING.md, "The synergy index was measuring
        where the subject was pointed".

        A model that does not expose its pelvis pose is left alone rather than
        guessed at -- the fake models in the test suite that only implement
        center_of_mass() still work, and only the assertion about root
        invariance needs the fuller protocol.
        """
        rotation = getattr(self.model, "pelvis_rotation_matrix", None)
        origin = getattr(self.model, "pelvis_origin", None)
        if rotation is None or origin is None:
            return position
        return np.asarray(rotation()).T @ (position - np.asarray(origin()))

    def _read(self):
        raise NotImplementedError

    def jacobian(self, joint_angles_degrees):
        """d(COM)/d(q), shape (3, n_dof), by central differences in degrees."""
        import ucm  # local import: keeps this module usable standalone
        return ucm.finite_difference_jacobian(
            self.evaluate, joint_angles_degrees, step=self.step_degrees
        )

    def as_jacobian_fn(self):
        """Adapter to ucm.analyse_cycle's expected callable signature."""
        return lambda mean_configuration, phase_index: self.jacobian(mean_configuration)


class PelvisRelativeComTask(_PelvisRelativeTask):
    """x = centre of mass relative to the pelvis.

    Chosen for cross-methodology comparability, but note the consequence
    measured 2026-08-25: this task is ~80x more sensitive to proximal than to
    distal DOFs, so ankle and subtalar variance lands in the uncontrolled
    manifold almost by construction and inflates Delta-V. See VENDORING.md.
    """

    def _read(self):
        return self.model.center_of_mass()


class FootPlacementTask(_PelvisRelativeTask):
    """x = position of a foot body relative to the pelvis.

    The counterpart to PelvisRelativeComTask, and the reason the task function
    is a swappable seam: foot placement depends strongly on the distal joints
    that COM is nearly blind to, so distal measurement noise should move out
    of V_UCM and into V_ORT. That makes it a direct test of whether the
    methodology difference seen under the COM task is an artifact.
    """

    def __init__(self, model, coordinate_names, body_name="calcn_r", step_degrees=1e-3):
        super().__init__(model, coordinate_names, step_degrees=step_degrees)
        self.body_name = body_name

    def _read(self):
        return self.model.body_position(self.body_name)


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

    def body_position(self, body_name):
        """Origin of a body in ground. With the pelvis translation zeroed by
        the task, this is the body's position relative to the pelvis."""
        self.model.realizePosition(self.state)
        body = self.model.getBodySet().get(body_name)
        position = body.getPositionInGround(self.state)
        return np.array([position.get(0), position.get(1), position.get(2)])

    def center_of_mass(self):
        self.model.realizePosition(self.state)
        position = self.model.calcMassCenterPosition(self.state)
        return np.array([position.get(0), position.get(1), position.get(2)])

    def pelvis_rotation_matrix(self):
        """The pelvis's orientation in ground, as a 3x3.

        Together with pelvis_origin this is what makes a task genuinely
        pelvis-relative rather than merely pelvis-centred -- see
        _PelvisRelativeTask._to_pelvis_frame for what went wrong without it.
        """
        self.model.realizePosition(self.state)
        rotation = self.model.getBodySet().get("pelvis").getTransformInGround(self.state).R()
        return np.array([[rotation.get(i, j) for j in range(3)] for i in range(3)])

    def pelvis_origin(self):
        """The pelvis body's origin in ground.

        Not always the zero vector even with pelvis_tx/ty/tz zeroed: the
        ground-pelvis joint can carry a fixed offset, and the model's own
        answer is cheaper to read than to reason about.
        """
        self.model.realizePosition(self.state)
        position = self.model.getBodySet().get("pelvis").getPositionInGround(self.state)
        return np.array([position.get(0), position.get(1), position.get(2)])

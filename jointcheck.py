"""Three-way mean +/- SD comparison figure, ported from jointcheck.m.

The supervisor's version overlays Xsens against OpenCap across 26 coordinates
plus 3 centre-of-mass channels, with stdshade-style ribbons. This adds the
third pipeline -- XtoO direct remapping -- so the figure shows both that the
routes agree where all three are valid, and the specific places where direct
remapping supplies kinematics inverse kinematics cannot reach.
"""
import numpy as np

# The 26 coordinates jointcheck.m plots: the full set minus pelvis
# translations, mtp and pro_sup. matrix_general.m strips exactly these, and it
# is the same exclusion set our own variance analysis arrived at independently.
COMPARISON_COORDINATES = (
    "pelvis_tilt", "pelvis_list", "pelvis_rotation",
    "hip_flexion_r", "hip_adduction_r", "hip_rotation_r",
    "knee_angle_r", "ankle_angle_r", "subtalar_angle_r",
    "hip_flexion_l", "hip_adduction_l", "hip_rotation_l",
    "knee_angle_l", "ankle_angle_l", "subtalar_angle_l",
    "lumbar_extension", "lumbar_bending", "lumbar_rotation",
    "arm_flex_r", "arm_add_r", "arm_rot_r", "elbow_flex_r",
    "arm_flex_l", "arm_add_l", "arm_rot_l", "elbow_flex_l",
)

COM_CHANNELS = ("comx", "comy", "comz")

# Blue / green / orange, following the supervisor's blue-vs-red convention
# while staying distinguishable in greyscale and for the common colour-vision
# deficiencies.
PIPELINE_COLOURS = {
    "OpenSim IK": "#1f6fb4",
    "XtoO direct": "#2e8b57",
    "OpenCap video": "#d95f02",
}


def ribbon(curves):
    """Mean and +/-1 SD envelope across strides.

    `curves` is (n_strides, n_points). Population SD (ddof=0), matching
    MATLAB's default in stdshade -- a reader comparing band widths against the
    supervisor's existing figures needs the same convention.
    """
    curves = np.atleast_2d(np.asarray(curves, dtype=float))
    if curves.shape[0] == 0:
        raise ValueError("no strides to summarise")
    mean = curves.mean(axis=0)
    deviation = curves.std(axis=0)          # ddof=0
    return mean, mean - deviation, mean + deviation


def plot_comparison(datasets, coordinates, columns=5, panel_size=(3.0, 2.2),
                    percent_axis=True):
    """Grid of per-coordinate panels, one ribbon per pipeline.

    `datasets` maps a pipeline label to {coordinate: (n_strides, n_points)}.
    A pipeline lacking a coordinate is simply not drawn on that panel --
    plotting zeros instead would read as a measured flatline, which is exactly
    the confusion this figure exists to resolve for mtp and the arms.
    """
    import matplotlib.pyplot as plt

    coordinates = list(coordinates)
    rows = int(np.ceil(len(coordinates) / columns))
    figure, axes = plt.subplots(
        rows, columns,
        figsize=(panel_size[0] * columns, panel_size[1] * rows),
        squeeze=False,
    )
    flat = [ax for row in axes for ax in row]

    for axis, name in zip(flat, coordinates):
        axis.set_title(name, fontsize=9)
        for label, series in datasets.items():
            curves = series.get(name)
            if curves is None or len(curves) == 0:
                continue
            mean, lower, upper = ribbon(curves)
            x = np.linspace(0, 100, len(mean)) if percent_axis else np.arange(len(mean))
            colour = PIPELINE_COLOURS.get(label)
            axis.fill_between(x, lower, upper, alpha=0.25, color=colour, linewidth=0)
            axis.plot(x, mean, color=colour, linewidth=1.3, label=label)
        axis.tick_params(labelsize=7)

    for axis in flat[len(coordinates):]:
        axis.axis("off")

    handles, labels = flat[0].get_legend_handles_labels()
    if handles:
        figure.legend(handles, labels, loc="lower center", ncol=len(handles), fontsize=9)
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    return figure

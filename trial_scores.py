"""Gait Deviation Index and synergy index for one trial's curve exports.

Built 2026-09-01, so the clinician report can carry both alongside the
spatiotemporal metrics it already shows.

**GDI is unambiguous; the synergy index is not.** GDI has an agreed feature
set (`reduced6`) and a regenerated control reference, so one number per side
is a complete answer. The synergy index does not have that property: measured
2026-08-25, the ranking between methodologies *reverses* depending on the task
variable (pelvis-relative COM gives Xsens 0.407 against OpenCap 0.803; foot
placement gives 0.475 against 0.179). Same strides, same joints, same code.

So a bare synergy number on a clinical report would be misleading. Every value
this module returns carries the formulation that produced it, and
`format_for_report` puts that on the page rather than in a footnote. If the
task variable is ever settled upstream, change the default here and the label
follows automatically.

Both are computed from the exported curve matrices rather than re-run from the
model, so they cannot disagree with the curves the same report plots.
"""
import importlib.util
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent

# The 18 DOFs ucm.py documents as its intended configuration: pelvis
# orientation, lumbar, and both legs. Excludes the pinned root translations,
# the toe joints (frozen in both methodologies) and the upper limb (saturated
# against its bounds on the IMU route).
UCM_COORDINATES = (
    "pelvis_tilt", "pelvis_list", "pelvis_rotation",
    "hip_flexion_r", "hip_adduction_r", "hip_rotation_r",
    "knee_angle_r", "ankle_angle_r", "subtalar_angle_r",
    "hip_flexion_l", "hip_adduction_l", "hip_rotation_l",
    "knee_angle_l", "ankle_angle_l", "subtalar_angle_l",
    "lumbar_extension", "lumbar_bending", "lumbar_rotation",
)

# ucm.py's own default. Named here so the report can state it.
DEFAULT_TASK_VARIABLE = "pelvis-relative centre of mass"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gdi_for_curves(curve_matrix_paths, reference_dir, feature_set=None,
                   gdi=None, curves=None):
    """GDI per side from this trial's exported curve matrices.

    `curve_matrix_paths` maps "right"/"left" to the trial's curve CSV. Returns
    a per-side mean over that trial's strides, plus the stride count, so a
    single-stride trial is visibly weaker evidence than a six-stride one.
    """
    gdi = gdi or _load("_gdi_for_scores", "gdi.py")
    curves = curves or _load("_curves_for_scores", "curve_features.py")
    feature_set = gdi.get_feature_set(feature_set or gdi.DEFAULT_FEATURE_SET)
    reference = gdi.load_gdi_reference(reference_dir, feature_set)
    row_order = curves.exported_row_order()

    scores = {}
    for side, path in curve_matrix_paths.items():
        if not path or not Path(path).is_file():
            scores[side] = None
            continue
        matrix = curves.load_curve_matrix(path, row_order)
        per_stride = curves.score_curves(matrix, side, reference, feature_set,
                                         gdi, row_order)
        scores[side] = {
            "mean": float(np.mean(per_stride)),
            "sd": float(np.std(per_stride)) if per_stride.size > 1 else None,
            "n_strides": int(per_stride.size),
        }
    scores["feature_set"] = feature_set.name
    return scores


def joint_cycles_from_curves(curve_matrix_path, coordinates=UCM_COORDINATES,
                             curves=None, row_order=None):
    """(n_phases, n_strides, n_dof) for ucm.analyse_cycle.

    Read from the same exported matrix the report plots, so the decomposition
    describes the curves the clinician is looking at.
    """
    curves = curves or _load("_curves_for_ucm", "curve_features.py")
    row_order = row_order or curves.exported_row_order()
    matrix = curves.load_curve_matrix(curve_matrix_path, row_order)

    missing = [c for c in coordinates if c not in row_order]
    if missing:
        raise KeyError(
            f"the export has no {missing}; the UCM configuration cannot be "
            "assembled from it.")

    blocks = [curves.coordinate_block(matrix, name, row_order)
              for name in coordinates]
    # (n_dof, n_phases, n_strides) -> (n_phases, n_strides, n_dof)
    return np.transpose(np.stack(blocks, axis=0), (1, 2, 0))


def synergy_for_trial(curve_matrix_path, model_path, coordinates=UCM_COORDINATES,
                      task="com", ucm=None, task_functions=None, curves=None):
    """Synergy index for one trial, with the formulation that produced it.

    Returns None for `value` when it cannot be computed rather than a
    placeholder: a zero or a NaN in a report table is indistinguishable from a
    real result, which is the same reason `methodology_comparison` refused to
    emit one.
    """
    ucm = ucm or _load("_ucm_for_scores", "ucm.py")
    task_functions = task_functions or _load("_tasks_for_scores",
                                             "task_functions.py")
    joint_cycles = joint_cycles_from_curves(curve_matrix_path, coordinates,
                                            curves)

    model = task_functions.OpenSimModel(model_path)
    if task == "com":
        task_object = task_functions.PelvisRelativeComTask(model, coordinates)
        label = DEFAULT_TASK_VARIABLE
    elif task == "foot":
        task_object = task_functions.FootPlacementTask(model, coordinates)
        label = "foot placement (calcn_r) relative to pelvis"
    else:
        raise ValueError(f"unknown task variable {task!r}; expected 'com' or 'foot'")

    def jacobian_fn(mean_configuration, _phase_index):
        return task_object.jacobian(mean_configuration)

    phases = ucm.analyse_cycle(joint_cycles, jacobian_fn)
    summary = ucm.summarise_cycle(phases)
    summary["task_variable"] = label
    summary["n_dof"] = len(coordinates)
    return summary


def _cell(value, units="", reason=None):
    """One metric cell in the shape report_formatting.format_metric_value wants.

    Counts are passed as strings: the formatter applies "%.2f" to any int or
    float, so a stride count would otherwise print as "4.00".

    An absent value carries its own reason rather than a number, because a
    zero in that table is indistinguishable from a computed result.
    """
    if value is None:
        return {"available": False, "status": reason if reason is not None
                else "not available"}
    return {"available": True, "status": "ok", "value": value, "units": units}


# A single space, not "": report_formatting does `status or "not available"`,
# and an empty string is falsy, so it would fall through to the very text this
# is trying to avoid. "not available" implies something was attempted and
# failed, where these columns simply do not apply to the row.
_BLANK_TEXT = " "


def _blank():
    """A cell for a column that does not apply to this row."""
    return {"available": False, "status": _BLANK_TEXT, "reason": _BLANK_TEXT}


def format_for_report(gdi_scores=None, synergy=None):
    """Rows for the report's metrics table.

    Each cell matches the nested shape the table renderer expects --
    {"available", "status", "value", "units"} -- so this needs no change to
    report_export or report_formatting.

    The synergy row names its task variable, because a bare number would be
    misleading: the ranking between methodologies reverses with that choice,
    so the figure is only interpretable alongside it.
    """
    rows = {}
    if gdi_scores:
        right, left = gdi_scores.get("right"), gdi_scores.get("left")
        rows[f"GDI ({gdi_scores.get('feature_set', 'reduced6')})"] = {
            "r": _cell(None if not right else round(right["mean"], 1)),
            "l": _cell(None if not left else round(left["mean"], 1)),
            "symmetry": _blank(),
        }
        if right or left:
            # str(), not int: the formatter would render 4 as "4.00".
            rows["GDI: strides scored"] = {
                "r": _cell(None if not right else str(right["n_strides"])),
                "l": _cell(None if not left else str(left["n_strides"])),
                "symmetry": _blank(),
            }
    if synergy and synergy.get("mean_delta_v") is not None:
        rows["Synergy index (dV)"] = {
            "r": _cell(round(synergy["mean_delta_v"], 3)),
            "l": _blank(),
            "symmetry": _blank(),
        }
        rows["Synergy: task"] = {
            "r": _cell(synergy["task_variable"]),
            "l": _blank(),
            "symmetry": _blank(),
        }
        rows["Synergy: phases with dV > 0"] = {
            "r": _cell(f"{synergy['phases_with_synergy']} of {synergy['n_phases']}"),
            "l": _blank(),
            "symmetry": _blank(),
        }
        rows["Synergy: DOF (UCM / orthogonal)"] = {
            "r": _cell(f"{synergy['n_dof']} ({synergy['dim_ucm']} / {synergy['dim_ort']})"),
            "l": _blank(),
            "symmetry": _blank(),
        }
    return rows

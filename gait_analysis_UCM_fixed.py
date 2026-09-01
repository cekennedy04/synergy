"""
    ---------------------------------------------------------------------------
    OpenCap processing: gaitAnalysis.py
    ---------------------------------------------------------------------------

    Copyright 2023 Stanford University and the Authors
    
    Author(s): Antoine Falisse, Scott Uhlrich
    
    Licensed under the Apache License, Version 2.0 (the "License"); you may not
    use this file except in compliance with the License. You may obtain a copy
    of the License at http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

    ---------------------------------------------------------------------------
    Synergy edits (2026-08-20) -- fixed copy of gait_analysis_UCM.py
    ---------------------------------------------------------------------------
    This is a copy, not an in-place edit -- gait_analysis_UCM.py (the coworker's
    file, emailed 2026-08-19) is left untouched, per the same "only make copies"
    rule already applied to utils.py/utilsKinematics.py. Bugs below were found by
    an independent Codex review (2026-08-19, see VENDORING.md) and confirmed by
    reading the code directly, not just trusting the review.

    1. `sys.path.append('../')`/`'./'` were relative to the CALLER's cwd, not
       this file's location -- fragile outside the one driver script that
       happens to set cwd correctly first. Now derived from `__file__`.
    2. Two blocking `input()` call sites made batch mode (`--all-trials`) hang
       on stdin with nothing providing it: the "gait events not in order, do
       you want to enter them manually?" prompt, and `manual_steps()`'s 4
       further prompts for step/toe-off times. New `allow_manual_entry=True`
       constructor arg (default True, preserving today's interactive
       behavior) -- set False to raise a clear exception instead of blocking.
    3. `ntrims=round(seshlen/.2)-2` could be 0 or negative for a short trial,
       making `trimarray=[0.2]*ntrims` empty, so `trimarray[0]=-1` raised an
       opaque `IndexError`. Now raises a clear, descriptive exception instead.
    4. The auto-trim retry loop's only "termination" check
       (`if j==len(trimarray)-2: checkflag=self.promflag`) reassigned a
       variable to its own value -- a no-op, not a real terminating
       condition. The loop could run `trimarray[j]` past the array's end.
       Now raises a clear exception once attempts are exhausted.
    5. Auto leg-selection (`if rHS[-1] > lHS[-1]`) indexed `rHS`/`lHS` before
       checking either was non-empty -- a real `IndexError` if peak detection
       found zero heel-strikes for a leg even without an ordering problem.
       Now checks emptiness first and raises a clear exception.
    6. `compute_correlations()`'s default (`cols_to_compare=None`) resolved
       to `df1.columns` while `df1` was still an empty, just-created
       DataFrame -- so the default was always "match nothing," and
       `len(correlations)` was then 0, raising `ZeroDivisionError` on the
       very first call with no arguments. Fixed to treat `None` as "no
       filter, compare everything" instead of snapshotting an empty frame.
       Also fixed a latent bug where `corresponding_col` from a *previous*
       iteration could be reused if `col1` matched neither `_r` nor `_l`.
       The docstring's claim of "interpolating to have 101 rows" was
       corrected -- `.interpolate()` fills internal NaN gaps, it does not
       resample to a fixed row count (unlike `get_coordinates_normalized_time`
       elsewhere in this file, which genuinely does). Left the actual
       resampling behavior unchanged since `df1`/`df2` already share the same
       row count by construction here (df2's two concatenated segments
       together span the same index range as df1) -- only the comment was
       wrong, not verified to be a numeric bug, so not rewritten.
    7. Center of mass was computed twice with two different, inconsistent
       filter settings: the `comx`/`comy`/`comz` columns inserted into
       `coordinateValues` in `__init__` used a hardcoded 10 Hz low-pass,
       while `comValues()` (used internally by `compute_gait_speed`, etc.)
       used whatever `lowpass_cutoff_frequency_for_coordinate_values` the
       class was constructed with (or unfiltered, if not given) -- so the
       exported CSV's COM columns and gait speed's internal COM used
       different numbers for "the same" trajectory. Both now consistently
       use `self.lowpass_cutoff_frequency_for_coordinate_values`.
    8. `find_nearest(array, value)` (module-level-looking but defined inside
       the class) was missing `self` as its first parameter and is never
       called anywhere in this file -- dead code with a latent bug if ever
       invoked as `self.find_nearest(x)`. Marked `@staticmethod` for
       correctness; still unused.
    9. `modelName` wasn't forwarded to `kinematics.__init__` -- found while
       trying to actually instantiate this class against a session without
       a full OpenCap-downloaded metadata file (e.g. one written by
       xsens_to_opensim.py's --session-dir mode). Without it,
       kinematics.__init__ falls back to a metadata lookup that such
       sessions don't have. Not from the Codex review; found by testing.

    NOT changed here -- flagged as a driver-side integration gap, not a bug
    in this file: `fpa_r`/`fpa_l` are correctly stored as columns on
    `coordinateValues` (this file's job), but nothing in
    `Examples/gaitAnalysis-UCM.py`'s own scalar/export list actually reads
    them back out, so the foot-progression-angle computation currently has
    no effect on any reported metric or CSV. Fixing that means deciding what
    should consume `fpa_r`/`fpa_l` (a new `compute_*` scalar? added to an
    existing export list?), which is a product decision, not something to
    guess at here.
"""

import os
import sys
_this_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(_this_dir)
sys.path.append(os.path.dirname(_this_dir))

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from matplotlib import pyplot as plt

from utilsKinematics import kinematics
from gait_event_picker import GaitEventPicker


# Floor on how much trial data the auto-trim retry loop is allowed to leave
# behind before it gives up (edit #12, 2026-08-24; rationale corrected the
# same day after testing against real matched data -- see the guard in
# segment_walking's `while checkflag==0` loop).
#
# This is a DEFENSIVE FLOOR, not a fix for any observed failure. It was
# originally written believing the retry loop caused a hard native crash
# (ucrtbase 0xc0000409) seen once in a GUI session; that belief did not
# survive testing. On a real non-gait trial the loop runs to ~238 trims
# across both legs, consumes ~23.8s of a 43.5s recording, and completes
# normally. On a real walking trial (CK-001, a verified Xsens/OpenCap
# matched pair) it needs ZERO retries. The crash has never been reproduced
# and its cause remains unknown -- do not describe this constant as its fix.
#
# What the floor is genuinely for: trimend() is cumulative, and the loop's
# only other bound is len(trimarray), itself derived from trial duration
# (ntrims = round(seshlen/.2) - 2), which for a long trial authorises
# trimming away essentially the whole recording. A gait cycle is roughly 1s
# and ordering validation needs a full ipsilateral cycle with the
# contralateral events inside it, so below ~2s no further retry can succeed
# and continuing only burns CPU on data that cannot answer the question.
MIN_REMAINING_SECONDS_FOR_GAIT_DETECTION = 2.0


# ---------------------------------------------------------------------------
# Manual gait-event entry (Phase 2.3, 2026-08-31)
# ---------------------------------------------------------------------------
# The third rung of segment_walking's fallback chain: prominence escalation
# (0.3 -> 0.25 -> 0.2), then the auto-trim retry loop, then a human. Rung
# three used to be four raw input() prompts asking the operator to type gait
# event TIMES, which were then snapped to the nearest sample with
# `(np.abs(marktimf - t)).argmin()`. Two things were wrong with that:
#
#   1. A typed time is never an exact sample, so the argmin ALWAYS snapped,
#      silently, with nothing reporting which frame it landed on. An operator
#      reading a heel strike off a plot types 0.28, not 0.283339.
#      segment_walking works in indices into markerDict['time'] anyway, so the
#      index is both the natural storage and the natural output, and storing
#      it means no conversion happens at all rather than one that is merely
#      usually right.
#
#      NOT the reason, though earlier drafts of this comment said so: that
#      these files are irregularly sampled. Measured 2026-09-01 across every
#      trial in Data/ -- 77 of 77 .trc files have a single distinct dt of
#      0.016667, and the .mot files sampled the same way. The "0.016667,
#      0.017, 0.016, 0.017" figure repeated in gait_event_picker.py's and
#      motion_scrubber.py's docstrings does not describe any data in this
#      repo, and a time round-trip would in fact land on the right frame here.
#      Indices are still correct; the justification was not.
#   2. It hard-wired stdin as the only possible UI.
#
# gait_event_picker.GaitEventPicker is now the data layer: it stores row
# indices, reports (never enforces) gait ordering, and its
# as_segment_walking_events() returns exactly the (rHS, lHS, rTO, lTO)
# four-tuple in exactly the order segment_walking unpacks. The UI is supplied
# by the caller through `manual_event_provider`; the stdin prompt below is
# only the fallback, and it asks for ROW INDICES, never times.
#
# THE RETURN CONTRACT IS FIXED: `return rHS, lHS, rTO, lTO`, four values, that
# order, matching detect_gait_peaks and trimend. Edit #13 exists because
# trimend returned those four in a different order for months, putting left
# heel-strikes in the right toe-off slot and silently corrupting every
# downstream metric. Do not add a fifth return value and do not reorder.


class MarkerTimeline:
    """The trial's own frame index space, in the shape GaitEventPicker needs.

    The picker asks a "motion" for `n_rows`, `time_at(row)` and `name`.
    motion_scrubber.MotionSource satisfies that for a .mot file, but a .mot's
    rows are NOT segment_walking's index space -- segmentation indexes
    markerDict['time'], which comes from the .trc and is trimmed separately.
    Handing the picker a .mot row would put events on frames nobody chose,
    which is precisely the class of silent wrongness this file keeps finding.
    So manual entry picks against this adapter over markerDict['time'], and a
    3D scrubber driving it is responsible for mapping its own display frame to
    a row of this timeline.
    """

    def __init__(self, times, name="", signals=None):
        self.times = [float(t) for t in times]
        self.name = name
        # What detect_gait_peaks ran its peak detection on, when the caller has
        # it: name -> per-frame values. A picker UI plots these so the operator
        # sees the same evidence the automatic rung saw. Empty is fine; a UI
        # with nothing to draw is the caller's problem to report, not a reason
        # to refuse to build the timeline.
        self.signals = dict(signals) if signals else {}
        # A signal of the wrong length is a frame-space mismatch, and frames
        # are what gait events ARE here. Caught at construction with a message
        # that names the cause, rather than surfacing later as matplotlib's
        # "x and y must have same first dimension".
        for signal_name, values in self.signals.items():
            if len(values) != len(self.times):
                raise ValueError(
                    "signal '" + signal_name + "' has " + str(len(values)) +
                    " values but this timeline has " + str(len(self.times)) +
                    " frames. They must index the same frames -- a stale "
                    "signal from before trimming is the usual cause.")

    @property
    def n_rows(self):
        return len(self.times)

    def time_at(self, row):
        """The trial's own recorded time for a row, read from the file rather
        than reconstructed as start + row*dt. Every trial measured here is in
        fact uniformly sampled, so the two agree today; reading it costs
        nothing and does not have to be revisited if one ever is not."""
        if not 0 <= row < self.n_rows:
            raise IndexError(
                'row ' + str(row) + ' out of range for a trial with ' +
                str(self.n_rows) + ' frames.')
        return self.times[row]


def build_manual_picker(analysis):
    """An empty GaitEventPicker over `analysis`'s own frame index space."""
    return GaitEventPicker(
        MarkerTimeline(analysis.markerDict['time'],
                       name=getattr(analysis, 'trial_name', '') or '',
                       signals=getattr(analysis, 'eventDetectionSignals', None)))


def prompt_for_event_rows(picker, input_fn=None, output_fn=None):
    """The no-UI fallback: four prompts, ROW INDICES, not times.

    Kept deliberately joyless. It exists so an operator at a bare terminal is
    not blocked when no picker UI is wired up, not as the intended path. It
    accepts indices because that is what the picker stores; accepting times
    here would reintroduce the snapping bug the picker was built to remove.

    input_fn/output_fn default to the builtins, resolved per call rather than
    bound as default arguments -- bound defaults would capture whatever
    `input` meant at import time, which is neither patchable nor what a
    caller redirecting the terminal would expect.
    """
    input_fn = input if input_fn is None else input_fn
    output_fn = print if output_fn is None else output_fn
    last = picker.motion.n_rows - 1
    output_fn(
        'Automatic gait-event detection failed. Enter events as FRAME INDICES '
        '(whole numbers, 0-' + str(last) + '), comma separated. Leave a line '
        'blank to enter none. These are frame numbers, not times.')
    # Nothing in the pipeline ever shows an operator a frame index -- the
    # diagnostic plots are drawn only under `visualize`, which __init__ does
    # not pass -- so without this listing the prompt asks for numbers there is
    # no way to obtain. Sampled rather than dumped: a real trial runs to
    # thousands of frames.
    for line in frame_time_reference(picker.motion):
        output_fn(line)
    for event_type, label in (('rHS', 'Right heel strikes'),
                              ('rTO', 'Right toe offs'),
                              ('lHS', 'Left heel strikes'),
                              ('lTO', 'Left toe offs')):
        while True:
            raw = input_fn(label + ' [' + event_type + '] as frame indices: ')
            try:
                rows = parse_event_rows(raw, event_type, last)
            except ValueError as exc:
                # Re-prompt rather than abort. segment_walking runs from
                # gait_analysis.__init__, so raising here would tear down the
                # whole trial and discard every event already entered because
                # of one mistyped digit on the fourth prompt.
                output_fn(str(exc) + ' Please try again.')
                continue
            break
        # Parsed completely before marking, so a bad token late in a line
        # cannot leave the event half-recorded.
        for row in rows:
            picker.mark(event_type, row)
    return picker


def frame_time_reference(motion, max_lines=20):
    """A sampled frame -> time listing, so the operator can map what they see
    on an external plot of the trial to the frame numbers this prompt wants."""
    n_rows = motion.n_rows
    if n_rows == 0:
        # A trial with no frames has no events to pick. Say that, rather than
        # letting rows[-1] raise a bare IndexError out of the fallback prompt.
        return ['  (this trial has no frames, so there is nothing to pick)']
    step = max(1, -(-n_rows // max_lines))
    rows = list(range(0, n_rows, step))
    if rows[-1] != n_rows - 1:
        rows.append(n_rows - 1)
    return ['  frame {0:>6}   t = {1:.3f}s'.format(row, motion.time_at(row))
            for row in rows]


def parse_event_rows(raw, event_type, last):
    """Frame indices from one typed line. Validates without marking, so the
    caller can reject the whole line rather than record part of it."""
    rows = []
    for token in raw.split(','):
        token = token.strip()
        if not token:
            continue
        try:
            row = int(token)
        except ValueError:
            raise ValueError(
                'Could not read ' + repr(token) + ' as a frame index for ' +
                event_type + '. Frame indices are whole numbers between 0 '
                'and ' + str(last) + '; this prompt does not accept times.'
            ) from None
        if not 0 <= row <= last:
            raise ValueError(
                'Frame ' + str(row) + ' is outside this trial, which has '
                'frames 0-' + str(last) + '.')
        rows.append(row)
    return rows


def collect_manual_events(analysis):
    """Get a picked event set for `analysis`, from its UI or from stdin.

    The provider is handed a ready-made picker built over this trial's own
    frames. It may mark events on that picker and return None, or return a
    picker of its own (a set restored from disk, say). Anything else is a
    wiring mistake and is refused here rather than allowed to reach
    segmentation as an unpackable object.
    """
    picker = build_manual_picker(analysis)
    provider = getattr(analysis, 'manual_event_provider', None)
    if provider is None:
        return prompt_for_event_rows(picker)

    returned = provider(picker)
    if returned is None:
        return picker
    motion = getattr(returned, 'motion', None)
    if not hasattr(returned, 'as_segment_walking_events') or motion is None:
        raise TypeError(
            'manual_event_provider returned ' + type(returned).__name__ +
            '; it must return None (having marked events on the picker it was '
            'given) or a picker exposing as_segment_walking_events() over a '
            '.motion.')
    expected = len(analysis.markerDict['time'])
    if motion.n_rows != expected:
        # Events are frame indices, so a picker built over a different frame
        # count is pointing at frames of some other trial.
        raise ValueError(
            'manual_event_provider returned events picked over ' +
            str(motion.n_rows) + ' frames, but this trial has ' +
            str(expected) + '. Gait events are frame indices and do not '
            'transfer between trials.')
    # Frame count is not identity. Fixed-duration walk captures from one
    # participant routinely share a frame count, so a saved set restored for
    # the wrong trial would clear the check above and land events on frames
    # nobody chose. The name is what actually distinguishes them; it is only
    # enforced when both sides have one, since a provider may legitimately
    # build a picker over an unnamed motion.
    picked_name = getattr(motion, 'name', '') or ''
    this_name = getattr(analysis, 'trial_name', '') or ''
    if picked_name and this_name and picked_name != this_name:
        raise ValueError(
            'manual_event_provider returned events picked on trial ' +
            repr(picked_name) + ', but this is ' + repr(this_name) + '. They '
            'have the same frame count, which is why the name is what has to '
            'be checked.')
    return returned


def manual_steps(self):
    """Hand-picked gait events, as (rHS, lHS, rTO, lTO).

    Called from segment_walking, which unpacks exactly those four in exactly
    that order. Lifted out of segment_walking (2026-08-31) so it is reachable
    by a test at all -- nested inside that method it was unverifiable, and the
    ordering contract it carries is the one edit #13 was about.
    """
    if not self.allow_manual_entry:
        # Guards the prompts below from blocking an unattended batch run
        # (edit #2). The caller (segment_walking) already checks
        # self.allow_manual_entry before reaching here, so this only fires if
        # manual_steps is ever called directly. clinician_gui.run_batch and
        # process_participants.py both depend on this raising rather than
        # waiting on a human who is not there.
        raise Exception(
            'Automatic gait-event detection failed and manual entry is disabled '
            '(allow_manual_entry=False). Re-run with allow_manual_entry=True for '
            'an interactive session, or adjust trimming_start/trimming_end.'
        )

    if self.dflag == 0:
        picker = collect_manual_events(self)
        rHS, lHS, rTO, lTO = picker.as_segment_walking_events()

        # Reported, never enforced. detect_correct_order's cycle is what a
        # typical gait produces, but a pathological one may genuinely violate
        # it, and this project stopped hard-refusing trials on 2026-08-27. The
        # operator gets the pipeline's own verdict and the trial proceeds
        # either way.
        ok, message = picker.ordering_report()
        print(('Manually entered gait events: ' if ok
               else 'Manually entered gait events (ordering warning): ') + message)

        self.rhs = rHS
        self.lhs = lHS
        self.rto = rTO
        self.lto = lTO
        self.manualEventPicker = picker
        self.dflag = 1
    else:
        rHS = self.rhs
        lHS = self.lhs
        rTO = self.rto
        lTO = self.lto

    # Edit #13 (2026-08-24): same left/right swap as trimend -- the call site
    # unpacks `rHS,lHS,rTO,lTO = manual_steps(self)`, so hand-entered gait
    # events were being scrambled on the way out. Four values, this order.
    return rHS, lHS, rTO, lTO


class gait_analysis(kinematics):
    
    def __init__(self, session_dir, trial_name, fpa_r, fpa_l, leg='auto',
                 lowpass_cutoff_frequency_for_coordinate_values=-1,
                 n_gait_cycles=-1, gait_style='auto', trimming_start=0,
                 trimming_end=0, allow_manual_entry=True, modelName=None,
                 manual_event_provider=None):

        # Inherit init from kinematics class. modelName wasn't forwarded
        # before (edit #9, found 2026-08-19 -- not from the Codex review,
        # from actually trying to instantiate this class against a session
        # without full OpenCap-downloaded metadata): without it,
        # kinematics.__init__ falls back to utils.get_model_name_from_metadata,
        # which requires a real downloaded session's metadata file. A real
        # session written by xsens_to_opensim.py's --session-dir mode (or
        # any session missing that metadata) can't be loaded without this.
        super().__init__(
            session_dir,
            trial_name,
            modelName=modelName,
            lowpass_cutoff_frequency_for_coordinate_values=lowpass_cutoff_frequency_for_coordinate_values)

        # We might want to trim the start/end of the trial to remove bad data.
        # For example, this might be needed with HRNet during overground
        # walking, where, at the end, the subject is leaving the field of view
        # but HRNet returns relatively high confidence values. As a result,
        # the trial is not well trimmed. Here, we provide the option to
        # manually trim the start and end of the trial.
        self.trimming_start = trimming_start
        self.trimming_end = trimming_end
        self.dflag=0
        # Auto-trim instrumentation (2026-08-27). Purely observational: set
        # here, written in segment_walking, read by nothing in this class.
        # It exists because the 2026-08-24 left/right swap (edit #13) lived
        # inside trimend(), so ONLY trials that entered the auto-trim retry
        # path were corrupted by it. A trial whose events came back correctly
        # ordered at prominence 0.3/0.25/0.2 never called trimend and is
        # clean. Recording that distinction is what lets a re-run target the
        # affected trials instead of the whole archive.
        self.usedAutoTrim = False
        self.nAutoTrims = 0
        self.rhs=[]
        self.lhs=[]
        self.rto=[]
        self.lto=[]
        # self.trimflag=0
        self.promflag=0
        # allow_manual_entry=False raises instead of blocking on input() --
        # needed for unattended batch runs (see class docstring, edit #2).
        self.allow_manual_entry = allow_manual_entry
        # The UI for manual gait-event entry, supplied by the caller (Phase
        # 2.3, 2026-08-31). A callable taking a GaitEventPicker built over
        # this trial's frames; it marks events on that picker and returns
        # None, or returns a picker of its own. None means "no UI wired up",
        # which falls back to a stdin prompt for FRAME INDICES. It is read
        # only after allow_manual_entry has already been checked, so a batch
        # run cannot reach either path.
        self.manual_event_provider = manual_event_provider
        # Kept for the picker's own record, which names the trial its frame
        # indices belong to.
        self.trial_name = trial_name

        # Marker data load and filter.
        self.markerDict = self.get_marker_dict(session_dir, trial_name, 
            lowpass_cutoff_frequency = lowpass_cutoff_frequency_for_coordinate_values)

        # Coordinate values.
        self.coordinateValues = self.get_coordinate_values()
        self.coordinateValues.insert(len(self.coordinateValues.columns),"fpa_r",fpa_r)
        self.coordinateValues.insert(len(self.coordinateValues.columns),"fpa_l",fpa_l)
        
        # print(self.coordinateValues)
        # input()
        # Trim marker data and coordinate values.
        if self.trimming_start > 0:
            self.idx_trim_start = np.where(np.round(self.markerDict['time'] - self.trimming_start,6) <= 0)[0][-1]
            self.markerDict['time'] = self.markerDict['time'][self.idx_trim_start:,]
            for marker in self.markerDict['markers']:
                self.markerDict['markers'][marker] = self.markerDict['markers'][marker][self.idx_trim_start:,:]
            self.coordinateValues = self.coordinateValues.iloc[self.idx_trim_start:]
            
        if self.trimming_end > 0:
            self.idx_trim_end = np.where(np.round(self.markerDict['time'],6) <= np.round(self.markerDict['time'][-1] - self.trimming_end,6))[0][-1] + 1
            self.markerDict['time'] = self.markerDict['time'][:self.idx_trim_end,]
            for marker in self.markerDict['markers']:
                self.markerDict['markers'][marker] = self.markerDict['markers'][marker][:self.idx_trim_end,:]
            self.coordinateValues = self.coordinateValues.iloc[:self.idx_trim_end]
        
        # Segment gait cycles.
        self.gaitEvents = self.segment_walking(n_gait_cycles=n_gait_cycles,leg=leg)
        self.nGaitCycles = np.shape(self.gaitEvents['ipsilateralIdx'])[0]
        
        # Determine treadmill speed (0 if overground).
        self.treadmillSpeed,_ = self.compute_treadmill_speed(gait_style=gait_style)
        
        # Initialize variables to be lazy loaded.
        self._comValues = None
        self._R_world_to_gait = None
        
        #adding COM values to output AJB 5/14/26
        # Uses the same lowpass_cutoff_frequency_for_coordinate_values as the
        # rest of this trial's coordinate columns, not a separate hardcoded
        # value -- previously hardcoded to 10 here but unfiltered (or whatever
        # was passed to __init__) in comValues() below, so the exported CSV's
        # COM and compute_gait_speed's internal COM silently disagreed with
        # each other despite representing "the same" trajectory (edit #7).
        comm=self.get_center_of_mass_values(
            lowpass_cutoff_frequency=self.lowpass_cutoff_frequency_for_coordinate_values)
        self.coordinateValues.insert(len(self.coordinateValues.columns),"comx",comm['x'])
        self.coordinateValues.insert(len(self.coordinateValues.columns),"comy",comm['y'])
        self.coordinateValues.insert(len(self.coordinateValues.columns),"comz",comm['z'])



    # Compute COM trajectory.
    def comValues(self):
        if self._comValues is None:
            self._comValues = self.get_center_of_mass_values(
                lowpass_cutoff_frequency=self.lowpass_cutoff_frequency_for_coordinate_values)
            if self.trimming_start > 0:
                self._comValues = self._comValues.iloc[self.idx_trim_start:]            
            if self.trimming_end > 0:
                self._comValues = self._comValues.iloc[:self.idx_trim_end]
        return self._comValues
    
    # Compute gait frame.
    def R_world_to_gait(self):
        if self._R_world_to_gait is None:
            self._R_world_to_gait = self.compute_gait_frame()
        return self._R_world_to_gait
    
    def get_gait_events(self):
        
        return self.gaitEvents
    
    def compute_scalars(self,scalarNames,return_all=False):
               
        # Verify that scalarNames are methods in gait_analysis.
        method_names = [func for func in dir(self) if callable(getattr(self, func))]
        possibleMethods = [entry for entry in method_names if 'compute_' in entry]
        
        if scalarNames is None:
            print('No scalars defined, these methods are available:')
            print(*possibleMethods)
            return
        
        nonexistant_methods = [entry for entry in scalarNames if 'compute_' + entry not in method_names]
        
        if len(nonexistant_methods) > 0:
            raise Exception(str(['compute_' + a for a in nonexistant_methods]) + ' does not exist in gait_analysis class.')
        
        scalarDict = {}
        for scalarName in scalarNames:
            thisFunction = getattr(self, 'compute_' + scalarName)
            scalarDict[scalarName] = {}
            (scalarDict[scalarName]['value'],
                scalarDict[scalarName]['units']) = thisFunction(return_all=return_all)
        
        return scalarDict
    
    def compute_stride_length(self,return_all=False):
        
        leg,_ = self.get_leg()
        
        calc_position = self.markerDict['markers'][leg + '_calc_study']

        # On treadmill, the stride length is the difference in ipsilateral
        # calcaneus position at heel strike + treadmill speed * time.
        strideLengths = (
            np.linalg.norm(
                calc_position[self.gaitEvents['ipsilateralIdx'][:,:1]] - 
                calc_position[self.gaitEvents['ipsilateralIdx'][:,2:3]], axis=2) + 
                self.treadmillSpeed * np.diff(self.gaitEvents['ipsilateralTime'][:,(0,2)]))
        
        # Average across all strides.
        strideLength = np.mean(strideLengths)
        
        # Define units.
        units = 'm'
        
        if return_all:
            return strideLengths,units
        else: 
            return strideLength, units
    
    def compute_step_length(self,return_all=False):
        leg, contLeg = self.get_leg()
        step_lengths = {}
        
        step_lengths[contLeg.lower()] = (np.linalg.norm(
            self.markerDict['markers'][leg + '_calc_study'][self.gaitEvents['ipsilateralIdx'][:,:1]] - 
            self.markerDict['markers'][contLeg + '_calc_study'][self.gaitEvents['contralateralIdx'][:,1:2]], axis=2) + 
            self.treadmillSpeed * (self.gaitEvents['contralateralTime'][:,1:2] -
                                   self.gaitEvents['ipsilateralTime'][:,:1]))
        
        step_lengths[leg.lower()]  = (np.linalg.norm(
            self.markerDict['markers'][leg + '_calc_study'][self.gaitEvents['ipsilateralIdx'][:,2:]] - 
            self.markerDict['markers'][contLeg + '_calc_study'][self.gaitEvents['contralateralIdx'][:,1:2]], axis=2) + 
            self.treadmillSpeed * (-self.gaitEvents['contralateralTime'][:,1:2] +
                                   self.gaitEvents['ipsilateralTime'][:,2:]))
               
        # Average across all strides.
        step_length = {key: np.mean(values) for key, values in step_lengths.items()}
        
        # Define units.
        units = 'm'
        
        # some functions depend on having values for each step, otherwise return average
        if return_all:
            return step_lengths, units
        else:
            return step_length, units
        
    def compute_step_length_symmetry(self,return_all=False):
        step_lengths,units = self.compute_step_length(return_all=True)
        
        step_length_symmetry_all = step_lengths['r'] / step_lengths['l'] * 100
        
        # Average across strides
        step_length_symmetry = np.mean(step_length_symmetry_all)
        
        # define units 
        units = '% (R/L)'
        
        if return_all:
            return step_length_symmetry_all, units
        else:
            return step_length_symmetry, units
    
    def compute_gait_speed(self,return_all=False):
                           
        comValuesArray = np.vstack((self.comValues()['x'],self.comValues()['y'],self.comValues()['z'])).T
        gait_speeds = (
            np.linalg.norm(
                comValuesArray[self.gaitEvents['ipsilateralIdx'][:,:1]] -
                comValuesArray[self.gaitEvents['ipsilateralIdx'][:,2:3]], axis=2) /
                np.diff(self.gaitEvents['ipsilateralTime'][:,(0,2)]) + self.treadmillSpeed) 
        
        # Average across all strides.
        gait_speed = np.mean(gait_speeds)
        
        # Define units.
        units = 'm/s'
        
        if return_all:
            return gait_speeds,units
        else:
            return gait_speed, units
    
    def compute_cadence(self,return_all=False):
        
        # In steps per minute.
        cadence_all = 60*2/np.diff(self.gaitEvents['ipsilateralTime'][:,(0,2)])
        
        # Average across all strides.
        cadence = np.mean(cadence_all)
        
        # Define units.
        units = 'steps/min'
        
        if return_all:
            return cadence_all,units
        else:
            return cadence, units

    def compute_foot_progression_angle(self, return_all=False):
        # Mean foot progression angle (FPA) for the ipsilateral leg over
        # each gait cycle, in degrees. Added 2026-08-20 -- fpa_r/fpa_l are
        # computed by compute_foot_progression_angles() in
        # Examples/gaitAnalysis-UCM.py (your supervisor's own math, kept
        # completely unchanged -- see that function's docstring) and passed
        # into __init__, but until now nothing ever read them back out: not
        # a compute_* scalar, not in the exported curves CSV's column list.
        # This method is what makes the already-computed value actually
        # reach a reported metric. See VENDORING.md's 2026-08-20 FPA finding
        # for the full trace of where the value used to dead-end.
        leg = self.gaitEvents['ipsilateralLeg']
        fpaValues = self.coordinateValues['fpa_' + leg].to_numpy()

        fpaAngles = np.zeros((self.nGaitCycles,))
        for i in range(self.nGaitCycles):
            start_idx = self.gaitEvents['ipsilateralIdx'][i,0]
            end_idx = self.gaitEvents['ipsilateralIdx'][i,2]
            fpaAngles[i] = np.mean(fpaValues[start_idx:end_idx])

        # Average across all strides.
        fpaAngle = np.mean(fpaAngles)

        # Define units.
        units = 'deg'

        if return_all:
            return fpaAngles, units
        else:
            return fpaAngle, units

    def compute_treadmill_speed(self, overground_speed_threshold=0.3,
                                gait_style='auto', return_all=False):
        
        # Heuristic to determine if overground or treadmill.
        if gait_style == 'auto' or gait_style == 'treadmill':
            leg,_ = self.get_leg()
            
            foot_position = self.markerDict['markers'][leg + '_ankle_study']
            
            stanceTimeLength = np.round(np.diff(self.gaitEvents['ipsilateralIdx'][:,:2]))
            startIdx = np.round(self.gaitEvents['ipsilateralIdx'][:,:1]+.1*stanceTimeLength).astype(int)
            endIdx = np.round(self.gaitEvents['ipsilateralIdx'][:,1:2]-.3*stanceTimeLength).astype(int)
                
            # Average instantaneous velocities.
            dt = np.diff(self.markerDict['time'][:2])[0]
            treadmillSpeeds = np.zeros((self.nGaitCycles,))
            for i in range(self.nGaitCycles):
                treadmillSpeeds[i,] = np.linalg.norm(np.mean(np.diff(
                    foot_position[startIdx[i,0]:endIdx[i,0],:],axis=0),axis=0)/dt)
            
            treadmillSpeed = np.mean(treadmillSpeeds)
            
            # Overground if treadmill speed is below threshold and gait style not set to treadmill.
            if treadmillSpeed < overground_speed_threshold and not gait_style == 'treadmill':
                treadmillSpeed = 0
                treadmillSpeeds = np.zeros(self.nGaitCycles)
        
        # Overground if gait style set to overground.
        elif gait_style == 'overground':
            treadmillSpeed = 0
            treadmillSpeeds = np.zeros(self.nGaitCycles)
            
        # Define units.
        units = 'm/s'
                           
        if return_all:
            return treadmillSpeeds,units
        else:
            return treadmillSpeed, units
    
    def compute_step_width(self,return_all=False):
        
        leg,contLeg = self.get_leg()
        
        # Get ankle joint center positions.
        ankle_position_ips = (
            self.markerDict['markers'][leg + '_ankle_study'] + 
            self.markerDict['markers'][leg + '_mankle_study'])/2
        ankle_position_cont = (
            self.markerDict['markers'][contLeg + '_ankle_study'] + 
            self.markerDict['markers'][contLeg + '_mankle_study'])/2        
        
        # Find indices of 40-60% of the stance phase
        ips_stance_length = np.diff(self.gaitEvents['ipsilateralIdx'][:,(0,1)])
        cont_stance_length = (self.gaitEvents['contralateralIdx'][:,0] - 
                              self.gaitEvents['ipsilateralIdx'][:,0] +
                              self.gaitEvents['ipsilateralIdx'][:,2]-
                              self.gaitEvents['contralateralIdx'][:,1])
        
        midstanceIdx_ips = [range(self.gaitEvents['ipsilateralIdx'][i,0] + 
                                  int(np.round(.4*ips_stance_length[i])),
                                  self.gaitEvents['ipsilateralIdx'][i,0] + 
                                  int(np.round(.6*ips_stance_length[i]))) 
                                  for i in range(self.nGaitCycles)]
        
        midstanceIdx_cont = [range(np.min((self.gaitEvents['contralateralIdx'][i,1] + 
                                  int(np.round(.4*cont_stance_length[i])),
                                  self.gaitEvents['ipsilateralIdx'][i,2]-1)),
                                  np.min((self.gaitEvents['contralateralIdx'][i,1] + 
                                  int(np.round(.6*cont_stance_length[i])),
                                  self.gaitEvents['ipsilateralIdx'][i,2]))) 
                                  for i in range(self.nGaitCycles)]   
        
        ankleVector = np.zeros((self.nGaitCycles,3))
        for i in range(self.nGaitCycles):
            ankleVector[i,:] = (
                np.mean(ankle_position_cont[midstanceIdx_cont[i],:],axis=0) - 
                np.mean(ankle_position_ips[midstanceIdx_ips[i],:],axis=0))
                     
        ankleVector_inGaitFrame = np.array(
            [np.dot(ankleVector[i,:], self.R_world_to_gait()[i,:,:]) 
            for i in range(self.nGaitCycles)])
        
        # Step width is z distance.
        stepWidths = np.abs(ankleVector_inGaitFrame[:,2])
        
        # Average across all strides.
        stepWidth = np.mean(stepWidths)
        
        # Define units.
        units = 'm'
        
        if return_all:
            return stepWidths, units
        else:
            return stepWidth, units
    
    def compute_stance_time(self, return_all=False):
        
        stanceTimes = np.diff(self.gaitEvents['ipsilateralTime'][:,:2])
        
        # Average across all strides.
        stanceTime = np.mean(stanceTimes)
        
        # Define units.
        units = 's'
        
        if return_all:
            return stanceTimes, units
        else:
            return stanceTime, units
    
    def compute_swing_time(self, return_all=False):
        
        swingTimes = np.diff(self.gaitEvents['ipsilateralTime'][:,1:])
        
        # Average across all strides.
        swingTime = np.mean(swingTimes)
        
        # Define units.
        units = 's'
        
        if return_all:
            return swingTimes, units
        else:  
            return swingTime, units
    
    def compute_single_support_time(self,return_all=False):
        
        double_support_time,_ = self.compute_double_support_time(return_all=True) 

        singleSupportTimes = 100 - double_support_time    
        
        # Average across all strides.
        singleSupportTime = np.mean(singleSupportTimes)
        
        # Define units.
        units = '%'
        
        if return_all:
            return singleSupportTimes,units
        else:
            return singleSupportTime, units
        
    def compute_double_support_time(self,return_all=False):
        
        # Ipsilateral stance time - contralateral swing time.
        doubleSupportTimes = (
            (np.diff(self.gaitEvents['ipsilateralTime'][:,:2]) - 
            np.diff(self.gaitEvents['contralateralTime'][:,:2])) /
            np.diff(self.gaitEvents['ipsilateralTime'][:,(0,2)])) * 100
                            
        # Average across all strides.
        doubleSupportTime = np.mean(doubleSupportTimes)
        
        # Define units.
        units = '%'
        
        if return_all:
            return doubleSupportTimes, units
        else:
            return doubleSupportTime, units
        
    def compute_midswing_dorsiflexion_angle(self,return_all=False):
        # compute ankle dorsiflexion angle during midstance
        to_1_idx = self.gaitEvents['ipsilateralIdx'][:,1]
        hs_2_idx = self.gaitEvents['ipsilateralIdx'][:,2]
        
        # ankle markers
        leg,contLeg = self.get_leg()
        ankleVector = (self.markerDict['markers'][leg + '_ankle_study'] - 
                       self.markerDict['markers'][contLeg + '_ankle_study'])
        ankleVector_inGaitFrame = np.array(
            [np.dot(ankleVector, self.R_world_to_gait()[i,:,:]) 
              for i in range(self.nGaitCycles)])                                          
        
        swingDfAngles = np.zeros((to_1_idx.shape))
        
        for i in range(self.nGaitCycles):
            # find index within a swing phase with the smallest z distance between ankles
            idx_midSwing = np.argmin(np.abs(ankleVector_inGaitFrame[
                                     i,to_1_idx[i]:hs_2_idx[i],0]))+to_1_idx[i]
            
            swingDfAngles[i] = np.mean(self.coordinateValues['ankle_angle_' + 
                                self.gaitEvents['ipsilateralLeg']].to_numpy()[idx_midSwing])          
        
        # Average across all strides.
        swingDfAngle = np.mean(swingDfAngles)
        
        # Define units.
        units = 'deg'
        
        if return_all:
            return swingDfAngles, units
        else:
            return swingDfAngle, units
        
    def compute_midswing_ankle_heigh_dif(self,return_all=False):
        # compute vertical clearance of the swing ankle above the stance ankle
        # at the time when the ankles pass by one another
        to_1_idx = self.gaitEvents['ipsilateralIdx'][:,1]
        hs_2_idx = self.gaitEvents['ipsilateralIdx'][:,2]
        
        # ankle markers
        leg,contLeg = self.get_leg()
        ankleVector = (self.markerDict['markers'][leg + '_ankle_study'] - 
                       self.markerDict['markers'][contLeg + '_ankle_study'])
        ankleVector_inGaitFrame = np.array(
            [np.dot(ankleVector, self.R_world_to_gait()[i,:,:]) 
              for i in range(self.nGaitCycles)])                                          
        
        swingAnkleHeighDiffs = np.zeros((to_1_idx.shape))
        
        for i in range(self.nGaitCycles):
            # find index within a swing phase with the smallest z distance between ankles
            idx_midSwing = np.argmin(np.abs(ankleVector_inGaitFrame[
                                     i,to_1_idx[i]:hs_2_idx[i],0]))+to_1_idx[i]
            
            swingAnkleHeighDiffs[i] = ankleVector_inGaitFrame[i,idx_midSwing,1]  
        
        # Average across all strides.
        swingAnkleHeighDiff = np.mean(swingAnkleHeighDiffs)
        
        # Define units.
        units = 'm'
        
        if return_all:
            return swingAnkleHeighDiffs, units
        else:
            return swingAnkleHeighDiff, units
        
    def compute_peak_angle(self,dof,start_idx,end_idx,return_all=False):
        # start_idx and end_idx are 1xnGaitCycles        
        
        peakAngles = np.zeros((self.nGaitCycles))
        
        for i in range(self.nGaitCycles):                       
            peakAngles[i] = np.max(self.coordinateValues[dof + '_' +
                                self.gaitEvents['ipsilateralLeg']][start_idx[i]:end_idx[i]])
        
        # Average across all strides.
        peakAngle = np.mean(peakAngles)
        
        # Define units.
        units = 'deg'
        
        if return_all:
            return peakAngles, units
        else:
            return peakAngle, units
        
    def compute_rom(self,dof,start_idx,end_idx,return_all=False):
        # start_idx and end_idx are 1xnGaitCycles        
        
        roms = np.zeros((self.nGaitCycles))
        
        for i in range(self.nGaitCycles):                       
            roms[i] = np.ptp(self.coordinateValues[dof + '_' +
                                self.gaitEvents['ipsilateralLeg']][start_idx[i]:end_idx[i]])
        
        # Average across all strides.
        rom = np.mean(roms)
        
        # Define units.
        units = 'deg'
        
        if return_all:
            return roms, units
        else:
            return rom, units
        
    @staticmethod
    def find_nearest(array, value):
        # Was missing @staticmethod -- `array` would have silently bound to
        # `self` if ever called as `self.find_nearest(x)` (edit #8). Still
        # unused anywhere in this file; fixed for correctness, not wired in.
        array=np.asarray(array)
        idx=np.abs(array-value).argmin()
        return array[idx]

                        
    def compute_correlations(self, cols_to_compare=None, visualize=False,
                             return_all=False):
        # this computes a weighted correlation between either side's dofs. 
        # the weighting is based on mean absolute percent error. In effect,
        # this penalizes both shape and magnitude differences.
        
        leg,contLeg = self.get_leg(lower=True)
               
        correlations_all_cycles = []
        mean_correlation_all_cycles = np.zeros((self.nGaitCycles,1))
        
        for i in range(self.nGaitCycles):

            
            hs_ind_1 = self.gaitEvents['ipsilateralIdx'][i,0]
            hs_ind_cont = self.gaitEvents['contralateralIdx'][i,1]
            hs_ind_2 = self.gaitEvents['ipsilateralIdx'][i,2]
            
            df1 = pd.DataFrame()
            df2 = pd.DataFrame()

            # create a dataframe of coords for this gait cycle
            for col in self.coordinateValues.columns:
                if col.endswith('_' + leg):
                    df1[col] = self.coordinateValues[col][hs_ind_1:hs_ind_2]
                elif col.endswith('_' + contLeg):
                    df2[col] = np.concatenate((self.coordinateValues[col][hs_ind_cont:hs_ind_2],
                                               self.coordinateValues[col][hs_ind_1:hs_ind_cont]))
            df1 = df1.reset_index(drop=True)
            df2 = df2.reset_index(drop=True)

            # Fills internal NaN gaps -- does NOT resample to a fixed number
            # of rows (unlike get_coordinates_normalized_time elsewhere in
            # this file, which genuinely does). df1/df2 already share the
            # same row count by construction here (df2's two concatenated
            # segments together span the same index range as df1), so no
            # resampling is needed for this comparison; the old comment
            # claiming "101 rows" was simply wrong (edit #6).
            df1_interpolated = df1.interpolate(method='linear', limit_direction='both', limit_area='inside', limit=100)
            df2_interpolated = df2.interpolate(method='linear', limit_direction='both', limit_area='inside', limit=100)

            # Computing the correlation between appropriate columns in both dataframes
            correlations = {}
            total_weighted_correlation = 0
            # total_weight = 0

            for col1 in df1_interpolated.columns:
                # cols_to_compare=None used to resolve against `df1.columns`
                # while df1 was still empty, so the default silently matched
                # nothing and len(correlations) was 0 on every call with no
                # arguments -- ZeroDivisionError below. None now means "no
                # filter, compare everything" instead (edit #6).
                if cols_to_compare is not None and not any(
                    col1.startswith(col_compare) for col_compare in cols_to_compare
                ):
                    continue

                if col1.endswith('_r'):
                    corresponding_col = col1[:-2] + '_l'
                elif col1.endswith('_l'):
                    corresponding_col = col1[:-2] + '_r'
                else:
                    # Previously fell through with whatever corresponding_col
                    # was left over from a prior iteration instead of being
                    # skipped (edit #6).
                    continue

                if corresponding_col in df2_interpolated.columns:
                    signal1 = df1_interpolated[col1]
                    signal2 = df2_interpolated[corresponding_col]

                    max_range_signal1 = np.ptp(signal1)
                    max_range_signal2 = np.ptp(signal2)
                    max_range = max(max_range_signal1, max_range_signal2)

                    mean_abs_error = np.mean(np.abs(signal1 - signal2)) / max_range

                    correlation = signal1.corr(signal2)
                    weight = 1 - mean_abs_error

                    weighted_correlation = correlation * weight
                    correlations[col1] = weighted_correlation

                    total_weighted_correlation += weighted_correlation

                    # Plotting the signals if visualize is True
                    if visualize:
                        plt.figure(figsize=(8, 5))
                        plt.plot(signal1, label='df1')
                        plt.plot(signal2, label='df2')
                        plt.title(f"Comparison between {col1} and {corresponding_col} with weighted correlation {weighted_correlation}")
                        plt.legend()
                        plt.show()

            # len(correlations) can still legitimately be 0 (e.g. a
            # cols_to_compare filter that matches nothing) -- NaN instead of
            # ZeroDivisionError (edit #6).
            if len(correlations) == 0:
                mean_correlation_all_cycles[i] = np.nan
            else:
                mean_correlation_all_cycles[i] = total_weighted_correlation / len(correlations)
            correlations_all_cycles.append(correlations)

        if not return_all:
            mean_correlation_all_cycles = np.nanmean(mean_correlation_all_cycles)
            if correlations_all_cycles and correlations_all_cycles[0]:
                correlations_all_cycles = {
                    key: np.nanmean([d.get(key, np.nan) for d in correlations_all_cycles])
                    for key in correlations_all_cycles[0]
                }
            else:
                correlations_all_cycles = {}


        return correlations_all_cycles, mean_correlation_all_cycles

    def compute_gait_frame(self):

        # Create frame for each gait cycle with x: pelvis heading, 
        # z: average vector between ASIS during gait cycle, y: cross.
        
        # Pelvis center trajectory (for overground heading vector).
        pelvisMarkerNames = ['r.ASIS_study','L.ASIS_study','r.PSIS_study','L.PSIS_study']
        pelvisMarkers = [self.markerDict['markers'][mkr]  for mkr in pelvisMarkerNames]
        pelvisCenter = np.mean(np.array(pelvisMarkers),axis=0)
        
        # Ankle trajectory (for treadmill heading vector).
        leg = self.gaitEvents['ipsilateralLeg']
        if leg == 'l': leg='L'
        anklePos = self.markerDict['markers'][leg + '_ankle_study']
        
        # Vector from left ASIS to right ASIS (for mediolateral direction).
        asisMarkerNames = ['L.ASIS_study','r.ASIS_study']
        asisMarkers = [self.markerDict['markers'][mkr]  for mkr in asisMarkerNames]
        asisVector = np.squeeze(np.diff(np.array(asisMarkers),axis=0))
        
        # Heading vector per gait cycle.
        # If overground, use pelvis center trajectory; treadmill: ankle trajectory.
        if self.treadmillSpeed == 0:
            x = np.diff(pelvisCenter[self.gaitEvents['ipsilateralIdx'][:,(0,2)],:],axis=1)[:,0,:]
            x = x / np.linalg.norm(x,axis=1,keepdims=True)
        else: 
            x = np.zeros((self.nGaitCycles,3))
            for i in range(self.nGaitCycles):
                x[i,:] = anklePos[self.gaitEvents['ipsilateralIdx'][i,2]] - \
                         anklePos[self.gaitEvents['ipsilateralIdx'][i,1]]
            x = x / np.linalg.norm(x,axis=1,keepdims=True)
            
        # Mean ASIS vector over gait cycle.
        z = np.zeros((self.nGaitCycles,3))
        for i in range(self.nGaitCycles):
            z[i,:] = np.mean(asisVector[self.gaitEvents['ipsilateralIdx'][i,0]: \
                             self.gaitEvents['ipsilateralIdx'][i,2]],axis=0)
        z = z / np.linalg.norm(z,axis=1,keepdims=True)
        
        # Cross to get y.
        y = np.cross(z,x)
        
        # 3x3xnSteps.
        R_lab_to_gait = np.stack((x.T,y.T,z.T),axis=1).transpose((2, 0, 1))
        
        return R_lab_to_gait
    
    def get_leg(self,lower=False):

        if self.gaitEvents['ipsilateralLeg'] == 'r':
            leg = 'r'
            contLeg = 'L'
        else:
            leg = 'L'
            contLeg = 'r'
        
        if lower:
            return leg.lower(), contLeg.lower()
        else:
            return leg, contLeg
    
    def get_coordinates_normalized_time(self):
        
        colNames = self.coordinateValues.columns
        data = self.coordinateValues.to_numpy(copy=True)
        coordValuesNorm = []
        for i in range(self.nGaitCycles):
            coordValues = data[self.gaitEvents['ipsilateralIdx'][i,0]:self.gaitEvents['ipsilateralIdx'][i,2]+1]
            coordValuesNorm.append(np.stack([np.interp(np.linspace(0,100,101),
                                   np.linspace(0,100,len(coordValues)),coordValues[:,i]) \
                                   for i in range(coordValues.shape[1])],axis=1))
             
        coordinateValuesTimeNormalized = {}
        # Average.
        coordVals_mean = np.mean(np.array(coordValuesNorm),axis=0)
        coordinateValuesTimeNormalized['mean'] = pd.DataFrame(data=coordVals_mean, columns=colNames)
        
        # Standard deviation.
        if self.nGaitCycles >2:
            coordVals_sd = np.std(np.array(coordValuesNorm), axis=0)
            coordinateValuesTimeNormalized['sd'] = pd.DataFrame(data=coordVals_sd, columns=colNames)
        else:
            coordinateValuesTimeNormalized['sd'] = None
        
        # Return to dataframe.
        coordinateValuesTimeNormalized['indiv'] = [pd.DataFrame(data=d, columns=colNames) for d in coordValuesNorm]
        
        return coordinateValuesTimeNormalized
    
    

    def segment_walking(self, n_gait_cycles=-1, leg='auto', visualize=False):

        # n_gait_cycles = -1 finds all accessible gait cycles. Otherwise, it 
        # finds that many gait cycles, working backwards from end of trial.
               
        # Helper functions
        def detect_gait_peaks(r_calc_rel_x,
                              l_calc_rel_x,
                              r_toe_rel_x,
                              l_toe_rel_x,
                              prominence = 0.3):
            # Find HS.
            rHS, _ = find_peaks(r_calc_rel_x, prominence=prominence)
            lHS, _ = find_peaks(l_calc_rel_x, prominence=prominence)
            
            # Find TO.
            rTO, _ = find_peaks(-r_toe_rel_x, prominence=prominence)
            lTO, _ = find_peaks(-l_toe_rel_x, prominence=prominence)
            
            return rHS,lHS,rTO,lTO
        
        def trimend(self, trim):
            
            # self.trimming_start=trim
            # if self.trimming_start > 0:
            #     self.idx_trim_start = np.where(np.round(self.markerDict['time'] - self.trimming_start,6) <= 0)[0][-1]
            #     self.markerDict['time'] = self.markerDict['time'][self.idx_trim_start:,]
            #     for marker in self.markerDict['markers']:
            #         self.markerDict['markers'][marker] = self.markerDict['markers'][marker][self.idx_trim_start:,:]
            #     self.coordinateValues = self.coordinateValues.iloc[self.idx_trim_start:]
            
            self.trimming_end=trim
            
            if self.trimming_end > 0:
                self.idx_trim_end = np.where(np.round(self.markerDict['time'],6) <= np.round(self.markerDict['time'][-1] - self.trimming_end,6))[0][-1] + 1
                self.markerDict['time'] = self.markerDict['time'][:self.idx_trim_end,]
                for marker in self.markerDict['markers']:
                    self.markerDict['markers'][marker] = self.markerDict['markers'][marker][:self.idx_trim_end,:]
                self.coordinateValues = self.coordinateValues.iloc[:self.idx_trim_end]
                
            r_calc_rel = (
                self.markerDict['markers']['r_calc_study'] - 
                self.markerDict['markers']['r.PSIS_study'])
            
            r_toe_rel = (
                self.markerDict['markers']['r_toe_study'] - 
                self.markerDict['markers']['r.PSIS_study'])
            r_toe_rel_x = r_toe_rel[:,0]
            # Repeat for left.
            l_calc_rel = (
                self.markerDict['markers']['L_calc_study'] - 
                self.markerDict['markers']['L.PSIS_study'])
            l_toe_rel = (
                self.markerDict['markers']['L_toe_study'] - 
                self.markerDict['markers']['L.PSIS_study'])
            
            # Identify which direction the subject is walking.
            mid_psis = (self.markerDict['markers']['r.PSIS_study'] + self.markerDict['markers']['L.PSIS_study'])/2
            mid_asis = (self.markerDict['markers']['r.ASIS_study'] + self.markerDict['markers']['L.ASIS_study'])/2
            mid_dir = mid_asis - mid_psis
            mid_dir_floor = np.copy(mid_dir)
            mid_dir_floor[:,1] = 0
            mid_dir_floor = mid_dir_floor / np.linalg.norm(mid_dir_floor,axis=1,keepdims=True)
            
            # Dot product projections   
            r_calc_rel_x = np.einsum('ij,ij->i', mid_dir_floor,r_calc_rel)
            l_calc_rel_x = np.einsum('ij,ij->i', mid_dir_floor,l_calc_rel)
            r_toe_rel_x = np.einsum('ij,ij->i', mid_dir_floor,r_toe_rel)
            l_toe_rel_x = np.einsum('ij,ij->i', mid_dir_floor,l_toe_rel)

            # Refreshed here as well as in segment_walking, because trimend is
            # CUMULATIVE: it shortens markerDict every call. A picker opened on
            # an instance that went through auto-trim would otherwise get the
            # trimmed time vector with the ORIGINAL, longer signals, which is a
            # length mismatch the plotting layer reports as an unreadable
            # "x and y must have same first dimension".
            self.eventDetectionSignals = {
                'r_calc': r_calc_rel_x, 'r_toe': r_toe_rel_x,
                'l_calc': l_calc_rel_x, 'l_toe': l_toe_rel_x,
            }

            prominences = [0.3, 0.25, 0.2]
                     
            for i,prom in enumerate(prominences):
            
                
                rHS,lHS,rTO,lTO = detect_gait_peaks(r_calc_rel_x=r_calc_rel_x,
                                    l_calc_rel_x=l_calc_rel_x,
                                    r_toe_rel_x=r_toe_rel_x,
                                    l_toe_rel_x=l_toe_rel_x,
                                    prominence=prom)
                
                # print(detect_correct_order(rHS=rHS, rTO=rTO, lHS=lHS, lTO=lTO))
                if not detect_correct_order(rHS=rHS, rTO=rTO, lHS=lHS, lTO=lTO):
                    if prom == prominences[-1]:
                         
                        print("Could not detect peak, auto-trimming again")
                        break
                             
                    else:
                        print('The gait events were not in the correct order. Trying peak detection again ' +
                           'with prominence = ' + str(prominences[i+1]) + '.')
                else:
                    # everything was in the correct order. continue.
                    self.promflag=1
                    break



            # Edit #13 (2026-08-24): was `return rHS, rTO, lHS, lTO`, but the
            # only call site unpacks `rHS,lHS,rTO,lTO = trimend(...)` -- so
            # every auto-trim retry silently swapped left heel-strikes with
            # right toe-offs on the way OUT. Matches detect_gait_peaks' own
            # (correct) `return rHS,lHS,rTO,lTO` order.
            #
            # Scope of the bug, stated precisely: this does NOT affect whether
            # the retry loop converges. The ordering check that drives
            # convergence runs INSIDE this function
            # (`detect_correct_order(rHS=rHS, rTO=rTO, lHS=lHS, lTO=lTO)`
            # above) on correctly-ordered locals, and signals success only
            # through `self.promflag` -- set before this return executes, and
            # the sole thing the caller's `while checkflag==0` loop reads. An
            # earlier draft of this comment blamed the swap for the loop
            # grinding without converging; that is not mechanically possible.
            # What the swap actually corrupted is every downstream consumer of
            # the returned events once convergence HAD happened -- gait-cycle
            # segmentation and every metric derived from it silently ran on
            # left heel-strikes sitting in the right toe-off slot. That is
            # arguably worse than a hang: it yields plausible wrong numbers
            # rather than an obvious failure.
            return rHS, lHS, rTO, lTO

            
        
        # manual_steps used to be defined here. It is now a module-level
        # function (2026-08-31) that drives gait_event_picker.GaitEventPicker
        # instead of four stdin prompts for event times. It is still called
        # below as `manual_steps(self)` -- it always took self explicitly --
        # and still returns rHS, lHS, rTO, lTO in that order.

        def detect_correct_order(rHS, rTO, lHS, lTO):
            # checks if the peaks are in the right order
                    
            expectedOrder = {'rHS': 'lTO',
                             'lTO': 'lHS',
                             'lHS': 'rTO',
                             'rTO': 'rHS'}
                    
            # Identify vector that has the smallest value in it. Put this vector name
            # in vName1
            vectors = {'rHS': rHS, 'rTO': rTO, 'lHS': lHS, 'lTO': lTO}
            non_empty_vectors = {k: v for k, v in vectors.items() if len(v) > 0}
        
            # Check if there are any non-empty vectors
            if not non_empty_vectors:
                return True  # All vectors are empty, consider it correct order
        
            vName1 = min(non_empty_vectors, key=lambda k: non_empty_vectors[k][0])
        
            # While there are any values in any of the vectors (rHS, rTO, lHS, or lTO)
            while any([len(vName) > 0 for vName in vectors.values()]):
                # Delete the smallest value from the vName1
                vectors[vName1] = np.delete(vectors[vName1], 0)
        
                # Then find the vector with the next smallest value. Define vName2 as the
                # name of this vector
                non_empty_vectors = {k: v for k, v in vectors.items() if len(v) > 0}
                
                # Check if there are any non-empty vectors
                if not non_empty_vectors:
                    break  # All vectors are empty, consider it correct order
        
                vName2 = min(non_empty_vectors, key=lambda k: non_empty_vectors[k][0])
        
                # If vName2 != expectedOrder[vName1], return False
                if vName2 != expectedOrder[vName1]:
                    return False
        
                # Set vName1 equal to vName2 and clear vName2
                vName1, vName2 = vName2, ''
        
            return True
        
        # Subtract sacrum from foot.
        # It looks like the position-based approach will be more robust.        
        r_calc_rel = (
            self.markerDict['markers']['r_calc_study'] - 
            self.markerDict['markers']['r.PSIS_study'])
        
        r_toe_rel = (
            self.markerDict['markers']['r_toe_study'] - 
            self.markerDict['markers']['r.PSIS_study'])
        r_toe_rel_x = r_toe_rel[:,0]
        # Repeat for left.
        l_calc_rel = (
            self.markerDict['markers']['L_calc_study'] - 
            self.markerDict['markers']['L.PSIS_study'])
        l_toe_rel = (
            self.markerDict['markers']['L_toe_study'] - 
            self.markerDict['markers']['L.PSIS_study'])
        
        # Identify which direction the subject is walking.
        mid_psis = (self.markerDict['markers']['r.PSIS_study'] + self.markerDict['markers']['L.PSIS_study'])/2
        mid_asis = (self.markerDict['markers']['r.ASIS_study'] + self.markerDict['markers']['L.ASIS_study'])/2
        mid_dir = mid_asis - mid_psis
        mid_dir_floor = np.copy(mid_dir)
        mid_dir_floor[:,1] = 0
        mid_dir_floor = mid_dir_floor / np.linalg.norm(mid_dir_floor,axis=1,keepdims=True)
        
        # Dot product projections   
        r_calc_rel_x = np.einsum('ij,ij->i', mid_dir_floor,r_calc_rel)
        l_calc_rel_x = np.einsum('ij,ij->i', mid_dir_floor,l_calc_rel)
        r_toe_rel_x = np.einsum('ij,ij->i', mid_dir_floor,r_toe_rel)
        l_toe_rel_x = np.einsum('ij,ij->i', mid_dir_floor,l_toe_rel)

        # Kept for the manual picker (2026-09-01). These four are exactly what
        # detect_gait_peaks runs its peak detection on, so an operator picking
        # by hand is looking at the same evidence the automatic rung looked at
        # rather than a different rendering of the trial. They are locals here
        # and the provider is only handed a picker, so they are stashed on the
        # instance for build_manual_picker to attach. Observational only --
        # nothing in this class reads them back.
        self.eventDetectionSignals = {
            'r_calc': r_calc_rel_x, 'r_toe': r_toe_rel_x,
            'l_calc': l_calc_rel_x, 'l_toe': l_toe_rel_x,
        }
        
        # Old Approach that does not take the heading direction into account.
        # r_psis_x = self.markerDict['markers']['r.PSIS_study'][:,0]
        # r_asis_x = self.markerDict['markers']['r.ASIS_study'][:,0]
        # r_dir_x = r_asis_x-r_psis_x
        # position_approach_scaling = np.where(r_dir_x > 0, 1, -1)        
        # r_calc_rel_x = r_calc_rel[:,0] * position_approach_scaling
        # r_toe_rel_x = r_toe_rel[:,0] * position_approach_scaling
        # l_calc_rel_x = l_calc_rel[:,0] * position_approach_scaling
        # l_toe_rel_x = l_toe_rel[:,0] * position_approach_scaling
                       
        # Detect peaks, check if they're in the right order, if not reduce prominence.
        # the peaks can be less prominent with pathological or slower gait patterns
        prominences = [0.3, 0.25, 0.2]
        manual_flag=0
        # promflag=0
        trimflag=0
        # trimcount=0
        # print(self.markerDict['time'][-1])
        seshlen=np.round(self.markerDict['time'][-1],6)
        ntrims=round(seshlen/.2)-2
        if ntrims < 1:
            # Previously: an empty trimarray made trimarray[0]=-1 raise an
            # opaque IndexError for short trials (edit #3).
            raise Exception(
                'Trial is too short (' + str(seshlen) + 's) for auto-trim retry to have '
                'any candidate trim amounts (needs at least ~0.6s). Cannot proceed with '
                'automatic gait-event detection for this trial.'
            )
        trimarray=[0.2]*ntrims
        trimarray[0]=-1
        
        # for j,trim in enumerate(trimarray):
        #     if j>0:
        #         if trimflag==0:
        #             trimend(self,trimarray[j])
                
                
        for i,prom in enumerate(prominences):
          
            if manual_flag==0:
                rHS,lHS,rTO,lTO = detect_gait_peaks(r_calc_rel_x=r_calc_rel_x,
                                  l_calc_rel_x=l_calc_rel_x,
                                  r_toe_rel_x=r_toe_rel_x,
                                  l_toe_rel_x=l_toe_rel_x,
                                  prominence=prom)
            
                
            # print(r_calc_rel_x)
            # print (rHS)
            # print(self.markerDict['time'])
            if not detect_correct_order(rHS=rHS, rTO=rTO, lHS=lHS, lTO=lTO):
                if prom == prominences[-1]:
                    # if j==len(trimarray):

                    # allow_manual_entry=False skips straight to auto-trim
                    # instead of blocking on stdin (edit #2) -- the whole
                    # point of unattended batch runs.
                    if not self.allow_manual_entry:
                        trimflag=1
                        break

                    if getattr(self, 'manual_event_provider', None) is not None:
                        # A UI is wired up, so asking on stdin whether the
                        # operator wants a UI would block the very session the
                        # UI was supplied for. Hand it the trial; if it wants
                        # to decline it can return a picker with no events,
                        # and the empty-heel-strike guard below reports that.
                        manual_flag=1
                        break

                    response = input("Do you want to enter gait events manually? [Y/N]: ").lower()

                    if response.lower() != 'y':
                        # raise ValueError('The ordering of gait events is not correct. Consider trimming your trial using the trimming_start and trimming_end options.')
                        trimflag=1
                        break
                    else:
                        manual_flag=1
                        break
                    
                        
                else:
                    print('The gait events were not in the correct order. Trying peak detection again ' +
                      'with prominence = ' + str(prominences[i+1]) + '.')
            else:
                # everything was in the correct order. continue.
                # promflag=1
                break
            # if promflag==1:
            #     print("its good")
            #     trimflag=1
            #     break
        
        if manual_flag==1:
            rHS,lHS,rTO,lTO = manual_steps(self)

            # A picker handed back with nothing on it is the operator
            # declining, and declining must not cost them rung two. Before a
            # UI existed, the only route here was answering 'Y' to the stdin
            # prompt, and answering 'N' fell through to auto-trim; wiring a
            # provider made the human unconditionally pre-empt auto-trim, so
            # cancelling the picker hard-failed a trial the retry loop might
            # have rescued. The fallback chain is prominence -> auto-trim ->
            # human, and a declined pick puts us back on rung two.
            if not any(len(events) for events in (rHS, lHS, rTO, lTO)):
                print('No gait events were picked; falling back to auto-trim.')
                # Not cached as an answer: dflag=1 would make the decline
                # stick for the other leg, which never got asked.
                self.dflag = 0
                self.rhs, self.lhs, self.rto, self.lto = [], [], [], []
                # Cleared too, or a later auto-trim failure gets reported as a
                # manual-entry failure. detect_correct_order treats all-empty
                # vectors as correctly ordered, so auto-trim can converge with
                # no heel strikes for the requested leg -- and the guard below
                # would then blame the operator for a pick they declined to
                # make, quoting a tally of zeros back at them.
                self.manualEventPicker = None
                trimflag = 1

        if trimflag==1:
            self.usedAutoTrim = True
            j=1
            checkflag=self.promflag

            # Previously: `if j==len(trimarray)-2: checkflag=self.promflag`
            # reassigned checkflag to its own current value -- a no-op, not
            # a real termination condition. The loop could keep incrementing
            # j past the end of trimarray and crash with an uncaught
            # IndexError instead of failing clearly (edit #4).
            while checkflag==0:
                if j >= len(trimarray):
                    raise Exception(
                        'Auto-trim retry exhausted all ' + str(len(trimarray) - 1) + ' attempts '
                        'without finding correctly-ordered gait events. Consider manual '
                        'trimming_start/trimming_end, or allow_manual_entry=True for an '
                        'interactive session.'
                    )
                # Edit #12 (2026-08-24): trimend() is CUMULATIVE -- each call
                # shaves another 0.2s off the already-trimmed data -- but the
                # loop's only bound was `len(trimarray)`, itself derived from
                # the trial's duration (ntrims = round(seshlen/.2) - 2). For a
                # 43.5s trial that authorises ~215 trims x 0.2s = ~43s of
                # trimming: the loop may consume essentially the ENTIRE
                # recording looking for gait events that a non-gait trial will
                # never have.
                #
                # Measured behaviour, not inferred (real non-gait trial, both
                # legs): ~238 trims total, ~119 per leg, ~23.8s removed from a
                # 43.5s recording, ~19.7s left -- and it completed, converging
                # on one spurious "gait cycle" per leg. The guard below does
                # NOT fire in that run (it only trips under ~2.2s remaining),
                # which is the intended behaviour: it is a backstop against
                # pathological trimming, not a filter for non-gait trials.
                # A real walking trial from a verified matched pair needs zero
                # retries and never reaches this code at all.
                #
                # An earlier draft of this comment claimed the loop caused a
                # hard native crash (ucrtbase 0xc0000409). That was wrong: 238
                # iterations complete cleanly, the crash has never been
                # reproduced across the pipeline, display, export or threaded
                # -import paths, and its cause is still unknown. Fixing the
                # message here does not fix that crash.
                #
                # Bound the retry by REMAINING DATA rather than iteration count,
                # and fail with a clinically meaningful message. MIN_REMAINING_
                # SECONDS_FOR_GAIT_DETECTION is deliberately conservative: gait
                # detection needs at least one full ipsilateral cycle plus the
                # contralateral events inside it to check ordering at all, so
                # anything under a couple of seconds cannot succeed no matter
                # how many more times it is retried.
                remaining = float(
                    np.round(self.markerDict['time'][-1] - self.markerDict['time'][0], 6)
                )
                if remaining - trimarray[j] < MIN_REMAINING_SECONDS_FOR_GAIT_DETECTION:
                    raise Exception(
                        'Auto-trim stopped after ' + str(j - 1) + ' attempt(s): trimming '
                        'further would leave only ' + str(round(remaining - trimarray[j], 2)) +
                        's of data, below the ' + str(MIN_REMAINING_SECONDS_FOR_GAIT_DETECTION) +
                        's minimum needed to detect a gait cycle. No correctly-ordered '
                        'gait events were found in this trial. This usually means the '
                        'recording is not walking (or the walking portion is too short '
                        'or too noisy to segment) -- check that this is a gait trial '
                        'before retrying.'
                    )
                print("Trying auto-Trim")
                rHS,lHS,rTO,lTO=trimend(self, trimarray[j])
                self.nAutoTrims += 1
                # print(j)
                j+=1
                checkflag=self.promflag

        # print([rHS,lHS,rTO,lTO])
        
        # if manual_flag==1:
        #     rHS,lHS,rTO,lTO = manual_steps(self)
        
        if visualize:
            import matplotlib.pyplot as plt
            plt.close('all')
            plt.figure(1)
            plt.plot(self.markerDict['time'],r_toe_rel_x,label='toe')
            plt.plot(self.markerDict['time'],r_calc_rel_x,label='calc')
            plt.scatter(self.markerDict['time'][rHS], r_calc_rel_x[rHS], color='red', label='rHS')
            plt.scatter(self.markerDict['time'][rTO], r_toe_rel_x[rTO], color='blue', label='rTO')
            plt.legend()

            plt.figure(2)
            plt.plot(self.markerDict['time'],l_toe_rel_x,label='toe')
            plt.plot(self.markerDict['time'],l_calc_rel_x,label='calc')
            plt.scatter(self.markerDict['time'][lHS], l_calc_rel_x[lHS], color='red', label='lHS')
            plt.scatter(self.markerDict['time'][lTO], l_toe_rel_x[lTO], color='blue', label='lTO')
            plt.legend()

        # Find the number of gait cycles for the foot of interest.
        if leg=='auto':
            # Previously indexed rHS[-1]/lHS[-1] before checking either was
            # non-empty -- a real IndexError if peak detection found zero
            # heel-strikes for a leg even without an ordering problem
            # (edit #5).
            if len(rHS) == 0 or len(lHS) == 0:
                # leg='auto' is the DEFAULT, so this guard fires before the
                # manual-entry one further down. Without the branch below, an
                # operator who picked events for only one leg was told to
                # "check the trial's marker data quality" and never heard about
                # their own picks -- the exact confusion the manual-entry
                # message was added to remove.
                if getattr(self, 'manualEventPicker', None) is not None:
                    raise Exception(
                        'Manual entry supplied heel strikes for only one leg (rHS: ' +
                        str(len(rHS)) + ', lHS: ' + str(len(lHS)) + '), so the '
                        'leg cannot be chosen automatically. Picked so far: ' +
                        str(self.manualEventPicker.counts()) + ". Pick heel strikes "
                        "for both legs, or pass leg='r'/'l' explicitly."
                    )
                raise Exception(
                    'No heel-strike events detected for one or both legs (rHS: ' +
                    str(len(rHS)) + ', lHS: ' + str(len(lHS)) + '). Cannot auto-select a '
                    "leg -- pass leg='r' or leg='l' explicitly, or check the trial's marker "
                    'data quality.'
                )
            # Find the last HS of either foot.
            if rHS[-1] > lHS[-1]:
                leg = 'r'
            else:
                leg = 'l'
        
        # Find the number of gait cycles for the foot of interest.
        if leg == 'r':
            hsIps = rHS
            toIps = rTO
            hsCont = lHS
            toCont = lTO
        elif leg == 'l':
            hsIps = lHS
            toIps = lTO
            hsCont = rHS
            toCont = rTO

        # Edit #14 (2026-08-27, found by the Phase 1.1 re-run survey). Edit #5
        # added an empty-heel-strike guard, but only inside the `leg=='auto'`
        # branch above -- and clinician_gui never takes that branch, because it
        # asks for leg='r' and leg='l' explicitly. With a leg supplied, an
        # empty hsIps made n_gait_cycles = len(hsIps)-1 = -1, which survives
        # both adjustments below and reaches np.zeros((-1, 3)) as
        # "ValueError: negative dimensions are not allowed" -- a numpy message
        # naming nothing the operator can act on.
        #
        # Observed on real data, not hypothesised: Trial3_1 in session
        # ca505b02 failed exactly this way on both legs, 2 of 92 trial-legs
        # surveyed. Those trials need the manual event picker, and the survey
        # can only route them there if the failure says what it is.
        if len(hsIps) == 0:
            # Two very different causes reach here, and telling an operator who
            # just hand-picked events to "supply the events manually" sends
            # them back to the thing they already did. Manual entry lands here
            # when events were picked for the other leg only.
            if getattr(self, 'manualEventPicker', None) is not None:
                raise Exception(
                    "Manual entry supplied no heel-strike events for the '" + leg +
                    "' leg, so no gait cycle can be segmented for it. Picked so far: " +
                    str(self.manualEventPicker.counts()) + ". This leg needs at least "
                    'two heel strikes.'
                )
            raise Exception(
                "No heel-strike events were detected for the '" + leg + "' leg, so "
                'no gait cycle can be segmented. This is a detection failure rather '
                "than a short trial -- check the trial's marker data quality, or "
                'supply the events manually.'
            )

        if len(hsIps)-1 < n_gait_cycles:
            print('You requested {} gait cycles, but only {} were found. '
                  'Proceeding with this number.'.format(n_gait_cycles,len(hsIps)-1))
            n_gait_cycles = len(hsIps)-1
        if n_gait_cycles == -1:
            n_gait_cycles = len(hsIps)-1
            print('Processing {} gait cycles, leg: '.format(n_gait_cycles) + leg + '.')
            
        # Ipsilateral gait events: heel strike, toe-off, heel strike.
        gaitEvents_ips = np.zeros((n_gait_cycles, 3),dtype=int)
        # Contralateral gait events: toe-off, heel strike.
        gaitEvents_cont = np.zeros((n_gait_cycles, 2),dtype=int)
        if n_gait_cycles <1:
            raise Exception('Not enough gait cycles found.')

        for i in range(n_gait_cycles):
            # Ipsilateral HS, TO, HS.
            gaitEvents_ips[i,0] = hsIps[-i-2]
            gaitEvents_ips[i,2] = hsIps[-i-1]
            
            # Iterate in reverse through ipsilateral TO, finding the one that
            # is within the range of gaitEvents_ips.
            toIpsFound = False
            for j in range(len(toIps)):
                if toIps[-j-1] > gaitEvents_ips[i,0] and toIps[-j-1] < gaitEvents_ips[i,2] and not toIpsFound:
                    gaitEvents_ips[i,1] = toIps[-j-1]
                    toIpsFound = True

            # Contralateral TO, HS.
            # Iterate in reverse through contralateral HS and TO, finding the
            # one that is within the range of gaitEvents_ips
            hsContFound = False
            toContFound = False
            for j in range(len(toCont)):
                if toCont[-j-1] > gaitEvents_ips[i,0] and toCont[-j-1] < gaitEvents_ips[i,2] and not toContFound:
                    gaitEvents_cont[i,0] = toCont[-j-1]
                    toContFound = True
                    
            for j in range(len(hsCont)):
                if hsCont[-j-1] > gaitEvents_ips[i,0] and hsCont[-j-1] < gaitEvents_ips[i,2] and not hsContFound:
                    gaitEvents_cont[i,1] = hsCont[-j-1]
                    hsContFound = True
            
            # Skip this step if no contralateral peaks fell within ipsilateral events
            # This can happen with noisy data with subject far from camera. 
            if not toContFound or not hsContFound:                   
                print('Could not find contralateral gait event within ' + 
                               'ipsilateral gait event range ' + str(i+1) + 
                               ' steps until the end. Skipping this step.')
                gaitEvents_cont[i,:] = -1
                gaitEvents_ips[i,:] = -1
                print(gaitEvents_cont)
                print(gaitEvents_ips)
        
        # Remove any nan rows
        mask_ips = (gaitEvents_ips == -1).any(axis=1)
        if all(mask_ips):
            raise Exception('No good steps for ' + leg + ' leg.')
        gaitEvents_ips = gaitEvents_ips[~mask_ips]
        gaitEvents_cont = gaitEvents_cont[~mask_ips]
            
        # Convert gaitEvents to times using self.markerDict['time'].
        gaitEventTimes_ips = self.markerDict['time'][gaitEvents_ips]
        gaitEventTimes_cont = self.markerDict['time'][gaitEvents_cont]
                            
        gaitEvents = {'ipsilateralIdx':gaitEvents_ips,
                      'contralateralIdx':gaitEvents_cont,
                      'ipsilateralTime':gaitEventTimes_ips,
                      'contralateralTime':gaitEventTimes_cont,
                      'eventNamesIpsilateral':['HS','TO','HS'],
                      'eventNamesContralateral':['TO','HS'],
                      'ipsilateralLeg':leg}
        
        return gaitEvents
    
        

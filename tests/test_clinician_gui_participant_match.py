"""Tests the GUI's participant guard: which participant a session belongs to,
and whether the trials being run are that participant's.

Why this exists. On 2026-09-04, during the plan's required manual smoke run,
twelve AN-xxx trials were processed into an OpenCap session belonging to a
different participant. Nothing objected. The session folder is named
`OpenCapData_<uuid>`, and the identity lives in a `sessionMetadata.yaml` the
operator has no reason to open -- so the window never said whose session was
selected, and there was no way to notice.

Every trial is processed against that session's scaled model, so the result
is complete, plausible, and the wrong person's. `session_scaffold.py` already
names this as "the failure mode this project keeps running into"; it guards
the scaffolding step and nothing guarded the GUI.

Loads clinician_gui.py by path per this repo's convention.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'clinician_gui.py')


def _load_module():
    spec = importlib.util.spec_from_file_location(
        'clinician_gui_participant_match_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def _session(tmp_path, subject_id=None, name="OpenCapData_7de6caea"):
    session = tmp_path / name
    session.mkdir()
    if subject_id is not None:
        (session / "sessionMetadata.yaml").write_text(
            f"subjectID: {subject_id}\nopenSimModel: LaiUhlrich2022\n",
            encoding="utf-8")
    return session


# ---------------------------------------------------------------------------
# Identity, and the rule that it is a code and never a name.
# ---------------------------------------------------------------------------

def test_a_full_name_is_reduced_to_initials_not_carried_around(mod, tmp_path):
    """subjectID is sometimes a real name. This repository is public, and
    session_scaffold already forbids writing one into a filename or a log --
    a value shown in a window and pasted into a warning needs the same rule."""
    session = _session(tmp_path, "Ada Lovelace")
    assert mod.session_participant_code(session) == "AL"


def test_a_session_already_carrying_a_code_keeps_it(mod, tmp_path):
    assert mod.session_participant_code(_session(tmp_path, "KM")) == "KM"


def test_a_session_with_no_metadata_is_unknown_not_an_error(mod, tmp_path):
    """A scaffolded Xsens session has its own layout and need not carry one."""
    assert mod.session_participant_code(_session(tmp_path)) is None


def test_trial_codes_come_off_the_filename_convention(mod):
    assert mod.trial_participant_code("AN-012") == "AN"
    assert mod.trial_participant_code("ck_003") == "CK"
    assert mod.trial_participant_code("SB-001.mvnx") == "SB"


def test_a_trial_not_following_the_convention_claims_nothing(mod):
    """Absence of evidence must not become a mismatch."""
    assert mod.trial_participant_code("walking_trial") is None
    assert mod.trial_participant_code("12345") is None


# ---------------------------------------------------------------------------
# The check itself.
# ---------------------------------------------------------------------------

def test_the_2026_09_04_mismatch_is_caught(mod, tmp_path):
    """The real case: AN trials run against another participant's session."""
    session = _session(tmp_path, "Sungjin Bae")          # -> SB
    ok, message = mod.check_participant_match(
        session, [f"AN-{n:03d}" for n in range(1, 13)])

    assert not ok
    assert "SB" in message and "AN" in message
    # The warning says why it matters, not merely that two strings differ.
    assert "scaled model" in message
    # And it names neither participant in full.
    assert "Sungjin" not in message and "Bae" not in message


def test_a_matching_session_and_trials_pass_quietly(mod, tmp_path):
    session = _session(tmp_path, "Aravind Nehrujee")     # -> AN
    ok, message = mod.check_participant_match(session, ["AN-001", "AN-002"])
    assert ok and message == ""


def test_a_session_without_metadata_cannot_mismatch(mod, tmp_path):
    """It must not cry wolf on a session it simply cannot check."""
    ok, _ = mod.check_participant_match(_session(tmp_path), ["AN-001"])
    assert ok


def test_unconventional_trial_names_cannot_mismatch(mod, tmp_path):
    session = _session(tmp_path, "KM")
    ok, _ = mod.check_participant_match(session, ["walking", "trial_two"])
    assert ok


def test_every_mismatched_code_in_a_mixed_batch_is_named(mod, tmp_path):
    """A folder holding two participants' trials is worse than one holding
    the wrong participant's, and the message must show both."""
    session = _session(tmp_path, "KM")
    ok, message = mod.check_participant_match(
        session, ["KM-001", "AN-002", "SB-003"])

    assert not ok
    assert "AN" in message and "SB" in message


def test_the_check_reports_and_never_refuses(mod, tmp_path):
    """This project's standing rule is that code flags a data problem and a
    human decides. A legitimately odd pairing must stay runnable."""
    session = _session(tmp_path, "KM")
    ok, message = mod.check_participant_match(session, ["AN-001"])

    assert (ok, bool(message)) == (False, True)
    assert "Continue only if" in message


def test_a_prose_filename_with_a_separator_is_not_a_participant_code(mod):
    """'trial_two' parsed as participant 'TRIAL' under the first regex. A
    guard that fires on ordinary files is one an operator learns to dismiss
    unread, which costs more than the mistake it was added to catch."""
    assert mod.trial_participant_code("trial_two") is None
    assert mod.trial_participant_code("walking_left") is None
    assert mod.trial_participant_code("static_cal") is None
    # ...while the real convention still reads.
    assert mod.trial_participant_code("AN-012") == "AN"
    assert mod.trial_participant_code("MINT-004") == "MINT"

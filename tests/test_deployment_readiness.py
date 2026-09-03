"""Deployment-readiness gates for this repo.

Every other test file here pins *behaviour*: given this input, the code must
produce that output. These pin something different -- whether the thing a
person would actually install and run is coherent as a deliverable. A repo can
be 100% green on behaviour and still be undeployable because a dependency is
undeclared, an entry point hangs, or nobody can say where a file came from.

Each test is one gate. A failing gate is not a bug in a function; it is a
statement that the product is not ready to hand to someone else, and its
message says what would have to change.

The organising principle is the one the rest of this codebase already works
to, stated in `gdi.py` and the GDI audit: *never emit a plausible wrong
number*. These gates extend it outward from the arithmetic to the packaging --
a pipeline that cannot be installed reproducibly, or whose entry points cannot
be inspected, fails that principle at a different layer.
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Import name -> distribution name, where they differ. Without this the
# dependency gate reports false misses on packages that install under a
# different name than they import under.
IMPORT_TO_DISTRIBUTION = {
    "decouple": "python-decouple",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "PIL": "pillow",
}

# Directories that are not part of what gets deployed and run.
EXCLUDED_DIRS = {".git", "__pycache__", "tests", "docs", ".claude"}

# The commit that vendored the upstream opencap-processing baseline.
# PROVENANCE.md names this commit and defines tier A as its contents.
VENDORED_BASELINE_COMMIT = "cfcf7ad"


def _shipped_python_files():
    """Every .py file that is part of the deliverable.

    Tracked by git, not merely present on disk. The distinction is the whole
    meaning of these gates: what a user receives is the checkout, and a
    working tree also holds things that are deliberately not in it.
    `.gitignore` lists `context/` because those are local scratch copies of
    upstream sources, and a half-written analysis script is not part of any
    release either. Walking `rglob` reported both as undeclared dependencies
    and as missing from PROVENANCE.md -- release gates failing on files no
    user will ever see, which is how a gate becomes something people learn to
    skip.

    `check=True` on purpose: an unreadable index must fail loudly here rather
    than return nothing and let every gate above pass by having nothing left
    to judge. The vendored-baseline gate below already assumes git the same
    way.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(
        (REPO_ROOT / name).resolve()
        for name in tracked
        if not any(part in EXCLUDED_DIRS for part in Path(name).parts)
    )


def _in_repo_module_names():
    """Module names importable because they are files or packages in this repo.

    Covers three shapes, all of which look like third-party imports to a
    naive scan but are not:
      - top-level modules (`gdi.py`)
      - subdirectory modules imported by bare name (`ActivityAnalyses/
        gait_analysis.py`, imported as `gait_analysis`)
      - subdirectory *packages* (`import ActivityAnalyses.sts_analysis`)
    """
    names = {p.stem for p in _shipped_python_files()}
    for path in _shipped_python_files():
        # Every ancestor directory, not just the immediate parent:
        # `UtilsDynamicSimulations/OpenSimAD/*.py` is imported as
        # `UtilsDynamicSimulations.OpenSimAD`, whose top-level name is two
        # levels up from the file.
        names.update(path.relative_to(REPO_ROOT).parts[:-1])
    return names


def _declared_distributions():
    """Everything declared by either manifest.

    Two files, for a reason that is not redundancy. `requirements.txt` is tier
    A -- vendored from upstream opencap-processing in `cfcf7ad` -- and this
    repo's ground rule is that upstream files are never edited in place, so it
    cannot be where a synergy-side dependency gets added. `environment.yml` is
    ours, and is also the only one of the two that can express `opensim`,
    which is not on PyPI at all.
    """
    declared = set()

    for line in (REPO_ROOT / "requirements.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        line = line.split("#")[0].strip()
        if line:
            name = re.split(r"[=<>!~\[]", line)[0].strip()
            if name:
                declared.add(name.lower())

    environment = REPO_ROOT / "environment.yml"
    if environment.exists():
        for line in environment.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if not line.startswith("- "):
                continue
            entry = line[2:].strip()
            if not entry or entry.endswith(":"):
                continue
            name = re.split(r"[=<>!~\[]", entry)[0].strip()
            if name:
                declared.add(name.lower())

    return declared


def _top_level_imports(path):
    """Third-party module names this file imports, ignoring relative imports."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _docstring_nodes(tree):
    """Every string node that is documentation rather than a value.

    Covers module, class and function docstrings plus bare string expression
    statements, which this codebase uses as block commentary. They are the
    only place a `.py` filename appears as prose rather than as a target.
    """
    documentation = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                documentation.add(id(first.value))
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            documentation.add(id(node.value))
    return documentation


def _referenced_module_filenames(path):
    """`.py` filenames this file names as a load target, not as prose.

    Matching on string literals rather than on call shape is deliberate. The
    repo reaches other modules by path in at least four spellings -- a local
    `_load(name, filename)`, `module_loading.load_module_by_path` through an
    aliased `_load_module_by_path`, a direct
    `importlib.util.spec_from_file_location`, and module-level `_..._PATH`
    constants built with `os.path.join` or the `/` operator. Every one of them
    has to name the file as a literal somewhere. Keying on the literal catches
    all four and does not break when a fifth spelling is invented.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()

    documentation = _docstring_nodes(tree)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.endswith(".py")
        # A bare ".py" is an extension being concatenated onto a name computed
        # at runtime (`fooName + '.py'`, several times in utilsOpenSimAD.py),
        # not a file anyone can check for. Require a stem.
        and len(node.value) > len(".py")
        and id(node) not in documentation
    }


def test_every_third_party_import_is_declared_as_a_dependency():
    """`pip install -r requirements.txt` must be enough to import the code.

    An undeclared import is the difference between "works on the machine it
    was written on" and "installable". It does not surface as a test failure
    on a developer box, because the package is already there for some other
    reason -- it surfaces on the first fresh install, which is exactly the
    moment a deployment is supposed to be routine.
    """
    stdlib = set(sys.stdlib_module_names)
    in_repo = _in_repo_module_names()
    declared = _declared_distributions()

    undeclared = {}
    for path in _shipped_python_files():
        for name in _top_level_imports(path):
            if name in stdlib or name in in_repo:
                continue
            distribution = IMPORT_TO_DISTRIBUTION.get(name, name).lower()
            if distribution in declared:
                continue
            undeclared.setdefault(name, set()).add(
                str(path.relative_to(REPO_ROOT))
            )

    assert not undeclared, (
        "these packages are imported by shipped code but not declared in "
        "requirements.txt, so a fresh `pip install -r requirements.txt` "
        "produces an installation that cannot import its own modules:\n"
        + "\n".join(
            f"  {name}  <- {', '.join(sorted(files)[:4])}"
            for name, files in sorted(undeclared.items())
        )
    )


def test_every_shipped_module_is_classified_in_the_provenance_map():
    """PROVENANCE.md calls itself authoritative; that has to stay true.

    This repo vendors 57 files of third-party upstream code under a separate
    licence, alongside supervisor-supplied code and code written here. The map
    is the only thing that can tell those apart -- git authorship cannot,
    because every commit is authored by the repo owner, including the one that
    vendored the upstream tree.

    An unclassified file is therefore a file whose licence and provenance
    nobody can state. That is a release blocker for a public repo, not a
    documentation nicety.
    """
    provenance = (REPO_ROOT / "PROVENANCE.md").read_text(encoding="utf-8")
    named = {Path(m).name for m in re.findall(r"[\w./-]+\.py", provenance)}

    # Tier A is defined by construction rather than by listing all 57 files,
    # and PROVENANCE.md gives the command that regenerates it. Use that same
    # command as the source of truth instead of duplicating the list here --
    # otherwise this gate would drift from the document it is checking.
    vendored = subprocess.run(
        ["git", "ls-tree", "-r", VENDORED_BASELINE_COMMIT, "--name-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    vendored_names = {Path(f).name for f in vendored}

    unclassified = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in _shipped_python_files()
        if p.name not in named and p.name not in vendored_names
    )

    assert not unclassified, (
        "PROVENANCE.md describes itself as the authoritative map of where "
        "every file came from, but these shipped files are not named in it, "
        "so their provenance and licence cannot be stated:\n"
        + "\n".join(f"  {f}" for f in unclassified)
    )


def _command_line_entry_points():
    """Files that parse argv, i.e. that a person is expected to run."""
    entry_points = []
    for path in _shipped_python_files():
        if path.parent != REPO_ROOT:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if "ArgumentParser" in source or "__main__" in source:
            entry_points.append(path)
    return entry_points


def _kill_tree(process):
    """Kill a process *and its descendants*.

    Necessary, not defensive: `launch_gui.py` deliberately re-executes the GUI
    under a different interpreter, so killing the direct child leaves the
    grandchild running. Terminating only the child is what turned an earlier
    version of this gate into a hang that outlived the test run and leaked
    GUI processes.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.kill()
    process.wait(timeout=10)


@pytest.mark.parametrize(
    "entry_point",
    _command_line_entry_points(),
    ids=lambda p: p.name,
)
def test_no_command_line_entry_point_hangs_on_help(entry_point):
    """`--help` must terminate. Anything else is undiagnosable in the field.

    `--help` is the first thing a person runs against an unfamiliar tool and
    the first thing a deployment smoke-check runs. It must not open a window,
    wait on input, or block on a heavy import. Exiting non-zero is acceptable
    here -- some of these legitimately need OpenSim, which is not installed
    under the test interpreter. Hanging is not: it gives the operator nothing
    to read, nothing to act on, and (as this repo does today) can leave an
    orphaned window running after the caller has given up.

    Streams go to DEVNULL rather than pipes on purpose. With pipes, a
    grandchild that inherits the handles keeps them open, so the read blocks
    even after the direct child is killed -- the timeout never fires and the
    gate hangs instead of reporting.
    """
    process = subprocess.Popen(
        [sys.executable, str(entry_point), "--help"],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        pytest.fail(
            f"{entry_point.name} did not terminate within 20s of being asked "
            "for --help. An entry point that blocks on --help cannot be "
            "smoke-tested by a deployment check, and gives an operator no way "
            "to discover how to run it."
        )


def test_the_path_load_detector_flags_a_file_that_is_not_there(tmp_path):
    """Proof that the gate below can fail. Without this, a green gate is
    indistinguishable from a gate that looks at nothing.
    """
    source = tmp_path / "loader.py"
    source.write_text(
        "import importlib.util\n"
        "def _load():\n"
        "    return importlib.util.spec_from_file_location('x', "
        "REPO_ROOT / 'definitely_absent.py')\n",
        encoding="utf-8",
    )
    assert "definitely_absent.py" in _referenced_module_filenames(source)


def test_the_path_load_detector_ignores_prose(tmp_path):
    """A filename discussed in a docstring is not a dependency.

    This codebase documents itself heavily and names other modules constantly
    -- `gdi.py` alone mentions half the repo. Flagging those would make the
    gate unusable, and worse, would train everyone to ignore it.
    """
    source = tmp_path / "documented.py"
    source.write_text(
        '"""This module explains how session_report.py works.\n\n'
        'It also mentions cohort_figures.py at length.\n"""\n'
        "\n"
        "def f():\n"
        '    """See also make_reports.py."""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    assert _referenced_module_filenames(source) == set()


def test_every_path_loaded_module_is_present_in_the_repo():
    """A file loaded by path must exist, or the caller breaks at runtime.

    The dependency gate above walks `import` statements. This repo mostly does
    not use them for its own modules: `module_loading.load_module_by_path`,
    the local `_load` helpers, and direct
    `importlib.util.spec_from_file_location` calls are the convention, chosen
    deliberately so callers work regardless of how they are launched.

    Nothing checks those. A module can name a file that is not on this branch
    and every import-based check stays green, because there is no import to
    look at -- the failure waits until someone runs it. That is exactly what
    happened on `feat/cohort-reporting`: `cohort_scores.py` loads
    `session_report.py`, which lives only on the picker branch, and the whole
    suite passed anyway.
    """
    present = {p.name for p in REPO_ROOT.rglob("*.py")}

    missing = {}
    for path in _shipped_python_files():
        for filename in _referenced_module_filenames(path):
            if filename not in present:
                missing.setdefault(filename, set()).add(
                    str(path.relative_to(REPO_ROOT))
                )

    assert not missing, (
        "these files are loaded by path but are not in the repository, so the "
        "modules naming them break at runtime while every import-based check "
        "stays green:\n"
        + "\n".join(
            f"  {name}  <- loaded by {', '.join(sorted(sources))}"
            for name, sources in sorted(missing.items())
        )
    )


def test_the_disabled_feature_set_is_refused_across_a_module_boundary():
    """The central safety claim, checked where the modules actually meet.

    `gdi.get_feature_set` deliberately passes a feature-set *object* through
    unchecked -- documented in its own docstring, because this repo loads
    modules by path and the same `gdi.py` can be live under two different
    module objects at once, which would break an isinstance check.
    `compute_gdi` is what closes that hole, and `gdi.py`'s comment states the
    consequence directly: "so no route reaches a score".

    `tests/test_gdi.py` already pins both guards inside one module object.
    What it cannot pin is the claim about *routes*, which is a property of the
    system rather than of `gdi.py`. This loads gdi twice, the way
    `module_loading.py` does at runtime, and passes a disabled set from one
    module object into the other -- the exact scenario the duck-typing note
    exists for.
    """
    import importlib.util

    def load(register_name):
        spec = importlib.util.spec_from_file_location(
            register_name, REPO_ROOT / "gdi.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    producer = load("gdi_producer")
    scorer = load("gdi_scorer")
    assert producer is not scorer, "the two loads must be distinct module objects"

    disabled = producer.GDI9
    assert disabled.is_disabled, (
        "this test is only meaningful while gdi9 is the disabled set; if it "
        "was re-enabled, point this at whichever set carries disabled_reason"
    )

    # The object path: `scorer` has never seen `producer`'s class, so an
    # isinstance check would reject it and a bare name check would miss it.
    with pytest.raises(scorer.GdiFeatureSetDisabledError):
        scorer.compute_gdi(
            feature_vector=None,
            reference={"feature_set": disabled},
            feature_set=disabled,
        )


def test_the_test_suite_runs_in_continuous_integration():
    """Green on one laptop is not evidence; green on every push is.

    Every readiness claim made about this repo so far -- 474 passing, then 589
    -- rests on someone remembering to run pytest locally, under the right
    one of the two interpreters this project uses. Nothing enforces that a
    change is tested before it lands, and nothing records that it was.

    For a clinical-facing pipeline whose stated purpose is to refuse to emit
    plausible wrong numbers, "we usually remember to run the tests" is the
    weakest link in the chain.
    """
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))

    assert workflows, (
        "no CI workflow found under .github/workflows. Nothing runs this "
        "suite automatically, so every passing-test claim about this repo is "
        "a claim about one machine at one moment, unreproducible by a reviewer."
    )

    runs_pytest = [
        w for w in workflows
        if "pytest" in w.read_text(encoding="utf-8", errors="replace")
    ]
    assert runs_pytest, (
        "CI workflows exist but none of them runs pytest: "
        + ", ".join(w.name for w in workflows)
    )


# -- the gates' own definition of "shipped" --------------------------------


def test_the_gates_judge_only_what_is_actually_shipped():
    """"Shipped" means tracked by git, not merely present on disk.

    Every gate above rests on `_shipped_python_files`, so its definition is
    the definition of the deliverable. Walking the working tree made that
    definition "whatever happens to be in this directory", which is a
    different thing: `.gitignore` lists `context/` precisely because those are
    local scratch copies of upstream sources, and an untracked analysis
    script mid-write is not part of any release either. Both were being
    reported as undeclared dependencies and as missing from PROVENANCE.md --
    failures that named files no user will ever receive, on a machine whose
    checkout is clean by definition.

    The failure this replaces was not cosmetic. A gate that cries wolf on
    local files is a gate people learn to ignore, and these are the gates
    that stand between the repo and a release nobody can install.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    tracked_paths = {(REPO_ROOT / name).resolve() for name in tracked}

    shipped = set(_shipped_python_files())

    assert shipped, "the gates found nothing to judge, so they prove nothing"
    untracked = sorted(str(p.relative_to(REPO_ROOT))
                       for p in shipped - tracked_paths)
    assert not untracked, (
        "these files are not tracked by git but the deployment gates treat "
        "them as part of the deliverable, so a local scratch file can fail a "
        "release gate:\n  " + "\n  ".join(untracked)
    )


def test_the_gates_do_not_lose_files_that_are_shipped():
    """The other half: narrowing the definition must not quietly empty it.

    A `git ls-files` that returned nothing -- wrong cwd, a detached worktree,
    git missing -- would make every gate above pass by having nothing to
    check, which is the most dangerous way for a gate to fail.
    """
    shipped = {p.name for p in _shipped_python_files()}

    for expected in ("gdi.py", "gait_event_picker.py",
                     "gait_event_picker_ui.py", "clinician_gui.py"):
        assert expected in shipped, (
            expected + " is tracked, shipped, and imported by the pipeline, "
            "but the deployment gates cannot see it.")


def test_excluded_directories_are_still_excluded():
    """Tracked-ness replaces the working-tree walk, not the exclusion list:
    `tests/` and `docs/` are tracked but are not what gets deployed."""
    shipped = _shipped_python_files()

    assert not [p for p in shipped
                if "tests" in p.relative_to(REPO_ROOT).parts]

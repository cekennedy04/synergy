r"""
Verifies the fix to Examples/gaitAnalysis-UCM.py's os.chdir() call (2026-08-16).

Before: os.chdir(os.path.abspath(r'\\fs2.ric.org\smulab2\alex\projects\opencap\opencap_git\opencap-processing'))
After:  os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

The goal: cwd should land on this repo's root, regardless of (a) which machine this runs on,
and (b) what the process's working directory was before the script started. This test doesn't
run the whole script (it imports opensim and the still-missing gait_analysis_UCM, neither of
which exist in this environment) -- it isolates just the chdir line and checks its behavior
directly, from several different starting directories.
"""
import ast
import os
import re
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TARGET_SCRIPT = os.path.join(REPO_ROOT, 'Examples', 'gaitAnalysis-UCM.py')

# Marker files/dirs that should only all be present together at the real repo root.
ROOT_MARKERS = ['README.md', 'VENDORING.md', 'ActivityAnalyses', 'Examples']


def _extract_chdir_line():
    """Pull the exact os.chdir(...) statement out of the real file, so this test fails loudly
    if someone changes that line to something else instead of silently testing stale logic."""
    with open(TARGET_SCRIPT, encoding='utf-8') as f:
        source = f.read()
    tree = ast.parse(source, filename=TARGET_SCRIPT)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'chdir'
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'os'):
            return ast.get_source_segment(source, node)
    raise AssertionError('No os.chdir(...) call found in ' + TARGET_SCRIPT)


def test_chdir_line_is_not_hardcoded_unc_path():
    line = _extract_chdir_line()
    assert 'fs2.ric.org' not in line, (
        'The hardcoded network path is back in gaitAnalysis-UCM.py: ' + line
    )
    assert '__file__' in line, (
        'Expected the chdir target to be derived from __file__ for portability, got: ' + line
    )


def test_chdir_resolves_to_repo_root_regardless_of_starting_cwd():
    chdir_line = _extract_chdir_line()

    runner = (
        "import os\n"
        "__file__ = {target!r}\n"
        "{chdir_line}\n"
        "print(os.getcwd())\n"
    ).format(target=TARGET_SCRIPT, chdir_line=chdir_line)

    starting_dirs = [
        REPO_ROOT,                                   # already at repo root
        os.path.join(REPO_ROOT, 'Examples'),          # typical IDE cwd when running this script
        tempfile.gettempdir(),                        # nowhere near the repo
        os.path.dirname(REPO_ROOT),                   # one level above the repo
    ]

    for start_dir in starting_dirs:
        result = subprocess.run(
            [sys.executable, '-c', runner],
            cwd=start_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            'Runner failed starting from {}: {}'.format(start_dir, result.stderr)
        )
        resolved_cwd = result.stdout.strip()
        assert os.path.normcase(os.path.normpath(resolved_cwd)) == os.path.normcase(os.path.normpath(REPO_ROOT)), (
            'Starting from {}, expected cwd to resolve to repo root {}, got {}'.format(
                start_dir, REPO_ROOT, resolved_cwd
            )
        )
        for marker in ROOT_MARKERS:
            assert os.path.exists(os.path.join(resolved_cwd, marker)), (
                'Resolved cwd {} is missing expected repo-root marker {}'.format(resolved_cwd, marker)
            )


def test_no_leftover_machine_specific_paths_in_script():
    with open(TARGET_SCRIPT, encoding='utf-8') as f:
        source = f.read()
    # Any remaining \\host\share-style UNC path is a sign a hardcoded path snuck back in.
    unc_paths = re.findall(r'\\\\\\\\[A-Za-z0-9_.-]+\\\\[A-Za-z0-9_.\\\\-]+', source)
    assert not unc_paths, 'Found leftover hardcoded UNC path(s) in script: ' + repr(unc_paths)

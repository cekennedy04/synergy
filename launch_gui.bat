@echo off
REM Launch the clinician GUI. Double-click this, or run it from any shell.
REM No `conda activate` needed -- launch_gui.py finds the opencap-processing
REM environment itself. See .claude/skills/run-gui/SKILL.md for details.

setlocal
cd /d "%~dp0"

REM Try whatever python is on PATH first; launch_gui.py re-execs into the right
REM environment from there. Fall back to the usual miniconda location for the
REM common case where conda was installed without touching PATH.
where python >nul 2>&1
if %errorlevel%==0 (
    python launch_gui.py %*
) else if exist "%USERPROFILE%\miniconda3\python.exe" (
    "%USERPROFILE%\miniconda3\python.exe" launch_gui.py %*
) else if exist "%USERPROFILE%\anaconda3\python.exe" (
    "%USERPROFILE%\anaconda3\python.exe" launch_gui.py %*
) else (
    echo error: no python found on PATH or in %USERPROFILE%\miniconda3.
    echo Install miniconda, or run launch_gui.py with a python you have.
    pause
    exit /b 2
)

if %errorlevel% neq 0 pause
endlocal

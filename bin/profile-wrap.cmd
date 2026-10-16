@echo off
rem profile-wrap launcher for Windows. Finds Python >= 3.10, then runs profile-wrap.py.
rem Override the interpreter with PROFILE_WRAP_PYTHON set to the full path of python.exe
setlocal
set "SCRIPT=%~dp0profile-wrap.py"

if defined PROFILE_WRAP_PYTHON (
  "%PROFILE_WRAP_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 ( "%PROFILE_WRAP_PYTHON%" "%SCRIPT%" %* & exit /b )
)
for %%V in (3.13 3.12 3.11 3.10) do (
  py -%%V -c "import sys" >nul 2>nul
  if not errorlevel 1 ( py -%%V "%SCRIPT%" %* & exit /b )
)
for %%P in (python3 python) do (
  %%P -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 ( %%P "%SCRIPT%" %* & exit /b )
)
where uv >nul 2>nul
if not errorlevel 1 ( uv run --no-project --python 3.12 "%SCRIPT%" %* & exit /b )

echo profile-wrap needs Python 3.10 or newer, and none was found. 1>&2
echo   Fix: winget install Python.Python.3.12   (or: scoop install python) 1>&2
echo   Or install uv (https://docs.astral.sh/uv/) and run: uv run --python 3.12 profile-wrap ... 1>&2
exit /b 1

@echo off
rem njli launcher for Windows. Finds Python >= 3.10, then runs njli.py.
rem Override the interpreter with NJLI_PYTHON set to the full path of python.exe
setlocal
set "SCRIPT=%~dp0njli.py"

if defined NJLI_PYTHON (
  "%NJLI_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 ( "%NJLI_PYTHON%" "%SCRIPT%" %* & exit /b )
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

echo njli needs Python 3.10 or newer, and none was found. 1>&2
echo   Fix: winget install Python.Python.3.12   (or: scoop install python) 1>&2
echo   Or install uv (https://docs.astral.sh/uv/) and run: uv run --python 3.12 njli ... 1>&2
exit /b 1

@echo off
setlocal
set "DESTINY_ROOT=%~dp0"
if exist "%DESTINY_ROOT%.venv\Scripts\python.exe" (
  "%DESTINY_ROOT%.venv\Scripts\python.exe" "%DESTINY_ROOT%scripts\destiny_analyzer.py" %*
) else (
  py -3 "%DESTINY_ROOT%scripts\destiny_analyzer.py" %*
)
exit /b %ERRORLEVEL%

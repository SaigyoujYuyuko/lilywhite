@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0rename.ps1" %*
set "RENAME_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %RENAME_EXIT%

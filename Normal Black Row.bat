@echo off
cd /d "%~dp0"
py -3 "%~dp0app_gui.py" %*
if errorlevel 1 pause

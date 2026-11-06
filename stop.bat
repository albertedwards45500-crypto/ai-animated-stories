@echo off
setlocal
title AI Drama - Stop All
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" -KeepWindow
endlocal

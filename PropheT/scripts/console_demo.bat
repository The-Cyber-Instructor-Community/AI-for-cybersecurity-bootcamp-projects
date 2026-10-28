@echo off
rem console_demo.bat: the Chimera Console over the demo folder (Oct 25): cases_demo holds the three real-call demo
rem cases (scripts\make_demo_cases.py) and copies of the ten synthetic ones, so the demo shows one list. Evidence
rem goes to out\ like the main Console's, because the LangFlow flow's components read out\<case>\evidence.md.
rem Double-click it, wait for "Uvicorn running", then open http://127.0.0.1:8421 (set CHIMERA_PORT to change it).
cd /d "%~dp0.."
rem Windows opened from the desktop can carry an old PATH; put winget's ffmpeg first (the voice check needs it).
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin;%PATH%"
set "CHIMERA_CASES=cases_demo"
set "CHIMERA_OUT=out"
if not defined CHIMERA_PORT set "CHIMERA_PORT=8421"
".venv\Scripts\python.exe" -m chimera.api
pause

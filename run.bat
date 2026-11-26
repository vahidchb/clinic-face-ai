@echo off
REM Run the clinic-face-ai service on Windows.
REM First time: copy .env.example to .env and put your Hormouz API key in it.
REM Then just double-click this file, or run .\run.bat in the VS Code terminal.
if not exist .env (
  echo .env not found - copy .env.example to .env and put your Hormouz API key in it.
  pause
  exit /b 1
)
for /f "eol=# tokens=1,* delims==" %%a in (.env) do set %%a=%%b
python -m uvicorn app:app --reload --port 8000

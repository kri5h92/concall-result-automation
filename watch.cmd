@echo off
:: ============================================================
:: Concall Watch Mode
:: Edit config.yaml to change tickers, models, and poll interval.
:: ============================================================

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo.
echo  Starting watch mode - config from config.yaml
echo  Press Ctrl+C to stop.
echo.

python main.py --watch

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: exited with code %ERRORLEVEL%
    pause
)

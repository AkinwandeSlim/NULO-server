@echo off
echo ========================================
echo   Nulo Africa - FastAPI Server
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
echo.

REM Install/update dependencies
echo Checking dependencies...
pip install -r requirements.txt --quiet
echo.

REM Start server
echo ========================================
echo   Starting FastAPI Server...
echo   API: http://localhost:8000
echo   Docs: http://localhost:8000/api/docs
echo ========================================
echo.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

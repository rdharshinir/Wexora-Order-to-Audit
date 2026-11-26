@echo off
echo ====================================================================
echo  WEXORA - Order-to-Audit ERP System
echo  Centre for Digital Infrastructure, NIT Tiruchirappalli
echo  "Every Order. Every Transaction. Complete Transparency."
echo ====================================================================
echo.

REM 1. Seed benchmark master data if not seeded
echo [1/2] Checking database and seeding Section 5 Benchmark data...
python backend/seed.py

REM 2. Launch FastAPI Full-Stack Server (serving API and Frontend)
echo [2/2] Starting WEXORA Full-Stack Server at http://127.0.0.1:8000 ...
echo.
echo Open your browser at: http://127.0.0.1:8000
echo Test Logins:
echo   - Factory Admin: admin
echo   - Salesman A (TN): salesman_a
echo   - Salesman B (KA): salesman_b
echo   - Production Supervisor: supervisor
echo   - Auditor: auditor
echo   - Owner: owner
echo.
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

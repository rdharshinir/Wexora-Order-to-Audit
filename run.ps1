# WEXORA - One-Click PowerShell Launcher
Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host " WEXORA - Order-to-Audit ERP System" -ForegroundColor Green
Write-Host " Centre for Digital Infrastructure, NIT Tiruchirappalli" -ForegroundColor Yellow
Write-Host " 'Every Order. Every Transaction. Complete Transparency.'" -ForegroundColor White
Write-Host "====================================================================" -ForegroundColor Cyan

# 1. Seed benchmark data
Write-Host "`n[1/2] Seeding Section 5 Benchmark Data..." -ForegroundColor Yellow
python backend/seed.py

# 2. Run server
Write-Host "`n[2/2] Launching WEXORA Server at http://127.0.0.1:8000 ..." -ForegroundColor Green
Write-Host "Web Application: http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "API Documentation: http://127.0.0.1:8000/docs" -ForegroundColor Cyan
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

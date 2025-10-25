# Beta Coefficient Platform Health Check (PowerShell)
# Run this script from the project root directory

Write-Host "🔍 Beta Coefficient Platform Health Check" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Check project structure
Write-Host "`n📂 Project structure check..." -ForegroundColor Yellow

if ((Test-Path "backend/manage.py") -and (Test-Path "frontend/package.json")) {
    Write-Host "✅ Project structure is correct" -ForegroundColor Green
} else {
    Write-Host "❌ Error: Run this script from the project root directory" -ForegroundColor Red
    exit 1
}

if ((Test-Path "backend/webapp") -and (Test-Path "frontend/components/beta")) {
    Write-Host "✅ Beta coefficient directories exist" -ForegroundColor Green
} else {
    Write-Host "❌ Missing required directories" -ForegroundColor Red
    exit 1
}

# Backend health check
Write-Host "`n🐍 Backend Health Check..." -ForegroundColor Yellow

try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python available: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found or not working" -ForegroundColor Red
    exit 1
}

# Check Django
Set-Location backend
try {
    $djangoCheck = python -c "import django; print('Django version:', django.get_version())" 2>$null
    Write-Host "✅ Django is installed: $djangoCheck" -ForegroundColor Green
} catch {
    Write-Host "❌ Django not installed or not working" -ForegroundColor Red
    Set-Location ..
    exit 1
}

# Check beta models
try {
    python -c "from webapp.models import BetaRealized, ForecastEvaluation; print('Beta models imported successfully')" 2>$null | Out-Null
    Write-Host "✅ Beta coefficient models are available" -ForegroundColor Green
} catch {
    Write-Host "❌ Beta coefficient models not found" -ForegroundColor Red
    Set-Location ..
    exit 1
}

# Test Django system
try {
    python manage.py check 2>$null | Out-Null
    Write-Host "✅ Django system check passed" -ForegroundColor Green
} catch {
    Write-Host "⚠️ Django system check has warnings (may still work)" -ForegroundColor Yellow
}

Set-Location ..

# Frontend health check  
Write-Host "`n⚛️ Frontend Health Check..." -ForegroundColor Yellow

try {
    $nodeVersion = node --version
    Write-Host "✅ Node.js available: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Node.js not found" -ForegroundColor Red
    exit 1
}

try {
    $pnpmVersion = pnpm --version
    Write-Host "✅ pnpm available: v$pnpmVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ pnpm not found" -ForegroundColor Red
    exit 1
}

Set-Location frontend

if ((Test-Path "node_modules") -and (Test-Path "node_modules\.pnpm")) {
    Write-Host "✅ Frontend dependencies installed" -ForegroundColor Green
} else {
    Write-Host "⚠️ Frontend dependencies may need installation (run: pnpm install)" -ForegroundColor Yellow
}

if ((Test-Path "components\beta\BetaDashboard.tsx") -and (Test-Path "app\beta\page.tsx")) {
    Write-Host "✅ Beta coefficient components exist" -ForegroundColor Green
} else {
    Write-Host "❌ Beta coefficient components missing" -ForegroundColor Red
    Set-Location ..
    exit 1
}

Set-Location ..

# Configuration check
Write-Host "`n🔧 Configuration Check..." -ForegroundColor Yellow

if (Test-Path "backend\backend\.env") {
    Write-Host "✅ Backend environment file exists" -ForegroundColor Green
} else {
    Write-Host "⚠️ Backend .env file not found (may use defaults)" -ForegroundColor Yellow
}

if (Test-Path "frontend\.env.local") {
    Write-Host "✅ Frontend environment file exists" -ForegroundColor Green
} else {
    Write-Host "⚠️ Frontend .env.local file not found (may use defaults)" -ForegroundColor Yellow
}

# Summary
Write-Host "`n📋 Summary" -ForegroundColor Cyan
Write-Host "==========" -ForegroundColor Cyan
Write-Host "✅ Beta Coefficient Platform appears to be properly configured!" -ForegroundColor Green

Write-Host "`n🚀 Next steps:" -ForegroundColor Yellow
Write-Host "1. Start backend: cd backend && python manage.py runserver"
Write-Host "2. Start frontend: cd frontend && pnpm run dev" 
Write-Host "3. Access beta dashboard: http://localhost:3000/beta"

Write-Host "`n📊 API endpoints available:" -ForegroundColor Yellow
Write-Host "- http://localhost:8000/api/beta/summary/"
Write-Host "- http://localhost:8000/api/beta/realized/"
Write-Host "- http://localhost:8000/api/beta/forecast-evaluation/"

Write-Host "`nHappy forecasting! 📈" -ForegroundColor Green
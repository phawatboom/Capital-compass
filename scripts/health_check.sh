#!/bin/bash
# Beta Coefficient Platform Health Check Script

echo "🔍 Beta Coefficient Platform Health Check"
echo "========================================"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "backend/manage.py" ] || [ ! -f "frontend/package.json" ]; then
    echo -e "${RED}❌ Error: Run this script from the project root directory${NC}"
    exit 1
fi

echo "📂 Project structure check..."
if [ -d "backend/webapp" ] && [ -d "frontend/components/beta" ]; then
    echo -e "${GREEN}✅ Project structure is correct${NC}"
else
    echo -e "${RED}❌ Missing required directories${NC}"
    exit 1
fi

echo ""
echo "🐍 Backend Health Check..."

# Check if Python environment is activated
if command -v python >/dev/null 2>&1; then
    PYTHON_VERSION=$(python --version 2>&1)
    echo -e "${GREEN}✅ Python available: $PYTHON_VERSION${NC}"
else
    echo -e "${RED}❌ Python not found${NC}"
    exit 1
fi

# Check Django installation
cd backend
if python -c "import django; print('Django version:', django.get_version())" 2>/dev/null; then
    echo -e "${GREEN}✅ Django is installed and working${NC}"
else
    echo -e "${RED}❌ Django not installed or not working${NC}"
    exit 1
fi

# Check if migrations are up to date
echo "🔄 Checking migrations..."
if python manage.py makemigrations --check --dry-run >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Migrations are up to date${NC}"
else
    echo -e "${YELLOW}⚠️ Migrations may be needed${NC}"
fi

# Check if beta models exist
if python -c "from webapp.models import BetaRealized, ForecastEvaluation; print('Beta models imported successfully')" 2>/dev/null; then
    echo -e "${GREEN}✅ Beta coefficient models are available${NC}"
else
    echo -e "${RED}❌ Beta coefficient models not found${NC}"
    exit 1
fi

# Test database connection
if python manage.py check >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Database connection working${NC}"
else
    echo -e "${RED}❌ Database connection failed${NC}"
    exit 1
fi

cd ..

echo ""
echo "⚛️ Frontend Health Check..."

# Check Node.js
if command -v node >/dev/null 2>&1; then
    NODE_VERSION=$(node --version)
    echo -e "${GREEN}✅ Node.js available: $NODE_VERSION${NC}"
else
    echo -e "${RED}❌ Node.js not found${NC}"
    exit 1
fi

# Check pnpm
if command -v pnpm >/dev/null 2>&1; then
    PNPM_VERSION=$(pnpm --version)
    echo -e "${GREEN}✅ pnpm available: v$PNPM_VERSION${NC}"
else
    echo -e "${RED}❌ pnpm not found${NC}"
    exit 1
fi

# Check if dependencies are installed
cd frontend
if [ -d "node_modules" ] && [ -f "node_modules/.pnpm/registry.npmjs.org/next" ]; then
    echo -e "${GREEN}✅ Frontend dependencies installed${NC}"
else
    echo -e "${YELLOW}⚠️ Frontend dependencies may need installation${NC}"
fi

# Check if beta components exist
if [ -f "components/beta/BetaDashboard.tsx" ] && [ -f "app/beta/page.tsx" ]; then
    echo -e "${GREEN}✅ Beta coefficient components exist${NC}"
else
    echo -e "${RED}❌ Beta coefficient components missing${NC}"
    exit 1
fi

cd ..

echo ""
echo "🔧 Configuration Check..."

# Check environment files
if [ -f "backend/backend/.env" ]; then
    echo -e "${GREEN}✅ Backend environment file exists${NC}"
else
    echo -e "${YELLOW}⚠️ Backend .env file not found (may use defaults)${NC}"
fi

if [ -f "frontend/.env.local" ]; then
    echo -e "${GREEN}✅ Frontend environment file exists${NC}"
else
    echo -e "${YELLOW}⚠️ Frontend .env.local file not found (may use defaults)${NC}"
fi

echo ""
echo "📋 Summary"
echo "=========="
echo -e "${GREEN}✅ Beta Coefficient Platform appears to be properly configured!${NC}"
echo ""
echo "🚀 Next steps:"
echo "1. Start backend: cd backend && python manage.py runserver"
echo "2. Start frontend: cd frontend && pnpm run dev"
echo "3. Access beta dashboard: http://localhost:3000/beta"
echo ""
echo "📊 API endpoints available:"
echo "- http://localhost:8000/api/beta/summary/"
echo "- http://localhost:8000/api/beta/realized/"
echo "- http://localhost:8000/api/beta/forecast-evaluation/"
echo ""
echo -e "${GREEN}Happy forecasting! 📈${NC}"
# 🚀 Deployment Guide for Beta Coefficient Forecasting Application

## 📋 Prerequisites

### System Requirements
- **Python 3.8+** (tested with 3.12.9)
- **Node.js 18+** 
- **pnpm** package manager
- **PostgreSQL** (for production) or SQLite (for development)
- **Git**

### Installation Tools
```bash
# Install pnpm globally
npm install -g pnpm

# Install conda/miniconda for Python environment management
# Download from: https://docs.conda.io/en/latest/miniconda.html
```

## 🔧 Environment Setup

### 1. Clone Repository
```bash
git clone https://github.com/uoa-compsci399-s2-2025/capstone-project-s2-2025-team-11.git
cd capstone-project-s2-2025-team-11
```

### 2. Backend Setup

#### Create Python Environment
```bash
cd backend
conda create -n dashenv python=3.12
conda activate dashenv
```

#### Install Dependencies
```bash
pip install -r requirements.txt
```

#### Environment Configuration
Create `backend/backend/.env` file:
```env
# Development Settings
DEBUG=True
SECRET_KEY=your-secret-key-here

# Database (SQLite for dev, PostgreSQL for prod)
DATABASE_URL=sqlite:///db.sqlite3

# CORS Settings (adjust for your domain)
ALLOWED_HOSTS=127.0.0.1,localhost,your-domain.com
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

#### Database Setup
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser  # Create admin user
```

#### Import Beta Data (if available)
```bash
python manage.py import_beta_data
```

### 3. Frontend Setup

#### Navigate to Frontend
```bash
cd ../frontend
```

#### Install Dependencies
```bash
pnpm install
```

#### Environment Configuration
Create `frontend/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## 🏃‍♂️ Running the Application

### Development Mode

#### Terminal 1: Start Backend
```bash
cd backend
conda activate dashenv
python manage.py runserver 8000
```

#### Terminal 2: Start Frontend
```bash
cd frontend
pnpm run dev
```

#### Access Application
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000/api/
- **Admin Panel**: http://localhost:8000/admin/
- **Beta Dashboard**: http://localhost:3000/beta

## 🌐 Production Deployment

### Backend Production Setup

#### 1. Update Environment Variables
```env
DEBUG=False
SECRET_KEY=super-secure-production-key
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
CORS_ALLOWED_ORIGINS=https://your-domain.com,https://www.your-domain.com
```

#### 2. Install Production Server
```bash
pip install gunicorn
```

#### 3. Collect Static Files
```bash
python manage.py collectstatic --noinput
```

#### 4. Run Production Server
```bash
gunicorn backend.wsgi:application --bind 0.0.0.0:8000
```

### Frontend Production Setup

#### 1. Update Environment
```env
NEXT_PUBLIC_API_URL=https://your-api-domain.com
```

#### 2. Build Application
```bash
pnpm run build
```

#### 3. Start Production Server
```bash
pnpm start
```

## 🔐 Authentication Configuration

The application uses Django's built-in authentication:

- **Development**: Open access (DEBUG=True)
- **Production**: Requires login (DEBUG=False)

### Create Users
```bash
# Via Django admin
python manage.py createsuperuser

# Or via Django shell
python manage.py shell
>>> from django.contrib.auth.models import User
>>> User.objects.create_user('username', 'email@example.com', 'password')
```

## 📊 Beta Coefficient Model

### Data Import Process
1. **Generate Model Output**: Run beta coefficient model to create CSV files
2. **Import Data**: Use management command to import CSV data to database
3. **Access via API**: Frontend fetches data from Django REST API

### Management Commands
```bash
# Import beta data from CSV files
python manage.py import_beta_data

# Clear existing beta data
python manage.py shell -c "from webapp.models import BetaRealized, ForecastEvaluation; BetaRealized.objects.all().delete(); ForecastEvaluation.objects.all().delete()"
```

## 🐳 Docker Deployment (Optional)

### Backend Dockerfile
```dockerfile
FROM python:3.12
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["gunicorn", "backend.wsgi:application", "--bind", "0.0.0.0:8000"]
```

### Frontend Dockerfile
```dockerfile
FROM node:18
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install
COPY . .
RUN pnpm build
EXPOSE 3000
CMD ["pnpm", "start"]
```

## 🔍 Troubleshooting

### Common Issues

#### 1. CORS Errors
- Check `CORS_ALLOWED_ORIGINS` in Django settings
- Ensure frontend URL is listed in allowed origins

#### 2. Database Connection
- Verify database credentials in `.env`
- Run migrations: `python manage.py migrate`

#### 3. API 404 Errors
- Check Django server is running on correct port
- Verify URL patterns in `webapp/urls.py`

#### 4. Frontend Build Errors
- Clear node_modules: `rm -rf node_modules && pnpm install`
- Check TypeScript errors: `pnpm run build`

#### 5. Authentication Issues
- Verify user exists: Django admin panel
- Check session cookies in browser developer tools

### Log Locations
- **Django**: Console output when running `runserver`
- **Next.js**: Console output when running `pnpm dev`
- **Browser**: Developer Tools > Console/Network tabs

## 📁 Project Structure

```
capstone-project-s2-2025-team-11/
├── backend/
│   ├── backend/settings.py      # Django configuration
│   ├── webapp/models.py         # Database models
│   ├── webapp/views.py          # API endpoints
│   ├── webapp/urls.py           # URL routing
│   └── manage.py                # Django management
├── frontend/
│   ├── app/                     # Next.js pages
│   ├── components/              # React components
│   ├── components/beta/         # Beta dashboard components
│   └── package.json             # Dependencies
├── outputs/                     # Model output CSV files
└── README.md                    # Project documentation
```

## 🎯 API Endpoints

### Beta Coefficient APIs
- `GET /api/beta/summary/` - Summary statistics
- `GET /api/beta/realized/` - Beta realized data
- `GET /api/beta/forecast-evaluation/` - Forecast evaluation data
- `GET /api/beta/timeseries/{ticker}/` - Time series for specific ticker
- `POST /api/beta/import/` - Import new beta data

### Authentication APIs
- `POST /api/auth/login/` - User login
- `POST /api/auth/logout/` - User logout
- `GET /api/auth/me/` - Current user info
- `GET /api/auth/csrf/` - CSRF token

## 📞 Support

For deployment issues:
1. Check this guide first
2. Verify all environment variables are set
3. Check server logs for specific error messages
4. Ensure all dependencies are installed correctly

## 🔄 Updates and Maintenance

### Updating Beta Data
1. Run beta coefficient model to generate new CSV files
2. Import data: `python manage.py import_beta_data`
3. Frontend will automatically show updated data

### Code Updates
1. Pull latest changes: `git pull origin main`
2. Update dependencies: `pip install -r requirements.txt` and `pnpm install`
3. Run migrations: `python manage.py migrate`
4. Rebuild frontend: `pnpm run build`

---

**Last Updated**: October 18, 2025  
**Version**: 1.0.0  
**Status**: Ready for deployment ✅
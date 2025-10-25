# Beta Coefficient Forecasting Platform

A comprehensive web application for forecasting and analyzing stock beta coefficients, built with Django REST Framework backend and Next.js frontend.

## 👥 Team Bobbers

| Name              | Specialization            |
|-------------------| ------------------------- |
| Henri Chemla      | Web Application |
| Trey Miller-Henry | Web Application |
| Phawat Saengsiripongpun | Web Application |
| Charles Benson    | Model/Stats     |
| Shawna Chandra    | Model/Stats     |
| Josh Nguyen       | Model/Stats     |

## 🎯 Overview

This platform integrates sophisticated beta coefficient forecasting models with a modern web interface, enabling users to:

- **Predict stock beta coefficients** using advanced ARIMA time series modeling
- **Visualize forecasting results** with interactive charts and confidence intervals  
- **Monitor prediction accuracy** with statistical validation (R², p-values, significance)
- **Access real-time data** through comprehensive REST API endpoints
- **Analyze market sensitivity** patterns across multiple stock portfolios

## 🏗️ Architecture

### Backend (Django REST Framework)
- **API**: RESTful endpoints for data management and model results
- **Database**: PostgreSQL with models for stock data and predictions
- **Models**: Integration with beta coefficient forecasting pipeline
- **Authentication**: User management and session handling

### Frontend (Next.js + TypeScript)
- **Dashboard**: Interactive beta coefficient visualization
- **Charts**: Time series plots with confidence intervals
- **Tables**: Sortable and filterable prediction summaries
- **Responsive**: Mobile-friendly interface using Tailwind CSS

### Data Pipeline
- **Model**: Advanced beta coefficient forecasting with ARIMA and OLS
- **Features**: Price-based predictors with statistical validation
- **Outputs**: CSV files with predictions and evaluation metrics

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- pnpm package manager
- PostgreSQL (optional, SQLite for development)

### Development Setup

#### 1. Clone Repository
```bash
git clone https://github.com/uoa-compsci399-s2-2025/capstone-team-bobbers.git
cd capstone-project-s2-2025-team-11
```

#### 2. Backend Setup
```bash
cd backend

pip install -r requirements.txt
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python manage.py migrate
python manage.py import_beta_data  # Import beta coefficient data
python manage.py runserver 8000
```

#### 3. Frontend Setup
```bash
cd frontend
pnpm install
pnpm run dev
```

#### 4. Access Application
- **Frontend**: http://localhost:3000
- 
### 📖 Deployment Guide

For detailed production deployment instructions, see **[readme-files/DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)**


### Database Import

Import beta coefficient model outputs:
```bash
# Import from default locations
python manage.py import_beta_data

# Import from custom files
python manage.py import_beta_data --betas-file path/to/betas.csv --forecast-file path/to/forecast.csv

# Clear existing data first
python manage.py import_beta_data --clear-existing
```


## 📈 Model Integration

### Running Predictions
```bash
# Run beta coefficient model
python data_analysis/bcoefficient_production_level_code_patched.py

# Import results to database
python manage.py import_beta_data

# Or use the automation script
python scripts/run_beta_model.py
```



## Web Application ERD draw.io

https://drive.google.com/file/d/1aYSvOKf-rMmw-iKoTTLAGJ-eNH6uc5Kg/view?usp=sharing

## If you want to code online

[![Open in Codespaces](https://classroom.github.com/assets/launch-codespace-2972f46106e565e64193e422d61a12cf1da4916b45550586e14ef0a7c637dd04.svg)](https://classroom.github.com/open-in-codespaces?assignment_repo_id=19989671)






# Backend Setup Guide

This guide will walk you through setting up the backend for the project. 
The backend is built using Django. 
We are in the process of migrating away from sqlite. 
We will soon require a PostgreSQL database to develop the web application.
Follow the steps below to configure and run the backend server.

---

## Prerequisites

1. **Python**: Ensure Python 3.10 or higher is installed on your system.
2. **PostgreSQL**: Install PostgreSQL and set up a database.
3. **PgAdmin4**: Download and install PgAdmin4 for managing your PostgreSQL database.

---

## Environment Setup

### 1. Create a `.env` File

Create a `.env` file in the `./backend` folder with the following format:

```env
DB_ENGINE=postgres
DEBUG=True
SECRET_KEY=django-insecure-5^xeqdu*#8a0agg1y&#@o7%sxw+l35mv1%!w@p%a_0qf*t@&j=

DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_HOST=localhost
DB_PORT=5432
MEDIA_ROOT=backend/db-media
```

Replace `your_database_name`, `your_database_user`, and `your_database_password` with the credentials for your PostgreSQL database.

`MEDIA_ROOT` points to the paths where you want to store media files during development.
If unspecified, the default will be `db-media` folders in the backend directory.

### 2. Install Dependencies
The project uses one set of dependencies:
- `requirements.txt`: Contains the core dependencies needed to run the backend.

To install the dependencies, run the following commands:
```# Navigate to the backend directory
cd backend

# Create a virtual environment
python -m venv venv

# Activate the virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install core dependencies
pip install -r requirements.txt

```

### 3. Set Up the Database
Ensure the migration files are located in the webapp/migrations folder. Then, run the following commands to apply migrations and set up the database:

```
python manage.py migrate
```

### 4. Run the Development Server
Start the Django development server with the following command:

```
python manage.py runserver
```

The server will start at http://127.0.0.1:8000/.


## Frontend (Next.js) Setup in PyCharm

1. Install Node.js (includes npm): https://nodejs.org (Reload after installation)
```bash
node -v
npm -v
```

2. Go to the frontend directory:
```bash
cd frontend
```

3. Install dependencies:
```bash
npm install
npm install axios
npm install react-date-range date-fns
```

4. Start the development server:
```bash
npm run dev
```

# Capital Compass, a Beta Coefficient Prediction Platform


A web application for forecasting and analyzing stock beta coefficients, built with Django REST Framework backend and Next.js frontend.

## Team 11 - Bobbers

| Name              | Specialization            |
|-------------------| ------------------------- |
| Henri Chemla      | Web Application |
| Trey Miller-Henry | Web Application |
| Phawat Saengsiripongpun | Web Application |
| Charles Benson    | Model/Stats     |
| Shawna Chandra    | Model/Stats     |
| Josh Nguyen       | Model/Stats     |

## What is Capital Compass?

Capital Compass is a web application designed to predict and analyze the beta coefficients of stocks. 
Beta coefficients are crucial in finance as they measure a stock's volatility relative to the overall market. 
By accurately predicting these coefficients, investors can make informed decisions about their portfolios, balancing risk and return effectively.


## Project Management Tool

We use GitHub Projects for project management. You can view our project board here:

https://github.com/orgs/uoa-compsci399-s2-2025/projects/10


## Usage Examples


## Public-Facing URL

The application is currently live at the following URL:
### http://3.104.120.14


# Web Application Setup Guide

This guide will walk you through setting up the backend for the project. 
The backend is built using Django.
Follow the steps below to configure and run the backend server.

---

## Prerequisites

1. **Python**: Ensure Python 3.10 or higher is installed on your system.
2. **PostgreSQL**: Install PostgreSQL and set up a database.
3. **PgAdmin4**: Download and install PgAdmin4 for managing your PostgreSQL database.

---

## Clone the Repository

```bash
git clone https://github.com/uoa-compsci399-s2-2025/capstone-team-bobbers.git
cd capstone-team-bobbers
```


## Environment Setup

### 1. Create a backend `.env` File

Create a `.env` file in the `./backend/backend` folder with the following format:

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

---

## Frontend Setup


1. Go to the frontend directory:
```bash
cd frontend
```

2. Create a frontend `.env` file with the following contents:
```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api 
```

3. Install dependencies:
```bash
npm install
```

4. Start the development server:
```bash
npm run dev
```

5. Open your browser and navigate to http://127.0.0.1:3000 to view the frontend application.

6. If you want to build the frontend for production, run:
```bash
npm run build
``` 
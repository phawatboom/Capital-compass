## Hi Team Bobbers!


## Team members and specializations

| Name              | Spec            |
|-------------------| --------------- |
| Henri Chemla      | Web Application |
| Trey Miller-Henry | Web Application |
| Phawat Saengsiripongpun | Web Application |
| Charles Benson    | Model/Stats     |
| Shawna Chandra    | Model/Stats     |
| Josh Nguyen       | Model/Stats     |

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
```

4. Start the development server:
```bash
npm run dev
```

#### The frontend will run at http://localhost:3000/
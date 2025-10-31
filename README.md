# Project 35: Developing quantitative tools to assist trading decisions in US equity market.


A web application for forecasting and analyzing stock beta coefficients, built with a Django REST Framework backend and a Next.js frontend.

## Team 11 - Bobbers

| Name               | Github Username | Specialization  |
|--------------------|-----------------|-----------------|
| Henri Chemla       | neryadom        | Web Application |
| Trey Miller-Henry  |                 | Web Application |
| Phawat Saengsiripongpun|                 | Web Application |
| Charles Benson     |                 | Model/Stats     |
| Shawna Chandra     |                 | Model/Stats     |
| Hoang Nguyen       |                 | Model/Stats     |

## What is Capital Compass?

Our application called Capital Compass is designed to predict and analyze the beta coefficients of stocks. 
Beta coefficients are crucial in finance as they measure a stock's volatility relative to the overall market. 
By accurately predicting these coefficients, investors can make informed decisions about their portfolios, balancing risk and return effectively.


## Project Management Tool

We use GitHub Projects for project management. You can view our project board here:

https://github.com/orgs/uoa-compsci399-s2-2025/projects/10


## Technologies

Backend (Python):
- Python 3.10+
- Django 5.2.5
- Django REST Framework 3.16.1
- django-cors-headers 4.7.0
- django-environ 0.12.0
- djangorestframework-simplejwt 5.5.1
- psycopg2 2.9.10 (PostgreSQL driver)
- NumPy 2.1.3, pandas 2.2.2
- Matplotlib, statsmodels, scikit-learn, joblib (modeling/analysis)
- boto3, django-storages (optional: cloud storage integration)
- Tooling: pytest 8.4.1, pytest-django 4.11.1, pytest-cov 6.2.1, ruff 0.12.11

Frontend (TypeScript/React):
- Node.js 18.18+ or 20+
- Next.js 15.4.7, React 18.3.1, TypeScript 5.9.2
- Tailwind CSS 4.1.9
- axios 1.12.2, recharts 3.1.2
- Radix UI component primitives (various @radix-ui/* packages)
- zod 3.25.67, react-hook-form 7.60.0

Infrastructure:
- PostgreSQL 14+ (local dev) and pgAdmin 4 (optional)


## Usage Examples


## Public-Facing URL

The application is currently live at the following URL:
### http://3.104.120.14


# Web Application Setup Guide

This guide will walk you through setting up the backend for the project. 
The backend is built using Django. The frontend is built using Next.js
Follow the steps below to configure and run the backend server and frontend locally.

---

## Prerequisites

1. **Python**: Ensure Python 3.10 or higher is installed on your system.
2. **PostgreSQL**: Install PostgreSQL and set up a database.
3. **PgAdmin4**: Download and install PgAdmin4 for managing your PostgreSQL database.
4. **Node.js and pnpm**: Install Node.js (version 18.18 or higher) and pnpm package manager for the frontend.

## Dependencies

1. **Backend Dependencies**: Listed in `requirements.txt` in the backend directory.
2. **Frontend Dependencies**: Listed in `package.json` in the frontend directory.
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


### 1. Go to the frontend directory:
```bash
cd frontend
```

### 2. Create a frontend `.env` file with the following contents:
```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api 
```

### 3. Install dependencies:
```bash
# From the repo root
cd frontend
pnpm install
```

### 4. Start the frontend development server
```bash
pnpm dev
```
Open your browser and navigate to http://127.0.0.1:3000 to view the frontend application.

### 5. If you want to build the frontend for production, run:
```bash
pnpm build

#once the application is built, serve it with:
pnpm start
``` 


---

# Future Plans

In future versions of our product, a central focus would be the implementation of machine learning to enhance the models accuracy. The current system only uses statistical indicators and standard time-series metrics derived from the returns data. In the future developments should incorporate predictive models capable of learning complex, subtle, and nonlinear relationships in complex and noisy market data. Techniques such as recurrent neural networks (RNNs), random forests, and gradient boosting should be explored thoroughly because these technologies are industry standard for this type of analysis.

Another important change will be to expand the dataset beyond simple returns derived features. We think incorporating other data such as volume, order book dynamics, sentiment indicators, and companies finances etc could provide more insight into stock behavior. 

For the web application, implementing permission tiers is a significant step toward scalability and security. Future versions of the web application should support multiple account types, from basic users with access to the analysis, to more advanced users who can run analysis, or adjust model parameters etc.

---

# Acknowledgements

We would like to acknowledge our client Nicholas Bagnall for his invaluable guidance 
and support throughout the development of this project. 

We would also like to thank our Anna Trofimova, course instructors and teaching assistants for their assistance and feedback.

We would also like to thank Matt Edwards and Andrew Balemni for their help with the model.

Finally, we appreciate the open-source community for providing the tools and libraries that made this project possible.

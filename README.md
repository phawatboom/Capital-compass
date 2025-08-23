## Hi Team Bobbers!


## Team members and specilizations

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

## Setup Environment

Get into the backend folder:

```bash
cd backend
```

### Create a venv:

#### On a Windows system:
```bash
python -m venv venv
```

#### Or on macOS/Linux system:
```bash
python3 -m venv venv
```

### Then activate the venv:

#### on a Windows system:
```bash
venv\Scripts\activate
```

#### On a macOS/Linux system:
```bash
source venv/bin/activate 
```


## Install dependencies
pip install -r requirements.txt


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

## Testing CSV Upload and Download Features

### 1. Start the Backend
#### Open a Git Bash terminal and navigate to the backend folder:
```bash
cd backend
```

#### Activate the virtual environment:
###### on a Windows system:
```bash
venv\Scripts\activate
```

###### On a macOS/Linux system:
```bash
source venv/bin/activate 
```

#### Run the Django development server:
```bash
python manage.py runserver
```

### 2. Start the Frontend
#### Open a second Git Bash terminal and navigate to the frontend folder:
```bash
cd frontend
```

#### Start the Next.js development server:
```bash
pnpm run dev
#switch to use pnpm instead because it is faster
#npm run dev
```
#### The frontend will run at http://localhost:3000/
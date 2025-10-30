# 🚀 Quick Setup Guide for Team Members

## Prerequisites
- Python 3.12 (check: `python --version`)
- Node.js 18+ (check: `node --version`)
- pnpm (install: `npm install -g pnpm`)

## 1. Backend Setup (5 minutes)

```bash
cd backend

# Create environment file
copy backend\.env.example backend\.env
# Edit .env file if needed (SQLite is fine for development)

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup database
python manage.py migrate

# Test the server
python manage.py runserver
# Should see: "Starting development server at http://127.0.0.1:8000/"
```

## 2. Frontend Setup (3 minutes)

```bash
cd frontend

# Install dependencies
pnpm install

# Start development server
pnpm run dev
# Should see: "Ready - started server on http://127.0.0.1:3000"
```

## 3. Test Data Upload

1. Go to http://localhost:3000/upload
2. Upload a CSV file with "prices" in the filename
3. CSV should have specific format (see examples in test_data folder)

## 4. Common Issues

### "Could not determine data type from CSV filename"
- **Fix**: Ensure filename contains "prices", "returns", or "bql_query"
- **Example**: `my_stock_prices.csv` ✅, `data.csv` ❌

### "No valid stock names found in header"
- **Fix**: Check if stock names contain exchange codes (UN, UW, UQ, UF)
- **Example**: `AAPL UW`, `MSFT UN`

### Database connection errors
- **Fix**: Check if `.env` file exists in `backend/backend/`
- **Fix**: Use SQLite (default) for development

### Date parsing errors
- **Fix**: Use supported date formats: DD-MMM-YYYY, YYYY-MM-DD, DD/MM/YYYY

## 5. Need Help?
- Check FAQ_TROUBLESHOOTING.md
- Look at test files in backend/webapp/test_data/
- Run tests: `python manage.py test webapp.CSVUploadTest`
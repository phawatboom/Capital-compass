# AWS Deployment Guide for Integrated Universal Beta Platform

## 🚀 **Complete Integrated Solution Architecture**

Your platform now supports **both** pre-trained models AND custom client data analysis within a single AWS deployment:

### **🎯 Client Workflow (All in One Build)**
1. **Upload** → Client uploads CSV data via web interface
2. **Process** → Universal model runs in background (2-5 minutes)
3. **Store** → Results saved to database automatically  
4. **Display** → Frontend shows personalized dashboard
5. **Compare** → Access pre-trained models for benchmarking

---

## 📊 **Architecture Overview**

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Frontend      │    │    Backend       │    │   Database      │
│   (Next.js)     │◄──►│   (Django)       │◄──►│  (PostgreSQL)   │
│                 │    │                  │    │                 │
│ • Upload UI     │    │ • File Upload    │    │ • Universal     │
│ • Dashboard     │    │ • Model Runner   │    │   Predictions   │
│ • Results View  │    │ • API Endpoints  │    │ • Client Results│
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         │              ┌────────▼────────┐             │
         │              │   File Storage  │             │
         │              │   (S3/EFS)      │             │
         │              │                 │             │
         └──────────────► • Client CSV    │◄────────────┘
                        │ • Model Results │
                        │ • Temp Files    │
                        └─────────────────┘
```

---

## 🏗️ **AWS Infrastructure Setup**

### **Option 1: Elastic Beanstalk (Recommended)**

**Benefits:**
- ✅ Handles auto-scaling
- ✅ Load balancing 
- ✅ Health monitoring
- ✅ Easy deployments
- ✅ Cost-effective for variable workloads

```bash
# 1. Install EB CLI
pip install awsebcli

# 2. Initialize Elastic Beanstalk
cd capstone-project-s2-2025-team-11
eb init universal-beta-platform

# 3. Create environment
eb create production --database.engine postgres

# 4. Deploy
eb deploy
```

### **Option 2: ECS with Fargate**

**Benefits:**
- ✅ Containerized deployment
- ✅ Serverless compute
- ✅ Fine-grained resource control
- ✅ Easy scaling

### **Option 3: EC2 with Docker**

**Benefits:**
- ✅ Full control
- ✅ Cost predictable
- ✅ Custom configurations

---

## 🔧 **Required AWS Services**

### **Compute**
- **EC2/ECS/Elastic Beanstalk**: Run Django backend + model processing
- **Lambda** (optional): For model trigger functions

### **Storage**
- **RDS PostgreSQL**: Main database for predictions and results
- **S3**: Client file uploads and model outputs
- **EFS** (optional): Shared file system for multi-instance setups

### **Infrastructure**
- **Application Load Balancer**: Route traffic to frontend/backend
- **CloudFront**: CDN for frontend static files
- **Route 53**: DNS management
- **VPC**: Network isolation

### **Monitoring & Logs**
- **CloudWatch**: Application monitoring and logs
- **SNS**: Notifications for model completion

---

## 📁 **File Structure for Deployment**

```
capstone-project-s2-2025-team-11/
├── backend/
│   ├── Dockerfile                  # Django container
│   ├── requirements.txt           # Python dependencies
│   ├── .platform/                # EB configuration
│   └── webapp/
│       ├── integrated_universal_model.py
│       ├── views_integrated.py
│       └── models_universal.py
├── frontend/
│   ├── Dockerfile                 # Next.js container
│   ├── package.json
│   └── components/beta/
│       ├── IntegratedWorkflow.tsx
│       └── UniversalBetaDashboard.tsx
├── docker-compose.yml            # Local development
├── .ebextensions/               # Elastic Beanstalk config
└── deploy/                      # Deployment scripts
```

---

## 🛠️ **Step-by-Step Deployment**

### **Step 1: Prepare Environment Files**

Create `.env.production`:
```bash
# Database
DATABASE_URL=postgresql://username:password@your-rds-endpoint:5432/betadb

# AWS Settings
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_STORAGE_BUCKET_NAME=universal-beta-uploads
AWS_S3_REGION_NAME=us-east-1

# Django Settings
SECRET_KEY=your-super-secret-key
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Frontend
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
```

### **Step 2: Database Setup**

```sql
-- Create RDS PostgreSQL instance
-- Then run migrations:
```

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --noinput
```

### **Step 3: S3 Configuration**

```python
# settings.py additions
import os

# S3 Settings for file uploads
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

# Use S3 for media files (client uploads)
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'

# Static files (use S3 or CloudFront)
STATICFILES_STORAGE = 'storages.backends.s3boto3.StaticS3Boto3Storage'
STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/static/'
```

### **Step 4: Elastic Beanstalk Configuration**

Create `.ebextensions/01_packages.config`:
```yaml
packages:
  yum:
    postgresql-devel: []
    gcc: []
    python3-devel: []

option_settings:
  aws:elasticbeanstalk:application:environment:
    DJANGO_SETTINGS_MODULE: backend.settings
    PYTHONPATH: /opt/python/current/app
  aws:elasticbeanstalk:container:python:
    WSGIPath: backend.wsgi:application
```

Create `.ebextensions/02_django.config`:
```yaml
container_commands:
  01_migrate:
    command: "source /opt/python/run/venv/bin/activate && python manage.py migrate --noinput"
    leader_only: true
  02_collectstatic:
    command: "source /opt/python/run/venv/bin/activate && python manage.py collectstatic --noinput"
  03_create_superuser:
    command: "source /opt/python/run/venv/bin/activate && python manage.py shell -c \"from django.contrib.auth.models import User; User.objects.filter(username='admin').exists() or User.objects.create_superuser('admin', 'admin@example.com', 'adminpass123')\""
    leader_only: true
```

### **Step 5: Docker Setup (Alternative)**

Create `Dockerfile` for backend:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "backend.wsgi:application"]
```

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  db:
    image: postgres:13
    environment:
      POSTGRES_DB: betadb
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/betadb
    depends_on:
      - db
    volumes:
      - ./backend:/app
      - media_volume:/app/media

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000

volumes:
  postgres_data:
  media_volume:
```

---

## 💰 **Cost Optimization**

### **For Client Processing Workloads:**

1. **Use Spot Instances** for model training (save 70%)
2. **Auto Scaling Groups** - scale down when no processing
3. **S3 Intelligent Tiering** for file storage
4. **CloudFront** for frontend caching
5. **RDS Reserved Instances** for predictable database costs

### **Estimated Monthly Costs:**

| Component | Basic Setup | Production Setup |
|-----------|-------------|------------------|
| **EC2/ECS** | $20-50 | $100-300 |
| **RDS PostgreSQL** | $15-30 | $50-150 |
| **S3 Storage** | $5-10 | $20-50 |
| **Load Balancer** | $15 | $15 |
| **Data Transfer** | $5-10 | $20-50 |
| **Total** | **$60-115** | **$205-565** |

---

## 🔄 **Client Processing Workflow**

### **1. File Upload** (Immediate)
```
Client uploads CSV → S3 storage → Database record created
```

### **2. Model Processing** (2-5 minutes)
```
Background task → Feature engineering → Model training → Predictions generated
```

### **3. Results Storage** (Automatic)
```
Model outputs → Structured format → Database import → Frontend ready
```

### **4. Dashboard Display** (Real-time)
```
API endpoints → Dashboard refresh → Client-specific results shown
```

---

## 🚦 **Monitoring & Alerts**

### **CloudWatch Metrics:**
- Model processing time
- API response times  
- Database connections
- S3 storage usage
- Error rates

### **SNS Notifications:**
- Model completion alerts
- Processing failures
- System health issues

---

## 🔐 **Security Considerations**

1. **VPC**: Isolate resources in private subnets
2. **IAM Roles**: Least privilege access
3. **S3 Bucket Policies**: Secure file uploads
4. **SSL/TLS**: HTTPS everywhere
5. **Database**: Encrypted at rest and in transit
6. **CORS**: Proper frontend/backend communication

---

## 🎉 **Deployment Result**

After deployment, clients can:

1. **Visit your domain** → See complete beta platform
2. **Upload CSV data** → Automatic processing starts
3. **Wait 2-5 minutes** → Model runs in background
4. **View results** → Personalized dashboard appears
5. **Compare models** → Access pre-trained benchmarks
6. **Export data** → Download predictions and metrics

**Everything runs within a single AWS deployment** - no separate data import needed!

---

## 📞 **Next Steps**

1. Choose deployment method (Elastic Beanstalk recommended)
2. Set up AWS services (RDS, S3, etc.)
3. Configure environment variables
4. Deploy and test with sample data
5. Set up monitoring and alerts
6. Go live with client access!

The platform is now **production-ready** for AWS deployment with full client data processing capabilities! 🚀
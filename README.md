# 🐍 Nulo Africa - FastAPI Backend

## Python Backend with Supabase Integration

---

## 🚀 **Quick Start**

```bash
# 1. Create virtual environment
python -m venv venv

# 2. Activate virtual environment
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env  # Edit with your credentials

# 5. Run server
uvicorn app.main:app --reload --port 8000
```

**Server will be available at:**
- API: http://localhost:8000
- Swagger Docs: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

---

## 📁 **Project Structure**

```
server/
├── app/
│   ├── routes/              # API endpoints
│   │   ├── auth.py         # Authentication
│   │   ├── properties.py   # Property management
│   │   ├── applications.py # Tenant applications
│   │   ├── tenants.py      # Tenant profiles
│   │   ├── favorites.py    # Saved properties
│   │   └── messages.py     # Messaging system
│   │
│   ├── models/              # Pydantic models
│   │   ├── user.py         # User models
│   │   └── property.py     # Property models
│   │
│   ├── middleware/          # Middleware
│   │   └── auth.py         # JWT authentication
│   │
│   ├── main.py             # FastAPI app
│   ├── config.py           # Configuration
│   └── database.py         # Supabase client
│
├── requirements.txt         # Python dependencies
├── .env.example            # Environment template
└── README.md               # This file
```

---

## 🔑 **Environment Variables**

Required in `.env`:

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_service_role_key

# JWT
JWT_SECRET_KEY=your_secret_key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=True

# CORS
ALLOWED_ORIGINS=http://localhost:3000
```

---

## 📡 **API Endpoints**

### **Authentication** (`/api/v1/auth`)
- `POST /register` - Register new user
- `POST /login` - Login user
- `GET /me` - Get current user
- `POST /logout` - Logout user

### **Properties** (`/api/v1/properties`)
- `GET /search` - Search properties
- `POST /` - Create property (landlord only)
- `GET /{id}` - Get property details
- `PATCH /{id}` - Update property (landlord only)
- `DELETE /{id}` - Delete property (landlord only)

### **Applications** (`/api/v1/applications`)
- `POST /` - Submit application (tenant only)
- `GET /` - Get user applications
- `PATCH /{id}/approve` - Approve application (landlord only)
- `PATCH /{id}/reject` - Reject application (landlord only)

### **Tenants** (`/api/v1/tenants`)
- `GET /profile` - Get tenant profile
- `POST /complete-profile` - Complete profile (deferred KYC)
- `PATCH /profile` - Update profile

### **Favorites** (`/api/v1/favorites`)
- `GET /` - Get saved properties
- `POST /` - Add to favorites
- `DELETE /{property_id}` - Remove from favorites

### **Messages** (`/api/v1/messages`)
- `GET /conversations` - Get conversations
- `GET /{user_id}` - Get messages with user
- `POST /` - Send message

---

## 🔐 **Authentication**

All protected endpoints require JWT token in header:

```bash
Authorization: Bearer <your_jwt_token>
```

**Example:**
```python
import requests

headers = {
    "Authorization": f"Bearer {access_token}"
}

response = requests.get(
    "http://localhost:8000/api/v1/auth/me",
    headers=headers
)
```

---

## 🧪 **Testing**

### **Using Swagger UI**
1. Go to http://localhost:8000/api/docs
2. Click "Authorize" button
3. Enter JWT token
4. Try endpoints interactively

### **Using curl**
```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "password123",
    "full_name": "Test User",
    "user_type": "tenant"
  }'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "password123"
  }'
```

---

## 🛠️ **Development**

### **Running in Development Mode**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### **Code Formatting**
```bash
# Format code with black
black app/

# Lint with flake8
flake8 app/

# Type checking with mypy
mypy app/
```

### **Running Tests**
```bash
pytest tests/ -v
```

---

## 📦 **Dependencies**

- **fastapi** - Modern web framework
- **uvicorn** - ASGI server
- **supabase** - Database client
- **pydantic** - Data validation
- **python-jose** - JWT handling
- **passlib** - Password hashing

---

## 🚀 **Deployment**

### **Railway**
```bash
railway up
```

### **Render**
1. Connect GitHub repo
2. Select "Python" environment
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### **Docker**
```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 📝 **Notes**

- Always activate virtual environment before running
- Keep `.env` file secure (never commit to Git)
- Use Swagger docs for API testing
- Check logs for errors
- CORS is configured for frontend at localhost:3000

---

## 🐛 **Troubleshooting**

**Module not found:**
```bash
pip install -r requirements.txt
```

**Port already in use:**
```bash
uvicorn app.main:app --reload --port 8001
```

**Supabase connection error:**
- Check `.env` credentials
- Verify Supabase project is active

---

**Happy Coding!** 🎉

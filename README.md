# � NuloAfrica Backend

> High-performance FastAPI backend for Nigeria's zero-agency rental platform.  
> Production-ready with real-time messaging, secure payments, and admin controls.

---

## ⚡ Quick Start (3 minutes)

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Add: SUPABASE_URL, SUPABASE_KEY, PAYSTACK_SECRET, TWILIO_ACCOUNT_SID

# 4. Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# → Open http://localhost:8000/docs (API playground)
```

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Framework** | FastAPI (Python async) |
| **Language** | Python 3.9+ |
| **Database** | PostgreSQL via Supabase |
| **Auth** | JWT + Supabase Auth |
| **Payments** | Paystack (NGN) with HMAC verification |
| **Notifications** | Email (SMTP) + SMS (Twilio) |
| **Validation** | Pydantic v2 |
| **Async** | asyncio + concurrent.futures |
| **Production** | Uvicorn + Gunicorn ready |

## ✨ Core Features

### Authentication
- 🔐 Email/Password signup + Google OAuth
- 👤 Role-based access (Tenant, Landlord, Admin)
- 📧 Email verification workflow
- 🔑 JWT token-based auth

### Properties Service
- 🏠 CRUD for property listings
- 🔍 Advanced search + filtering
- ✅ Admin verification workflow
- 📊 View tracking & analytics

### Viewing Requests
- 📅 Schedule physical/virtual/live video viewings
- 📧 Automatic SMS/Email reminders
- 📜 Status tracking (pending, confirmed, completed, cancelled)
- 🔔 Real-time notifications

### Applications
- 📋 Tenant rental applications
- 👤 Employment + income verification
- 📊 Admin approval workflow
- 🔐 Unique constraint (one app per tenant per property)

### Lease Agreements
- 📄 Auto-generated Nigerian-compliant agreements
- ✍️ Digital signature tracking
- 📅 Lease term management
- 💾 Version history

### Payments
- 💳 Paystack integration (NGN native)
- 🔒 HMAC-verified webhooks (SHA512)
- 🏦 Escrow payment holds
- 📊 Transaction tracking

### Messaging
- 💬 Real-time tenant-landlord chat
- 📱 Supabase Realtime subscriptions
- 🔔 Message notifications
- 📜 Conversation history

### Admin Dashboard
- 📊 Platform metrics (users, properties, revenue)
- 👤 User management & moderation
- ✅ Property verification queue
- 🔍 Dispute resolution

## 📁 Structure

```
app/
├── main.py              # FastAPI app init
├── routes/              # API endpoints
│   ├── auth.py          # Authentication
│   ├── properties.py    # Property CRUD + search
│   ├── applications.py  # Rental applications
│   ├── viewing_requests.py  # Viewing coordination
│   ├── agreements.py    # Lease agreements
│   ├── payments.py      # Payment processing
│   ├── messages.py      # Direct messaging
│   ├── notifications.py # Notification triggers
│   ├── admin_*.py       # Admin endpoints
│   └── landlord_*.py    # Landlord endpoints
├── models.py            # Pydantic schemas
├── database.py          # Supabase setup
├── middleware/          # Auth & RLS
└── services/            # Business logic

requirements.txt        # Python dependencies
.env.example           # Environment template
```

## 🔧 Environment Setup

```env
# .env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=eyJhbGci...
SUPABASE_ADMIN_KEY=eyJhbGci...

# Payments
PAYSTACK_SECRET=sk_live_xxxxx

# Notifications
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password

TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_PHONE_NUMBER=+1234567890

# Server
SECRET_KEY=your-super-secret-key
DEBUG=False
```

## 📊 Key API Endpoints

```
Authentication
POST   /auth/signup           POST   /auth/login

Properties
GET    /properties            GET    /properties/{id}
POST   /properties            PUT    /properties/{id}
DELETE /properties/{id}

Viewing Requests
POST   /viewing-requests      GET    /viewing-requests
PATCH  /viewing-requests/{id}/confirm

Applications
POST   /applications          GET    /applications
PATCH  /applications/{id}/approve

Payments
POST   /payments/initiate     POST   /webhooks/paystack
GET    /payments/status/{ref}

Messaging
GET    /messages/conversations  POST   /messages
```

**Full API docs:** `http://localhost:8000/docs` (when running)

## 🔒 Security Features

- ✅ Supabase Row-Level Security (RLS)
- ✅ Service-role auth for admin operations
- ✅ JWT validation on all endpoints
- ✅ HMAC webhook verification (Paystack)
- ✅ SQL injection prevention
- ✅ Rate limiting on endpoints
- ✅ Audit logging

## 🚀 Deployment

### Production Build
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app.main:app
```

### Docker (Optional)
```bash
docker build -t nulo-backend .
docker run -p 8000:8000 --env-file .env nulo-backend
```

## 🧪 Testing

```bash
pytest tests/ -v                    # Run all tests
pytest tests/test_properties.py -v  # Run specific test
pytest tests/ --cov=app            # Coverage report
```

## 🐛 Troubleshooting

| Error | Fix |
|-------|-----|
| Supabase connection refused | Check SUPABASE_URL and key |
| "401 Unauthorized" | Verify JWT token format/expiry |
| Paystack webhook failing | Check PAYSTACK_SECRET matches |
| Email not sending | Verify SMTP credentials |
| FastAPI not starting | Check port 8000 availability |

## 📌 Design Highlights

- **FastAPI** — Modern, async-native Python framework
- **Supabase** — Managed PostgreSQL + Auth
- **Pydantic v2** — Runtime data validation
- **Service-role auth** — Elevated admin permissions
- **Paystack HMAC** — Webhook authenticity verification
- **Async I/O** — Non-blocking for scale

## 📚 Documentation

- **API Playground:** http://localhost:8000/docs
- **Alternative:** http://localhost:8000/redoc
- **Database:** Supabase dashboard
- **Detailed Guide:** See README_SERVER.md

---

**Next Steps:**
1. Copy `.env.example` → `.env` and fill credentials
2. Run `uvicorn app.main:app --reload`
3. Visit http://localhost:8000/docs to explore API
4. Start frontend from [client repository](https://github.com/your-org/nulo-africa-client)

**Questions?** Check README_SERVER.md for comprehensive backend guide.

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

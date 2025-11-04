# 🚀 Start FastAPI Server

## Quick Start Commands

### **Step 1: Create Virtual Environment (First Time Only)**
```bash
cd C:\Users\ALEX\Documents\Nuelo_Poc\v0-real-estate-app-design\server
python -m venv venv
```

### **Step 2: Activate Virtual Environment**
```bash
# Windows Command Prompt:
venv\Scripts\activate

# Windows PowerShell:
venv\Scripts\Activate.ps1

# You should see (venv) in your terminal
```

### **Step 3: Install Dependencies**
```bash
pip install -r requirements.txt
```

### **Step 4: Run Server**
```bash
# Option 1: Using uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Option 2: Using Python
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Option 3: Run main.py directly
python app/main.py
```

---

## 🌐 **Access Points**

Once server is running:
- **API Base:** http://localhost:8000
- **Swagger Docs:** http://localhost:8000/api/docs
- **ReDoc:** http://localhost:8000/api/redoc
- **Health Check:** http://localhost:8000/health

---

## 🐛 **Common Errors & Solutions**

### **Error: "No module named 'fastapi'"**
**Solution:**
```bash
# Make sure virtual environment is activated (you should see (venv))
venv\Scripts\activate
pip install -r requirements.txt
```

### **Error: "No module named 'app'"**
**Solution:**
```bash
# Make sure you're in the server directory
cd C:\Users\ALEX\Documents\Nuelo_Poc\v0-real-estate-app-design\server
# Then run uvicorn
uvicorn app.main:app --reload
```

### **Error: "Port 8000 is already in use"**
**Solution:**
```bash
# Use a different port
uvicorn app.main:app --reload --port 8001

# Or kill the process using port 8000
netstat -ano | findstr :8000
taskkill /PID <PID_NUMBER> /F
```

### **Error: "pydantic_settings not found"**
**Solution:**
```bash
pip install pydantic-settings
```

### **Error: "supabase module not found"**
**Solution:**
```bash
pip install supabase
```

---

## ✅ **Verify Installation**

Test if server is running:
```bash
# In a new terminal (don't close the server terminal)
curl http://localhost:8000/health

# Or open in browser:
# http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "environment": "development",
  "version": "1.0.0"
}
```

---

## 📝 **Development Workflow**

1. **Start server** (Terminal 1):
   ```bash
   cd server
   venv\Scripts\activate
   uvicorn app.main:app --reload
   ```

2. **Start frontend** (Terminal 2):
   ```bash
   cd client
   npm run dev
   ```

3. **Make changes** - Server auto-reloads with `--reload` flag

4. **Test API** - Use Swagger UI at http://localhost:8000/api/docs

---

## 🔧 **Environment Variables**

Make sure `server/.env` has:
```bash
SUPABASE_URL=https://aawielnjhtjqfvmpvold.supabase.co
SUPABASE_KEY=your_anon_key
SUPABASE_SERVICE_KEY=your_service_role_key
JWT_SECRET_KEY=your_secret_key
ALLOWED_ORIGINS=http://localhost:3000
```

---

## 📊 **Current Status**

✅ All route files created:
- ✅ `routes/auth.py` - Authentication (register, login, me)
- ✅ `routes/properties.py` - Property management (placeholder)
- ✅ `routes/applications.py` - Applications (placeholder)
- ✅ `routes/tenants.py` - Tenant profiles (placeholder)
- ✅ `routes/favorites.py` - Favorites (placeholder)
- ✅ `routes/messages.py` - Messages (placeholder)

✅ Core files:
- ✅ `app/main.py` - FastAPI app
- ✅ `app/config.py` - Configuration
- ✅ `app/database.py` - Supabase client
- ✅ `app/middleware/auth.py` - JWT auth

---

## 🎯 **Next Steps**

1. ✅ Start the server
2. ⏳ Test authentication endpoints
3. ⏳ Implement remaining route logic
4. ⏳ Connect frontend to backend

**Server is ready to run!** 🚀

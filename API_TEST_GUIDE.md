# 🧪 API Testing Guide - Thunder Client

## Fix "Email is invalid" Error

---

## 🚨 **Current Issue**

Error: `"Email address \"test@gmail.com\" is invalid"`

This happens because **Supabase email confirmation is enabled**.

---

## ✅ **Solution 1: Disable Email Confirmation (Recommended for Dev)**

### **Steps:**
1. Go to https://supabase.com/dashboard
2. Select your project
3. Navigate to: **Authentication** → **Settings**
4. Scroll to **"Email Auth"** section
5. Find **"Enable email confirmations"**
6. **Toggle it OFF** (disable)
7. Click **Save**

### **Why?**
- In development, you don't want to verify emails
- This allows instant registration
- You can re-enable it in production

---

## ✅ **Solution 2: Use Real Email (Alternative)**

If you want to keep email confirmation enabled:

1. Use your actual email address
2. Check your inbox for confirmation email
3. Click the confirmation link
4. Then you can login

---

## 🧪 **Test Registration (Thunder Client)**

### **Endpoint:**
```
POST http://localhost:8000/api/v1/auth/register
```

### **Headers:**
```json
{
  "Content-Type": "application/json"
}
```

### **Body (JSON):**
```json
{
  "email": "youremail@example.com",
  "password": "password123",
  "full_name": "John Doe",
  "user_type": "tenant"
}
```

### **Expected Success Response:**
```json
{
  "success": true,
  "user": {
    "id": "uuid-here",
    "email": "youremail@example.com",
    "full_name": "John Doe",
    "user_type": "tenant",
    "trust_score": 50,
    "verification_status": "partial",
    "created_at": "2025-01-12T08:00:00"
  },
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "message": "Registration successful! Please check your email to verify your account."
}
```

---

## 🧪 **Test Login (Thunder Client)**

### **Endpoint:**
```
POST http://localhost:8000/api/v1/auth/login
```

### **Body (JSON):**
```json
{
  "email": "youremail@example.com",
  "password": "password123"
}
```

### **Expected Success Response:**
```json
{
  "success": true,
  "user": {
    "id": "uuid-here",
    "email": "youremail@example.com",
    "full_name": "John Doe",
    "user_type": "tenant",
    "trust_score": 50,
    "verification_status": "partial",
    "tenant_profile": {
      "budget": null,
      "profile_completion": 0,
      "onboarding_completed": false
    }
  },
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

---

## 🧪 **Test Get Current User (Thunder Client)**

### **Endpoint:**
```
GET http://localhost:8000/api/v1/auth/me
```

### **Headers:**
```json
{
  "Authorization": "Bearer YOUR_ACCESS_TOKEN_HERE"
}
```

**Note:** Replace `YOUR_ACCESS_TOKEN_HERE` with the `access_token` from login response.

### **Expected Success Response:**
```json
{
  "id": "uuid-here",
  "email": "youremail@example.com",
  "full_name": "John Doe",
  "user_type": "tenant",
  "trust_score": 50,
  "verification_status": "partial",
  "tenant_profile": {
    "budget": null,
    "preferred_location": null,
    "profile_completion": 0,
    "onboarding_completed": false
  }
}
```

---

## 🧪 **Test Health Check**

### **Endpoint:**
```
GET http://localhost:8000/health
```

### **Expected Response:**
```json
{
  "status": "healthy",
  "environment": "development",
  "version": "1.0.0"
}
```

---

## 📝 **Thunder Client Collection**

### **Create Collection:**
1. Open Thunder Client in VS Code
2. Click "Collections"
3. Click "New Collection"
4. Name it "Nulo Africa API"

### **Add Requests:**

**1. Health Check**
- Method: GET
- URL: `http://localhost:8000/health`

**2. Register**
- Method: POST
- URL: `http://localhost:8000/api/v1/auth/register`
- Body: JSON (see above)

**3. Login**
- Method: POST
- URL: `http://localhost:8000/api/v1/auth/login`
- Body: JSON (see above)

**4. Get Me**
- Method: GET
- URL: `http://localhost:8000/api/v1/auth/me`
- Headers: Authorization: Bearer {{token}}

---

## 🔑 **Using Environment Variables in Thunder Client**

1. Click "Env" tab
2. Create new environment: "Local"
3. Add variables:
   ```
   base_url: http://localhost:8000
   token: (leave empty, will be set after login)
   ```
4. Use in requests: `{{base_url}}/api/v1/auth/register`

---

## ❌ **Common Errors**

### **Error: "Email is invalid"**
**Solution:** Disable email confirmation in Supabase (see Solution 1 above)

### **Error: "User already registered"**
**Solution:** Use a different email or delete the user from Supabase dashboard

### **Error: "Could not validate credentials"**
**Solution:** Make sure you're using the correct access_token in Authorization header

### **Error: "Connection refused"**
**Solution:** Make sure FastAPI server is running (`uvicorn app.main:app --reload`)

---

## ✅ **Quick Test Checklist**

- [ ] Disable email confirmation in Supabase
- [ ] Restart FastAPI server
- [ ] Test health check endpoint
- [ ] Test registration with your email
- [ ] Copy access_token from response
- [ ] Test login with same credentials
- [ ] Test /auth/me with access_token
- [ ] Verify user created in Supabase dashboard

---

## 🎯 **Next Steps After Successful Auth**

Once authentication works:
1. ✅ Test property endpoints (coming soon)
2. ✅ Test application endpoints (coming soon)
3. ✅ Connect frontend to backend
4. ✅ Test full user flow

**Your API is ready for testing!** 🚀

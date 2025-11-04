"""
Quick script to check users in database
"""
from app.database import supabase_admin

def check_users():
    """Check all users in database"""
    try:
        response = supabase_admin.table("users").select("id, email, user_type, created_at").execute()
        
        if response.data:
            print(f"\n✅ Found {len(response.data)} users:\n")
            for user in response.data:
                print(f"  Email: {user['email']}")
                print(f"  Type: {user['user_type']}")
                print(f"  Created: {user['created_at']}")
                print(f"  ID: {user['id']}")
                print("-" * 50)
        else:
            print("\n❌ No users found in database")
            print("\n💡 Create a user by signing up at: http://localhost:3001/signup")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    check_users()

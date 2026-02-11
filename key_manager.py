import secrets
import os
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime, timedelta

# Load Env variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: .env file not found or keys missing!")
    exit()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def generate_key(owner, credits=0, days_valid=365, unlimited=False):
    # Generate a secure random key
    api_key = "sk_" + secrets.token_urlsafe(24) 
    
    expiry = None
    if days_valid:
        expiry = (datetime.utcnow() + timedelta(days=days_valid)).isoformat()

    data = {
        "key_string": api_key,
        "owner_name": owner,
        "credits": credits,
        "is_unlimited": unlimited,
        "expires_at": expiry,
        "is_active": True
    }
    
    try:
        supabase.table("api_keys").insert(data).execute()
        print("\n" + "="*40)
        print(f"✅ SUCCESS: API Key Created for '{owner}'")
        print("="*40)
        print(f"🔑 API Key : {api_key}")
        print(f"💰 Credits : {'Unlimited ♾️' if unlimited else credits}")
        print(f"📅 Expires : {expiry}")
        print("="*40 + "\n")
    except Exception as e:
        print(f"❌ Error creating key: {e}")

# --- Menu ---
if __name__ == "__main__":
    print("\n--- 🧠 My Guru Brain: Key Manager ---")
    print("1. Create Limited Credit Key")
    print("2. Create Unlimited Key (For your Website)")
    
    choice = input("Select an option (1/2): ")
    
    owner = input("Enter Client Name (e.g. MyWebsite): ")
    
    if choice == "1":
        try:
            creds = int(input("Enter Credit Amount (e.g. 100): "))
            generate_key(owner, credits=creds, unlimited=False)
        except ValueError:
            print("Invalid number for credits.")
    elif choice == "2":
        generate_key(owner, credits=0, unlimited=True)
    else:
        print("Invalid choice.")
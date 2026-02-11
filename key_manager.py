import secrets
import os
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime, timedelta

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def generate_key(owner, credits, days_valid=365, unlimited=False):
    api_key = "sk_" + secrets.token_urlsafe(24) # e.g., sk_Au9s...
    
    expiry = None
    if days_valid:
        expiry = (datetime.utcnow() + timedelta(days=days_valid)).isoformat()

    data = {
        "key_string": api_key,
        "owner_name": owner,
        "credits": credits,
        "is_unlimited": unlimited,
        "expires_at": expiry
    }
    
    supabase.table("api_keys").insert(data).execute()
    print(f"\n✅ Key Created for {owner}!")
    print(f"🔑 Key: {api_key}")
    print(f"💰 Credits: {'Unlimited' if unlimited else credits}")
    print(f"📅 Expires: {expiry}\n")

# Example Usage:
print("1. Create Limited Key")
print("2. Create Unlimited Key")
choice = input("Select: ")

name = input("Client Name: ")

if choice == "1":
    creds = int(input("Credits Amount: "))
    generate_key(name, creds)
else:
    generate_key(name, 0, unlimited=True)
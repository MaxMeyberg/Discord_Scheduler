import os
from dotenv import load_dotenv
from supabase import create_client

# Simple direct test
load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

print(f"URL found: {url is not None}")
print(f"Key found: {key is not None}")

try:
    client = create_client(url, key)
    print("Direct connection successful!")
    
    # Try a simple query
    response = client.table("users").select("*").execute()
    print(f"Query successful! Found {len(response.data)} users")
except Exception as e:
    print(f"Connection failed: {e}") 
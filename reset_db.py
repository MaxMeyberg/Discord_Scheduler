#!/usr/bin/env python3
"""
This script has been updated to prepare for Supabase migration.
SQLite database reset functionality has been removed.
"""

import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client

async def reset_database():
    """Reset the Supabase users table"""
    load_dotenv()
    
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    if not url or not key:
        print("ERROR: Supabase credentials not found")
        return
        
    client = create_client(url, key)
    
    try:
        # Delete all records from the users table
        response = client.table("users").delete().execute()
        print(f"Database reset complete - all users deleted")
        if hasattr(response, 'error') and response.error:
            print(f"Error: {response.error}")
    except Exception as e:
        print(f"Error resetting database: {e}")

if __name__ == "__main__":
    asyncio.run(reset_database()) 
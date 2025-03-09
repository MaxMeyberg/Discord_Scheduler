#!/usr/bin/env python3
"""Test Supabase connection"""
import os
import asyncio
from dotenv import load_dotenv
from database import Database

async def test_supabase():
    """Test Supabase connection and operations"""
    load_dotenv()
    db = Database()
    
    # Test user
    test_user = {
        "discord_id": "test_user_123",
        "discord_name": "Test User",
        "auth_code": "test_auth_code",
        "access_token": "test_access_token",
        "email": "test@example.com"
    }
    
    print("Testing Supabase connection...")
    
    # Test saving a user
    print("Testing save_user...")
    save_result = await db.save_user(test_user)
    print(f"Save result: {save_result}")
    
    # Test getting a user
    print("Testing get_user...")
    user = await db.get_user("test_user_123")
    print(f"Retrieved user: {user}")
    
    # Test getting all users
    print("Testing get_all_users...")
    all_users = await db.get_all_users()
    print(f"All users count: {len(all_users)}")
    
    # Clean up - delete test user
    print("Testing delete_user...")
    delete_result = await db.delete_user("test_user_123")
    print(f"Delete result: {delete_result}")
    
    print("Supabase tests complete!")

if __name__ == "__main__":
    asyncio.run(test_supabase()) 
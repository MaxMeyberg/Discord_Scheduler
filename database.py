import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from supabase import create_client
import asyncio
from dotenv import load_dotenv
import uuid

class Database:
    """Database class using Supabase as the backend."""
    
    def __init__(self):
        """Initialize Supabase connection."""
        # Explicitly load environment variables
        load_dotenv()
        
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        
        if not self.supabase_url or not self.supabase_key:
            print(f"ERROR: Supabase credentials not found in environment variables.")
            print(f"Looking for: SUPABASE_URL and SUPABASE_KEY")
            print(f"URL found: {'Yes' if self.supabase_url else 'No'}")
            print(f"Key found: {'Yes' if self.supabase_key else 'No'}")
            self.client = None
        else:
            try:
                print(f"Initializing Supabase with URL: {self.supabase_url[:30]}...")
                self.client = create_client(self.supabase_url, self.supabase_key)
                print("Supabase client successfully initialized")
            except Exception as e:
                print(f"ERROR initializing Supabase client: {e}")
                self.client = None
    
    async def setup(self):
        """Setup function - not needed for Supabase as tables are created in the dashboard"""
        print("Using Supabase - tables should be created in the Supabase dashboard")
        pass
    
    async def _run_sync(self, func):
        """Run a synchronous function in an executor to make it async-compatible"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, func) 
    
    async def save_user(self, user_data: Dict[str, Any]) -> bool:
        """Save user data to Supabase."""
        if not self.client:
            print("Supabase client not initialized - cannot save user data")
            return False
            
        discord_id = user_data.get("discord_id")
        if not discord_id:
            return False
        
        try:
            # Prepare data for insertion
            insert_data = {
                "discord_id": discord_id,
                "discord_name": user_data.get("discord_name", ""),
                "auth_code": user_data.get("auth_code", ""),
                "access_token": user_data.get("access_token", ""),
                "refresh_token": user_data.get("refresh_token", ""),
                "email": user_data.get("email", ""),
                # Convert timestamp to ISO string if it exists
                "token_expiry": datetime.fromtimestamp(user_data.get("token_expiry", 0)).isoformat() 
                if user_data.get("token_expiry") else None,
                # Store additional data as JSON
                "data": json.dumps({k: v for k, v in user_data.items() 
                                if k not in ["discord_id", "discord_name", "auth_code", 
                                             "access_token", "refresh_token", "email", 
                                             "token_expiry"]})
            }
            
            # Define a regular function (not async!)
            def _do_upsert():
                return self.client.table("users").upsert(insert_data).execute()
            
            # Call _run_sync with the function object
            response = await self._run_sync(_do_upsert)
            
            if hasattr(response, 'error') and response.error:
                print(f"Error saving user: {response.error}")
                return False
                
            print(f"User saved successfully: {discord_id}")
            return True
            
        except Exception as e:
            print(f"Error saving user to Supabase: {e}")
            return False
    
    async def get_user(self, discord_id: str) -> Optional[Dict[str, Any]]:
        """Get user data from Supabase."""
        if not self.client:
            print("Supabase client not initialized - cannot get user data")
            return None
            
        try:
            # Define a regular function to pass to run_sync
            def _do_select():
                return self.client.table("users").select("*").eq("discord_id", discord_id).execute()
            
            # Run the synchronous function in an executor
            response = await self._run_sync(_do_select)
            
            if hasattr(response, 'error') and response.error:
                print(f"Error getting user: {response.error}")
                return None
                
            data = response.data
            
            if not data or len(data) == 0:
                return None
                
            user_data = data[0]
            
            # Convert JSON string to dict if it exists
            if user_data.get("data"):
                try:
                    extra_data = json.loads(user_data.get("data", "{}"))
                    user_data.update(extra_data)
                except:
                    pass
                    
            return user_data
            
        except Exception as e:
            print(f"Error getting user from Supabase: {e}")
            return None
    
    async def delete_user(self, discord_id: str) -> bool:
        """Delete user from Supabase."""
        if not self.client:
            print("Supabase client not initialized - cannot delete user")
            return False
            
        try:
            def _do_delete():
                return self.client.table("users").delete().eq("discord_id", discord_id).execute()
            
            response = await self._run_sync(_do_delete)
            
            if hasattr(response, 'error') and response.error:
                print(f"Error deleting user: {response.error}")
                return False
                
            return True
            
        except Exception as e:
            print(f"Error deleting user from Supabase: {e}")
            return False
    
    async def get_all_users(self) -> list:
        """Get all users from Supabase."""
        if not self.client:
            print("Supabase client not initialized - cannot get users")
            return []
            
        try:
            def _do_select_all():
                return self.client.table("users").select("*").execute()
            
            response = await self._run_sync(_do_select_all)
            
            if hasattr(response, 'error') and response.error:
                print(f"Error getting all users: {response.error}")
                return []
                
            users = response.data
            
            # Process each user's extra data
            for user in users:
                if user.get("data"):
                    try:
                        extra_data = json.loads(user.get("data", "{}"))
                        user.update(extra_data)
                    except:
                        pass
            
            return users
            
        except Exception as e:
            print(f"Error getting all users from Supabase: {e}")
            return [] 
    
    async def refresh_token(self, discord_id: str) -> bool:
        """Refresh an expired Cronofy access token"""
        user_data = await self.get_user(discord_id)
        if not user_data or not user_data.get("refresh_token"):
            return False
        
        # Call Cronofy token refresh endpoint
        # This would be implemented in agent.py or a separate cronofy.py file
        # ...
        
        return True 
    
    async def get_or_create_user_id(self, discord_id):
        """Get existing user ID or create a new persistent one"""
        # Check if user already exists in our system
        user_data = await self.get_user(discord_id)
        
        if user_data and "user_uuid" in user_data:
            # User exists and has a UUID, return it
            return user_data["user_uuid"]
        else:
            # Generate a new UUID for this user
            new_uuid = str(uuid.uuid4())
            
            # Store it in the database (create or update user record)
            if not user_data:
                user_data = {"discord_id": discord_id}
            
            user_data["user_uuid"] = new_uuid
            await self.store_user(discord_id, user_data)
            
            return new_uuid 
    
    async def get_user_by_uuid(self, uuid):
        """Get a user by their persistent UUID"""
        all_users = await self.get_all_users()
        
        for user_id, user_data in all_users.items():
            if user_data.get("user_uuid") == uuid:
                return user_data
        
        return None 
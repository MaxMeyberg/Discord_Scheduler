import sqlite3
import json
import os
import aiosqlite  # For async database operations

class Database:
    def __init__(self):
        # Create database file in the schedge directory
        self.db_path = os.path.join(os.path.dirname(__file__), "users.db")
        # Create tables immediately
        self.create_tables()
        
    def create_tables(self):
        """Create database tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            discord_name TEXT,
            auth_code TEXT,
            data TEXT
        )
        ''')
        conn.commit()
        conn.close()
        
    async def save_user(self, user_data):
        """Save user data to database"""
        async with aiosqlite.connect(self.db_path) as db:
            discord_id = str(user_data.get("discord_id"))
            discord_name = user_data.get("discord_name", "")
            auth_code = user_data.get("auth_code", "")
            # Store additional data as JSON
            data = json.dumps({k: v for k, v in user_data.items() 
                              if k not in ["discord_id", "discord_name", "auth_code"]})
            
            await db.execute(
                "INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
                (discord_id, discord_name, auth_code, data)
            )
            await db.commit()
            return user_data
            
    async def get_user(self, user_id):
        """Get user data from database"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT * FROM users WHERE discord_id = ?", (str(user_id),))
            row = await cursor.fetchone()
            
            if not row:
                return None
                
            user_data = {
                "discord_id": row[0],
                "discord_name": row[1],
                "auth_code": row[2]
            }
            
            # Add any additional data
            if row[3]:
                extra_data = json.loads(row[3])
                user_data.update(extra_data)
                
            return user_data
            
    async def delete_user(self, user_id):
        """Delete user from database"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM users WHERE discord_id = ?", (str(user_id),))
            await db.commit()
            return True  # Assume success 

    async def get_all_users(self):
        """Get all users from database"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT * FROM users")
            rows = await cursor.fetchall()
            
            if not rows:
                return []
                
            users = []
            for row in rows:
                user_data = {
                    "discord_id": row[0],
                    "discord_name": row[1],
                    "auth_code": row[2]
                }
                
                # Add any additional data
                if row[3]:
                    try:
                        extra_data = json.loads(row[3])
                        user_data.update(extra_data)
                    except:
                        pass
                        
                users.append(user_data)
                
            return users 
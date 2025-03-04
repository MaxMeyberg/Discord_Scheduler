import os
import sqlite3

def reset_database():
    """Reset the entire database"""
    # Path to database file
    db_path = os.path.join(os.path.dirname(__file__), "users.db")
    
    # Check if it exists
    if os.path.exists(db_path):
        try:
            # Connect and clear the users table
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users")
            conn.commit()
            conn.close()
            print("Database has been reset - all users deleted")
        except Exception as e:
            print(f"Error resetting database: {e}")
    else:
        print("Database file not found - nothing to reset")

if __name__ == "__main__":
    reset_database() 
import os
from mistralai import Mistral
import discord
from datetime import datetime, timedelta
import asyncio
import requests
import json

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = "You are a helpful assistant."

class MistralAgent:
    def __init__(self):
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=MISTRAL_API_KEY)
        
        # Cronofy API credentials
        self.cronofy_client_id = os.getenv("CRONOFY_CLIENT_ID")
        self.cronofy_redirect_uri = os.getenv("CRONOFY_REDIRECT_URI", "https://oauth.pstmn.io/v1/callback")
        
        # Move these inside the class as instance attributes
        self.user_database = {}
        self.registration_states = {}

    async def run(self, message: discord.Message):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message.content},
        ]

        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        return response.choices[0].message.content
        
    def get_cronofy_auth_url(self, discord_user_id):
        """Generate a Cronofy authorization URL for a user"""
        scope = "read_events read_free_busy"
        state = str(discord_user_id)  # Use Discord user ID as state parameter
        
        auth_url = (
            f"https://app.cronofy.com/oauth/authorize"
            f"?client_id={self.cronofy_client_id}"
            f"&response_type=code"
            f"&redirect_uri={self.cronofy_redirect_uri}"
            f"&scope={scope}"
            f"&state={state}"
        )
        
        return auth_url
        
    async def start_registration(self, user: discord.User):
        """Begin the registration process for a user via DM"""
        try:
            # Initialize registration state - use self.registration_states now
            self.registration_states[user.id] = {
                "step": "email",
            }
            
            await user.send("Thanks for registering with Skedge! Please enter your email address to continue.")
            return True
        except Exception as e:
            print(f"Error starting registration for {user.name}: {e}")
            return False
            
    async def process_registration_dm(self, message: discord.Message):
        """Process registration DMs from users"""
        user_id = message.author.id
        
        # Use self.registration_states
        if user_id not in self.registration_states:
            await message.author.send("Please start registration by typing !register in a server channel.")
            return
            
        state = self.registration_states[user_id]
        
        if state["step"] == "email":
            # Validate email (basic validation for now)
            email = message.content.strip()
            if "@" in email and "." in email:
                # Store email and update state
                state["email"] = email
                state["step"] = "calendar"
                
                # Generate authorization URL
                auth_url = self.get_cronofy_auth_url(user_id)
                
                await message.author.send(
                    f"Thanks! Your email {email} has been registered.\n\n"
                    f"Now, to connect your calendar, please click this link:\n{auth_url}\n\n"
                    f"After authorizing, you'll see a page with a code. Just copy that code and send it to me here."
                )
            else:
                await message.author.send("That doesn't look like a valid email. Please try again.")
        
        elif state["step"] == "calendar":
            # Just confirm we received a code for now
            code = message.content.strip()
            
            # Store in database - use self.user_database
            self.user_database[user_id] = {
                "email": state["email"],
                "discord_id": user_id,
                "discord_name": message.author.name,
                "auth_code": code  # We'll use this in the next step
            }
            
            # Registration complete
            del self.registration_states[user_id]
            
            await message.author.send("Registration complete! Your calendar has been connected.")
    
    async def exchange_code_for_token(self, code):
        """Exchange authorization code for access token"""
        # In a real implementation, this would be an async HTTP request
        # For simplicity, we're using a synchronous request here
        
        try:
            response = requests.post(
                "https://api.cronofy.com/oauth/token",
                data={
                    "client_id": self.cronofy_client_id,
                    "client_secret": self.cronofy_client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.cronofy_redirect_uri
                }
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error exchanging code: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Exception during token exchange: {e}")
            return None
    
    async def find_common_free_time(self, users, date=None):
        """Find common free time slots for the given users using Cronofy"""
        if date is None:
            date = datetime.now().date()
            
        # Get list of participant calendar IDs
        participants = []
        for user in users:
            user_data = self.user_database.get(user.id)
            if not user_data:
                continue
                
            # Add this user's calendars to the participants list
            participants.append({
                "sub": user_data.get("auth_code"),  # Just use auth_code for now
                "calendar_ids": []  # Empty means all calendars
            })
        
        # Mock implementation returning fake data
        current_hour = datetime.now().hour
        mock_slots = [
            datetime.combine(date, datetime.min.time()) + timedelta(hours=current_hour + 1),
            datetime.combine(date, datetime.min.time()) + timedelta(hours=current_hour + 3),
            datetime.combine(date, datetime.min.time()) + timedelta(hours=current_hour + 5)
        ]
        
        return mock_slots
        
    async def call_cronofy_availability_api(self, participants, start_date, end_date):
        """Call Cronofy's Real-Time Scheduling API to find availability"""
        # This is a placeholder for the actual API call
        # In a real implementation, you would make an HTTP request to Cronofy's API
        
        # Example of what the real API call might look like:
        """
        headers = {
            "Authorization": f"Bearer {your_cronofy_api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "participants": participants,
            "required": "all",
            "available_periods": [
                {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat()
                }
            ],
            "duration": {"minutes": 60}  # Looking for 1-hour slots
        }
        
        response = requests.post("https://api.cronofy.com/v1/availability", headers=headers, json=data)
        return response.json()
        """
        
        # For now, return mock data
        return {
            "available_slots": [
                {"start": "2023-05-01T10:00:00Z", "end": "2023-05-01T11:00:00Z"},
                {"start": "2023-05-01T14:00:00Z", "end": "2023-05-01T15:00:00Z"},
                {"start": "2023-05-01T16:00:00Z", "end": "2023-05-01T17:00:00Z"}
            ]
        }

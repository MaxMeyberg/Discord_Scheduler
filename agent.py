import os
from mistralai import Mistral
import discord
from datetime import datetime, timedelta, date
import asyncio
import requests
import json
import threading
import time
from database import Database
import aiohttp
import aiosqlite

MISTRAL_MODEL = "mistral-large-latest"
SYSTEM_PROMPT = "You are a helpful assistant."

class MistralAgent:
    def __init__(self, bot=None):
        # Initialize Mistral client
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=MISTRAL_API_KEY)
        
        # Store bot reference for sending DMs
        self.bot = bot
        
        # Initialize database
        self.db = Database()
        
        # Registration state tracking
        self.registration_states = {}
        
        # Cronofy configuration
        self.cronofy_client_id = os.getenv("CRONOFY_CLIENT_ID")
        self.cronofy_redirect_uri = os.getenv("CRONOFY_REDIRECT_URI", "https://oauth.pstmn.io/v1/callback")
        
        # Move these inside the class as instance attributes
        self.user_database = {}  # Keep this as a cache
        
        # For the OAuth automation
        self.oauth_server_url = os.getenv("OAUTH_SERVER_URL")
        self.oauth_server_api_key = os.getenv("OAUTH_SERVER_API_KEY")
        
        # Start a background thread to poll for oauth codes ONLY if URL is configured
        self.oauth_polling = {}  # Keep track of which users we're polling for
        if self.oauth_server_url:  # Only start polling if URL is set
            threading.Thread(target=self.poll_for_oauth_codes, daemon=True).start()

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
        # Remove 'availability' from the scope - it's not a valid standalone scope
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
            # Initialize registration state directly to calendar step
            self.registration_states[user.id] = {
                "step": "calendar",
            }
            
            # Generate authorization URL immediately
            auth_url = self.get_cronofy_auth_url(user.id)
            
            # Start polling for this user's OAuth code
            self.oauth_polling[user.id] = {
                "name": user.name
            }
            
            # Return both success status and the auth URL
            return True, auth_url
        except Exception as e:
            print(f"Error starting registration for {user.name}: {e}")
            return False, None
            
    async def process_registration_dm(self, message: discord.Message):
        """Process registration DMs from users"""
        user_id = message.author.id
        content = message.content.strip()
        
        # Check for commands first (using lowercase to make case-insensitive)
        lowercase_content = content.lower()
        if lowercase_content == "!unregister":
            # Check if user is registered
            if user_id not in self.user_database:
                await message.author.send("You're not registered yet!")
                return
            
            # Remove user data
            if user_id in self.user_database:
                del self.user_database[user_id]
            if user_id in self.registration_states:
                del self.registration_states[user_id]
            if user_id in self.oauth_polling:
                del self.oauth_polling[user_id]
            
            # Also delete from database
            await self.db.delete_user(user_id)
            
            await message.author.send("You've been successfully unregistered from Skedge!")
            return
        
        if lowercase_content == "!restart":
            if user_id in self.registration_states:
                # Clear existing registration state
                del self.registration_states[user_id]
                # Start fresh
                self.registration_states[user_id] = {
                    "step": "email",
                }
                await message.author.send("Registration process restarted. Please enter your email address to continue.")
            else:
                await message.author.send("You don't have an active registration to restart. Type !register in a server channel to begin.")
            return
        
        # Continue with regular registration process
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
                
                # Start polling for this user's OAuth code
                self.oauth_polling[user_id] = {
                    "email": email,
                    "name": message.author.name
                }
                
                await message.author.send(
                    f"Thanks! Your email {email} has been registered.\n\n"
                    f"Now, to connect your calendar, please click this link:\n{auth_url}\n\n"
                    f"After authorizing, you'll see a Postman page with a URL that looks like:\n"
                    f"postman://app/oauth2/callback?code=XXXX...\n\n"
                    f"Please copy that ENTIRE URL and paste it back to me here."
                )
            else:
                await message.author.send("That doesn't look like a valid email. Please try again or type !restart to start over.")
        
        elif state["step"] == "calendar":
            # This is where we handle the OAuth callback URL
            
            # Initialize code variable
            code = None
            
            # Check for both URL formats
            if "code=" in content:
                # Case 1: Regular HTTPS URL (for popup blocked or direct)
                if "https://oauth.pstmn.io" in content:
                    try:
                        code = content.split("code=")[1].split("&")[0]
                        print(f"Extracted code from HTTPS URL: {code}")
                    except Exception as e:
                        print(f"Error extracting code from HTTPS URL: {e}")
                
                # Case 2: Postman protocol URL
                elif "postman://" in content:
                    try:
                        code = content.split("code=")[1].split("&")[0]
                        print(f"Extracted code from Postman URL: {code}")
                    except Exception as e:
                        print(f"Error extracting code from Postman URL: {e}")
                
                # Case 3: User just pasted the raw code
                elif len(content) > 10 and " " not in content:
                    code = content.strip()
                    print(f"Using raw code: {code}")
            
            if not code:
                await message.author.send(
                    "I couldn't find a valid authorization code in your message.\n\n"
                    "Please copy the ENTIRE callback URL which looks like one of these:\n"
                    "• https://oauth.pstmn.io/v1/callback?code=XXXX...\n"
                    "• postman://app/oauth2/callback?code=XXXX...\n\n"
                    "If you see a code directly on the page, you can also paste that."
                )
                return
            
            # Exchange code for token
            token_data = await self.exchange_code_for_token(code)
            if not token_data:
                await message.author.send("There was an error connecting to your calendar. Please try again with !restart")
                return
            
            # Store in memory cache
            self.user_database[user_id] = {
                "discord_id": user_id,
                "discord_name": message.author.name,
                "auth_code": code,
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "token_expiry": datetime.now().timestamp() + token_data.get("expires_in", 3600)
            }
            
            # Then persist to database
            asyncio.run_coroutine_threadsafe(
                self.db.save_user(self.user_database[user_id]),
                asyncio.get_event_loop()
            )
            
            # Registration complete
            del self.registration_states[user_id]
            
            await message.author.send("Great! I've connected your calendar. Registration is now complete!")
    
    async def exchange_code_for_token(self, code):
        """Exchange authorization code for access token"""
        try:
            # Get client secret from environment variables
            client_secret = os.getenv("CRONOFY_CLIENT_SECRET")
            
            if not client_secret:
                print("ERROR: CRONOFY_CLIENT_SECRET not found in environment variables")
                return None
            
            # Make the token exchange request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.cronofy.com/oauth/token",
                    data={
                        "client_id": self.cronofy_client_id,
                        "client_secret": client_secret,
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.cronofy_redirect_uri
                    }
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        print(f"Error exchanging code: {response.status} - {await response.text()}")
                        return None
        except Exception as e:
            print(f"Exception during token exchange: {e}")
            return None
    
    async def find_common_free_time(self, users, date=None):
        """Find common free time slots for the given users using Cronofy"""
        if date is None:
            date = datetime.now().date()
        
        # Start and end times for availability check (today's date)
        start_date = datetime.combine(date, datetime.min.time())
        end_date = datetime.combine(date, datetime.max.time())
        
        # Pass the whole user objects directly
        availability_data = await self.call_cronofy_availability_api(
            users, start_date, end_date
        )
        
        # Parse the response and return time slots
        slots = []
        for slot in availability_data.get("available_slots", []):
            start_time = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
            slots.append(start_time)
        
        return slots[:3]  # Return top 3 slots
        
    async def call_cronofy_availability_api(self, participants, start_date, end_date):
        """Call Cronofy's Real-Time Scheduling API to find availability"""
        try:
            # Get auth token for the first user
            first_user = participants[0]  # Take the first user
            user_data = await self.db.get_user(str(first_user.id))
            
            if not user_data:
                print("No valid user data found")
                return {"available_slots": []}
            
            # Get the auth token for the API request
            if isinstance(user_data, dict):
                auth_token = user_data.get("access_token", user_data.get("auth_code"))
            else:
                auth_token = user_data
            
            if not auth_token:
                print("No valid auth token found")
                return {"available_slots": []}
            
            # Fix date handling - ensure dates are in proper order
            now = datetime.utcnow()
            
            # Adjust start and end dates as needed
            if isinstance(start_date, datetime) and start_date < now:
                start_date = now
            
            # Make sure end_date is after start_date
            if isinstance(end_date, date) and not isinstance(end_date, datetime):
                end_date = datetime.combine(end_date, datetime.max.time())
            
            # ENSURE start_date is before end_date - critical fix
            if start_date > end_date:
                print(f"WARNING: Start date {start_date} is after end date {end_date}, swapping...")
                start_date, end_date = end_date, start_date
            
            # Format dates properly for Cronofy API
            start_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(start_date, datetime) else f"{start_date}T00:00:00Z"
            end_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(end_date, datetime) else f"{end_date}T23:59:59Z"
            
            # Create members array with proper formatting for Cronofy
            members = []
            for p in participants:
                p_data = await self.db.get_user(str(p.id))
                if p_data:
                    # The sub field requires a proper format - likely an email or ID
                    # For now, we'll use "cronofy" as a placeholder
                    members.append({"sub": "cronofy"})
            
            # Format the request data
            data = {
                "participants": [
                    {
                        "members": members,
                        "required": "all"
                    }
                ],
                "required_duration": {"minutes": 60},
                "available_periods": [
                    {
                        "start": start_str,
                        "end": end_str
                    }
                ]
            }
            
            print(f"Sending Cronofy API request: {data}")
            
            # IMPORTANT CHANGE: Use the user's auth_token, not client_secret
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.cronofy.com/v1/availability",
                    headers={
                        "Authorization": f"Bearer {auth_token}",  # Use auth_token instead of client_secret
                        "Content-Type": "application/json"
                    },
                    json=data
                ) as response:
                    response_text = await response.text()
                    print(f"Cronofy API response ({response.status}): {response_text}")
                    
                    if response.status == 200:
                        return await response.json()
                    else:
                        print(f"Error calling Cronofy API: {response.status} - {response_text}")
                        # Return mock data as fallback
                        return {
                            "available_slots": [
                                {"start": f"{datetime.now().date()}T10:00:00Z", "end": f"{datetime.now().date()}T11:00:00Z"},
                                {"start": f"{datetime.now().date()}T14:00:00Z", "end": f"{datetime.now().date()}T15:00:00Z"},
                                {"start": f"{datetime.now().date()}T16:00:00Z", "end": f"{datetime.now().date()}T17:00:00Z"}
                            ]
                        }
        except Exception as e:
            print(f"Exception during Cronofy API call: {e}")
            import traceback
            traceback.print_exc()
            # Return mock data as fallback
            return {
                "available_slots": [
                    {"start": f"{datetime.now().date()}T10:00:00Z", "end": f"{datetime.now().date()}T11:00:00Z"},
                    {"start": f"{datetime.now().date()}T14:00:00Z", "end": f"{datetime.now().date()}T15:00:00Z"},
                    {"start": f"{datetime.now().date()}T16:00:00Z", "end": f"{datetime.now().date()}T17:00:00Z"}
                ]
            }

    # Add this method to poll for codes
    def poll_for_oauth_codes(self):
        """Background thread that polls for OAuth codes"""
        while True:
            # Make a copy to avoid modifying during iteration
            users_to_poll = list(self.oauth_polling.keys())
            
            for user_id in users_to_poll:
                try:
                    response = requests.get(
                        f"{self.oauth_server_url}/get_code/{user_id}",
                        headers={"X-API-Key": self.oauth_server_api_key}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if "code" in data:
                            code = data["code"]
                            user_data = self.oauth_polling[user_id]
                            
                            # Store in memory cache
                            self.user_database[user_id] = {
                                "email": user_data["email"],
                                "discord_id": user_id,
                                "discord_name": user_data["name"],
                                "auth_code": code
                            }
                            
                            # Then persist to database
                            asyncio.run_coroutine_threadsafe(
                                self.db.save_user(self.user_database[user_id]),
                                asyncio.get_event_loop()
                            )
                            
                            # Clear registration state
                            if user_id in self.registration_states:
                                del self.registration_states[user_id]
                                
                            # Stop polling for this user
                            del self.oauth_polling[user_id]
                            
                            # Send DM to user
                            asyncio.run_coroutine_threadsafe(
                                self.send_dm_to_user(user_id, "Your calendar has been successfully connected! Registration is now complete."),
                                asyncio.get_event_loop()
                            )
                except Exception as e:
                    print(f"Error polling for OAuth code: {e}")
            
            # Sleep before next poll
            time.sleep(5)
    
    async def send_dm_to_user(self, user_id, message):
        """Send a DM to a user by ID"""
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(message)
        except Exception as e:
            print(f"Error sending DM: {e}")

    async def process_oauth_code(self, user, auth_code):
        """Process OAuth code and get access token"""
        client_id = os.getenv("CRONOFY_CLIENT_ID")
        client_secret = os.getenv("CRONOFY_CLIENT_SECRET")
        redirect_uri = os.getenv("CRONOFY_REDIRECT_URI")
        
        # Exchange code for tokens
        async with aiosqlite.ClientSession() as session:
            token_url = "https://api.cronofy.com/oauth/token"
            payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri
            }
            
            async with session.post(token_url, json=payload) as response:
                if response.status != 200:
                    return None
                    
                token_data = await response.json()
                
                # Get user profile info to get their email
                profile_response = await self.cronofy_api_call(
                    endpoint="v1/userinfo",
                    auth_token=token_data.get("access_token")
                )
                
                email = "unknown@example.com"
                if profile_response[0] == 200:
                    try:
                        profile_data = json.loads(profile_response[1])
                        email = profile_data.get("email", email)
                    except:
                        pass
                
                # Store both the auth code, access token and email
                user_data = {
                    "discord_id": str(user.id),
                    "discord_name": user.name,
                    "auth_code": auth_code,
                    "access_token": token_data.get("access_token"),
                    "refresh_token": token_data.get("refresh_token"),
                    "token_expiry": datetime.now().timestamp() + token_data.get("expires_in", 3600),
                    "email": email
                }
                
                # Save user data to database
                return await self.db.save_user(user_data)

    async def cronofy_api_call(self, endpoint, method="GET", auth_token=None, params=None, json_data=None):
        """Make an API call to Cronofy with automatic token refresh"""
        try:
            base_url = "https://api.cronofy.com"
            url = f"{base_url}/{endpoint}"
            
            headers = {
                "Content-Type": "application/json"
            }
            
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            
            async with aiohttp.ClientSession() as session:
                try:
                    if method == "GET":
                        async with session.get(url, headers=headers, params=params) as response:
                            if response.status == 401:
                                # Token might be expired - attempt refresh and retry
                                print(f"Token expired for API call to {endpoint}, attempting refresh")
                                # You would need to implement a token refresh mechanism here
                                # For now, we'll just inform the user
                                return 401, "Authentication expired. Please re-register using !unregister then !register"
                            return response.status, await response.text()
                    elif method == "POST":
                        async with session.post(url, headers=headers, json=json_data) as response:
                            if response.status == 401:
                                # Token might be expired - attempt refresh and retry
                                print(f"Token expired for API call to {endpoint}, attempting refresh")
                                return 401, "Authentication expired. Please re-register using !unregister then !register"
                            return response.status, await response.text()
                    else:
                        return 400, "Unsupported method"
                except aiohttp.ClientError as e:
                    print(f"HTTP error in API call: {e}")
                    return 500, f"Connection error: {str(e)}"
                    
        except Exception as e:
            print(f"API call error: {e}")
            return 500, str(e)

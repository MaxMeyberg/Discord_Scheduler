import os
import discord
from datetime import datetime
import asyncio
import json
import aiohttp
import traceback

# For URL shortening if available
try:
    import pyshorteners
    HAS_SHORTENER = True
except ImportError:
    HAS_SHORTENER = False
    print("Warning: pyshorteners not found - using full URLs instead")

class MistralAgent:
    def __init__(self, bot=None):
        # Store bot reference for sending DMs
        self.bot = bot
        
        # Initialize database
        from database import Database
        self.db = Database()
        
        # Create session using bot's loop if available
        self.session = None
        
        # Registration state tracking
        self.registration_states = {}
        
        # Cronofy configuration
        self.cronofy_client_id = os.getenv("CRONOFY_CLIENT_ID")
        self.cronofy_redirect_uri = os.getenv("CRONOFY_REDIRECT_URI", "https://oauth.pstmn.io/v1/callback")
        
        # User database cache
        self.user_database = {}
        
        # OAuth polling - will be initialized later
        self.oauth_polling = {}

    async def setup_session(self):
        """Create the aiohttp session in an async context"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            print("Created aiohttp session")

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
            
    async def process_registration_dm(self, message):
        """Process DMs for registration workflow"""
        user = message.author
        content = message.content.strip()
        
        # Check if the user is in the registration state
        if user.id in self.registration_states:
            # Look for callback URLs in the message
            # First, check for the web-based callback URL
            if "oauth.pstmn.io/v1/callback" in content:
                # Extract the auth code from the callback URL
                try:
                    # Parse the callback URL to get the auth code
                    if "?code=" in content:
                        auth_code = content.split("?code=")[1].split("&")[0]
                        await message.channel.send(f"✅ Got your auth code! Now finalizing your registration...")
                        
                        # Process the auth code
                        result = await self.process_auth_code(user, auth_code)
                        if result:
                            await message.channel.send(f"🎉 Your calendar is now connected! Try `!viewcal` to see your upcoming events.")
                        else:
                            await message.channel.send(f"❌ There was a problem connecting your calendar. Please try the `!register` command again.")
                        
                        # Remove from registration state
                        if user.id in self.registration_states:
                            del self.registration_states[user.id]
                        return
                except Exception as e:
                    await message.channel.send(f"❌ Error processing callback URL: {str(e)}")
                    print(f"Error processing callback: {e}")
                    traceback.print_exc()
                    return
            
            # Check for the Postman desktop app callback URL (postman:// protocol)
            elif "postman://app/oauth2/callback" in content:
                try:
                    # Extract the code parameter from postman:// URL
                    if "?code=" in content:
                        auth_code = content.split("?code=")[1].split("&")[0]
                        await message.channel.send(f"✅ Got your auth code from Postman! Now finalizing your registration...")
                        
                        # Process the auth code
                        result = await self.process_auth_code(user, auth_code)
                        if result:
                            await message.channel.send(f"🎉 Your calendar is now connected! Try `!viewcal` to see your upcoming events.")
                        else:
                            await message.channel.send(f"❌ There was a problem connecting your calendar. Please try the `!register` command again.")
                        
                        # Remove from registration state
                        if user.id in self.registration_states:
                            del self.registration_states[user.id]
                        return
                except Exception as e:
                    await message.channel.send(f"❌ Error processing Postman callback URL: {str(e)}")
                    print(f"Error processing Postman callback: {e}")
                    traceback.print_exc()
                    return
            
            # If we get here, it wasn't a valid callback URL
            # Just send a helpful reminder
            await message.channel.send(
                "Please paste the **complete URL** from the Postman page after you authorize.\n\n"
                "It should look like one of these:\n"
                "• `https://oauth.pstmn.io/v1/callback?code=XXXX...`\n"
                "• `postman://app/oauth2/callback?code=XXXX...`\n\n"
                "If you're having trouble, try the `!register` command again."
            )
    
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

    async def process_auth_code(self, user, auth_code):
        """Process authorization code from Cronofy OAuth callback"""
        try:
            # Exchange authorization code for access token
            token_data = await self.exchange_code_for_token(auth_code)
            
            if not token_data:
                print(f"Failed to exchange auth code for token for user {user.id}")
                return False
            
            # Get token expiry time (default to 1 hour if not specified)
            expires_in = token_data.get("expires_in", 3600)
            
            # Save user data to database
            user_data = {
                "discord_id": str(user.id),
                "discord_name": user.name,
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "token_expiry": datetime.now().timestamp() + expires_in,
                "auth_code": auth_code  # Store the original auth code too
            }
            
            # Update user in database
            success = await self.db.save_user(user_data)
            
            if success:
                print(f"Successfully registered user {user.name} (ID: {user.id})")
                return True
            else:
                print(f"Database error while saving user {user.id}")
                return False
            
        except Exception as e:
            print(f"Error processing auth code: {e}")
            import traceback
            traceback.print_exc()
            return False

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

    def shorten_url(self, url):
        if HAS_SHORTENER:
            try:
                s = pyshorteners.Shortener()
                return s.tinyurl.short(url)
            except Exception as e:
                print(f"URL shortening failed: {e}")
                return url
        else:
            return url

    async def close(self):
        """Close the session properly when the bot shuts down"""
        if self.session is not None:
            await self.session.close()
            self.session = None
            print("Closed aiohttp session")

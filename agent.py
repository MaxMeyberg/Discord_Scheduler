import os
import discord
from datetime import datetime
import asyncio
import json
import aiohttp
import traceback
import pytz
import urllib.parse

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

    async def get_auth_url(self, discord_id):
        """Get the Cronofy authorization URL for a user"""
        client_id = os.getenv("CRONOFY_CLIENT_ID")
        client_secret = os.getenv("CRONOFY_CLIENT_SECRET")
        redirect_uri = os.getenv("REDIRECT_URI")
        
        if not client_id or not client_secret or not redirect_uri:
            print("ERROR: Missing Cronofy environment variables")
            return None
        
        # Add state parameter to track the user
        state = f"discord_{discord_id}"
        
        # Build the query parameters
        params = {
            'client_id': client_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'scope': 'read_events read_free_busy create_event delete_event',
            'state': state
        }
        
        # Encode the parameters properly
        query_string = urllib.parse.urlencode(params)
        
        # Use the proper authorization endpoint
        auth_url = f"https://app.cronofy.com/oauth/authorize?{query_string}"
        
        print(f"Generated auth URL: {auth_url}")
        
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
                "token_expiry": datetime.now(pytz.UTC).timestamp() + expires_in,
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
        """Safely shorten a URL or return the original if shortening fails"""
        try:
            if HAS_SHORTENER:
                try:
                    s = pyshorteners.Shortener()
                    shortened = s.tinyurl.short(url)
                    print(f"Successfully shortened URL: {shortened}")
                    return shortened
                except Exception as e:
                    print(f"URL shortening failed: {e}")
                    return url
            else:
                return url
        except Exception as e:
            print(f"Unexpected error in URL shortening: {e}")
            return url

    async def close(self):
        """Close the session properly when the bot shuts down"""
        if self.session is not None:
            await self.session.close()
            self.session = None
            print("Closed aiohttp session")

    async def call_mistral_api(self, prompt, max_tokens=500, temperature=0.7, timeout=30):
        """Call Mistral API with a prompt and return the generated text"""
        mistral_api_key = os.getenv("MISTRAL_API_KEY")
        if not mistral_api_key:
            print("ERROR: Mistral API key not found in environment variables.")
            return "Mistral API key not found in environment variables."
        
        try:
            print(f"Calling Mistral API with prompt of {len(prompt)} characters")
            url = "https://api.mistral.ai/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {mistral_api_key}"
            }
            
            payload = {
                "model": "mistral-medium",  # Use the appropriate model
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            
            print(f"Request payload: {json.dumps(payload)[:200]}...")
            
            async with aiohttp.ClientSession() as session:
                # Add timeout to the request
                async with session.post(url, headers=headers, json=payload, timeout=timeout) as response:
                    status_code = response.status
                    print(f"Mistral API response status: {status_code}")
                    
                    if status_code == 200:
                        data = await response.json()
                        content = data["choices"][0]["message"]["content"]
                        print(f"Received content of length: {len(content)}")
                        return content
                    else:
                        error_text = await response.text()
                        print(f"Mistral API error: {status_code} - {error_text}")
                        return f"API error: {status_code} - {error_text[:100]}"
        except asyncio.TimeoutError:
            print("Mistral API request timed out after 30 seconds")
            return "ERROR: The AI service timed out. Please try again."
        except Exception as e:
            print(f"Exception calling Mistral API: {e}")
            import traceback
            traceback.print_exc()
            return f"Error: {str(e)}"

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

    async def process_natural_language(self, message_content, author, mentioned_users):
        """Process natural language using Mistral API to understand intent and extract entities"""
        # Filter out the bot itself from mentioned_users before processing
        mentioned_users = [user for user in mentioned_users if user.id != self.bot.user.id]
        
        # Prepare more comprehensive prompt for Mistral with stronger emphasis on date detection
        prompt = f"""
        You are a scheduling assistant for a Discord bot called Skedge. Analyze this message and determine:
        1. What is the user's intent? (schedule_meeting, view_calendar, check_free_time, get_help, register)
        2. Who is involved? (the message author or mentioned people)
        3. IMPORTANT: Look for ANY time and date parameters mentioned:
           - Duration (e.g., 30 minutes, 1 hour)
           - Specific dates/day references (e.g., tomorrow, next Monday, this weekend, May 15th)
           - Days ahead (e.g., next 3 days)
           - Time of day references (morning, afternoon, evening)
        
        Message: {message_content}
        
        Respond in JSON format:
        {{
            "intent": "one of [schedule_meeting, view_calendar, check_free_time, get_help, register, unknown]",
            "target_users": "list of user mentions or 'author' if about the message sender",
            "duration_minutes": optional number,
            "days_ahead": optional number,
            "date_reference": optional string (e.g., "tomorrow", "next Monday", "weekend"),
            "time_of_day": optional string (e.g., "morning", "afternoon", "evening"),
            "specific_date": optional date in YYYY-MM-DD format if a specific date was mentioned
        }}
        
        Be particularly thorough in identifying date references. For example, if the message mentions "Friday", that should be included in date_reference. If it mentions a specific date like "May 15th", convert it to YYYY-MM-DD format in specific_date.
        """
        
        # Call Mistral API
        response = await self.call_mistral_api(prompt)
        
        try:
            # Parse the JSON response
            parsed_response = json.loads(response)
            print(f"Mistral parsed: {parsed_response}")  # Add logging to see what Mistral detected
            
            # Route to appropriate command based on intent
            if parsed_response["intent"] == "schedule_meeting":
                # Create findtime command
                return self.create_findtime_command(parsed_response, author, mentioned_users)
                
            elif parsed_response["intent"] == "view_calendar":
                # Create viewcal command
                return self.create_viewcal_command(parsed_response, author, mentioned_users)
                
            elif parsed_response["intent"] == "check_free_time":
                # Create freetime command
                return self.create_freetime_command(parsed_response, author, mentioned_users)
                
            elif parsed_response["intent"] == "get_help":
                # Create help command
                return "!help"
                
            elif parsed_response["intent"] == "register":
                # Create register command
                return "!register"
                
            else:
                # Unknown intent
                return None
                
        except Exception as e:
            print(f"Error processing Mistral response: {e}")
            return None

    def create_findtime_command(self, parsed_response, author, mentioned_users):
        """Create a !findtime command from parsed Mistral response with time references"""
        # Make sure we don't include the bot itself
        mentioned_users = [user for user in mentioned_users if user.id != self.bot.user.id]
        
        # Start with the base command
        command = "!findtime"
        
        # Add mentions if available
        if mentioned_users:
            for user in mentioned_users:
                command += f" {user.mention}"
        
        # Add duration if specified with validation
        if "duration_minutes" in parsed_response and parsed_response["duration_minutes"]:
            duration = parsed_response["duration_minutes"]
            # Sanitize duration (between 5 and 240 minutes)
            if isinstance(duration, (int, float)):
                duration = max(5, min(240, int(duration)))
                command += f" duration={duration}"
        
        # Add days_ahead if specified with validation
        if "days_ahead" in parsed_response and parsed_response["days_ahead"]:
            days = parsed_response["days_ahead"]
            # Sanitize days (between 1 and 14 days)
            if isinstance(days, (int, float)):
                days = max(1, min(14, int(days)))
                command += f" days={days}"
        
        # Add date_reference if specified
        if "date_reference" in parsed_response and parsed_response["date_reference"]:
            command += f" date={parsed_response['date_reference']}"
        
        # Add time_of_day if specified
        if "time_of_day" in parsed_response and parsed_response["time_of_day"]:
            command += f" time={parsed_response['time_of_day']}"
        
        # Add specific_date if specified
        if "specific_date" in parsed_response and parsed_response["specific_date"]:
            command += f" date={parsed_response['specific_date']}"
        
        return command

    def create_viewcal_command(self, parsed_response, author, mentioned_users):
        """Create a !viewcal command from parsed Mistral response with time references"""
        # Make sure we don't include the bot itself
        mentioned_users = [user for user in mentioned_users if user.id != self.bot.user.id]
        
        command = "!viewcal"
        
        # If target is not the author, add the target mention
        if "target_users" in parsed_response and parsed_response["target_users"] != "author":
            if mentioned_users:
                command += f" {mentioned_users[0].mention}"
        
        # Add date_reference if specified (custom parameter)
        if "date_reference" in parsed_response and parsed_response["date_reference"]:
            command += f" date={parsed_response['date_reference']}"
        
        # Add specific_date if specified (custom parameter)
        if "specific_date" in parsed_response and parsed_response["specific_date"]:
            command += f" date={parsed_response['specific_date']}"
        
        return command

    def create_freetime_command(self, parsed_response, author, mentioned_users):
        """Create a !freetime command from parsed Mistral response with time references"""
        # Make sure we don't include the bot itself
        mentioned_users = [user for user in mentioned_users if user.id != self.bot.user.id]
        
        command = "!freetime"
        
        # Only include a target user if we have valid mentioned users
        if mentioned_users:
            command += f" {mentioned_users[0].mention}"
        
        # Add date_reference if specified (custom parameter)
        if "date_reference" in parsed_response and parsed_response["date_reference"]:
            command += f" date={parsed_response['date_reference']}"
        
        # Add time_of_day if specified (custom parameter)
        if "time_of_day" in parsed_response and parsed_response["time_of_day"]:
            command += f" time={parsed_response['time_of_day']}"
        
        # Add specific_date if specified (custom parameter)
        if "specific_date" in parsed_response and parsed_response["specific_date"]:
            command += f" date={parsed_response['specific_date']}"
        
        return command

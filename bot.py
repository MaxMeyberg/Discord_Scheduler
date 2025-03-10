import os
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv
from agent import MistralAgent
from datetime import datetime, timedelta
import json
import asyncio
import pytz
import aiohttp

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord')

# Load environment variables
load_dotenv()

# Bot configuration
PREFIX = "!"
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Initialize agent
agent = MistralAgent(bot)

# Remove default help command
bot.remove_command('help')

# Admin users list
ADMIN_USERS = [
    "maxmeyberg",  
    "maxtonian",
    "itsalbertom", 
]

# Simplified admin check function
def is_admin(member):
    """Check if a member is an admin using their username or display name"""
    is_admin_user = (
        member.name.lower() in [name.lower() for name in ADMIN_USERS] or 
        member.display_name.lower() in [name.lower() for name in ADMIN_USERS]
    )
    return is_admin_user

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    logger.info(f"{bot.user} has connected to Discord!")
    print(f"Logged in as {bot.user}")
    print(f"Bot is ready with prefix: {PREFIX}")
    print(f"No cogs loaded - all commands are directly in bot.py")
    
    # Set up the agent's session
    await agent.setup_session()

@bot.event
async def on_message(message):
    """Process incoming messages"""
    # Process commands
    await bot.process_commands(message)
    
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Handle registration DMs
    if isinstance(message.channel, discord.DMChannel) and not message.content.startswith(PREFIX):
        await agent.process_registration_dm(message)
        return

@bot.command(name="help")
async def help_command(ctx):
    """Show available commands"""
    embed = discord.Embed(
        title="📅 Skedge Help",
        description="Here are the available commands:",
        color=discord.Color.blue()
    )
    
    # Standard commands
    embed.add_field(
        name="Calendar Connection",
        value=(
            "`!register` - Connect your Google Calendar to Skedge\n"
            "`!unregister` - Remove your calendar connection\n"
            "`!status` - Check if your calendar is connected"
        ),
        inline=False
    )
    
    embed.add_field(
        name="Calendar View",
        value=(
            "`!viewcal` or `!cal` - View your calendar for the week\n"
            "`!viewcal @user` - View another user's calendar (if they're registered)"
        ),
        inline=False
    )
    
    embed.add_field(
        name="Scheduling",
        value=(
            "`!findtime @user` - Find available meeting times (default: next 3 days, 30 min)\n"
            "`!findtime @user duration=15` - Find 15-minute meeting slots\n"
            "`!findtime @user days=7` - Look ahead 7 days instead of 3\n"
            "`!findtime @user1 @user2 duration=15 days=7` - Multiple users with options"
        ),
        inline=False
    )
    
    # Admin commands - only show to admins
    if is_admin(ctx.author):
        embed.add_field(
            name="Admin Commands",
            value=(
                "`!users` - List all registered users\n"
                "`!dbtest` - Test database connection"
            ),
            inline=False
        )
    
    embed.set_footer(text="Made with ❤️ by the Skedge team")
    await ctx.send(embed=embed)

@bot.command(name="viewcal", aliases=["calendar", "cal"])
async def view_calendar(ctx, username=None):
    """View a user's calendar for the next week"""
    # Resolve target user
    target_user = None
    if username:
        # Try to find by mention
        if ctx.message.mentions:
            target_user = ctx.message.mentions[0]
        else:
            # Try to find by name
            for member in ctx.guild.members:
                if username.lower() in member.name.lower() or (member.nick and username.lower() in member.nick.lower()):
                    target_user = member
                    break
    else:
        # Default to command invoker
        target_user = ctx.author
    
    if not target_user:
        await ctx.send(f"❌ User '{username}' not found.")
        return
        
    # Check if the user is registered
    user_data = await agent.db.get_user(str(target_user.id))
    if not user_data or not user_data.get("access_token"):
        await ctx.send(f"❌ {target_user.mention} is not registered or needs to reconnect their calendar.")
        return
    
    # Send a "working on it" message
    loading_message = await ctx.send(f"📅 Fetching calendar for {target_user.mention}...")
    
    try:
        # Access token for API call
        access_token = user_data.get("access_token")
        
        # Check if token is expired and needs refresh
        token_expiry = user_data.get("token_expiry", 0)
        
        # Fix for token_expiry handling - handle both timestamp and ISO format
        current_time = datetime.now().timestamp()
        
        # If token_expiry is a string, try to handle it properly
        if isinstance(token_expiry, str):
            try:
                # First try direct float conversion (for legacy timestamps)
                token_expiry = float(token_expiry)
            except ValueError:
                try:
                    # If that fails, try parsing as ISO datetime
                    expiry_dt = datetime.fromisoformat(token_expiry)
                    token_expiry = expiry_dt.timestamp()
                except Exception:
                    # If all parsing fails, assume token is expired
                    token_expiry = 0
                    print(f"Could not parse token expiry: {token_expiry}")
        
        if current_time > token_expiry:
            # Try to refresh the token
            refresh_success = await refresh_token_for_user(
                target_user.id, user_data.get("refresh_token")
            )
            
            if refresh_success:
                # Get the updated user data with new token
                user_data = await agent.db.get_user(str(target_user.id))
                access_token = user_data.get("access_token")
            else:
                await ctx.send(f"❌ Could not refresh the calendar token for {target_user.mention}. Please `!unregister` and `!register` again.")
                await loading_message.delete()
                return
                
        # Get user's timezone or use Pacific by default
        user_tz = user_data.get("timezone", "America/Los_Angeles")
        display_timezone = pytz.timezone(user_tz)
        
        # Get calendar events for the next 7 days
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=7)
        
        # Fetch events from Cronofy
        status, response_text = await agent.cronofy_api_call(
            endpoint="v1/events",
            auth_token=access_token,
            params={
                "tzid": user_tz,
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "include_managed": "true"
            }
        )
        
        if status != 200:
            if status == 401:
                await ctx.send(f"❌ Authentication failed for {target_user.mention}'s calendar. They need to `!unregister` and `!register` again.")
            else:
                await ctx.send(f"❌ Error fetching calendar: {status}")
            await loading_message.delete()
            return
        
        # Parse the events
        try:
            response_data = json.loads(response_text)
            events = response_data.get("events", [])
            
            if not events:
                await ctx.send(f"📅 No events found in {target_user.mention}'s calendar for the next week.")
                await loading_message.delete()
                return
            
            # Format the events nicely
            formatted_events = format_events(events, display_timezone)
            await ctx.send(f"📅 **Calendar for {target_user.mention}**:\n{formatted_events}")
            
        except Exception as e:
            await ctx.send(f"❌ Error processing calendar data: {str(e)}")
            print(f"Error processing calendar: {e}")
        
        # Delete the loading message
        await loading_message.delete()
        
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")
        await loading_message.delete()
        print(f"Calendar view error: {e}")

def format_events(events, display_timezone):
    """Format events into a readable text format"""
    days = {}
    
    for event in events:
        try:
            # Get basic event info
            summary = event.get("summary", "Untitled Event")
            
            # Handle different time formats from the API
            start_str = event.get("start", "")
            end_str = event.get("end", "")
            
            # Default time string
            time_str = "All day"
            day_str = ""
            
            # Handle event times
            if isinstance(start_str, str) and "T" in start_str:
                # Parse start time - assume UTC since we requested UTC times
                event_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                if event_start.tzinfo is None:
                    event_start = event_start.replace(tzinfo=pytz.UTC)
                
                # Always convert to the display timezone
                local_start = event_start.astimezone(display_timezone)
                
                # Parse end time with the same approach
                event_end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if event_end.tzinfo is None:
                    event_end = event_end.replace(tzinfo=pytz.UTC)
                local_end = event_end.astimezone(display_timezone)
                
                # Format times
                day_str = local_start.strftime("%Y-%m-%d")
                start_time_str = local_start.strftime("%-I:%M %p")
                end_time_str = local_end.strftime("%-I:%M %p")
                
                # Get timezone abbreviation
                tz_abbr = local_start.strftime("%Z")
                time_str = f"{start_time_str} - {end_time_str} {tz_abbr}"
            
            # Add to the appropriate day
            if day_str not in days:
                days[day_str] = []
            
            days[day_str].append({
                "time": time_str,
                "summary": summary
            })
        except Exception as e:
            print(f"Error parsing event: {e}")
            continue
    
    # Format the output
    formatted_events = "```\n"
    
    for day_str in sorted(days.keys()):
        # Convert day string to datetime for proper formatting
        day_date = datetime.strptime(day_str, "%Y-%m-%d").date()
        day_name = day_date.strftime("%A, %B %d")
        
        formatted_events += f"{day_name}:\n"
        
        # Sort events by time
        days[day_str].sort(key=lambda x: x["time"])
        
        for event in days[day_str]:
            formatted_events += f"  • {event['time']}: {event['summary']}\n"
        
        formatted_events += "\n"
    
    formatted_events += "```"
    return formatted_events

async def refresh_token_for_user(user_id, refresh_token):
    """Attempt to refresh an expired token"""
    try:
        token_url = "https://api.cronofy.com/oauth/token"
        payload = {
            "client_id": agent.cronofy_client_id,
            "client_secret": os.getenv("CRONOFY_CLIENT_SECRET"),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }
        
        headers = {"Content-Type": "application/json"}
        
        async with agent.session.post(token_url, headers=headers, json=payload) as response:
            if response.status == 200:
                token_data = await response.json()
                
                # Update user with new tokens
                user_data = await agent.db.get_user(str(user_id))
                if user_data:
                    user_data["access_token"] = token_data.get("access_token")
                    user_data["refresh_token"] = token_data.get("refresh_token")
                    user_data["token_expiry"] = datetime.now().timestamp() + token_data.get("expires_in", 3600)
                    
                    # Save updated tokens
                    await agent.db.save_user(user_data)
                    return True
            else:
                error_data = await response.text()
                print(f"Token refresh error: {error_data}")
                return False
    except Exception as e:
        print(f"Exception refreshing token: {e}")
        return False
    
    return False

@bot.command(name="register", help="Connect your Google Calendar to Skedge")
async def register(ctx):
    """Start the registration process"""
    user = ctx.author
    
    # Check if already registered
    user_data = await agent.db.get_user(str(user.id))
    if user_data:
        await ctx.send(f"{user.mention}, you're already registered! If you're having issues, try `!unregister` first, then register again.")
        return
        
    # Check if registration in progress
    if user.id in agent.registration_states:
        await ctx.send(f"{user.mention}, you already have a registration in progress. Please check your DMs.")
        return
        
    # Start registration
    success, auth_url = await agent.start_registration(user)
    
    if success:
        await user.send(
            f"Thanks for registering with Schedge!\n\n"
            f"**IMPORTANT:** Before clicking the link below, make sure you're logged into YOUR Google account in your browser.\n\n"
            f"To connect your calendar, click this link:\n"
            f"{auth_url}\n\n"
            f"After authorizing, you'll see a Postman page with a callback URL that will look like one of these:\n"
            f"• `https://oauth.pstmn.io/v1/callback?code=XXXX...`\n"
            f"• `postman://app/oauth2/callback?code=XXXX...`\n\n"
            f"Please copy that ENTIRE URL and paste it back to me here.\n\n"
            f"If you encounter any errors, try `!unregister` followed by `!register` again."
        )
        await ctx.send(f"{ctx.author.mention}, I've sent you a DM with registration instructions. Please check your messages!")
    else:
        await ctx.send(f"Error starting registration process. Please try again later.")


@bot.command(name="unregister", help="Remove your calendar connection from Skedge")
async def unregister(ctx):
    """Unregister a user and cancel any registration in progress"""
    user = ctx.author
    registration_in_progress = user.id in agent.registration_states
    
    # Check if registered or has registration in progress
    user_data = await agent.db.get_user(str(user.id))
    
    if not user_data and not registration_in_progress:
        await ctx.send(f"{user.mention}, you're not registered yet!")
        return
    
    # Message to confirm what we're doing
    message = f"{user.mention}, you've been successfully unregistered from Skedge!"
    if registration_in_progress:
        message = f"{user.mention}, your registration process has been canceled and any existing data has been removed."
    
    # Clean up all user data
    if user.id in agent.user_database:
        del agent.user_database[user.id]
    if user.id in agent.registration_states:
        del agent.registration_states[user.id]
    if user.id in agent.oauth_polling:
        del agent.oauth_polling[user.id]
    
    # Delete from database
    await agent.db.delete_user(str(user.id))
    
    await ctx.send(message)


@bot.command(name="status", help="Check your registration status")
async def status(ctx):
    """Check a user's registration status"""
    user_data = await agent.db.get_user(str(ctx.author.id))
    
    if not user_data:
        await ctx.send(f"{ctx.author.mention}, you're not registered. Use `!register` to connect your calendar.")
        return
    
    if user_data.get("access_token"):
        await ctx.send(f"{ctx.author.mention}, your calendar is connected and active. ✅")
    else:
        await ctx.send(f"{ctx.author.mention}, your registration is pending. Please complete the process by following the DM instructions.")

@bot.event
async def on_close():
    """Called when the bot is shutting down"""
    print("Bot is shutting down, closing sessions...")
    await agent.close()

@bot.command(name="users")
async def list_users(ctx):
    """List all registered users (admin only)"""
    # Admin check
    if not is_admin(ctx.author):
        await ctx.send("❌ This command is only available to admins.")
        return
    
    # Get all users from database
    all_users = await agent.db.get_all_users()
    
    if not all_users:
        await ctx.send("No users are currently registered.")
        return
    
    # Create an embed to display user info
    embed = discord.Embed(
        title="Registered Users",
        description=f"There are {len(all_users)} registered users.",
        color=discord.Color.blue()
    )
    
    # Add each user to the embed
    for user_data in all_users:
        discord_id = user_data.get("discord_id", "Unknown")
        discord_name = user_data.get("discord_name", "Unknown")
        
        # Check token status
        has_token = "access_token" in user_data and user_data["access_token"]
        token_status = "✅ Active" if has_token else "❌ Missing"
        
        # Check expiry - FIXED TYPE ERROR
        token_expiry = user_data.get("token_expiry", 0)
        expiry_text = ""
        if token_expiry:
            try:
                # If token_expiry is a string, try to handle it properly
                if isinstance(token_expiry, str):
                    try:
                        # First try direct float conversion (for legacy timestamps)
                        token_expiry = float(token_expiry)
                    except ValueError:
                        try:
                            # If that fails, try parsing as ISO datetime
                            expiry_dt = datetime.fromisoformat(token_expiry)
                            token_expiry = expiry_dt.timestamp()
                        except Exception:
                            # If parsing fails, keep the string for display
                            expiry_text = f"\nExpiry data invalid: {token_expiry}"
                            token_expiry = None
                
                if token_expiry is not None:
                    expiry_date = datetime.fromtimestamp(token_expiry)
                    expiry_text = f"\nExpires: {expiry_date.strftime('%Y-%m-%d %H:%M')}"
            except (ValueError, TypeError) as e:
                expiry_text = f"\nExpiry data error: {str(e)}"
        
        embed.add_field(
            name=f"{discord_name} ({discord_id})",
            value=f"Token: {token_status}{expiry_text}",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name="dbtest")
async def db_test(ctx):
    """Test database connection"""
    try:
        user_count = len(await agent.db.get_all_users())
        await ctx.send(f"✅ Database connection successful. Found {user_count} users.")
    except Exception as e:
        await ctx.send(f"❌ Database error: {type(e).__name__}: {str(e)}")

@bot.command(name="findtime", aliases=["schedule", "meet"])
async def find_time(ctx, *, participants_and_options=None):
    """Find available meeting times between registered users
    
    Usage: !findtime @user1 @user2 [options]
    Options (optional):
      duration=30 (in minutes)
      days=3 (how many days ahead to look)
    """
    # Parse command arguments
    if not participants_and_options:
        await ctx.send("❌ Please mention at least one other user to find meeting times with.")
        return
    
    # Parse mentions and any options
    mentions = ctx.message.mentions
    participants = [ctx.author] + mentions  # Include command author
    
    # Make sure we have at least 2 participants
    if len(participants) < 2:
        await ctx.send("❌ Please mention at least one other user to find meeting times with.")
        return
    
    # Check that all participants are registered
    unregistered_users = []
    participant_tokens = {}
    participant_profile_ids = []
    
    # Loading message
    loading_msg = await ctx.send(f"🔍 Finding available times for {len(participants)} participants...")
    
    # Get tokens and profile IDs for all participants
    for user in participants:
        user_data = await agent.db.get_user(str(user.id))
        if not user_data or not user_data.get("access_token"):
            unregistered_users.append(user.mention)
        else:
            # Handle token expiry
            token_expiry = user_data.get("token_expiry", 0)
            current_time = datetime.now().timestamp()
            
            # Parse token_expiry properly
            if isinstance(token_expiry, str):
                try:
                    token_expiry = float(token_expiry)
                except ValueError:
                    try:
                        expiry_dt = datetime.fromisoformat(token_expiry)
                        token_expiry = expiry_dt.timestamp()
                    except Exception:
                        token_expiry = 0
            
            # Refresh token if needed
            if current_time > token_expiry:
                refreshed = await refresh_token_for_user(user.id, user_data.get("refresh_token"))
                if refreshed:
                    user_data = await agent.db.get_user(str(user.id))
                else:
                    unregistered_users.append(user.mention)
                    continue
            
            # Get Cronofy profile ID
            try:
                status, userinfo_response = await agent.cronofy_api_call(
                    endpoint="v1/userinfo",
                    auth_token=user_data.get("access_token")
                )
                
                if status != 200:
                    print(f"Failed to get userinfo: {status}")
                    unregistered_users.append(user.mention)
                    continue
                
                userinfo = json.loads(userinfo_response)
                cronofy_sub = userinfo.get("sub")
                
                if not cronofy_sub:
                    print(f"No sub ID in userinfo for {user.display_name}")
                    unregistered_users.append(user.mention)
                    continue
                
                # Store the access token and profile ID
                participant_tokens[str(user.id)] = user_data.get("access_token")
                participant_profile_ids.append({
                    "sub": cronofy_sub
                })
                
                print(f"Found Cronofy profile ID for {user.display_name}: {cronofy_sub}")
                
            except Exception as e:
                print(f"Error getting user profile: {e}")
                unregistered_users.append(user.mention)
                continue
    
    # If any users aren't registered, notify and exit
    if unregistered_users:
        if len(unregistered_users) == 1:
            await ctx.send(f"❌ {unregistered_users[0]} needs to connect their calendar using `!register` first.")
        else:
            users_list = ", ".join(unregistered_users)
            await ctx.send(f"❌ These users need to connect their calendars: {users_list}")
        await loading_msg.delete()
        return
    
    # Parse options
    duration = 30  # Default 30 minute meetings
    days_ahead = 3  # Default look 3 days ahead
    
    if participants_and_options:
        options_text = participants_and_options.split(" ")
        for option in options_text:
            if "duration=" in option:
                try:
                    duration = int(option.split("=")[1])
                except:
                    pass
            if "days=" in option:
                try:
                    days_ahead = int(option.split("=")[1])
                except:
                    pass
    
    # Prepare query periods (days with business hours)
    now = datetime.now()
    query_periods = []
    
    # Start from tomorrow to avoid partial day issues
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    
    for day_offset in range(days_ahead):
        day = start_day + timedelta(days=day_offset)
        
        # Skip weekends if you want - COMMENTING OUT TO INCLUDE WEEKENDS
        # if day.weekday() < 5:  # 0-4 are weekdays (Mon-Fri)
        
        # Extended hours: 7 AM - 9 PM
        day_start = day.replace(hour=7, minute=0, second=0)
        day_end = day.replace(hour=21, minute=0, second=0)
        
        query_periods.append({
            "start": day_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": day_end.strftime("%Y-%m-%dT%H:%M:%SZ")
        })
    
    try:
        # Build availability request with the correct format
        availability_data = {
            "participants": [
                {
                    "members": participant_profile_ids,
                    "required": "all"
                }
            ],
            "required_duration": {"minutes": duration},
            "available_periods": [
                {
                    "start": start_day.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": (start_day + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
                }
            ]
        }
        
        # Debug print
        print("==== AVAILABILITY REQUEST ====")
        print(json.dumps(availability_data, indent=2))
        print("=============================")
        
        # Make the API call using first participant's token
        first_token = list(participant_tokens.values())[0]
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {first_token}"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.cronofy.com/v1/availability", 
                headers=headers,
                json=availability_data
            ) as response:
                response_text = await response.text()
                
                # Debug print
                print("==== AVAILABILITY RESPONSE ====")
                print(f"Status: {response.status}")
                print(response_text)
                print("=============================")
                
                if response.status == 200:
                    result = json.loads(response_text)
                    available_slots = result.get("slots", [])
                    
                    if not available_slots:
                        await ctx.send(f"❌ No common availability found in the next {days_ahead} days for a {duration} minute meeting.")
                    else:
                        # Format available slots
                        slot_text = format_available_slots(available_slots)
                        
                        # Show results
                        participant_names = [p.display_name for p in participants]
                        names_text = ", ".join(participant_names)
                        
                        embed = discord.Embed(
                            title=f"📅 Available Meeting Times",
                            description=f"Common availability for: {names_text}\nFor a {duration} minute meeting:",
                            color=discord.Color.green()
                        )
                        
                        embed.add_field(name="Available Slots", value=slot_text, inline=False)
                        embed.set_footer(text="To schedule, copy a time and create a calendar event")
                        
                        await ctx.send(embed=embed)
                else:
                    await ctx.send(f"❌ Error finding availability: {response.status} - {response_text[:100]}")
    except Exception as e:
        await ctx.send(f"❌ Error checking availability: {str(e)}")
        print(f"Availability API error: {e}")
    
    # Delete loading message
    await loading_msg.delete()

def format_available_slots(slots):
    """Format available time slots into readable text"""
    if not slots:
        return "No available slots found."
    
    formatted_text = ""
    current_day = None
    
    for slot in slots:
        # Updated to work with new format from Cronofy slots format
        start_time = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
        
        # Convert to local time (Pacific Time)
        pacific = pytz.timezone("America/Los_Angeles")
        local_start = start_time.astimezone(pacific)
        local_end = end_time.astimezone(pacific)
        
        # Check if this is a new day
        day_str = local_start.strftime("%A, %B %d")
        if day_str != current_day:
            current_day = day_str
            formatted_text += f"\n**{day_str}**\n"
        
        # Format the time slot
        start_str = local_start.strftime("%-I:%M %p")
        end_str = local_end.strftime("%-I:%M %p %Z")
        formatted_text += f"• {start_str} - {end_str}\n"
    
    return formatted_text

@bot.command(name="freetime")
async def free_time(ctx, username=None):
    """Check a user's free time directly from their calendar"""
    # Get target user
    target_user = ctx.author
    if username and ctx.message.mentions:
        target_user = ctx.message.mentions[0]
        
    # Get user data
    user_data = await agent.db.get_user(str(target_user.id))
    if not user_data or not user_data.get("access_token"):
        await ctx.send(f"❌ {target_user.mention} is not registered.")
        return
    
    # Get free/busy directly
    access_token = user_data.get("access_token")
    start_date = datetime.now()
    end_date = start_date + timedelta(days=3)
    
    status, response_text = await agent.cronofy_api_call(
        endpoint="v1/free_busy",
        auth_token=access_token,
        params={
            "from": start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
    )
    
    if status == 200:
        response_data = json.loads(response_text)
        free_busy = response_data.get("free_busy", [])
        
        if not free_busy:
            await ctx.send(f"📅 No busy periods found for {target_user.mention} in the next 3 days.")
        else:
            # Count busy periods
            count = len(free_busy)
            await ctx.send(f"📅 Found {count} busy periods for {target_user.mention} in the next 3 days.")
            
            # Show a few examples
            if count > 0:
                examples = free_busy[:3]  # Show up to 3 examples
                example_text = "\n".join([f"• {e.get('start')} to {e.get('end')}" for e in examples])
                await ctx.send(f"Example busy times:\n{example_text}")
    else:
        await ctx.send(f"❌ Error checking free/busy: {status}")

# Run the bot
if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
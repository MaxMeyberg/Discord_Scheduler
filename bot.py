import os
import discord
import logging
from discord.ext import commands, tasks
from dotenv import load_dotenv
from agent import MistralAgent
from datetime import datetime, timedelta
import json
import pytz
import copy

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('discord')

# Load environment variables and setup bot
load_dotenv()
PREFIX = "!"
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)
agent = MistralAgent(bot)
bot.remove_command('help')

# Admin users list
ADMIN_USERS = ["maxmeyberg", "maxtonian", "itsalbertom"]

# Simplified admin check function
def is_admin(member):
    """Check if a member is an admin using their username or display name"""
    is_admin_user = (
        member.name.lower() in [name.lower() for name in ADMIN_USERS] or 
        member.display_name.lower() in [name.lower() for name in ADMIN_USERS]
    )
    return is_admin_user

# Store processed message IDs
PROCESSED_MESSAGES = set()

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    logger.info(f"{bot.user} has connected to Discord!")
    print(f"Logged in as {bot.user}")
    
    # Set up the agent's session
    await agent.setup_session()
    
    # Start the cleanup task
    cleanup_processed_messages.start()

@bot.event
async def on_message(message):
    """Process messages and catch mentions"""
    # Skip messages from the bot itself
    if message.author == bot.user:
        return
        
    # Special handling for DMs - process registration callbacks
    if message.guild is None:
        print(f"Processing DM: '{message.content}'")
        
        # Check if this is an OAuth callback URL
        if "code=" in message.content and ("postman" in message.content.lower() or "callback" in message.content.lower()):
            print("Detected OAuth callback URL in DM")
            
            # Extract the auth code
            try:
                code_start = message.content.find("code=") + 5
                code_end = message.content.find("&", code_start)
                
                if code_end == -1:  # No & after code
                    auth_code = message.content[code_start:]
                else:
                    auth_code = message.content[code_start:code_end]
                
                # Process the auth code
                success = await agent.process_auth_code(message.author, auth_code)
                
                if success:
                    await message.channel.send("✅ Successfully connected your calendar! You can now use Skedge's scheduling features.")
                else:
                    await message.channel.send("❌ There was a problem connecting your calendar. Please try `!register` again or contact support.")
                return
            except Exception as e:
                await message.channel.send(f"❌ Error processing registration: {str(e)}")
                return
        
        # For other DMs, just process as normal commands
        await bot.process_commands(message)
        return
        
    # Prevent recursive processing
    if message.id in PROCESSED_MESSAGES:
        await bot.process_commands(message)
        return
    
    # Check if the bot is mentioned
    is_mentioned = False
    mention_string = f"<@{bot.user.id}>"
    if mention_string in message.content or bot.user in message.mentions:
        is_mentioned = True
    
    # If not mentioned, just process commands
    if not is_mentioned:
        await bot.process_commands(message)
        return
        
    # Process the mention
    content = message.content.lower().replace(f"<@{bot.user.id}>", "").strip()
    print(f"Processing mention: '{content}'")
    
    # Extract mentions (except the bot)
    mentioned_users = [user for user in message.mentions if user.id != bot.user.id]
    
    # Find time command handling
    if "free" in content and ("when" in content or "time" in content) and mentioned_users:
        await message.channel.send(f"🔍 Looking for common free time...")
        
        # Create a command message
        fake_message = copy.copy(message)
        mention_text = " ".join([user.mention for user in mentioned_users if user.id != bot.user.id])
        
        if not mention_text:
            await message.channel.send("❌ Please mention at least one other user to find common free time.")
            return
        
        fake_message.content = f"!findtime {mention_text}"
        PROCESSED_MESSAGES.add(fake_message.id)
        
        # Execute the command
        ctx = await bot.get_context(fake_message)
        if ctx.valid:
            await bot.process_commands(fake_message)
        else:
            await message.channel.send(f"❌ I couldn't run the findtime command. Try using `!findtime @user` directly.")
    else:
        await message.channel.send(f"I'm not sure what you're asking. For finding meeting times, try: '@Schedge when are @user and I free?'")

@tasks.loop(minutes=10)
async def cleanup_processed_messages():
    """Clear the processed messages set periodically"""
    global PROCESSED_MESSAGES
    print(f"Cleaning up {len(PROCESSED_MESSAGES)} processed messages")
    PROCESSED_MESSAGES.clear()

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
            "`!viewcal @user` - View another user's calendar (if they're registered)\n"
            "`!freetime` - Show your available time slots (6AM-9PM, next 3 days)\n"
            "`!freetime @user` - Show available time slots for another user"
        ),
        inline=False
    )
    
    embed.add_field(
        name="Scheduling",
        value=(
            "`!findtime @user` - Find overlapping free time between you and mentioned users\n"
            "`!findtime @user duration=15` - Find common free slots of at least 15 minutes\n"
            "`!findtime @user days=7` - Look ahead 7 days instead of the default 3 days\n"
            "`!findtime @user1 @user2 duration=15 days=7` - Multiple users with options"
        ),
        inline=False
    )
    
    # Add AI Assistant section - updated for mentions
    embed.add_field(
        name="AI Calendar Assistant",
        value=(
            "Mention the bot (@Skedge) in your message to ask any scheduling question:\n"
            "• @Skedge When am I free tomorrow?\n"
            "• @Skedge Find time to meet with @user\n"
            "• @Skedge Show me my calendar"
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
    
    # Add a section for default values and tips
    embed.add_field(
        name="Default Settings",
        value=(
            "• Business hours: 6:00 AM - 9:00 PM\n"
            "• Scheduling window: Next 3 days\n"
            "• Minimum meeting duration: 30 minutes\n"
            "• Minimum free time slot: 15 minutes"
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
        current_time = datetime.now(pytz.UTC).timestamp()
        
        # If token_expiry is a string, try to handle it properly
        if isinstance(token_expiry, str):
            try:
                # First try direct float conversion (for legacy timestamps)
                token_expiry = float(token_expiry)
            except ValueError:
                try:
                    # If that fails, try parsing as ISO datetime with timezone
                    expiry_dt = datetime.fromisoformat(token_expiry.replace('Z', '+00:00'))
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
                
                # Get token expiry time (default to 1 hour if not specified)
                expires_in = token_data.get("expires_in", 3600)
                token_expiry = datetime.now(pytz.UTC).timestamp() + expires_in
                
                # Update the user data with the new token
                user_data = {
                    "discord_id": str(user_id),
                    "access_token": token_data.get("access_token"),
                    "refresh_token": token_data.get("refresh_token"),
                    "token_expiry": token_expiry  # Using UTC-based timestamp
                }
                
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

# First, let's create a helper function to get a user's free time
async def get_user_free_periods(user_id, access_token, start_date, end_date, days_ahead):
    """Get free time periods for a user"""
    # Format dates for Cronofy
    from_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Get events from Cronofy
    status, response_text = await agent.cronofy_api_call(
        endpoint="v1/events",
        auth_token=access_token,
        params={
            "tzid": "UTC",
            "from": from_str,
            "to": to_str,
            "include_managed": "true"
        }
    )
    
    if status != 200:
        print(f"Error getting events for user {user_id}: {status}")
        return []
    
    # Parse response
    response_data = json.loads(response_text)
    events = response_data.get("events", [])
    
    # Create a list of busy periods with start and end times
    busy_periods = []
    for event in events:
        try:
            start_str = event.get("start", "")
            end_str = event.get("end", "")
            
            # Parse ISO times to datetime objects
            start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_time = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            
            busy_periods.append((start_time, end_time))
        except Exception as e:
            print(f"Error parsing event time: {e}")
    
    # Sort busy periods by start time
    busy_periods.sort(key=lambda x: x[0])
    
    # Calculate free periods between busy periods
    free_periods = []
    
    # Set time boundaries
    pacific = pytz.timezone("America/Los_Angeles")
    
    # Get current time in Pacific
    now = datetime.now(pacific)
    
    # Loop through each day
    for day_offset in range(days_ahead):
        # Calculate the day we're looking at
        target_day = (now + timedelta(days=day_offset)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        # For today, start at current time or 6AM, whichever is later
        if day_offset == 0:
            current_hour = now.hour
            current_minute = now.minute
            
            if current_hour < 6:
                time_start = target_day.replace(hour=6, minute=0)
            else:
                time_start = now
        else:
            # For future days, start at 6AM
            time_start = target_day.replace(hour=6, minute=0)
        
        # End at 9PM
        time_end = target_day.replace(hour=21, minute=0)
        
        # Filter busy periods for this day
        day_busy_periods = [
            (s, e) for s, e in busy_periods 
            if s.date() == target_day.date() or e.date() == target_day.date()
        ]
        
        # If no busy periods for this day, the whole day is free
        if not day_busy_periods:
            free_periods.append((time_start, time_end))
            continue
        
        # Calculate free time between busy periods for this day
        last_end_time = time_start
        
        for busy_start, busy_end in day_busy_periods:
            # Convert to Pacific time for comparison
            busy_start_local = busy_start.astimezone(pacific)
            busy_end_local = busy_end.astimezone(pacific)
            
            # Skip events outside our 6AM-9PM window
            if busy_end_local <= time_start or busy_start_local >= time_end:
                continue
            
            # If busy period starts after our last endpoint, we have free time
            if busy_start_local > last_end_time:
                free_periods.append((last_end_time, busy_start_local))
            
            # Update the last end time, taking the maximum
            last_end_time = max(last_end_time, busy_end_local)
        
        # Add any remaining time at the end of the day
        if last_end_time < time_end:
            free_periods.append((last_end_time, time_end))
    
    return free_periods

# Now let's update the find_time command to use this function
@bot.command(name="findtime", aliases=["schedule", "meet"])
async def find_time(ctx, *args):
    """Find common free time between multiple users"""
    # Parse arguments
    min_duration = 30  # Default: 30 minute slots
    days_ahead = 3     # Default: Look ahead 3 days
    
    # Extract parameters
    mentions = ctx.message.mentions
    participants = []
    
    # Go through args to find mentions and parameters
    for arg in args:
        # Check for duration parameter
        if arg.startswith("duration="):
            try:
                min_duration = int(arg.split("=")[1])
            except ValueError:
                await ctx.send("❌ Invalid duration format. Use `duration=30` for 30 minutes.")
                return
            
        # Check for days parameter
        elif arg.startswith("days="):
            try:
                days_ahead = int(arg.split("=")[1])
                if days_ahead > 14:
                    await ctx.send("❌ Maximum days ahead is 14.")
                    return
            except ValueError:
                await ctx.send("❌ Invalid days format. Use `days=7` for 7 days.")
                return
    
    # Include the message author by default
    participants.append(ctx.author)
    
    # Add mentioned users, filtering out the bot
    for user in mentions:
        if user.id != bot.user.id:  # Skip the bot itself
            if user not in participants:  # Avoid duplicates
                participants.append(user)
    
    # Make sure we have at least 2 participants
    if len(participants) < 2:
        await ctx.send("❌ Please mention at least one other user to find meeting times with.")
        return
    
    # Check that all participants are registered
    unregistered_users = []
    participant_tokens = {}
    
    # Loading message
    loading_msg = await ctx.send(f"🔍 Finding common free time for {len(participants)} participants...")
    
    # Get tokens for all participants
    for user in participants:
        user_data = await agent.db.get_user(str(user.id))
        if not user_data or not user_data.get("access_token"):
            unregistered_users.append(user.mention)
        else:
            # Handle token expiry
            token_expiry = user_data.get("token_expiry", 0)
            current_time = datetime.now(pytz.UTC).timestamp()
            
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
            
            # Store the access token
            participant_tokens[str(user.id)] = user_data.get("access_token")
    
    # If any users aren't registered, notify and exit
    if unregistered_users:
        if len(unregistered_users) == 1:
            await ctx.send(f"❌ {unregistered_users[0]} needs to connect their calendar using `!register` first.")
        else:
            users_list = ", ".join(unregistered_users)
            await ctx.send(f"❌ These users need to connect their calendars: {users_list}")
        await loading_msg.delete()
        return
    
    # Set start and end dates for the search period
    now = datetime.now(pytz.timezone("America/Los_Angeles"))
    start_date = now
    end_date = now + timedelta(days=days_ahead)
    
    # Get free periods for each participant
    all_free_periods = {}
    for user in participants:
        user_id = str(user.id)
        if user_id in participant_tokens:
            free_periods = await get_user_free_periods(
                user_id, 
                participant_tokens[user_id],
                start_date,
                end_date,
                days_ahead
            )
            all_free_periods[user_id] = free_periods
    
    # Find overlapping free time between all participants
    user_ids = list(all_free_periods.keys())
    
    # Start with the first user's free periods
    if not user_ids or not all_free_periods.get(user_ids[0]):
        await ctx.send("❌ No free time found for participants.")
        await loading_msg.delete()
        return
        
    common_free_periods = all_free_periods[user_ids[0]]
    
    # Intersect with each subsequent user's free periods
    for i in range(1, len(user_ids)):
        user_id = user_ids[i]
        user_free_periods = all_free_periods.get(user_id, [])
        
        # Calculate intersection with previous common free periods
        new_common_periods = []
        
        for period1 in common_free_periods:
            for period2 in user_free_periods:
                # Find overlap between periods
                overlap_start = max(period1[0], period2[0])
                overlap_end = min(period1[1], period2[1])
                
                # If there's a valid overlap, add it
                if overlap_start < overlap_end:
                    # Check if the overlap is long enough
                    duration = (overlap_end - overlap_start).total_seconds() / 60
                    if duration >= min_duration:
                        new_common_periods.append((overlap_start, overlap_end))
        
        # Update common free periods
        common_free_periods = new_common_periods
        
        # If no common periods found, exit early
        if not common_free_periods:
            break
    
    # Format results
    if not common_free_periods:
        await ctx.send(f"⛔ No common free time found for all {len(participants)} participants.")
        await loading_msg.delete()
        return
    
    # Sort by start time
    common_free_periods.sort(key=lambda x: x[0])
    
    # Merge adjacent or overlapping periods
    merged_periods = []
    if common_free_periods:
        current_start, current_end = common_free_periods[0]
        
        for start, end in common_free_periods[1:]:
            # If this period starts after current_end (with a small buffer)
            if start > current_end + timedelta(minutes=5):
                # Add the current period and start a new one
                merged_periods.append((current_start, current_end))
                current_start, current_end = start, end
            else:
                # Extend the current period
                current_end = max(current_end, end)
        
        # Add the last period
        merged_periods.append((current_start, current_end))
    
    # Create embed for display
    embed = discord.Embed(
        title=f"📅 Common Free Time",
        description=f"Found times when all {len(participants)} participants are available:",
        color=discord.Color.green()
    )
    
    # Format the time slots for display
    slots_text = ""
    current_day = None
    
    for start, end in merged_periods:
        # Get date for grouping
        day_str = start.strftime("%Y-%m-%d")
        
        if day_str != current_day:
            current_day = day_str
            # Add day header
            day_header = start.strftime("%A, %B %d")
            slots_text += f"\n**{day_header}**\n"
        
        # Format times
        start_time_str = start.strftime("%-I:%M %p")
        end_time_str = end.strftime("%-I:%M %p")
        
        # Calculate duration
        duration = (end - start).total_seconds() / 60
        hours = int(duration // 60)
        minutes = int(duration % 60)
        
        # Build the text
        slot_text = f"• {start_time_str} to {end_time_str}"
        if hours > 0:
            slot_text += f" ({hours}h"
            if minutes > 0:
                slot_text += f" {minutes}m"
            slot_text += ")"
        else:
            slot_text += f" ({minutes}m)"
            
        slots_text += slot_text + "\n"
    
    # Add participants field
    participants_text = "\n".join([f"• {user.display_name}" for user in participants])
    embed.add_field(
        name="Participants",
        value=participants_text,
        inline=False
    )
    
    # Add available slots field
    embed.add_field(
        name="📆 Available Meeting Times",
        value=slots_text.strip(),
        inline=False
    )
    
    embed.set_footer(text=f"Minimum duration: {min_duration} minutes")
    
    await ctx.send(embed=embed)
    await loading_msg.delete()

@bot.command(name="freetime")
async def free_time(ctx, username=None):
    """Show a user's free time slots in the next few days"""
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
    
    # Calculate dates - use simpler ISO format without microseconds
    now = datetime.now()
    start_date = now
    end_date = now + timedelta(days=3)
    
    # Format dates properly for Cronofy
    from_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Loading message
    loading_msg = await ctx.send(f"🔍 Finding free time for {target_user.mention}...")
    
    try:
        # Use the events endpoint for calendar data
        status, response_text = await agent.cronofy_api_call(
            endpoint="v1/events",
            auth_token=access_token,
            params={
                "tzid": "UTC",
                "from": from_str,
                "to": to_str,
                "include_managed": "true"
            }
        )
        
        if status == 200:
            response_data = json.loads(response_text)
            events = response_data.get("events", [])
            
            # Create a list of busy periods with start and end times
            busy_periods = []
            for event in events:
                try:
                    start_str = event.get("start", "")
                    end_str = event.get("end", "")
                    
                    # Parse ISO times to datetime objects
                    start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    end_time = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    
                    busy_periods.append((start_time, end_time))
                except Exception as e:
                    print(f"Error parsing event time: {e}")
            
            # Sort busy periods by start time
            busy_periods.sort(key=lambda x: x[0])
            
            # Calculate free periods between busy periods
            free_periods = []
            
            # Set time boundaries for the day (9AM to 5PM)
            pacific = pytz.timezone("America/Los_Angeles")
            
            # Start with current time or beginning of day if we're before 9AM
            current_time = now.astimezone(pacific)
            day_start = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
            
            # If it's already past 9AM, use current time as start
            if current_time.hour >= 9:
                day_start = current_time
            
            # Loop through each of the next 3 days
            for day_offset in range(3):
                # Calculate the day we're looking at
                target_day = (current_time + timedelta(days=day_offset)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                
                # For today, start at current time or 9AM, whichever is later
                if day_offset == 0:
                    time_start = day_start
                else:
                    # For future days, start at 9AM
                    time_start = target_day.replace(hour=6, minute=0)
                
                # End at 5PM
                time_end = target_day.replace(hour=21, minute=0)
                
                # Filter busy periods for this day
                day_busy_periods = [
                    (s, e) for s, e in busy_periods 
                    if s.date() == target_day.date() or e.date() == target_day.date()
                ]
                
                # If no busy periods for this day, the whole day is free
                if not day_busy_periods:
                    free_periods.append((time_start, time_end))
                    continue
                
                # Calculate free time between busy periods for this day
                last_end_time = time_start
                
                for busy_start, busy_end in day_busy_periods:
                    # Convert to Pacific time for comparison
                    busy_start_local = busy_start.astimezone(pacific)
                    busy_end_local = busy_end.astimezone(pacific)
                    
                    # Skip events outside our 9-5 window
                    if busy_end_local <= time_start or busy_start_local >= time_end:
                        continue
                    
                    # If busy period starts after our last endpoint, we have free time
                    if busy_start_local > last_end_time:
                        free_periods.append((last_end_time, busy_start_local))
                    
                    # Update the last end time, taking the maximum
                    last_end_time = max(last_end_time, busy_end_local)
                
                # Add any remaining time at the end of the day
                if last_end_time < time_end:
                    free_periods.append((last_end_time, time_end))
            
            # Count free time slots
            slot_count = len(free_periods)
            
            if slot_count == 0:
                await ctx.send(f"❌ No free time found for {target_user.mention} in the next 3 days during business hours (9AM-5PM).")
                await loading_msg.delete()
                return
                
            # Create embed for the free time display
            embed = discord.Embed(
                title=f"📅 Free Time for {target_user.display_name}", 
                color=discord.Color.blue()
            )
            
            # Create description with the count
            embed.description = f"Found {slot_count} free time slots in the next 3 days:"
            
            # Format free time slots for display - match viewcal style
            free_times_text = ""
            current_day = None
            
            for start, end in free_periods:
                # Check if the free period is at least 15 minutes
                duration = (end - start).total_seconds() / 60
                if duration < 15:  # Skip slots shorter than 15 minutes
                    continue
                
                # Get date for grouping
                day_str = start.strftime("%Y-%m-%d")
                
                if day_str != current_day:
                    current_day = day_str
                    # Add day header - format it like viewcal does
                    day_header = start.strftime("%A, %B %d")
                    free_times_text += f"**{day_header}**\n"
                
                # Format times to match viewcal's format
                start_time_str = start.strftime("%-I:%M %p")
                end_time_str = end.strftime("%-I:%M %p")
                
                # Build the free time entry with duration
                slot_text = f"• {start_time_str} to {end_time_str}"
                hours = int(duration // 60)
                minutes = int(duration % 60)
                
                if hours > 0:
                    slot_text += f" ({hours}h"
                    if minutes > 0:
                        slot_text += f" {minutes}m"
                    slot_text += ")"
                else:
                    slot_text += f" ({minutes}m)"
                    
                free_times_text += slot_text + "\n"
            
            # Use calendar emoji to match viewcal
            calendar_emoji = "📆"
            embed.add_field(
                name=f"{calendar_emoji} Available Time Slots (9AM-5PM)",
                value=free_times_text if free_times_text else "No qualifying free time slots found.",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
        else:
            await ctx.send(f"❌ Error checking calendar: {status} - {response_text[:100]}")
    except Exception as e:
        await ctx.send(f"❌ Error finding free time: {str(e)}")
        print(f"Free time error: {e}")
    
    # Delete loading message
    await loading_msg.delete()

# Run the bot
if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
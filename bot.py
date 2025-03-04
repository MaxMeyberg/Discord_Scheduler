import os
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv
from agent import MistralAgent
from datetime import datetime, timedelta
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord')

# Load environment variables
load_dotenv()

# Bot configuration
PREFIX = "!"
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Import the agent
agent = MistralAgent(bot)

# Remove default help command
bot.remove_command('help')

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    logger.info(f"{bot.user} has connected to Discord!")
    print(f"Logged in as {bot.user}")
    print(f"Bot is ready with prefix: {PREFIX}")

@bot.event
async def on_message(message):
    """Process incoming messages"""
    await bot.process_commands(message)
    
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Handle registration DMs
    if isinstance(message.channel, discord.DMChannel) and not message.content.startswith(PREFIX):
        await agent.process_registration_dm(message)
        return

@bot.command(name="help", help="Show available commands")
async def help_command(ctx):
    """Show available commands"""
    embed = discord.Embed(
        title="📅 Skedge Help",
        description="Here are the available commands:",
        color=discord.Color.blue()
    )
    
    # Registration commands
    embed.add_field(
        name="!register", 
        value="Connect your Google Calendar to Skedge",
        inline=False
    )
    
    embed.add_field(
        name="!unregister", 
        value="Remove your calendar connection from Skedge",
        inline=False
    )
    
    embed.add_field(
        name="!asciical", 
        value="Show your calendar in ASCII art format",
        inline=False
    )
    
    embed.add_field(
        name="!help", 
        value="Shows all commands",
        inline=False
    )
    
    embed.set_footer(text="Skedge - Making scheduling simple!")
    await ctx.send(embed=embed)

# Registration Commands
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
            f"Thanks for registering with Skedge!\n\n"
            f"**IMPORTANT:** Before clicking the link below, make sure you're logged into YOUR Google account in your browser.\n\n"
            f"To connect your calendar, please copy and paste this entire link into your browser:\n"
            f"```\n{auth_url}\n```\n\n"
            f"After authorizing, you'll see a Postman page with a callback URL that will look like one of these:\n"
            f"• `https://oauth.pstmn.io/v1/callback?code=XXXX...`\n"
            f"• `postman://app/oauth2/callback?code=XXXX...`\n\n"
            f"Please copy that ENTIRE URL and paste it back to me here.\n\n"
            f"If you encounter any errors, try `!unregister` followed by `!register` again."
        )
        await ctx.send(f"{user.mention}, I've sent you a DM with registration instructions. Please check your messages!")
    else:
        await ctx.send(f"{user.mention}, I couldn't send you a DM. Please make sure you have DMs enabled from server members.")


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

@bot.command(name="asciical", help="Show your calendar in ASCII format")
async def ascii_calendar(ctx):
    """Display a user's calendar in ASCII art format"""
    user = ctx.author
    
    # Check if user is registered
    user_data = await agent.db.get_user(str(user.id))
    if not user_data:
        await ctx.send(f"{user.mention}, you need to register first! Use `!register` to connect your calendar.")
        return
    
    await ctx.send(f"📊 Generating your ASCII calendar, {user.mention}...")
    
    try:
        # Get token
        if isinstance(user_data, dict):
            auth_token = user_data.get("access_token", user_data.get("auth_code"))
        else:
            auth_token = user_data
            
        if not auth_token:
            await ctx.send(f"❌ Couldn't find your authorization token. Please try `!register` again.")
            return
        
        # Get calendar events for the next 7 days - use local timezone
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=7)
        
        # Fetch events with debug info
        print(f"Fetching events from {start_date} to {end_date}")
        
        # Fetch events
        status, response_text = await agent.cronofy_api_call(
            endpoint="v1/events",
            auth_token=auth_token,
            params={
                "tzid": "America/Los_Angeles",
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "include_managed": "true"
            }
        )
        
        if status != 200:
            if status == 401:
                await ctx.send(f"❌ **Authentication Error:** Your calendar connection needs to be refreshed. Please `!unregister` and then `!register` again.")
            else:
                await ctx.send(f"❌ Error fetching your calendar: {status}\nDetails: {response_text[:100]}...")
            print(f"Calendar API Error ({status}): {response_text}")
            return
            
        # Detailed debug for event data
        print(f"API response: {response_text[:200]}...")
        
        try:
            response_data = json.loads(response_text)
            events = response_data.get("events", [])
            
            # Print the first entire event for debugging
            if events and len(events) > 0:
                print(f"First event structure: {json.dumps(events[0], indent=2)}")
            
            # Debug event count
            print(f"Found {len(events)} events in calendar")
            
            # Validate and process each event with the correct structure
            valid_events = []
            for i, event in enumerate(events):
                try:
                    if isinstance(event, dict):
                        summary = event.get("summary", "Unknown")
                        
                        # Handle different API response formats
                        start_time = None
                        
                        # Check for direct ISO string format
                        if isinstance(event.get("start"), str) and "T" in event.get("start"):
                            # Format the event into our expected structure
                            start_time = event.get("start")
                            end_time = event.get("end")
                            
                            # Create a normalized event dict
                            normalized_event = {
                                "summary": summary,
                                "start": {"time": start_time},
                                "end": {"time": end_time}
                            }
                            print(f"Event {i}: {summary} at {start_time}")
                            valid_events.append(normalized_event)
                        # Check for standard dictionary format
                        elif isinstance(event.get("start"), dict):
                            valid_events.append(event)
                        else:
                            print(f"Event {i} has unrecognized start field format: {event.get('start')}")
                    else:
                        print(f"Skipping non-dictionary event {i}: {event}")
                except Exception as e:
                    print(f"Error processing event {i}: {e}")
                    continue
            
            # Generate ASCII calendar with validated events - now as MULTIPLE MESSAGES
            calendar_days = generate_daily_ascii_calendars(valid_events, start_date, end_date)
            
            # Send each day's calendar as a separate message
            if calendar_days:
                for day_cal in calendar_days:
                    await ctx.send(f"```\n{day_cal}\n```")
            else:
                await ctx.send("📅 No events found for the next week!")
                
        except json.JSONDecodeError:
            await ctx.send("❌ Could not parse calendar data. API might be returning invalid JSON.")
            print(f"Invalid JSON: {response_text}")
        
    except Exception as e:
        await ctx.send(f"❌ Error generating ASCII calendar: {str(e)}")
        print(f"ASCII calendar error: {e}")
        import traceback
        traceback.print_exc()

def generate_daily_ascii_calendars(events, start_date, end_date):
    """Generate separate ASCII calendar boxes for each day"""
    calendar_days = []
    
    # Process each day
    current_date = start_date
    while current_date <= end_date:
        day_name = current_date.strftime("%A")
        date_str = current_date.strftime("%B %d")
        
        # Create a calendar table for this day
        day_cal = f"╔═══════════════ {day_name.upper()} {date_str} ════════════════╗\n"
        
        # Filter events for this day - with better timezone handling
        day_events = []
        for event in events:
            # Validate the event
            if not isinstance(event, dict):
                continue
            
            # Get the start time
            start_dict = event.get("start", {})
            if not isinstance(start_dict, dict):
                continue
                
            # Get time or date from the event
            event_start = start_dict.get("time") or start_dict.get("date")
            if not event_start:
                continue
                
            try:
                # Handle timezone properly by converting to local time first
                if 'T' in event_start:  # This is a timestamp with time
                    # Force UTC+0 interpretation then convert to local time
                    event_dt = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                    # Convert to local date - subtract 8 hours for PST
                    local_dt = event_dt - timedelta(hours=8)
                    event_date = local_dt.date()
                else:  # This is just a date
                    event_date = datetime.fromisoformat(event_start).date()
                
                # Check if this event is on the current day
                if event_date == current_date:
                    day_events.append(event)
            except (ValueError, AttributeError):
                continue
        
        # Sort events by start time (with timezone adjustment)
        def safe_get_time(e):
            start = e.get("start", {})
            if not isinstance(start, dict):
                return ""
                
            time_str = start.get("time", "") or start.get("date", "")
            if time_str and 'T' in time_str:
                try:
                    # Convert to local time for sorting
                    dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')) - timedelta(hours=8)
                    return dt.isoformat()
                except:
                    pass
            return time_str
            
        day_events.sort(key=safe_get_time)
        
        # Add events or indication that day is empty
        if day_events:
            for event in day_events:
                event_name = event.get("summary", "Busy")
                
                # Safely get and format times
                try:
                    start_dict = event.get("start", {})
                    end_dict = event.get("end", {})
                    
                    if isinstance(start_dict, dict) and isinstance(end_dict, dict):
                        # Check for time-based event first, then date-based (all-day) event
                        start_time_str = start_dict.get("time", "")
                        end_time_str = end_dict.get("time", "")
                        
                        if start_time_str and end_time_str:
                            # Fix timezone by subtracting 8 hours
                            start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')) - timedelta(hours=8)
                            end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00')) - timedelta(hours=8)
                            
                            # Format as 12-hour time
                            start_fmt = start_time.strftime("%I:%M %p")
                            end_fmt = end_time.strftime("%I:%M %p")
                            
                            time_range = f"{start_fmt} - {end_fmt}"
                            event_str = f"║ {time_range} | {event_name}"
                            day_cal += event_str.ljust(49) + "║\n"
                        else:
                            # All-day event
                            day_cal += f"║ All day | {event_name}".ljust(49) + "║\n"
                    else:
                        day_cal += f"║ Unknown time | {event_name}".ljust(49) + "║\n"
                except Exception:
                    day_cal += f"║ Error | {event_name}".ljust(49) + "║\n"
        else:
            day_cal += "║ No events scheduled".ljust(49) + "║\n"
        
        # Add bottom border
        day_cal += "╚═══════════════════════════════════════════════╝"
        
        # Add this day's calendar to the list
        calendar_days.append(day_cal)
        
        # Move to next day
        current_date += timedelta(days=1)
    
    return calendar_days

# Add this simple version as a separate command for testing
@bot.command(name="simplecal", help="Simple calendar view")
async def simple_calendar(ctx):
    """Simple calendar view that's more error tolerant"""
    user = ctx.author
    
    # Check if registered
    user_data = await agent.db.get_user(str(user.id))
    if not user_data:
        await ctx.send(f"{user.mention}, you need to register first with `!register`")
        return
        
    await ctx.send(f"📅 Fetching your calendar, {user.mention}...")
    
    try:
        # Get token
        auth_token = user_data.get("access_token") if isinstance(user_data, dict) else user_data
        
        # Get events for next 7 days
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=7)
        
        # Call API
        status, response_text = await agent.cronofy_api_call(
            endpoint="v1/events",
            auth_token=auth_token,
            params={
                "tzid": "America/Los_Angeles",
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
            }
        )
        
        if status != 200:
            await ctx.send(f"❌ Calendar API error: {status}")
            return
            
        # Parse response with super safe error handling
        calendar_text = "📅 **Your Calendar**\n\n"
        
        try:
            data = json.loads(response_text)
            events = data.get("events", [])
            
            # Print the first entire event for debugging
            if events and len(events) > 0:
                print(f"First event structure: {json.dumps(events[0], indent=2)}")
            
            # Group events by day
            days = {}
            for event in events:
                if not isinstance(event, dict):
                    continue
                    
                # Get summary safely
                summary = str(event.get("summary", "Busy Time"))
                
                # Handle different API response formats for start time
                start_str = None
                
                # Check if start is a direct ISO string
                if isinstance(event.get("start"), str) and "T" in event.get("start"):
                    start_str = event.get("start")
                # Check for dictionary format
                elif isinstance(event.get("start"), dict):
                    start_str = event.get("start").get("time") or event.get("start").get("date")
                
                if not start_str:
                    continue
                    
                # Parse the start time
                try:
                    if "T" in start_str:
                        event_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        day_str = event_dt.strftime("%Y-%m-%d")
                        time_str = event_dt.strftime("%I:%M %p")
                    else:
                        day_str = start_str
                        time_str = "All day"
                        
                    # Add to days dict
                    if day_str not in days:
                        days[day_str] = []
                        
                    days[day_str].append(f"• {time_str}: {summary}")
                except:
                    continue
            
            # Now format the days
            for day_str in sorted(days.keys()):
                try:
                    day_date = datetime.fromisoformat(day_str).date()
                    day_name = day_date.strftime("%A, %B %d")
                    
                    calendar_text += f"**{day_name}**\n"
                    for event_str in days[day_str]:
                        calendar_text += f"{event_str}\n"
                    calendar_text += "\n"
                except:
                    continue
                    
            if not days:
                calendar_text += "No events found in your calendar."
                
            await ctx.send(calendar_text)
            
        except Exception as e:
            await ctx.send(f"❌ Error parsing calendar: {e}")
            
    except Exception as e:
        await ctx.send(f"❌ Calendar error: {e}")

# Start the bot
token = os.getenv("DISCORD_TOKEN")
bot.run(token)

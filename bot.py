import os
import discord
import logging
import re
from datetime import datetime

from discord.ext import commands
from dotenv import load_dotenv
from agent import MistralAgent

PREFIX = "!"

# Setup logging
logger = logging.getLogger("discord")
logging.basicConfig(level=logging.INFO)

# Load the environment variables
load_dotenv()

# Create the bot with all intents
# The message content and members intent must be enabled in the Discord Developer Portal for the bot to work.
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Import the Mistral agent from the agent.py file
agent = MistralAgent()

# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")


@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_ready
    """
    logger.info(f"{bot.user} has connected to Discord!")
    print(f"Logged in as {bot.user}")
    print(f"Bot is ready with prefix: {PREFIX}")
    print("Available commands:")
    for command in bot.commands:
        print(f" - {command.name}")


@bot.event
async def on_message(message: discord.Message):
    """
    Called when a message is sent in any channel the bot can see.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_message
    """
    # Don't delete this line! It's necessary for the bot to process commands.
    await bot.process_commands(message)

    # Ignore messages from self or other bots to prevent infinite loops.
    if message.author.bot:
        return
        
    # Check if this is a DM for registration process
    if isinstance(message.channel, discord.DMChannel) and not message.content.startswith(PREFIX):
        await agent.process_registration_dm(message)
        return

    # Handle mentions for scheduling
    if bot.user in message.mentions and not message.content.startswith(PREFIX):
        await handle_schedule_request(message)
        return
        
    # For regular messages that don't fall into any of the above categories
    if not message.content.startswith(PREFIX) and not isinstance(message.channel, discord.DMChannel):
        logger.info(f"Processing message from {message.author}: {message.content}")
        response = await agent.run(message)
        await message.reply(response)


async def handle_schedule_request(message):
    """Handle requests to find common free time between users"""
    content = message.content.lower()
    
    # Check if this is a scheduling request
    if "when are" in content and "free" in content:
        # Extract mentioned users
        mentioned_users = message.mentions
        
        # Remove the bot from the list of mentioned users
        mentioned_users = [user for user in mentioned_users if user.id != bot.user.id]
        
        if not mentioned_users:
            await message.reply("Please mention the users you want to find common free time with.")
            return
            
        # Check if all mentioned users are registered
        unregistered_users = []
        for user in mentioned_users:
            if user.id not in agent.user_database:
                unregistered_users.append(user.name)
                
        if unregistered_users:
            users_list = ", ".join(unregistered_users)
            await message.reply(f"The following users need to register first: {users_list}")
            return
            
        # Parse date from message if specified
        date = None
        if "today" in content:
            date = datetime.now().date()
        # Add more date parsing as needed
            
        # Find common free time
        free_slots = await agent.find_common_free_time(mentioned_users, date)
        
        # Format response
        if free_slots:
            response = "Here are the 3 closest times when everyone is free:\n"
            for i, slot in enumerate(free_slots, 1):
                response += f"{i}. {slot.strftime('%I:%M %p')}\n"
        else:
            response = "Sorry, I couldn't find any common free time for the mentioned users."
            
        await message.reply(response)
    else:
        # For other bot mentions, use the regular agent
        response = await agent.run(message)
        await message.reply(response)


# Commands


# This example command is here to show you how to add commands to the bot.
# Run !ping with any number of arguments to see the command in action.
# Feel free to delete this if your project will not need commands.
@bot.command(name="register", help="Register with Skedge to share your calendar availability")
async def register(ctx):
    """Command to start the registration process"""
    user = ctx.author
    
    # Check if user is already registered
    if user.id in agent.user_database:
        await ctx.send(f"{user.mention}, you're already registered!")
        return
        
    # Check if user is already in registration process
    if user.id in agent.registration_states:
        await ctx.send(f"{user.mention}, you already have a registration in progress. Please check your DMs.")
        return
        
    # Start registration process
    success = await agent.start_registration(user)
    
    if success:
        await ctx.send(f"{user.mention}, I've sent you a DM to complete the registration process!")
    else:
        await ctx.send(f"{user.mention}, I couldn't send you a DM. Please make sure you have DMs enabled from server members.")


@bot.command(name="ping", help="Pings the bot.")
async def ping(ctx, *, arg=None):
    if arg is None:
        await ctx.send("Pong!")
    else:
        await ctx.send(f"Pong! Your argument was {arg}")


# Start the bot, connecting it to the gateway
bot.run(token)

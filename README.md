# Skedge - Discord Calendar Bot

A Discord bot that allows users to view their calendars through Discord by connecting to calendar services like Google Calendar.

## Features

- **Registration**: Connect your Google Calendar to Skedge
- **View Calendar**: See your upcoming events for the week
- **User Management**: Admins can see who has registered

## Commands

- `!register` - Start the registration process
- `!unregister` - Disconnect your calendar
- `!viewcal [username]` - View your calendar or another user's calendar
- `!status` - Check if your calendar is connected
- `!users` - (Admin only) View all registered users

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables in `.env`:
   - `DISCORD_TOKEN` - Your Discord bot token
   - `CRONOFY_CLIENT_ID` - Your Cronofy client ID
   - `CRONOFY_CLIENT_SECRET` - Your Cronofy client secret
   - `SUPABASE_URL` - Your Supabase URL
   - `SUPABASE_KEY` - Your Supabase key
   - `TIMEZONE` - Default timezone (e.g., "America/Los_Angeles")

4. Run the bot: `python -m schedge.bot`

## Quick Start Guide

Follow these simple steps to get your own Schedge bot up and running!

### Prerequisites

You'll need:
- A computer with internet access
- Python 3.8+ installed
- A Discord account with admin access to a server
- Google or Outlook calendar you want to connect

### Step 1: Install Python

**Windows:**
1. Download Python from [python.org](https://www.python.org/downloads/)
2. Run the installer, check "Add Python to PATH"
3. Click "Install Now"

**Mac:**
1. Install Homebrew by opening Terminal and running:
   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
2. Install Python:
   ```
   brew install python
   ```

### Step 2: Download Schedge Bot

1. Download the Schedge code:
   - Visit [the repository](https://github.com/yourusername/schedge)
   - Click the green "Code" button and select "Download ZIP"
2. Extract the ZIP file to a folder on your computer

### Step 3: Set Up Your Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name (like "Schedge")
3. Go to the "Bot" tab on the left sidebar
4. Click "Reset Token" and copy the token that appears
5. Under "Privileged Gateway Intents", enable ALL THREE options:
   - Presence Intent
   - Server Members Intent
   - Message Content Intent
6. Click "Save Changes"
7. Go to "OAuth2" → "URL Generator" on the left sidebar
8. Check "bot" under SCOPES
9. Under BOT PERMISSIONS, check:
   - Read Messages/View Channels
   - Send Messages
   - Manage Messages
   - Embed Links
   - Read Message History
10. Copy the generated URL at the bottom
11. Paste the URL in your browser and select your server to add the bot

### Step 4: Get Your API Keys

#### A. Mistral API Key
1. Go to [Mistral AI Console](https://console.mistral.ai)
2. Sign up for an account
3. Click "API Keys" in the left sidebar
4. Click "Create API Key" and copy the key

#### B. Cronofy API Credentials
1. Go to [Cronofy Developers](https://www.cronofy.com/developers/)
2. Sign up and create a new app
3. Set the redirect URI to: `https://oauth.pstmn.io/v1/callback`
4. Copy your Client ID and Client Secret

#### C. Supabase Database
1. Go to [Supabase](https://supabase.com/) and sign up
2. Create a new project
3. Go to "Table Editor" and create a new table named "users" with these columns:
   - discord_id (text, primary key)
   - discord_name (text)
   - auth_code (text)
   - access_token (text)
   - refresh_token (text)
   - token_expiry (timestamp)
   - email (text)
   - data (json)
   - created_at (timestamp with default now())
4. Go to "Authentication" → "Policies" and enable Row Level Security (RLS)
5. Create a new policy:
   - Name: service_account_full_access
   - Using expression: true
   - With check expression: true
   - Target roles: All
6. Go to "Project Settings" → "API" and copy:
   - Project URL
   - service_role API key (not the anon key)

### Step 5: Configure Your Bot

1. In the extracted folder, create a file named `.env` (with the dot)
2. Add these lines, replacing everything after = with your actual values:

```
DISCORD_TOKEN=your_discord_bot_token
MISTRAL_API_KEY=your_mistral_api_key
CRONOFY_CLIENT_ID=your_cronofy_client_id
CRONOFY_CLIENT_SECRET=your_cronofy_client_secret
CRONOFY_REDIRECT_URI=https://oauth.pstmn.io/v1/callback
ADMIN_PASSWORD=your_chosen_admin_password
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_service_role_key
TIMEZONE=America/Los_Angeles
```

3. Edit `bot.py` and change the `ADMIN_USERS` list to include your Discord username:

```python
ADMIN_USERS = [
    "your_discord_username",  # Your Discord username
]
```

### Step 6: Install Dependencies & Run the Bot

Open a terminal/command prompt in the extracted folder and run:

**Windows:**
```
pip install -r requirements.txt
pip install pyshorteners
python bot.py
```

**Mac/Linux:**
```
pip install -r requirements.txt
pip install pyshorteners
python3 bot.py
```

You should see "Bot is ready" message if everything works correctly!

## Using Your Bot

Once your bot is running, you can use these commands in Discord:

- `!help` - See all available commands
- `!register` - Connect your calendar
- `!asciical` - View your calendar in ASCII art
- `!simplecal` - View your calendar as text
- `!find_times @user1 @user2` - Find common free times

## Admin Commands

- `!users` - Show all registered users
- `!viewcal [username]` - View another user's calendar

## Troubleshooting

**Bot doesn't respond:**
- Make sure the bot is running (terminal shows "Bot is ready")
- Check that you invited the bot to your server
- Ensure your bot has the right permissions

**Can't connect calendar:**
- Make sure Cronofy API keys are correct
- Check the redirect URI is set properly

**Database errors:**
- Verify Supabase URL and key are correct
- Make sure the users table has the right columns
- Check that RLS policy is enabled correctly

**Missing module errors:**
- If you see `ModuleNotFoundError`, run `pip install pyshorteners`
- Make sure you've installed all requirements with `pip install -r requirements.txt`

**If all else fails:**
Run `python test_supabase.py` to check database connection

## License

[MIT License](LICENSE)

## Security Notice

This repository does not contain any API keys, tokens, or secrets. You will need to provide your own credentials in a `.env` file (see [Setup](#setup) below).

**NEVER commit your `.env` file to GitHub or share your API keys publicly.**

## Obtaining Your Own API Keys

To run this bot, you'll need to obtain these API keys:

### Discord Bot Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to the "Bot" tab and click "Add Bot"
4. Copy the token

### Mistral API Key
1. Go to [Mistral AI Console](https://console.mistral.ai)
2. Sign up for an account
3. Navigate to API Keys section
4. Create a new key

### Cronofy API Credentials
1. Go to [Cronofy Developer Portal](https://app.cronofy.com/developers)
2. Create a new application
3. Set redirect URI to `https://oauth.pstmn.io/v1/callback`
4. Copy Client ID and Client Secret

### Supabase Database
1. Go to [Supabase](https://supabase.com/)
2. Create a new project
3. Create a "users" table with the structure described in the setup guide
4. Copy your URL and service_role key

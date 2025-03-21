#!/bin/bash
# Setup script for Schedge

# Install dependencies
pip install -r requirements.txt

# Create systemd service file (for Linux users)
cat > /tmp/schedge.service << EOL
[Unit]
Description=Schedge Discord Bot
After=network.target

[Service]
User=$(whoami)
WorkingDirectory=$(pwd)
ExecStart=$(which python3) $(pwd)/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# Instructions for deploying as a service
echo "
DEPLOYMENT OPTIONS:
--------------------------
1. For Linux systemd service:
   sudo cp /tmp/schedge.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable schedge
   sudo systemctl start schedge

2. For AWS deployment:
   See the AWS deployment guide in the documentation.

3. For manual running:
   python bot.py
"

# Instructions for setting up AWS Parameter Store
echo "
AWS PARAMETER STORE SETUP:
--------------------------
1. Go to AWS Systems Manager → Parameter Store
2. Create the following parameters (use SecureString type):
   - /schedge/DISCORD_TOKEN
   - /schedge/MISTRAL_API_KEY
   - /schedge/CRONOFY_CLIENT_ID
   - /schedge/CRONOFY_CLIENT_SECRET
   - /schedge/CRONOFY_REDIRECT_URI
   - /schedge/SUPABASE_URL
   - /schedge/SUPABASE_KEY
   - /schedge/TIMEZONE (use String type)
3. Ensure your EC2 instance has an IAM role with SSM Parameter Store read access
" 
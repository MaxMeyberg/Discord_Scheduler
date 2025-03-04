from flask import Flask, request
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Store authorized codes temporarily
auth_codes = {}

@app.route('/callback')
def callback():
    """Handle the OAuth callback from Cronofy"""
    code = request.args.get('code')
    state = request.args.get('state')  # This contains the Discord user ID
    
    if not code or not state:
        return "Error: Missing parameters", 400
    
    # Store the code for the Discord bot to retrieve
    auth_codes[state] = code
    
    # Call your Discord bot's webhook to notify it about the new code
    discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if discord_webhook_url:
        requests.post(
            discord_webhook_url,
            json={
                "type": "oauth_callback",
                "user_id": state,
                "code": code
            }
        )
    
    return """
    <html>
        <body style="text-align: center; font-family: Arial, sans-serif; padding: 50px;">
            <h1>Calendar Connected Successfully!</h1>
            <p>You can now close this window and return to Discord.</p>
            <p>Your Skedge bot will automatically continue the setup process.</p>
        </body>
    </html>
    """

@app.route('/get_code/<user_id>')
def get_code(user_id):
    """API endpoint for the Discord bot to retrieve codes"""
    api_key = request.headers.get('X-API-Key')
    if api_key != os.getenv("OAUTH_SERVER_API_KEY"):
        return json.dumps({"error": "Unauthorized"}), 401
    
    code = auth_codes.get(user_id)
    if code:
        del auth_codes[user_id]  # Use the code only once
        return json.dumps({"code": code})
    return json.dumps({"error": "No code found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 
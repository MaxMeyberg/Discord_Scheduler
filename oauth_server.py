from flask import Flask, request, jsonify
import requests
import json
import os
from dotenv import load_dotenv
from datetime import datetime
import uuid
from database import Database

load_dotenv()

app = Flask(__name__)

# Store authorized codes temporarily
auth_codes = {}

# Create database instance
db = Database()

@app.route('/callback')
def callback():
    """Handle the OAuth callback from Cronofy"""
    code = request.args.get('code')
    state = request.args.get('state')  # This contains the user's UUID
    
    if not code or not state:
        return "Error: Missing parameters", 400
    
    # Store the code for the Discord bot to retrieve
    auth_codes[state] = {
        'code': code,
        'timestamp': datetime.now().isoformat()
    }
    
    # The Discord bot will handle storing this with the persistent UUID later
    # We're just storing the code here temporarily
    
    return """
    <html>
        <body style="text-align: center; font-family: Arial, sans-serif; padding: 50px;">
            <h1>Calendar Connected Successfully!</h1>
            <p>You can now close this window and return to Discord.</p>
            <p>Your Skedge bot will automatically continue the setup process.</p>
        </body>
    </html>
    """

@app.route('/get_code/<uuid>')
def get_code(uuid):
    """API endpoint for the Discord bot to retrieve codes by UUID"""
    api_key = request.headers.get('X-API-Key')
    if api_key != os.getenv("OAUTH_SERVER_API_KEY"):
        return jsonify({"error": "Unauthorized"}), 401
    
    code_data = auth_codes.get(uuid)
    if code_data:
        del auth_codes[uuid]  # Use the code only once
        return jsonify({"code": code_data['code'], "timestamp": code_data['timestamp']})
    return jsonify({"error": "No code found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 
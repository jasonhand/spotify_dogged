import os
from dotenv import load_dotenv
import logging
from flask import Flask, request, redirect
import requests
import webbrowser
from base64 import b64encode
import threading
import time
import json
from datadog import initialize, api

# Load environment variables
load_dotenv()

# Your Spotify API credentials
CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
REDIRECT_URI = "http://localhost:5000/callback"
SCOPE = "user-top-read user-read-recently-played"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
BASE_URL = "https://api.spotify.com/v1"
DATADOG_API_ENDPOINT = "https://http-intake.logs.datadoghq.com/v1/input"
DATADOG_API_KEY = os.getenv('DATADOG_API_KEY')
access_token = None  # Global variable to store the access token

app = Flask(__name__)

# Function to get the authorization URL
def get_auth_url():
    return f'{AUTH_URL}?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&scope={SCOPE}'

# Route to start the OAuth flow
@app.route('/login')
def login():
    return redirect(get_auth_url())

# Callback route
@app.route('/callback')
def callback():
    global access_token
    code = request.args.get('code')
    token_response = get_token(code)
    if 'access_token' in token_response:
        access_token = token_response['access_token']
        return 'Login successful! You can now close this window and return to the command line.'
    else:
        return f'Error obtaining token: {token_response}'

# Function to get the access token
def get_token(code):
    try:
        auth_header = {
            'Authorization': 'Basic ' + b64encode(f'{CLIENT_ID}:{CLIENT_SECRET}'.encode()).decode()
        }
        data = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}
        response = requests.post(TOKEN_URL, headers=auth_header, data=data)
        response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
        return response.json()
    except requests.RequestException as e:
        logging.error(f"HTTP Request failed: {e}")
        return {}

def get_recently_played():
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get(f'{BASE_URL}/me/player/recently-played?limit=50', headers=headers)
    return response.json()

def extract_recently_played_details(data):
    return [
        {
            'host': 'python_app',
            'service': 'spotify',
            'list': 'recently_played',
            'track_name': item['track']['name'],
            'artist': ', '.join(artist['name'] for artist in item['track']['artists']),
            'artist_id': ', '.join(artist['id'] for artist in item['track']['artists']),
            'played_at': item['played_at'],
            'duration_ms': item['track']['duration_ms'],
            'image_url': item['track']['album']['images'][0]['url'],
            'external_url': item['track']['external_urls']['spotify'],
            'release_date': item['track']['album']['release_date'],
            'album_name': item['track']['album']['name'],
            'track_id': item['track']['id']
        }
        for item in data.get('items', [])
    ]

def send_to_datadog(data):
    headers = {
        'Content-Type': 'application/json',
        'DD-API-KEY': DATADOG_API_KEY,
    }
    for item in data:
        response = requests.post(DATADOG_API_ENDPOINT, headers=headers, json=item)
        if response.status_code != 200:
            print(f"Failed to send data to Datadog: {response.text}")

# Initialize the Datadog API
options = {
    'api_key': DATADOG_API_KEY,
}
initialize(**options)

# Set up Python's built-in logging with Datadog
logging.basicConfig(level=logging.INFO)
dd_logger = logging.getLogger('datadog_logger')

def log_to_datadog(data):
    dd_logger.info(json.dumps(data))  # Log data as a JSON string

def user_menu():
    global access_token
    while not access_token:
        print("You need to login! Waiting for authentication... (Please check your browser)")
        time.sleep(5)

    while True:
        print("\nChoose an option:")
        print("1. Recently Played Tracks")
        print("2. Exit")
        main_choice = input("Enter your choice (1 or 2)" )

        if main_choice == '1':
            data = get_recently_played()
            custom_data = extract_recently_played_details(data)
            send_to_datadog(custom_data)

        elif main_choice == '2':
            print("Exiting...")
            break

        for item in custom_data:
            print(item)

def run_flask_app():
    app.run(debug=True, use_reloader=False)

if __name__ == '__main__':
    # Ensure environment variables are set
    if not all([CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, DATADOG_API_KEY]):
        raise ValueError("One or more required environment variables are missing.")

    # Run Flask app in a separate thread
    threading.Thread(target=run_flask_app).start()
    webbrowser.open(get_auth_url())
    user_menu()
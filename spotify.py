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

def get_time_range():
    print("1. Short Term")
    print("2. Medium Term")
    print("3. Long Term")
    time_choice = input("Enter your choice (1, 2, or 3): ")
    time_range_mapping = {'1': 'short_term', '2': 'medium_term', '3': 'long_term'}
    return time_range_mapping.get(time_choice, 'medium_term')


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
            'played_at': item['played_at']
        }
        for item in data.get('items', [])
    ]

def extract_custom_track_object(data, time_frame):
    custom_tracks = []
    for track in data.get('items', []):  # Safely access 'items' key
        # Safely access 'artists' key, default to an empty list if not found
        artists = track.get('artists', [])
        custom_track = {
            'host': 'python_app',
            'service': 'spotify',
            'list': 'top_tracks',
            'time_frame': time_frame,  # Add the time frame
            'artist': ', '.join(artist.get('name', 'Unknown Artist') for artist in artists),
            'track': track.get('name', 'Unknown Track'),
            'album': track.get('album', {}).get('name', 'Unknown Album')
        }
        custom_tracks.append(custom_track)
    return custom_tracks

def send_to_datadog(data):
    headers = {
        'Content-Type': 'application/json',
        'DD-API-KEY': DATADOG_API_KEY,
    }
    for item in data:
        response = requests.post(DATADOG_API_ENDPOINT, headers=headers, json=item)
        if response.status_code != 200:
            print(f"Failed to send data to Datadog: {response.text}")

# Function to get the top tracks or artists
def get_top(type, time_range):
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'limit': 50, 'time_range': time_range}  # Request 50 items with the specified time range
    response = requests.get(f'{BASE_URL}/me/top/{type}', headers=headers, params=params)
    return response.json()

# Function to extract names from the Spotify response
def extract_names(data, type):
    if type == "tracks":
        return [track['name'] for track in data['items']]
    elif type == "artists":
        return [artist['name'] for artist in data['items']]
    else:
        return []

def extract_custom_artist_object(data, time_frame):
    custom_artists = []
    for artist in data.get('items', []):
        # Extracting relevant information from each artist
        custom_artist = {
            'host': 'python_app',
            'service': 'spotify',
            'list': 'top_artists',
            'time_frame': time_frame,  # Add the time frame
            'artist': artist.get('name', 'Unknown Artist'),
            'followers': artist.get('followers', {}).get('total', 0),
            'genres': ', '.join(artist.get('genres', []))
        }
        custom_artists.append(custom_artist)
    return custom_artists

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
        print("1. Top Tracks")
        print("2. Top Artists")
        print("3. Recently Played Tracks")
        print("4. Exit")
        main_choice = input("Enter your choice (1, 2, 3, or 4): ")

        if main_choice == '4':
            print("Exiting...")
            break

        if main_choice in ['1', '2']:
            time_range = get_time_range()

            if main_choice == '1':
                data = get_top("tracks", time_range)
                custom_data = extract_custom_track_object(data, time_range)
            elif main_choice == '2':
                data = get_top("artists", time_range)
                custom_data = extract_custom_artist_object(data, time_range)

        elif main_choice == '3':
            data = get_recently_played()
            custom_data = extract_recently_played_details(data)

        print("\nDo you want to send the results to Datadog?")
        print("1. Yes")
        print("2. No")
        send_to_dd = input("Enter your choice (1 or 2): ")

        if send_to_dd == '1':
            send_to_datadog(custom_data)

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

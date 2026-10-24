"""
Song identification module using Shazam API
"""
import asyncio
import re
from shazamio import Shazam

def get_apple_music_link(shazam_response: dict) -> str:
    """
    Extracts the Apple Music link from the Shazam response.
    :param shazam_response: The Shazam response as a dictionary
    :return: The Apple Music link if available, otherwise None
    """
    try:
        if "track" in shazam_response and "hub" in shazam_response["track"]:
            # First method: Check options for "OPEN IN" actions
            for option in shazam_response["track"]["hub"].get("options", []):
                if option.get("caption") == "OPEN IN":
                    for action in option.get("actions", []):
                        if action.get("type") == "applemusicopen":
                            return action.get("uri")
            
            # Second method: Check providers directly
            providers = shazam_response["track"]["hub"].get("providers", [])
            for provider in providers:
                if provider.get("type") == "APPLEMUSIC":
                    actions = provider.get("actions", [])
                    if actions and "uri" in actions[0]:
                        return actions[0]["uri"]
    except Exception as e:
        print(f"Error extracting Apple Music link: {e}")
    
    return None

async def _recognize_song(file_path):
    """
    Use Shazam to recognize a song from an audio file
    """
    shazam = Shazam()
    out = await shazam.recognize_song(file_path)
    return out

def identify_song(file_path):
    """
    Identify a song from an audio file and return relevant information
    
    Args:
        file_path (str): Path to the audio file
        
    Returns:
        dict: Song information including title, artist, and links
    """
    try:
        result = asyncio.run(_recognize_song(file_path))
        
        # Check if we got a valid result
        if not result or 'track' not in result:
            # Try up to 5 times as shown in example code
            for _ in range(4):  # Already tried once above, so 4 more tries
                print("Retrying song identification...")
                result = asyncio.run(_recognize_song(file_path))
                if result and 'track' in result:
                    break
            
            # If still no valid result after retries
            if not result or 'track' not in result:
                return None
            
        track = result['track']
        
        # Extract relevant info
        song_info = {
            'title': track.get('title', 'Unknown'),
            'artist': track.get('subtitle', 'Unknown Artist'),
            'album': track.get('sections', [{}])[0].get('metadata', [{}])[0].get('text', 'Unknown Album'),
            'cover_art': track.get('images', {}).get('coverart', ''),
        }
        
        # Get Apple Music link using improved method
        song_info['apple_music_link'] = get_apple_music_link(result)
        
        # Extract other streaming links
        provider_data = track.get('hub', {}).get('providers', [])
        for provider in provider_data:
            if provider.get('type') == 'SPOTIFY':
                actions = provider.get('actions', [])
                if actions and 'uri' in actions[0]:
                    song_info['spotify_link'] = actions[0]['uri']
        
        # Get YouTube links from external sources if available
        share_urls = track.get('hub', {}).get('options', [{}])[0].get('actions', [{}])
        for action in share_urls:
            if action.get('type') == 'uri':
                uri = action.get('uri', '')
                if 'youtube' in uri:
                    song_info['youtube_link'] = uri
        
        return song_info
    except Exception as e:
        print(f"Error identifying song: {e}")
        return None
"""
Link converter module for converting music links between platforms
Uses the song.link API to convert between different music platform links
"""
import requests
import os
import re
from urllib.parse import urlparse

# API endpoint
SONGLINK_API = "https://api.song.link/v1-alpha.1/links"

def get_youtube_link(url):
    """
    Convert a music link from any platform to YouTube Music link
    Uses the song.link API
    
    Args:
        url (str): A music link from any supported platform
        
    Returns:
        str: YouTube Music link or None if not found
    """
    try:
        # Check if link is already a YouTube Music link
        parsed_url = urlparse(url)
        if parsed_url.netloc == 'music.youtube.com' or 'youtube' in parsed_url.netloc and 'music' in url:
            # If it's already a YouTube Music link, extract the video ID if needed
            match = re.search(r"v=([a-zA-Z0-9_-]+)", url)
            if match:
                video_id = match.group(1)
                return url  # Return the original link since it's already in correct format
            
        # Prepare request parameters
        params = {
            'songIfSingle': 'true',
            'platform': 'youtubeMusic,spotify',
            'type': 'song',
            'url': url
        }
        
        # Make API request
        response = requests.get(SONGLINK_API, params=params)
        
        if response.status_code != 200:
            print(f"Error: song.link API returned status code {response.status_code}")
            return None
            
        data = response.json()
        
        # Extract YouTube Music link
        platforms = data.get('linksByPlatform', {})
        
        # First try YouTube Music
        if 'youtubeMusic' in platforms:
            youtube_music_link = platforms['youtubeMusic'].get('url')
            if youtube_music_link:
                return youtube_music_link
            
        # If no YouTube Music link, try regular YouTube as fallback
        if 'youtube' in platforms:
            youtube_link = platforms['youtube'].get('url')
            if youtube_link:
                return youtube_link
        
        return None
    except Exception as e:
        print(f"Error getting YouTube link: {e}")
        return None

def extract_video_id(youtube_music_link):
    """
    Extracts the video ID from a YouTube Music link
    
    Args:
        youtube_music_link (str): YouTube Music URL
    
    Returns:
        str: Video ID or None if not found
    """
    if not youtube_music_link:
        return None
    
    try:
        match = re.search(r"v=([a-zA-Z0-9_-]+)", youtube_music_link)
        if match:
            return match.group(1)
        
        # Handle other URL formats
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", youtube_music_link)
        if match:
            return match.group(1)
            
        return None
    except Exception as e:
        print(f"Error extracting video ID: {e}")
        return None

def convert_link(input_link):
    """
    Convert a music link from any platform to YouTube Music link
    
    Args:
        input_link (str): A music link from any supported platform
        
    Returns:
        str: YouTube Music link or None if not found
    """
    youtube_music_link = get_youtube_link(input_link)
    return youtube_music_link
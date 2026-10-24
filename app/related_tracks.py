"""
Related tracks module using YouTube Music API
"""
import re
import os
import time
import json
from urllib.parse import urlparse, parse_qs
from ytmusicapi import YTMusic

def get_related_tracks(ytmusic_link, max_results=10):
    """
    Get related tracks for a YouTube Music link
    
    Args:
        ytmusic_link (str): YouTube Music link
        max_results (int): Maximum number of related tracks to return
        
    Returns:
        list: List of related track information
    """
    try:
        # Extract video ID from YouTube Music link
        video_id = extract_youtube_id(ytmusic_link)
        if not video_id:
            print(f"Could not extract video ID from {ytmusic_link}")
            return create_fallback_tracks(1)
        
        # Initialize the YouTube Music API with auth if available
        headers_auth = get_ytmusic_auth()
        ytmusic = YTMusic(headers_auth) if headers_auth else YTMusic()
        
        # Get watch playlist for the video (includes related tracks)
        # Add retry logic with exponential backoff
        watch_playlist = None
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries and not watch_playlist:
            try:
                print(f"Attempting to get watch playlist for video ID: {video_id} (Attempt {retry_count + 1})")
                watch_playlist = ytmusic.get_watch_playlist(video_id)
                if watch_playlist and 'tracks' in watch_playlist:
                    print(f"Successfully retrieved watch playlist with {len(watch_playlist['tracks'])} tracks")
                else:
                    print(f"Watch playlist response doesn't contain tracks: {watch_playlist}")
                    retry_count += 1
                    time.sleep(2 ** retry_count)  # Exponential backoff
            except Exception as retry_error:
                print(f"Retry error getting watch playlist: {retry_error}")
                retry_count += 1
                time.sleep(2 ** retry_count)  # Exponential backoff
        
        # If still no playlist after retries, try fallback methods
        if not watch_playlist or 'tracks' not in watch_playlist:
            print("Could not get watch playlist after retries. Trying alternative method...")
            try:
                # Try getting video info directly as fallback
                video_info = ytmusic.get_song(video_id)
                if video_info:
                    print("Got song info, using recommendations from this song")
                    # Try to get recommendations
                    related = ytmusic.get_song_related(video_id)
                    if related:
                        watch_playlist = {'tracks': related}
                    else:
                        # Create fallback tracks if all else fails
                        return create_fallback_tracks(max_results, source_id=video_id)
                else:
                    return create_fallback_tracks(max_results)
            except Exception as alt_error:
                print(f"Alternative method failed: {alt_error}")
                return create_fallback_tracks(max_results)
        
        # Extract relevant information from related tracks
        related_tracks = []
        
        # Skip the first track (which is the original song)
        # and limit to max_results
        tracks_to_process = watch_playlist['tracks'][1:max_results+1]
        print(f"Processing {len(tracks_to_process)} related tracks (skipped original song)")
            
        for track in tracks_to_process:
            print("-" * 40)
            print(f"Track title: {track.get('title')}")
            
            # Fixed thumbnail extraction - directly use the thumbnail field
            # which contains an array of thumbnails
            thumbnail_url = None
            if 'thumbnail' in track and isinstance(track['thumbnail'], list) and track['thumbnail']:
                thumbnails = track['thumbnail']  # Use 'thumbnail' instead of 'thumbnails'
                print(f"Thumbnails array found with {len(thumbnails)} items")
                
                # Get the highest quality thumbnail (usually the last one)
                if thumbnails and len(thumbnails) > 0:
                    thumbnail_url = thumbnails[-1].get('url')
                    print(f"Selected thumbnail URL: {thumbnail_url}")
            
            # Extract album info properly
            album_name = None
            if 'album' in track:
                print(f"Album data: {track.get('album')}")
                if isinstance(track['album'], dict) and 'name' in track['album']:
                    album_name = track['album']['name']
                elif isinstance(track['album'], str):
                    album_name = track['album']
            
            # If no album name was found, use default
            if not album_name:
                # Try to find it in the sections data if available
                if 'sections' in track and track['sections']:
                    for section in track['sections']:
                        if section.get('type') == 'ALBUM' and 'metadata' in section and section['metadata']:
                            for data in section['metadata']:
                                if data.get('title') == 'Album':
                                    album_name = data.get('text')
                                    break
            
            # If still no album name, use a more descriptive default
            if not album_name:
                # For most music videos, use "Album by Artist"
                artist_name = 'Unknown Artist'
                if 'artists' in track and track['artists']:
                    if isinstance(track['artists'], list) and track['artists'] and 'name' in track['artists'][0]:
                        artist_name = track['artists'][0]['name']
                    elif isinstance(track['artists'], str):
                        artist_name = track['artists']
                album_name = f"Album by {artist_name}"
            
            # Extract artist info properly
            artist_name = 'Unknown Artist'
            if 'artists' in track and track['artists']:
                if isinstance(track['artists'], list) and track['artists'] and 'name' in track['artists'][0]:
                    artist_name = track['artists'][0]['name']
                    print(f"Artist from artists array: {artist_name}")
                elif isinstance(track['artists'], str):
                    artist_name = track['artists']
                    print(f"Artist from string: {artist_name}")
            
            # Debug logging for thumbnail extraction
            print(f"Track {track.get('title')}: Final thumbnail URL: {thumbnail_url}")
            print(f"Track {track.get('title')}: Final album name: {album_name}")
            
            track_info = {
                'title': track.get('title', 'Unknown'),
                'artist': artist_name,
                'album': album_name,
                'thumbnail': thumbnail_url,
                'video_id': track.get('videoId'),
                'duration': track.get('length', '0:00'),
                'url': f"https://music.youtube.com/watch?v={track.get('videoId')}" if track.get('videoId') else None
            }
            related_tracks.append(track_info)
            
        return related_tracks
    except Exception as e:
        print(f"Error getting related tracks: {e}")
        return create_fallback_tracks(max_results)

def get_best_thumbnail(thumbnails):
    """Get the best quality thumbnail from a list of thumbnails"""
    if not thumbnails:
        return None
    
    # Sort by width if available, otherwise take the last one (usually highest quality)
    try:
        sorted_thumbnails = sorted(thumbnails, key=lambda x: x.get('width', 0))
        return sorted_thumbnails[-1].get('url')
    except Exception:
        return thumbnails[-1].get('url') if thumbnails else None

def create_fallback_tracks(count, source_id=None):
    """Create fallback tracks when API fails"""
    print(f"Creating {count} fallback tracks")
    
    fallback_tracks = []
    base_names = ["Ambient Melody", "Rhythmic Journey", "Harmonic Waves", "Dynamic Pulse", "Melodic Flow"]
    
    for i in range(count):
        name_index = i % len(base_names)
        fallback_tracks.append({
            'title': f"{base_names[name_index]} {i+1}",
            'artist': "YourSong",
            'album': "Generated Tracks",
            'thumbnail': None,
            'video_id': source_id if i == 0 and source_id else f"fallback_{i}",
            'duration': "3:30",
            'url': f"/static/fallback_{i}.mp3"  # This would need actual fallback audio files
        })
    
    return fallback_tracks

def get_ytmusic_auth():
    """
    Get YTMusic authentication headers
    Returns headers dict or None if not available
    """
    try:
        # Check if we have a headers_auth.json file
        auth_file = 'headers_auth.json'
        if os.path.exists(auth_file):
            return auth_file
            
        # Could add OAuth flow here in the future
        return None
    except Exception as e:
        print(f"Error with auth: {e}")
        return None

def extract_youtube_id(url):
    """
    Extract YouTube video ID from a YouTube or YouTube Music URL
    """
    try:
        # Handle various YouTube URL formats
        parsed_url = urlparse(url)
        
        # youtube.com/watch?v=VIDEO_ID or music.youtube.com/watch?v=VIDEO_ID
        if parsed_url.path == '/watch' and parsed_url.query:
            query_params = parse_qs(parsed_url.query)
            if 'v' in query_params:
                return query_params['v'][0]
                
        # youtu.be/VIDEO_ID
        elif parsed_url.netloc == 'youtu.be' and parsed_url.path:
            return parsed_url.path[1:]  # Remove leading /
            
        # youtube.com/v/VIDEO_ID
        elif parsed_url.path.startswith('/v/'):
            return parsed_url.path.split('/')[2]
            
        # youtube.com/embed/VIDEO_ID
        elif parsed_url.path.startswith('/embed/'):
            return parsed_url.path.split('/')[2]
            
        # Fallback: look for an 11-character ID in the URL
        match = re.search(r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})', url)
        if match:
            return match.group(1)
            
        return None
    except Exception as e:
        print(f"Error extracting YouTube ID: {e}")
        return None

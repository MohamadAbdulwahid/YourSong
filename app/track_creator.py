"""
Track creator module using pymusiclooper to create seamless transitions
"""
import os
import tempfile
import time
from pydub import AudioSegment
from pymusiclooper.core import MusicLooper  # Updated import path
import yt_dlp
import asyncio
from datetime import datetime
import shutil
import aiohttp
import aiofiles
from app.shared_state import processing_jobs, audio_path_cache
from app.similarity_finder import SEGMENTS_DIR

# Create a download semaphore to limit concurrent downloads
download_semaphore = asyncio.Semaphore(3)

def create_seamless_track(similar_parts, output_dir='static/output', process_id=None):
    """
    Create a seamless track from similar parts using pymusiclooper
    
    Args:
        similar_parts (list): List of similar parts with track information and timestamps
        output_dir (str): Directory to save the output file
        process_id (str): Process ID for tracking progress
        
    Returns:
        str: Path to the created track file
    """
    try:
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate unique filename for the output
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        output_path = f"{output_dir}/yoursong_{timestamp}.mp3"
        
        # If no similar parts, return early
        if not similar_parts:
            log_track_creation_progress(process_id, "No similar parts found", 0)
            return None
            
        # Extract parts from each track - using cached audio when possible
        segment_infos = []
        
        log_track_creation_progress(process_id, f"Creating seamless track from {len(similar_parts)} parts", 40)
        
        # List to keep track of segment files we create
        segment_files = []
        
        # Keep track of segment metadata for player visualization
        segment_metadata = []
        
        # Group similar parts by track to avoid downloading the same track multiple times
        track_parts = {}
        for i, part in enumerate(similar_parts):
            track_url = part['track']['url']
            if track_url not in track_parts:
                track_parts[track_url] = []
            track_parts[track_url].append((i, part))
        
        # Process each track only once
        for track_url, parts in track_parts.items():
            # Get info from the first part for this track
            first_part = parts[0][1]
            title = first_part['track']['title']
            artist = first_part['track']['artist']
            thumbnail = first_part.get('track', {}).get('thumbnail')
            
            # Use cached audio path if available
            audio_path = None
            
            # First check if the audio_path is directly in the track info (from similarity_finder)
            if 'audio_path' in first_part['track'] and os.path.exists(first_part['track']['audio_path']):
                audio_path = first_part['track']['audio_path']
                log_track_creation_progress(
                    process_id, 
                    f"Using cached audio file for {title} by {artist}", 
                    40 + (len(segment_infos) / len(similar_parts) * 10)
                )
            # Then check our global cache
            elif track_url in audio_path_cache and os.path.exists(audio_path_cache[track_url]):
                audio_path = audio_path_cache[track_url]
                log_track_creation_progress(
                    process_id, 
                    f"Using cached audio file for {title} by {artist}", 
                    40 + (len(segment_infos) / len(similar_parts) * 10)
                )
            # Otherwise download the audio
            else:
                log_track_creation_progress(
                    process_id, 
                    f"Downloading audio for {title} by {artist}", 
                    40 + (len(segment_infos) / len(similar_parts) * 10)
                )
                audio_path = download_audio(track_url)
            
            if not audio_path:
                log_track_creation_progress(
                    process_id, 
                    f"Failed to get audio for {title} by {artist}", 
                    40 + (len(segment_infos) / len(similar_parts) * 10)
                )
                continue
                
            # Load the audio file once for this track
            try:
                full_audio = AudioSegment.from_file(audio_path)
                
                # Process all segments from this track
                for i, part in parts:
                    start_time = part['start_time']
                    end_time = part['end_time']
                    similarity_score = part.get('similarity_score', 0)
                    
                    # Convert start and end times to milliseconds
                    start_ms = int(start_time * 1000)
                    end_ms = int(end_time * 1000)
                    
                    # Adjust end time if it exceeds the audio length
                    if end_ms > len(full_audio):
                        end_ms = len(full_audio)
                    
                    # Extract segment
                    segment = full_audio[start_ms:end_ms]
                    
                    # Save segment to project segments directory
                    segment_filename = f"segment_{timestamp}_{i}.mp3"
                    segment_path = os.path.join(SEGMENTS_DIR, segment_filename)
                    segment.export(segment_path, format="mp3")
                    segment_files.append(segment_path)
                    
                    # Add to segment_infos
                    segment_infos.append({
                        'segment': segment,
                        'title': title,
                        'artist': artist,
                        'start_time': start_time,
                        'end_time': end_time,
                        'audio_path': audio_path,
                        'segment_path': segment_path,
                        'segment_filename': segment_filename,
                        'thumbnail': thumbnail,
                        'similarity_score': similarity_score
                    })
                    
                    log_track_creation_progress(
                        process_id, 
                        f"Extracted segment from {title} by {artist} ({start_time:.2f}s to {end_time:.2f}s)", 
                        50 + (len(segment_infos) / len(similar_parts) * 10)
                    )
            except Exception as e:
                log_track_creation_progress(
                    process_id, 
                    f"Error processing track {title}: {e}", 
                    50
                )
                print(f"Error processing track: {e}")
                continue
                
        # If no segments were successfully extracted, return early
        if not segment_infos:
            log_track_creation_progress(process_id, "No segments were successfully extracted", 0)
            return None
            
        # Use our custom function to create transitions
        log_track_creation_progress(process_id, "Creating seamless transitions between segments", 60)
        combined_track, segments_with_positions = create_combined_track(segment_infos, process_id)
        
        # Save the combined track
        log_track_creation_progress(process_id, "Exporting final track...", 90)
        combined_track.export(output_path, format="mp3")
        
        # Store metadata about segments used (positions in the final track)
        if process_id and process_id in processing_jobs:
            processing_jobs[process_id]['segment_metadata'] = segments_with_positions
            print(f"Stored {len(segments_with_positions)} segments in metadata")
        
        # DO NOT delete the segment files - we're keeping them!
        log_track_creation_progress(process_id, f"Track created successfully: {output_path}", 100)
        return output_path
    except Exception as e:
        log_track_creation_progress(process_id, f"Error creating seamless track: {e}", 0)
        print(f"Error creating seamless track: {e}")
        return None

def log_track_creation_progress(process_id, message, progress_pct):
    """Log progress of track creation to the processing_jobs"""
    if not process_id or process_id not in processing_jobs:
        return
        
    # Update the progress
    processing_jobs[process_id]['message'] = message
    processing_jobs[process_id]['progress'] = 70 + (progress_pct / 100 * 30)  # Scale to 70%-100% range
    
    # Add to the track creation info
    if 'track_creation_info' not in processing_jobs[process_id]:
        processing_jobs[process_id]['track_creation_info'] = []
        
    processing_jobs[process_id]['track_creation_info'].append(message)
    
    # Print to console for debugging
    print(f"Track creation progress: {message}")

async def download_audio_async(url, download_path):
    """
    Asynchronously download audio from YouTube Music URL
    """
    # Use a semaphore to limit concurrent downloads
    async with download_semaphore:
        # For YouTube links, use yt-dlp
        if 'youtube.com' in url or 'youtu.be' in url or 'music.youtube' in url:
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': download_path.replace('.mp3', ''),
            }
            
            # Use synchronous yt-dlp but in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            
            return download_path
        # For local files
        elif url.startswith('/'):
            return url
        # For other URLs, try to download with aiohttp
        else:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            async with aiofiles.open(download_path, 'wb') as f:
                                await f.write(await response.read())
                            return download_path
            except Exception as e:
                print(f"Error downloading with aiohttp: {e}")
                return None

def download_audio(url):
    """
    Download audio from YouTube Music URL or return local file path
    
    Args:
        url (str): YouTube Music URL or local file path
        
    Returns:
        str: Path to downloaded/local audio file or None if failed
    """
    try:
        # Check if we have this URL cached
        if url in audio_path_cache and os.path.exists(audio_path_cache[url]):
            print(f"Using cached audio file for {url}")
            return audio_path_cache[url]
            
        # Check if it's a local file path
        if url.startswith('/uploads/'):
            # Get the project root directory
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # Create absolute path using project root
            absolute_path = os.path.join(project_root, url.lstrip('/'))
            print(f"Resolved local file path: {absolute_path}")
            # Verify file exists
            if os.path.exists(absolute_path):
                audio_path_cache[url] = absolute_path
                return absolute_path
            else:
                print(f"File not found at resolved path: {absolute_path}")
                return None
            
        # Generate a unique filename for the download
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        file_id = f"{timestamp}_{hash(url) % 10000}"
        download_path = os.path.join(SEGMENTS_DIR, f"{file_id}.mp3")
        
        # Download audio using yt-dlp (synchronous version)
        if 'youtube.com' in url or 'youtu.be' in url or 'music.youtube' in url:
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': os.path.join(SEGMENTS_DIR, f"{file_id}.%(ext)s"),
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
            
            # Add to cache
            audio_path_cache[url] = download_path
            return download_path
        
        return None
    except Exception as e:
        print(f"Error downloading audio: {e}")
        return None

def create_combined_track(segment_infos, process_id=None):
    """
    Create a combined track with crossfades between segments
    
    Args:
        segment_infos (list): List of dictionaries containing segments and their metadata
        process_id (str): Process ID for tracking progress
        
    Returns:
        tuple: (AudioSegment combined track, list of segment metadata with positions)
    """
    try:
        # Extract the actual audio segments
        segments = [info['segment'] for info in segment_infos]
        
        # If only one segment, return it with position metadata
        if len(segments) == 1:
            log_track_creation_progress(
                process_id, 
                f"Only one segment available: {segment_infos[0]['title']}, no transitions needed", 
                70
            )
            return segments[0], [{
                'title': segment_infos[0]['title'],
                'artist': segment_infos[0]['artist'],
                'start_position': 0,  # Start position in combined track (in seconds)
                'end_position': len(segments[0]) / 1000,  # End position in combined track (in seconds)
                'duration': len(segments[0]) / 1000,  # Duration in seconds
                'thumbnail': segment_infos[0].get('thumbnail'),
                'segment_path': segment_infos[0].get('segment_path'),
                'similarity_score': segment_infos[0].get('similarity_score', 0)
            }]
        
        log_track_creation_progress(
            process_id, 
            f"Creating transitions between {len(segments)} segments", 
            65
        )
        
        # Create a combined track with crossfades
        combined_track = segments[0]
        
        # Track position and duration of each segment in final track
        segment_positions = []
        current_position = 0  # in milliseconds
        
        # Add the first segment
        segment_positions.append({
            'title': segment_infos[0]['title'],
            'artist': segment_infos[0]['artist'],
            'start_position': 0,  # Start position in combined track (in seconds)
            'end_position': len(segments[0]) / 1000,  # End position in combined track (in seconds)
            'duration': len(segments[0]) / 1000,  # Duration in seconds
            'thumbnail': segment_infos[0].get('thumbnail'),
            'segment_path': segment_infos[0].get('segment_path'),
            'similarity_score': segment_infos[0].get('similarity_score', 0)
        })
        
        # Update position tracker
        current_position += len(segments[0])
        
        for i in range(1, len(segments)):
            segment = segments[i]
            info = segment_infos[i]
            
            # Calculate progress percentage
            progress_pct = 70 + (i / len(segments) * 20)
            
            # Apply crossfade between segments (3 seconds or less if segments are shorter)
            crossfade_duration = min(3000, len(combined_track), len(segment))
            
            log_track_creation_progress(
                process_id, 
                f"Applying {crossfade_duration/1000:.2f}s crossfade for {info['title']}", 
                progress_pct
            )
            
            # Calculate adjusted start position considering crossfade
            start_position = current_position - crossfade_duration
            
            # Append segment with crossfade
            combined_track = combined_track.append(segment, crossfade=crossfade_duration)
            
            # Calculate segment duration after crossfade
            segment_duration = len(segment)
            adjusted_end_position = start_position + segment_duration
            
            # Add segment position data
            segment_positions.append({
                'title': info['title'],
                'artist': info['artist'],
                'start_position': start_position / 1000,  # Convert to seconds
                'end_position': adjusted_end_position / 1000,  # Convert to seconds
                'duration': segment_duration / 1000,  # Convert to seconds
                'thumbnail': info.get('thumbnail'),
                'segment_path': info.get('segment_path'),
                'similarity_score': info.get('similarity_score', 0)
            })
            
            # Update position tracker for next segment
            current_position = current_position - crossfade_duration + segment_duration
        
        log_track_creation_progress(
            process_id, 
            f"Created track with duration: {len(combined_track)/1000:.2f}s", 
            90
        )
        return combined_track, segment_positions
    except Exception as e:
        log_track_creation_progress(process_id, f"Error creating combined track: {e}", 80)
        print(f"Error creating combined track: {e}")
        # Return the first segment as fallback
        if segment_infos:
            return segment_infos[0]['segment'], []
        return AudioSegment.silent(duration=1000), []

# Async wrapper for creating seamless tracks
async def create_seamless_track_async(similar_parts, output_dir='static/output', process_id=None):
    """
    Asynchronous wrapper for creating a seamless track
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        create_seamless_track, 
        similar_parts, 
        output_dir, 
        process_id
    )
"""
Similarity finder module using Google's Gemini AI with improved async processing
"""
import os
import json
import asyncio
import tempfile
import random
import numpy as np
import re
from scipy import signal
from datetime import datetime
from pydub import AudioSegment
import yt_dlp
from concurrent.futures import ThreadPoolExecutor
from google import genai
from google.genai import types

# Set up segments storage directory within the project
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEGMENTS_DIR = os.path.join(PROJECT_ROOT, 'segments')
# Ensure segments directory exists
os.makedirs(SEGMENTS_DIR, exist_ok=True)

async def find_similar_parts(favorite_part, related_tracks, similarity_threshold=0.7, process_id=None):
    """
    Find parts in related tracks that are similar to the user's favorite part using async processing
    
    Args:
        favorite_part (dict): Information about the user's favorite part (start_time, end_time)
        related_tracks (list): List of related track information
        similarity_threshold (float): Threshold for similarity (0.0-1.0)
        process_id (str): Optional process ID for updating progress info
        
    Returns:
        list: List of similar parts with track information and timestamps
    """
    try:
        # Extract and save favorite segment
        favorite_segment_path = await extract_favorite_segment(favorite_part, process_id)
        
        if not favorite_segment_path:
            print("Failed to extract favorite segment")
            return []
            
        # Extract features from the favorite segment
        favorite_features = extract_favorite_part_features(favorite_segment_path)
            
        print(f"Extracted features from favorite part: {favorite_features}")
        
        # Process each related track concurrently
        tasks = []
        for i, track in enumerate(related_tracks):
            task = process_track(track, favorite_segment_path, favorite_features, 
                                similarity_threshold, i, len(related_tracks), process_id)
            tasks.append(task)
            
        # Wait for all track processing to complete
        similar_parts = []
        results = await asyncio.gather(*tasks)
        
        # Combine results
        for parts in results:
            if parts:
                similar_parts.extend(parts)
                
        print(f"Found {len(similar_parts)} similar parts")
        
        # Check if we have any similar parts at all
        if not similar_parts:
            print("ERROR: No similar parts found in any tracks. Unable to create a personalized track.")
            
        return similar_parts
        
    except Exception as e:
        print(f"Error finding similar parts: {e}")
        return []

async def extract_favorite_segment(favorite_part, process_id):
    """
    Extract the user's favorite segment from the original audio
    
    Args:
        favorite_part (dict): Information about the user's favorite part
        process_id (str): Process ID for file naming
        
    Returns:
        str: Path to the extracted favorite segment
    """
    try:
        # Check if we have an audio path in favorite_part
        if 'audio_path' not in favorite_part or not os.path.exists(favorite_part['audio_path']):
            print("No audio path in favorite_part or file doesn't exist")
            return None
            
        # Load favorite audio
        favorite_audio = AudioSegment.from_file(favorite_part['audio_path'])
        
        # Extract the specific segment
        start_ms = int(favorite_part['start_time'] * 1000)
        end_ms = int(favorite_part['end_time'] * 1000)
        favorite_segment = favorite_audio[start_ms:end_ms]
        
        # Save the favorite segment to the segments directory
        fav_segment_path = os.path.join(SEGMENTS_DIR, f"favorite_{process_id}.mp3")
        favorite_segment.export(fav_segment_path, format="mp3")
        
        print(f"Extracted favorite segment to {fav_segment_path}")
        return fav_segment_path
    except Exception as e:
        print(f"Error extracting favorite segment: {e}")
        return None

async def process_track(track, favorite_segment_path, favorite_features, 
                       similarity_threshold, index, total_tracks, process_id):
    """
    Process a single track to find similar parts
    
    Args:
        track (dict): Track information
        favorite_segment_path (str): Path to favorite segment audio file
        favorite_features (dict): Features extracted from favorite segment
        similarity_threshold (float): Minimum similarity threshold
        index (int): Track index for progress reporting
        total_tracks (int): Total number of tracks
        process_id (str): Process ID for progress reporting
        
    Returns:
        list: Similar parts found in this track
    """
    from app.shared_state import processing_jobs
    
    try:
        # Update processing status
        if process_id and process_id in processing_jobs:
            processing_jobs[process_id]['current_track_analysis'] = {
                'track': track,
                'progress': index / total_tracks * 100
            }
            processing_jobs[process_id]['message'] = f'Analyzing "{track["title"]}" by {track["artist"]}...'
            processing_jobs[process_id]['progress'] = 40 + (index / total_tracks * 30)
            
        # Check if the URL is in a format Gemini can handle
        youtube_url = convert_to_standard_youtube_url(track['url'])
        if youtube_url:
            track['url'] = youtube_url
            print(f"Converted track URL to: {youtube_url}")
        
        # Find similar parts using Gemini
        parts = await find_similar_parts_with_gemini(
            track, 
            favorite_segment_path, 
            favorite_features,
            similarity_threshold
        )
        
        # If Gemini analysis fails, log an error and return empty list (no fallback)
        if not parts:
            print(f"ERROR: Gemini couldn't analyze track '{track['title']}'. Skipping this track.")
            return []
        
        # Add track info to each part
        similar_parts = []
        for part in parts:
            part['track'] = {
                'title': track['title'],
                'artist': track['artist'],
                'url': track['url'],
                'thumbnail': track['thumbnail'],
            }
            similar_parts.append(part)
            
        # Update the process status with the similar parts found for this track
        if process_id and process_id in processing_jobs:
            if 'current_track_analysis' in processing_jobs[process_id]:
                processing_jobs[process_id]['current_track_analysis']['similar_parts'] = parts
                
            # Add to analysis log
            log_entry = {
                'track': track['title'],
                'artist': track['artist'],
                'similar_parts_count': len(parts),
                'parts': parts  # Include the actual parts in the log
            }
            
            if 'analysis_log' not in processing_jobs[process_id]:
                processing_jobs[process_id]['analysis_log'] = []
                
            # Check if we already have an entry for this track to avoid duplicates
            track_exists = False
            for existing_entry in processing_jobs[process_id]['analysis_log']:
                if existing_entry.get('track') == track['title'] and existing_entry.get('artist') == track['artist']:
                    track_exists = True
                    break
                    
            if not track_exists:
                processing_jobs[process_id]['analysis_log'].append(log_entry)
                print(f"Found {len(parts)} similar parts in \"{track['title']}\" by {track['artist']}")
            
        return similar_parts
        
    except Exception as e:
        print(f"Error processing track {track['title']}: {e}")
        return []

def convert_to_standard_youtube_url(url):
    """
    Convert various YouTube URL formats to standard YouTube URL
    that Gemini can handle (https://youtu.be/{video_id})
    
    Args:
        url (str): YouTube or YouTube Music URL
    
    Returns:
        str: Standard YouTube URL or original URL if conversion failed
    """
    try:
        # If it's already in the youtu.be format, return it
        if url and "youtu.be" in url:
            return url
            
        # Try to extract video ID using regex patterns
        patterns = [
            # youtube.com/watch?v=VIDEO_ID
            r'(?:youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})',
            # music.youtube.com/watch?v=VIDEO_ID
            r'(?:music\.youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})',
            # youtube.com/v/VIDEO_ID
            r'(?:youtube\.com/v/)([a-zA-Z0-9_-]{11})',
            # youtube.com/embed/VIDEO_ID
            r'(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                return f"https://youtu.be/{video_id}"
                
        # If no match found, return the original URL
        print(f"Warning: Could not convert URL to standard YouTube format: {url}")
        return url
        
    except Exception as e:
        print(f"Error converting URL: {e}")
        return url

async def find_similar_parts_with_gemini(track, favorite_segment_path, favorite_features, similarity_threshold):
    """
    Use Gemini to find similar parts in a track by comparing the favorite segment
    with the YouTube Music track directly using the exact sample code approach
    
    Args:
        track (dict): Track information
        favorite_segment_path (str): Path to favorite segment audio file
        favorite_features (dict): Extracted features from favorite segment
        similarity_threshold (float): Minimum similarity threshold
        
    Returns:
        list: List of similar parts
    """
    try:
        # Check if we have a valid YouTube URL
        if not track.get('url') or not (track['url'].startswith('http://') or track['url'].startswith('https://')):
            print(f"No valid URL for track: {track.get('title')}")
            return []
        
        print(f"Using URL for Gemini analysis: {track['url']}")
        
        # Create a Gemini client - Using the approach from the sample code
        client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY"),
        )
        
        # Upload the favorite audio segment to Gemini - Using the exact approach from the sample code
        files = [
            client.files.upload(file=favorite_segment_path),
        ]
        
        # Create a formatted text description of key features
        feature_description = extract_key_characteristics(favorite_features)
        
        # Prepare the prompt for Gemini using the exact format from the sample
        prompt = f"""You are an expert music producer and audio engineer specializing in identifying similar musical patterns across tracks. I need you to find segments in a YouTube music track that closely match the musical characteristics of an uploaded audio clip.

TASK:
Analyze the provided audio clip (user's favorite music segment) and identify segments in the YouTube music track that would create a seamless, cohesive listening experience when combined.

REFERENCE AUDIO CLIP CHARACTERISTICS:
{feature_description}

MUSICAL ELEMENTS TO ANALYZE (in order of importance):
1. Energy profile and dynamics (loudness patterns, intensity)
2. Tonal characteristics (key, chord progressions, harmonic structure)
3. Rhythmic elements (tempo, beat pattern, groove)
4. Instrumentation and timbre (instrument sounds, texture)
5. Structural similarity (verse, chorus, bridge, build-up, drop)
6. Production style (reverb, spatial characteristics, mix balance)

SELECTION CRITERIA:
- Choose segments that match the emotional quality and energy of the reference clip
- Prefer segments with similar instrumentation and texture
- Select parts that would transition well when sequenced together
- Consider both musical and sonic coherence between segments
- Prioritize segments with clean beginnings/endings for seamless transitions
- Avoid segments with extreme stylistic differences that would create jarring transitions

REQUIREMENTS:
1. Return a JSON array of similar segments
2. Each segment must include:
   - start_time (number in seconds)
   - end_time (number in seconds) 
   - similarity_score (number between 0.0 and 1.0)
   - match_description (brief explanation of why this segment matches)
3. Only include segments with similarity_score >= {similarity_threshold}
4. Segments should be 8-13 seconds long (optimal for transitions)
5. Provide at least 2 segments if possible, choosing the most musically cohesive options

Your response must be ONLY a valid JSON array that can be parsed directly. 
Do not include any other text or explanations outside the JSON structure.
If no similar segments are found, return an empty array []."""

        # Create content for Gemini using the exact structure from the sample code
        model = "gemini-2.0-flash"
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(
                        file_uri=track['url'],
                        mime_type="video/*",
                    ),
                    types.Part.from_uri(
                        file_uri=files[0].uri,
                        mime_type=files[0].mime_type,
                    ),
                    types.Part.from_text(text=prompt),
                ],
            ),
        ]
        
        # Generate content using the same config from the sample
        generate_content_config = types.GenerateContentConfig(
            response_mime_type="text/plain",
        )
        
        # Use asyncio to run the generation in a thread
        response_text = ""
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=contents,
            config=generate_content_config
        )
        
        # Process the response
        response_text = response.text
        
        # Extract JSON content from response (handling various formats)
        json_content = extract_json_content(response_text)
        
        if not json_content:
            print(f"Could not extract valid JSON from Gemini response")
            return []
            
        # Parse JSON
        parts = json.loads(json_content)
        
        # Validate parts structure
        if not isinstance(parts, list):
            print("Parsed content is not a list")
            return []
            
        # Filter and clean up parts
        filtered_parts = []
        for part in parts:
            if part.get('similarity_score', 0) >= similarity_threshold:
                filtered_parts.append({
                    'start_time': part.get('start_time', 0),
                    'end_time': part.get('end_time', 0),
                    'similarity_score': part.get('similarity_score', 0),
                    'match_description': part.get('match_description', '')
                })
        
        print(f"Found {len(filtered_parts)} similar parts in {track['title']}")
        return filtered_parts
        
    except Exception as e:
        print(f"Error in Gemini analysis: {e}")
        return []

def extract_json_content(text):
    """Extract JSON content from text that may contain other content"""
    try:
        # Check for JSON code blocks
        if "```json" in text:
            json_start = text.find("```json") + 7
            json_end = text.rfind("```")
            return text[json_start:json_end].strip()
        elif "```" in text:
            json_start = text.find("```") + 3
            json_end = text.rfind("```")
            return text[json_start:json_end].strip()
        else:
            # Try to find any JSON array
            json_start = text.find('[')
            json_end = text.rfind(']') + 1
            if json_start != -1 and json_end != -1:
                return text[json_start:json_end].strip()
            else:
                return text.strip()
    except Exception as e:
        print(f"Error extracting JSON content: {e}")
        return None

def extract_favorite_part_features(audio_path):
    """
    Extract detailed features from the user's favorite audio segment
    
    Args:
        audio_path (str): Path to the audio file
        
    Returns:
        dict: Dictionary containing audio features
    """
    try:
        # Load audio file
        favorite_audio = AudioSegment.from_file(audio_path)
        
        # Get basic statistics
        duration = len(favorite_audio) / 1000  # in seconds
        loudness = favorite_audio.dBFS
        
        # Convert to numpy array for more analysis
        samples = np.array(favorite_audio.get_array_of_samples())
        sample_rate = favorite_audio.frame_rate
        
        # Calculate spectral features
        if len(samples) > 0:
            # Split into chunks for analysis
            chunk_duration = 0.05  # 50ms chunks
            chunk_size = int(chunk_duration * sample_rate)
            num_chunks = max(1, len(samples) // chunk_size)
            
            spectral_features = []
            temporal_features = []
            
            for i in range(min(20, num_chunks)):  # Limit to 20 chunks for performance
                chunk_start = i * chunk_size
                chunk_end = min(len(samples), (i + 1) * chunk_size)
                chunk = samples[chunk_start:chunk_end]
                
                if len(chunk) > 0:
                    # Calculate spectrum
                    spectrum = np.abs(np.fft.rfft(chunk))
                    # Get dominant frequencies
                    dominant_freqs = np.argsort(spectrum)[-5:]
                    # Convert to actual frequencies
                    dominant_freqs = [f * sample_rate / len(chunk) for f in dominant_freqs]
                    
                    spectral_features.append({
                        "time": i * chunk_duration,
                        "dominant_frequencies": dominant_freqs,
                        "energy": float(np.sum(spectrum))  # Convert to Python native type for JSON serialization
                    })
                    
                    # Calculate amplitude envelope
                    temporal_features.append({
                        "time": i * chunk_duration,
                        "rms": float(np.sqrt(np.mean(np.square(chunk)))),  # Convert to Python native type
                        "peak": float(np.max(np.abs(chunk)))  # Convert to Python native type
                    })
        
        # Return comprehensive features
        features = {
            "duration": duration,
            "loudness": loudness,
            "spectral_features": spectral_features[:10],  # Limit to first 10 for brevity
            "temporal_features": temporal_features[:10],  # Limit to first 10 for brevity
            "overall_characteristics": {
                "is_percussive": is_percussive(samples),
                "is_harmonic": is_harmonic(samples),
                "rhythm_complexity": estimate_rhythm_complexity(samples, sample_rate)
            }
        }
        
        return features
    except Exception as e:
        print(f"Error extracting favorite part features: {e}")
        return {"error": str(e)}

def extract_key_characteristics(features):
    """
    Extract key musical characteristics as a text description
    
    Args:
        features (dict): Audio features dictionary
        
    Returns:
        str: Formatted text description of key features
    """
    if not features or not isinstance(features, dict):
        return "Unknown musical characteristics"
    
    try:
        description_parts = []
        
        if 'duration' in features:
            description_parts.append(f"Duration: {features['duration']:.1f} seconds")
        
        if 'loudness' in features:
            description_parts.append(f"Loudness: {features['loudness']:.1f} dB")
            
        if 'overall_characteristics' in features:
            chars = features['overall_characteristics']
            
            if 'is_percussive' in chars:
                if chars['is_percussive']:
                    description_parts.append("Strong percussive elements")
                else:
                    description_parts.append("Minimal percussion")
                    
            if 'is_harmonic' in chars:
                if chars['is_harmonic']:
                    description_parts.append("Rich harmonic content")
                else:
                    description_parts.append("Less harmonic complexity")
                    
            if 'rhythm_complexity' in chars:
                complexity = chars['rhythm_complexity']
                if complexity < 0.3:
                    description_parts.append("Simple rhythmic structure")
                elif complexity < 0.7:
                    description_parts.append("Moderate rhythmic complexity")
                else:
                    description_parts.append("Complex rhythmic patterns")
                    
        # Add additional description based on temporal features
        if 'temporal_features' in features and features['temporal_features']:
            peaks = [f['peak'] for f in features['temporal_features']]
            avg_peak = sum(peaks) / len(peaks)
            
            if avg_peak > 0.7:
                description_parts.append("Dynamic with significant amplitude changes")
            elif avg_peak > 0.4:
                description_parts.append("Moderate dynamics")
            else:
                description_parts.append("Consistent amplitude profile")
        
        return ", ".join(description_parts)
    except Exception as e:
        print(f"Error extracting key characteristics: {e}")
        return "Musical segment with undefined characteristics"

def is_percussive(samples):
    """Simple detection of percussive content based on amplitude peaks"""
    if len(samples) == 0:
        return False
    # Normalize samples
    normalized = samples / (np.max(np.abs(samples)) + 1e-10)
    # Count sharp peaks
    peaks = np.where(np.abs(np.diff(normalized)) > 0.3)[0]
    return len(peaks) > len(normalized) * 0.01  # More than 1% are peaks

def is_harmonic(samples):
    """Simple detection of harmonic content based on spectral analysis"""
    if len(samples) == 0:
        return False
    # Calculate spectrum
    spectrum = np.abs(np.fft.rfft(samples))
    # Check for dominant frequency bands
    total_energy = np.sum(spectrum)
    if total_energy == 0:
        return False
    # Sort spectrum
    sorted_spectrum = np.sort(spectrum)
    # Check if top 10% of frequencies contain more than 70% of energy
    top_freqs_energy = np.sum(sorted_spectrum[-int(len(spectrum)*0.1):])
    return top_freqs_energy / total_energy > 0.7

def estimate_rhythm_complexity(samples, sample_rate):
    """Estimate rhythm complexity through onset detection"""
    if len(samples) == 0:
        return 0
    # Simple onset detection
    envelope = np.abs(samples)
    # Smooth
    window_size = int(0.01 * sample_rate)  # 10ms window
    if window_size > 1:
        kernel = np.ones(window_size) / window_size
        smoothed = np.convolve(envelope, kernel, mode='same')
        # Detect peaks
        peaks = signal.find_peaks(smoothed, height=np.mean(smoothed), distance=window_size)[0]
        # Rhythm complexity based on variability in inter-onset intervals
        if len(peaks) > 1:
            intervals = np.diff(peaks)
            # Complexity increases with variability in intervals
            return min(1.0, float(np.std(intervals) / np.mean(intervals)))
    return 0.2  # Default moderate complexity
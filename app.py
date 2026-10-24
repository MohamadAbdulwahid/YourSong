import os
import time
import json
import asyncio
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import threading

# Import custom modules
from app.song_identifier import identify_song
from app.link_converter import convert_link
from app.related_tracks import get_related_tracks
from app.similarity_finder import find_similar_parts
from app.track_creator import create_seamless_track
from app.shared_state import processing_jobs

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'yoursong-secret-key')

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'flac', 'm4a'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST']) 
def upload_file():
    """Handle file uploads or music links"""
    try:
        if 'audioFile' in request.files:
            # File upload handling
            file = request.files['audioFile']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
                
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                # Identify the song using Shazam
                song_info = identify_song(filepath)
                
                if not song_info:
                    return jsonify({'error': 'Could not identify the song. Please try a different audio file or use a music link instead.'}), 400
                
                # Store song info in session
                session['song_info'] = song_info
                session['audio_file'] = filename  # Store the filename for later use
                
                # Get YouTube Music link from Apple Music link if available
                ytmusic_link = None
                if song_info.get('apple_music_link'):
                    ytmusic_link = convert_link(song_info['apple_music_link'])
                    if ytmusic_link:
                        print(f"Converted Apple Music link to YouTube Music: {ytmusic_link}")
                        session['ytmusic_link'] = ytmusic_link
                
                return jsonify({
                    'success': True, 
                    'song_info': song_info,
                    'ytmusic_link': ytmusic_link,
                    'next_step': 'select_favorite'
                })
            else:
                return jsonify({'error': 'File type not allowed. Please upload an MP3, WAV, OGG, FLAC, or M4A file.'}), 400
                
        elif 'musicLink' in request.form:
            # Music link handling
            music_link = request.form['musicLink']
            
            if not music_link or not music_link.strip():
                return jsonify({'error': 'Please provide a valid music link'}), 400
                
            # Convert to YouTube Music link if needed
            ytmusic_link = convert_link(music_link)
            print(f"Converted link: {ytmusic_link}")
            
            if not ytmusic_link:
                return jsonify({'error': 'Could not process the provided link. Please check that it is a valid music link from a supported platform.'}), 400
                
            # Store link info in session
            session['ytmusic_link'] = ytmusic_link
            
            # Clear any previous file uploads
            if 'audio_file' in session:
                del session['audio_file']
            
            return jsonify({
                'success': True,
                'ytmusic_link': ytmusic_link,
                'next_step': 'select_favorite'
            })
        else:
            return jsonify({'error': 'No file or link provided. Please either upload an audio file or provide a music link.'}), 400
            
    except Exception as e:
        print(f"Error in upload_file: {str(e)}")
        return jsonify({'error': f'An unexpected error occurred: {str(e)}'}), 500

@app.route('/select_favorite')
def select_favorite():
    """Page for selecting favorite part of the song"""
    song_info = session.get('song_info')
    ytmusic_link = session.get('ytmusic_link')
    audio_file = session.get('audio_file')
    
    if not song_info and not ytmusic_link:
        return redirect(url_for('index'))
        
    return render_template('select_favorite.html', 
                          song_info=song_info, 
                          ytmusic_link=ytmusic_link,
                          audio_file=audio_file)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/segments/<filename>')
def segment_file(filename):
    """Serve segment files for individual playback"""
    from app.similarity_finder import SEGMENTS_DIR
    return send_from_directory(SEGMENTS_DIR, filename)

@app.route('/api/track_info')
def get_track_info():
    """API endpoint to get track information from a link"""
    # This would typically fetch detailed track info from a link
    # For now, just return a placeholder response
    return jsonify({
        'success': True,
        'track_info': {
            'title': 'Sample Track',
            'artist': 'Sample Artist',
            'album': 'Sample Album',
            'thumbnail': None
        },
        'audio_url': '/uploads/sample.mp3'  # Would be a real URL in production
    })

@app.route('/process_favorite', methods=['POST'])
def process_favorite():
    """Process the selected favorite part"""
    try:
        data = request.get_json()
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        
        if not start_time or not end_time:
            return jsonify({'error': 'Invalid time selection'}), 400
            
        # Store favorite part info in session
        favorite_part = {'start_time': start_time, 'end_time': end_time}
        session['favorite_part'] = favorite_part
        
        # Check if we have a file or YouTube Music link
        audio_file = session.get('audio_file')
        ytmusic_link = session.get('ytmusic_link')
        
        # Ensure output directory exists
        os.makedirs('static/output', exist_ok=True)
        
        # Generate a unique ID for this process
        process_id = str(int(time.time()))
        session['process_id'] = process_id
        
        # Store favorite part in processing_jobs immediately so background thread can access it
        if process_id not in processing_jobs:
            processing_jobs[process_id] = {
                'status': 'initialized',
                'progress': 0,
                'message': 'Initializing...',
                'favorite_part': favorite_part,  # Store it here for background thread
                'related_tracks': [],
                'similar_parts': [],
                'output_path': None,
                'error': None
            }
        
        if audio_file and not ytmusic_link:
            # For uploaded files, we'll redirect to the processing page
            # where we'll handle this with more visual feedback
            return jsonify({
                'success': True,
                'process_id': process_id,
                'next_step': 'processing'
            })
        elif ytmusic_link:
            # For YouTube links, redirect to processing page
            return jsonify({
                'success': True,
                'process_id': process_id,
                'next_step': 'processing'
            })
        else:
            return jsonify({'error': 'No audio source found. Please upload a file or provide a link.'}), 400
            
    except Exception as e:
        print(f"Error processing favorite part: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/create_track', methods=['POST'])
def create_track():
    """Create a seamless track from similar parts"""
    try:
        data = request.get_json()
        similarity_threshold = data.get('similarity_threshold', 0.7)
        max_parts = data.get('max_parts', 10)
        
        favorite_part = session.get('favorite_part')
        related_tracks = session.get('related_tracks')
        
        if not favorite_part or not related_tracks:
            return jsonify({'error': 'Missing required data'}), 400
            
        # Create an event loop to run the async find_similar_parts function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        similar_parts = loop.run_until_complete(
            find_similar_parts(
                favorite_part,
                related_tracks,
                similarity_threshold=similarity_threshold
            )
        )
        loop.close()
        
        # Limit the number of parts
        similar_parts = similar_parts[:max_parts]
        
        # Create seamless track
        output_path = create_seamless_track(similar_parts)
        
        return jsonify({
            'success': True,
            'output_path': output_path,
            'similar_parts': similar_parts
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/result')
def result():
    """Display final result page"""
    output_path = request.args.get('output_path') or session.get('output_path')
    similar_parts = session.get('similar_parts')
    process_id = session.get('process_id')
    
    # Get segment metadata for the timeline visualization
    segment_metadata = None
    formatted_analysis_log = None
    
    if process_id and process_id in processing_jobs:
        if 'segment_metadata' in processing_jobs[process_id]:
            segment_metadata = processing_jobs[process_id]['segment_metadata']
            print(f"Found segment metadata for process {process_id}: {len(segment_metadata)} segments")
        else:
            print(f"No segment metadata found for process {process_id}")
            
        # Get the formatted analysis log
        if 'formatted_analysis_log' in processing_jobs[process_id]:
            formatted_analysis_log = processing_jobs[process_id]['formatted_analysis_log']
            print(f"Found formatted analysis log with {len(formatted_analysis_log)} entries")
    
    if not output_path:
        return redirect(url_for('index'))
    
    # Add current date for display
    from datetime import datetime
    now = datetime.now()
    
    # Debug information
    segments_count = len(similar_parts) if similar_parts else 0
    metadata_count = len(segment_metadata) if segment_metadata else 0
    print(f"Rendering result page with {segments_count} similar parts and {metadata_count} segment metadata items")
    
    return render_template('result.html', 
                          output_path=output_path, 
                          similar_parts=similar_parts,
                          segment_metadata=segment_metadata,
                          formatted_analysis_log=formatted_analysis_log,
                          now=now)

# Helper function to run async code in a threadsafe way
def run_async(func, *args, **kwargs):
    """Run an async function from a synchronous context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(func(*args, **kwargs))
    loop.close()
    return result

# Main async processing function
async def process_song_async(process_id, audio_file=None, ytmusic_link=None):
    """
    Asynchronous function to process song, find similar parts and create track
    """
    from app.shared_state import processing_jobs
    
    try:
        print(f"Async processing starting for {process_id}")
        
        # Get the favorite part data
        favorite_part = None
        if process_id in processing_jobs and 'favorite_part' in processing_jobs[process_id]:
            favorite_part = processing_jobs[process_id]['favorite_part']
            print(f"Retrieved favorite part from processing_jobs: {favorite_part}")
        
        if not favorite_part:
            processing_jobs[process_id]['status'] = 'error'
            processing_jobs[process_id]['error'] = 'Missing favorite part information'
            print(f"Error: Missing favorite part information for process {process_id}")
            return
        
        # Initialize progress tracking
        processing_jobs[process_id] = {
            'status': 'starting',
            'progress': 0,
            'message': 'Starting processing...',
            'related_tracks': [],
            'similar_parts': [],
            'output_path': None,
            'error': None,
            'favorite_part': favorite_part,
            'current_track_analysis': None
        }
        
        # Step 1: Find related tracks
        print(f"Finding related tracks for process {process_id}")
        processing_jobs[process_id]['status'] = 'finding_related'
        processing_jobs[process_id]['message'] = 'Finding related tracks...'
        processing_jobs[process_id]['progress'] = 10
        
        # Get related tracks based on input type
        related_tracks = []
        
        # If we have a YouTube Music link, use that to find related tracks
        if ytmusic_link:
            print(f"Getting related tracks from YouTube Music link: {ytmusic_link}")
            related_tracks = get_related_tracks(ytmusic_link, max_results=15)
        # For uploaded files, try to get a YouTube Music link from song info if available
        elif audio_file:
            print(f"Processing uploaded file: {audio_file}")
            
            # Get song info from session if available
            song_info = None
            import flask
            if 'song_info' in flask.session:
                song_info = flask.session.get('song_info')
            
            # Try to get a YouTube Music link for the file
            file_ytmusic_link = None
            
            # If we have Apple Music link in song info, convert it
            if song_info and song_info.get('apple_music_link'):
                file_ytmusic_link = convert_link(song_info['apple_music_link'])
                print(f"Found Apple Music link in song info, converted to: {file_ytmusic_link}")
            
            # If we have a YouTube Music link for the file, use it to get related tracks
            if file_ytmusic_link:
                print(f"Getting related tracks for uploaded file using YouTube Music link: {file_ytmusic_link}")
                related_tracks = get_related_tracks(file_ytmusic_link, max_results=15)
            # Otherwise, create a basic entry for the uploaded file
            else:
                print(f"No YouTube Music link available for uploaded file. Creating basic entry.")
                related_tracks = [{
                    'title': 'Your Uploaded Track',
                    'artist': 'Unknown',
                    'album': 'Unknown',
                    'thumbnail': None,
                    'video_id': None,
                    'url': f"/uploads/{audio_file}",
                    'is_original': True
                }]
        
        print(f"Found {len(related_tracks)} related tracks")
        processing_jobs[process_id]['related_tracks'] = related_tracks
        processing_jobs[process_id]['progress'] = 30
        processing_jobs[process_id]['message'] = f'Found {len(related_tracks)} related tracks'
        
        # Exit early if no related tracks found
        if not related_tracks:
            processing_jobs[process_id]['status'] = 'error'
            processing_jobs[process_id]['error'] = 'No related tracks found'
            print(f"Error: No related tracks found for process {process_id}")
            return
        
        # Step 2: Find similar parts asynchronously with improved Gemini analysis
        print(f"Finding similar parts for process {process_id}")
        processing_jobs[process_id]['status'] = 'finding_similar'
        processing_jobs[process_id]['message'] = 'Analyzing tracks for similar musical patterns...'
        processing_jobs[process_id]['progress'] = 40
        
        # If audio_file is a filename, create an absolute path
        if audio_file:
            # Get the project root directory
            project_root = os.path.dirname(os.path.abspath(__file__))
            # Create absolute path for audio file
            audio_file_path = os.path.join(project_root, app.config['UPLOAD_FOLDER'], audio_file)
            favorite_part['audio_path'] = audio_file_path
            
        # Find similar parts using the async function
        similar_parts = await find_similar_parts(
            favorite_part,
            related_tracks,
            similarity_threshold=0.7,
            process_id=process_id
        )
        
        # Update progress information
        print(f"Found {len(similar_parts)} similar parts")
        processing_jobs[process_id]['similar_parts'] = similar_parts
        processing_jobs[process_id]['progress'] = 70
        processing_jobs[process_id]['message'] = f'Found {len(similar_parts)} similar musical parts'
        
        # Check if we have any similar parts - if not, we can't continue
        if not similar_parts:
            processing_jobs[process_id]['status'] = 'error'
            processing_jobs[process_id]['error'] = 'No similar parts found in any tracks. Unable to create a personalized track.'
            print(f"ERROR: No similar parts found in any tracks for process {process_id}")
            return
        
        # Step 3: Create a seamless track
        print(f"Creating seamless track for process {process_id}")
        processing_jobs[process_id]['status'] = 'creating_track'
        processing_jobs[process_id]['message'] = 'Creating your personalized seamless track...'
        processing_jobs[process_id]['progress'] = 80
        
        # Create the seamless track, passing the process_id so segment metadata gets stored
        output_path = create_seamless_track(similar_parts, process_id=process_id)
        
        # If output path is None, there was an error
        if not output_path:
            processing_jobs[process_id]['status'] = 'error'
            processing_jobs[process_id]['error'] = 'Failed to create seamless track'
            print(f"Error: Failed to create seamless track for process {process_id}")
            return
        
        # Make sure the output path is URL-friendly
        if output_path.startswith('/'):
            output_path = output_path[1:]  # Remove leading slash if present
        
        # Update final status
        print(f"Completed processing for {process_id}, output at: {output_path}")
        processing_jobs[process_id]['output_path'] = output_path
        processing_jobs[process_id]['status'] = 'completed'
        processing_jobs[process_id]['progress'] = 100
        processing_jobs[process_id]['message'] = 'Your personalized track is ready!'
        
        # Format and store analysis log for display on the result page
        if 'analysis_log' in processing_jobs[process_id]:
            formatted_log = []
            for entry in processing_jobs[process_id]['analysis_log']:
                track_info = f"\"{entry['track']}\" by {entry['artist']}"
                parts_info = []
                
                if 'parts' in entry:
                    for part in entry['parts']:
                        similarity = int(part['similarity_score'] * 100)
                        start = int(part['start_time'])
                        end = int(part['end_time'])
                        parts_info.append(f"→ Similar part from {start//60:02d}:{start%60:02d} to {end//60:02d}:{end%60:02d} ({similarity}% match)")
                
                formatted_log.append(f"Found {entry['similar_parts_count']} similar parts in {track_info}")
                formatted_log.extend(parts_info)
            
            processing_jobs[process_id]['formatted_analysis_log'] = formatted_log
        
    except Exception as e:
        # Handle errors
        print(f"Error in async processing for {process_id}: {str(e)}")
        processing_jobs[process_id]['status'] = 'error'
        processing_jobs[process_id]['error'] = str(e)
        processing_jobs[process_id]['message'] = f'Error: {str(e)}'

def process_song_background(process_id, audio_file=None, ytmusic_link=None):
    """Background processing function that runs the async task"""
    try:
        # Run the async processing function in a new event loop
        run_async(process_song_async, process_id, audio_file, ytmusic_link)
    except Exception as e:
        print(f"Error in background processing thread: {e}")
        # Update processing job with error
        if process_id in processing_jobs:
            processing_jobs[process_id]['status'] = 'error'
            processing_jobs[process_id]['error'] = str(e)

@app.route('/processing')
def processing():
    """Show processing page with real-time updates"""
    process_id = session.get('process_id')
    if not process_id:
        return redirect(url_for('index'))
    
    # Get information from session
    audio_file = session.get('audio_file')
    ytmusic_link = session.get('ytmusic_link')
    song_info = session.get('song_info')
    favorite_part = session.get('favorite_part')
    
    # Make sure processing_jobs exists for this process_id
    if process_id not in processing_jobs:
        processing_jobs[process_id] = {
            'status': 'initialized',
            'progress': 0,
            'message': 'Initializing...',
            'related_tracks': [],
            'similar_parts': [],
            'output_path': None,
            'error': None
        }
    
    # Store the favorite part in processing_jobs BEFORE starting the thread
    processing_jobs[process_id]['favorite_part'] = favorite_part
    
    # Print debug information
    print(f"Stored favorite part in processing_jobs[{process_id}]: {favorite_part}")
    print(f"Audio file: {audio_file}, YT Music link: {ytmusic_link}")
    
    # Start background processing thread
    thread = threading.Thread(
        target=process_song_background,
        args=(process_id, audio_file, ytmusic_link)
    )
    thread.daemon = True
    thread.start()
    
    return render_template('processing.html', 
                          process_id=process_id,
                          song_info=song_info,
                          audio_file=audio_file,
                          ytmusic_link=ytmusic_link)

@app.route('/api/process_status/<process_id>')
def process_status(process_id):
    """API endpoint to get the current processing status"""
    if process_id not in processing_jobs:
        return jsonify({
            'status': 'not_found',
            'message': 'Processing job not found'
        }), 404
    
    # Get the current status
    status = processing_jobs[process_id]
    
    # If processing is complete, store output path and similar parts in session
    if status['status'] == 'completed':
        session['output_path'] = status['output_path']
        session['similar_parts'] = status['similar_parts']
    
    return jsonify(status)

if __name__ == '__main__':
    app.run(debug=True)

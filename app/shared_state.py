"""
Shared state module for the app
"""
# Dict to track background processing jobs
processing_jobs = {}

# Cache of downloaded audio files (url -> file_path)
audio_path_cache = {}
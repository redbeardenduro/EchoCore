# config.py
"""
Configuration settings for Project EchoCore.
Loads API keys from environment variables (.env file).
"""

import os
import logging
from dotenv import load_dotenv

# Load environment variables from a.env file if it exists
load_dotenv()

# --- General Settings ---
LOG_LEVEL = logging.INFO # Logging level (e.g., logging.DEBUG, logging.INFO)

# --- API Keys ---
# Load from environment variables for security
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY")

# --- Audio Settings ---
# Use 'python -m sounddevice' to list available devices and their indices
AUDIO_INPUT_DEVICE_INDEX = None # None for default input device
AUDIO_OUTPUT_DEVICE_INDEX = None # None for default output device
AUDIO_SAMPLE_RATE = 16000 # Sample rate expected by Vosk/Porcupine (Hz)
AUDIO_CHUNK_SIZE = 1024 # Size of audio chunks for processing
AUDIO_INPUT_CHANNELS = 1
AUDIO_OUTPUT_CHANNELS = 1
AUDIO_DTYPE = 'int16' # Data type for audio samples
AUDIO_OUTPUT_LATENCY = 'low' # Latency setting for output stream ['low', 'high', float seconds]

# --- Wake Word Settings (Porcupine) ---
# Path to the Porcupine model file (.pv) - usually platform-specific
PORCUPINE_MODEL_PATH = None # Set to None to use default, or path to file in models/porcupine/
# Path(s) to Porcupine keyword files (.ppn)
PORCUPINE_KEYWORD_PATHS = ["models/porcupine/porcupine_raspberry-pi.ppn"] # Example path
PORCUPINE_SENSITIVITIES = [0.5] # Sensitivity for each keyword (0.0 to 1.0)

# --- STT Settings (Vosk) ---
# Path to the Vosk model directory
VOSK_MODEL_PATH = "models/vosk/vosk-model-small-en-us-0.15" # Example path
VOSK_LOG_LEVEL = -1 # Disable Vosk logging

# --- LLM Settings (OpenAI) ---
# Preferred OpenAI model
LLM_MODEL = "gpt-4o-mini" # e.g., "gpt-4o", "gpt-4o-mini" [1, 2, 3]
LLM_TIMEOUT = 30 # Timeout for API calls in seconds
LLM_OFFLINE_FALLBACK_ENABLED = True # Enable basic offline response (placeholder)
LLM_OFFLINE_RESPONSE = "I cannot connect to the internet right now."

# --- TTS Settings ---
# Choose TTS engine: 'openai', 'elevenlabs', or 'piper'
TTS_ENGINE = "openai" # Default to OpenAI TTS for cost-effectiveness [4, 5, 3]

# OpenAI TTS Settings
OPENAI_TTS_MODEL = "gpt-4o-mini-tts" # Or "tts-1", "tts-1-hd" [1, 3]
OPENAI_TTS_VOICE = "alloy" # Choose from 'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer' [3]
OPENAI_TTS_FORMAT = "pcm" # Recommended for direct playback [3]

# ElevenLabs TTS Settings
ELEVENLABS_VOICE = "Rachel" # Example voice name [6]
ELEVENLABS_MODEL = "eleven_multilingual_v2" # Or other available models [4]

# Piper TTS Settings (Local/Offline)
# Path to Piper voice model (.onnx file)
PIPER_MODEL_PATH = "models/piper/en_US-lessac-medium.onnx" # Example path [7]
PIPER_CONFIG_PATH = None # Optional: Path to config (.json), derived from model path if None
PIPER_SPEAKER_ID = 0 # Speaker ID for multi-speaker models

# --- Avatar Settings (Pygame) ---
AVATAR_WINDOW_WIDTH = 800
AVATAR_WINDOW_HEIGHT = 480
AVATAR_BACKGROUND_COLOR = (0, 0, 0) # Black
AVATAR_IDLE_COLOR = (0, 100, 255) # Blue
AVATAR_LISTENING_COLOR = (255, 255, 0) # Yellow
AVATAR_THINKING_COLOR = (255, 165, 0) # Orange
AVATAR_SPEAKING_COLOR = (0, 255, 0) # Green
AVATAR_ERROR_COLOR = (255, 0, 0) # Red
AVATAR_MIN_RADIUS = 20
AVATAR_MAX_RADIUS_FACTOR = 5 # Multiplier for amplitude scaling
AVATAR_FPS = 30 # Target frames per second

# --- Validation ---
if not PICOVOICE_ACCESS_KEY:
    logging.warning("PICOVOICE_ACCESS_KEY not set in environment variables.")
if not OPENAI_API_KEY:
    logging.warning("OPENAI_API_KEY not set in environment variables.")
if TTS_ENGINE == 'elevenlabs' and not ELEVENLABS_API_KEY:
    logging.warning("ELEVENLABS_API_KEY not set for selected TTS engine.")

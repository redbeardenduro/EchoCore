# config.py
"""
Configuration settings for Project EchoCore.
Loads API keys from environment variables (.env file).
"""

import os
import logging
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists
load_dotenv()

# --- Paths ---
ROOT_DIR = Path(__file__).parent.absolute()
MODELS_DIR = ROOT_DIR / "models"
LOGS_DIR = ROOT_DIR / "logs"
CACHE_DIR = ROOT_DIR / "cache"

# Create directories if they don't exist
for dir_path in [LOGS_DIR, CACHE_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# --- Logging Configuration ---
LOG_LEVEL = logging.INFO  # Logging level (e.g., logging.DEBUG, logging.INFO)
LOG_FILE = LOGS_DIR / "echocore.log"
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s'
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 3  # Keep 3 backup files

# --- System Settings ---
HEALTH_CHECK_INTERVAL = 30  # Seconds between system health checks
RECOVERY_ATTEMPTS = 3  # Number of times to attempt recovery before giving up
STANDBY_TIMEOUT = 300  # Seconds of inactivity before entering standby mode (if enabled)
ENABLE_STANDBY_MODE = False  # Whether to use reduced CPU when idle

# --- Security Settings ---
USE_SECURE_STORAGE = False  # If True, use system keyring instead of .env file
API_RATE_LIMITING = True  # Enable rate limiting for API calls
MAX_API_CALLS_PER_MINUTE = 10  # Maximum API calls per minute

# --- API Keys ---
# Load from environment variables for security
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY")

# --- Audio Settings ---
# Use 'python -m sounddevice' to list available devices and their indices
AUDIO_INPUT_DEVICE_INDEX = None  # None for default input device
AUDIO_OUTPUT_DEVICE_INDEX = None  # None for default output device
AUDIO_SAMPLE_RATE = 16000  # Sample rate expected by Vosk/Porcupine (Hz)
AUDIO_CHUNK_SIZE = 1024  # Size of audio chunks for processing
AUDIO_INPUT_CHANNELS = 1
AUDIO_OUTPUT_CHANNELS = 1
AUDIO_DTYPE = 'int16'  # Data type for audio samples
AUDIO_OUTPUT_LATENCY = 'low'  # Latency setting for output stream ['low', 'high', float seconds]
AUDIO_AMPLITUDE_SCALING_DIVISOR = 2**10  # Divisor for normalizing amplitude (moved from audio_output.py)

# --- Audio Feedback Settings ---
ENABLE_AUDIO_CUES = True  # Whether to play audio cues for state changes
AUDIO_CUE_VOLUME = 0.3  # Volume for audio cues (0.0 to 1.0)

# --- Wake Word Settings (Porcupine) ---
# Path to the Porcupine model file (.pv) - usually platform-specific
PORCUPINE_MODEL_PATH = None  # Set to None to use default, or path to file in models/porcupine/
# Path(s) to Porcupine keyword files (.ppn)
PORCUPINE_KEYWORD_PATHS = ["models/porcupine/porcupine_raspberry-pi.ppn"]  # Example path
PORCUPINE_SENSITIVITIES = [0.5]  # Sensitivity for each keyword (0.0 to 1.0)
LISTENING_TIMEOUT = 10.0  # Seconds to listen before timing out if no speech detected

# --- STT Settings (Vosk) ---
# Path to the Vosk model directory
VOSK_MODEL_PATH = "models/vosk/vosk-model-small-en-us-0.15"  # Example path
VOSK_LOG_LEVEL = -1  # Disable Vosk logging
VOSK_TIMEOUT_SECONDS = 10.0  # Seconds to wait before timing out speech recognition
STT_CONFIDENCE_THRESHOLD = 0.7  # Minimum confidence for accepting transcription

# --- LLM Settings (OpenAI) ---
# Preferred OpenAI model
LLM_MODEL = "gpt-4o-mini"  # e.g., "gpt-4o", "gpt-4o-mini"
LLM_TIMEOUT = 30  # Timeout for API calls in seconds
LLM_MAX_CONVERSATION_TURNS = 10  # Maximum conversation history to retain
LLM_TEMPERATURE = 0.7  # Controls randomness (0.0 to 1.0, higher = more random)
LLM_MAX_TOKENS = 150  # Maximum tokens in response
LLM_SYSTEM_PROMPT = """You are Echo, a helpful voice assistant. 
Keep your responses concise and conversational.
You're running on a Raspberry Pi 5 as part of Project EchoCore."""
LLM_OFFLINE_FALLBACK_ENABLED = True  # Enable basic offline response (placeholder)
LLM_OFFLINE_RESPONSE = "I cannot connect to the internet right now."
LLM_LOCAL_MODEL_PATH = None  # Path to a local LLM model (if available)
LLM_PREFER_LOCAL = False  # If True, try local LLM before cloud API

# --- TTS Settings ---
# Choose TTS engine: 'openai', 'elevenlabs', or 'piper'
TTS_ENGINE = "openai"  # Default to OpenAI TTS for cost-effectiveness
TTS_STREAMING = True  # Whether to stream partial TTS results as they come in
TTS_CACHE_ENABLED = True  # Cache TTS responses to reduce API usage
TTS_CACHE_SIZE = 100  # Maximum number of responses to cache
TTS_RESPONSE_CHUNK_SIZE = 50  # Maximum text length to send for TTS at once (for streaming)

# OpenAI TTS Settings
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"  # Or "tts-1", "tts-1-hd"
OPENAI_TTS_VOICE = "alloy"  # Choose from 'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'
OPENAI_TTS_FORMAT = "pcm"  # Recommended for direct playback

# ElevenLabs TTS Settings
ELEVENLABS_VOICE = "Rachel"  # Example voice name
ELEVENLABS_MODEL = "eleven_multilingual_v2"  # Or other available models
ELEVENLABS_STABILITY = 0.5  # Voice stability (0.0 to 1.0)
ELEVENLABS_SIMILARITY = 0.75  # Voice similarity enhancement (0.0 to 1.0)

# Piper TTS Settings (Local/Offline)
# Path to Piper voice model (.onnx file)
PIPER_MODEL_PATH = "models/piper/en_US-lessac-medium.onnx"  # Example path
PIPER_CONFIG_PATH = None  # Optional: Path to config (.json), derived from model path if None
PIPER_SPEAKER_ID = 0  # Speaker ID for multi-speaker models
PIPER_NOISE_SCALE = 0.667  # Noise scale for voice variation
PIPER_LENGTH_SCALE = 1.0  # Length scale for speech speed (>1 = slower)

# --- Avatar Settings (Pygame) ---
AVATAR_WINDOW_WIDTH = 800
AVATAR_WINDOW_HEIGHT = 480
AVATAR_BACKGROUND_COLOR = (0, 0, 0)  # Black
AVATAR_IDLE_COLOR = (0, 100, 255)  # Blue
AVATAR_LISTENING_COLOR = (255, 255, 0)  # Yellow
AVATAR_THINKING_COLOR = (255, 165, 0)  # Orange
AVATAR_SPEAKING_COLOR = (0, 255, 0)  # Green
AVATAR_ERROR_COLOR = (255, 0, 0)  # Red
AVATAR_MIN_RADIUS = 20
AVATAR_MAX_RADIUS_FACTOR = 5  # Multiplier for amplitude scaling
AVATAR_FPS = 30  # Target frames per second
AVATAR_ANIMATION_STYLE = "wave"  # Options: "circle", "wave", "particle", "hologram"
AVATAR_DISPLAY_STATUS_TEXT = True  # Show status text
AVATAR_FULLSCREEN = False  # Run in fullscreen mode
AVATAR_DEBUG_OVERLAY = False  # Enable debug overlay with state and amplitude

# --- Web Interface Settings ---
WEB_INTERFACE_ENABLED = False  # Whether to enable web configuration interface
WEB_INTERFACE_PORT = 8080  # Port for web interface
WEB_INTERFACE_HOST = "0.0.0.0"  # Host for web interface (0.0.0.0 = all interfaces)
WEB_INTERFACE_USERNAME = "admin"  # Username for basic auth
WEB_INTERFACE_PASSWORD = "echocore"  # Password for basic auth (should be changed)

# --- Load user configuration if exists ---
USER_CONFIG_PATH = ROOT_DIR / "user_config.json"
if USER_CONFIG_PATH.exists():
    try:
        with open(USER_CONFIG_PATH, 'r') as f:
            user_config = json.load(f)
            # Update globals with user config
            for key, value in user_config.items():
                if key in globals():
                    globals()[key] = value
        print(f"Loaded user configuration from {USER_CONFIG_PATH}")
    except Exception as e:
        print(f"Error loading user configuration: {e}")

# --- Validation ---
def validate_configuration():
    """Validate critical configuration settings."""
    errors = []
    warnings = []
    
    # Check API keys
    if not PICOVOICE_ACCESS_KEY:
        errors.append("PICOVOICE_ACCESS_KEY not set in environment variables.")
    if not OPENAI_API_KEY and not LLM_OFFLINE_FALLBACK_ENABLED:
        errors.append("OPENAI_API_KEY not set and offline fallback disabled.")
    if TTS_ENGINE == 'elevenlabs' and not ELEVENLABS_API_KEY:
        errors.append("ELEVENLABS_API_KEY not set for selected TTS engine.")
    
    # Check model paths
    if not os.path.exists(VOSK_MODEL_PATH):
        errors.append(f"VOSK_MODEL_PATH does not exist: {VOSK_MODEL_PATH}")
    for path in PORCUPINE_KEYWORD_PATHS:
        if not os.path.exists(path):
            errors.append(f"PORCUPINE_KEYWORD_PATH does not exist: {path}")
    if TTS_ENGINE == 'piper' and not os.path.exists(PIPER_MODEL_PATH):
        errors.append(f"PIPER_MODEL_PATH does not exist: {PIPER_MODEL_PATH}")
    
    # Print errors and warnings
    for error in errors:
        print(f"CONFIG ERROR: {error}")
    for warning in warnings:
        print(f"CONFIG WARNING: {warning}")
    
    return len(errors) == 0

# Run validation
VALID_CONFIG = validate_configuration()

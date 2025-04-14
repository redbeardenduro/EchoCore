# config.py
"""
Configuration settings for Project EchoCore.
Loads settings from environment variables (.env file) and a user configuration file (user_config.json).
"""

import os
import logging
import json
from pathlib import Path
from dotenv import load_dotenv
import sys

# --- Determine Root Directory ---
# Use Path(__file__).parent for reliable path relative to this file
ROOT_DIR = Path(__file__).parent.absolute()

# --- Load Environment Variables ---
# Load from .env file located in the root directory
dotenv_path = ROOT_DIR / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
    print(f"Loaded environment variables from {dotenv_path}")
else:
    print(f"Warning: .env file not found at {dotenv_path}. API keys might be missing.")

# --- Default Configuration Values ---
# These values will be used if not overridden by environment variables or user_config.json
DEFAULT_CONFIG = {
    # --- Paths ---
    "MODELS_DIR": ROOT_DIR / "models",
    "LOGS_DIR": ROOT_DIR / "logs",
    "CACHE_DIR": ROOT_DIR / "cache",
    "STATIC_DIR": ROOT_DIR / "static", # For web interface
    "TEMPLATES_DIR": ROOT_DIR / "templates", # For web interface
    "USER_CONFIG_PATH": ROOT_DIR / "user_config.json",

    # --- Logging Configuration ---
    "LOG_LEVEL": "INFO",  # Logging level (e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL)
    "LOG_FILE": "echocore.log", # Filename within LOGS_DIR
    "LOG_FORMAT": '%(asctime)s - %(levelname)s - %(threadName)s - %(name)s - %(message)s', # Added module name
    "LOG_MAX_SIZE": 10 * 1024 * 1024,  # 10 MB
    "LOG_BACKUP_COUNT": 3,  # Keep 3 backup files

    # --- System Settings ---
    "HEALTH_CHECK_INTERVAL": 30,  # Seconds between system health checks
    "RECOVERY_ATTEMPTS": 3,  # Number of times to attempt recovery before giving up
    "STANDBY_TIMEOUT": 300,  # Seconds of inactivity before entering standby mode (if enabled)
    "ENABLE_STANDBY_MODE": False,  # Whether to use reduced CPU when idle

    # --- Security Settings ---
    "USE_SECURE_STORAGE": False,  # Future: Use system keyring instead of .env file
    "API_RATE_LIMITING": True,  # Future: Enable rate limiting for API calls
    "MAX_API_CALLS_PER_MINUTE": 10,  # Future: Maximum API calls per minute

    # --- API Keys (Loaded primarily from .env) ---
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
    "ELEVENLABS_API_KEY": os.getenv("ELEVENLABS_API_KEY"),
    "PICOVOICE_ACCESS_KEY": os.getenv("PICOVOICE_ACCESS_KEY"),

    # --- Audio Settings ---
    "AUDIO_INPUT_DEVICE_INDEX": None,  # None for default input device
    "AUDIO_OUTPUT_DEVICE_INDEX": None,  # None for default output device
    "AUDIO_SAMPLE_RATE": 16000,  # Sample rate expected by Vosk/Porcupine (Hz)
    "AUDIO_CHUNK_SIZE": 1024,  # Size of audio chunks for processing
    "AUDIO_INPUT_CHANNELS": 1,
    "AUDIO_OUTPUT_CHANNELS": 1,
    "AUDIO_DTYPE": 'int16',  # Data type for audio samples
    "AUDIO_OUTPUT_LATENCY": 'low',  # Latency setting ['low', 'high', float seconds]
    "AUDIO_AMPLITUDE_SCALING_DIVISOR": 1024.0, # Use float for potentially better scaling

    # --- Audio Feedback Settings ---
    "ENABLE_AUDIO_CUES": True,  # Whether to play audio cues for state changes
    "AUDIO_CUE_VOLUME": 0.3,  # Volume for audio cues (0.0 to 1.0)

    # --- Wake Word Settings (Porcupine) ---
    "PORCUPINE_MODEL_PATH": None,  # Path to the Porcupine model file (.pv)
    "PORCUPINE_KEYWORD_PATHS": [], # List of paths to keyword files (.ppn)
    "PORCUPINE_SENSITIVITIES": [0.5],  # Sensitivity for each keyword (0.0 to 1.0)
    "LISTENING_TIMEOUT": 10.0,  # Seconds to listen before timing out

    # --- STT Settings (Vosk) ---
    "VOSK_MODEL_PATH": "models/vosk/vosk-model-small-en-us-0.15",  # Default path relative to MODELS_DIR
    "VOSK_LOG_LEVEL": -1,  # Disable Vosk logging
    "VOSK_TIMEOUT_SECONDS": 10.0,  # Seconds to wait before timing out speech recognition
    "STT_CONFIDENCE_THRESHOLD": 0.7,  # Minimum confidence for accepting transcription

    # --- LLM Settings (OpenAI) ---
    "LLM_MODEL": "gpt-4o-mini",  # e.g., "gpt-4o", "gpt-4o-mini"
    "LLM_TIMEOUT": 30.0,  # Timeout for API calls in seconds (use float)
    "LLM_MAX_CONVERSATION_TURNS": 10,  # Max user/assistant pairs in history
    "LLM_TEMPERATURE": 0.7,  # Controls randomness (0.0 to 1.0)
    "LLM_MAX_TOKENS": 150,  # Maximum tokens in response
    "LLM_SYSTEM_PROMPT": """You are Echo, a helpful voice assistant. Keep your responses concise and conversational. You're running on a Raspberry Pi 5 as part of Project EchoCore.""",
    "LLM_OFFLINE_FALLBACK_ENABLED": True,  # Enable basic offline response
    "LLM_OFFLINE_RESPONSE": "I cannot connect to the internet right now.",
    "LLM_LOCAL_MODEL_PATH": None,  # Path to a local LLM model (future use)
    "LLM_PREFER_LOCAL": False,  # Future: If True, try local LLM first

    # --- TTS Settings ---
    "TTS_ENGINE": "openai",  # 'openai', 'elevenlabs', or 'piper'
    "TTS_STREAMING": True,  # Stream partial TTS results
    "TTS_CACHE_ENABLED": True,  # Cache TTS responses
    "TTS_CACHE_SIZE": 100,  # Maximum number of responses to cache
    "TTS_RESPONSE_CHUNK_SIZE": 50, # Max text length for streaming (not directly used by all)

    # OpenAI TTS Settings
    "OPENAI_TTS_MODEL": "tts-1",  # e.g., "tts-1", "tts-1-hd"
    "OPENAI_TTS_VOICE": "alloy",  # 'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'
    "OPENAI_TTS_FORMAT": "pcm",  # Recommended format: pcm, mp3, opus, aac, flac

    # ElevenLabs TTS Settings
    "ELEVENLABS_VOICE": "Rachel",  # Example voice name or ID
    "ELEVENLABS_MODEL": "eleven_multilingual_v2",
    "ELEVENLABS_STABILITY": 0.5,
    "ELEVENLABS_SIMILARITY": 0.75,
    "ELEVENLABS_OUTPUT_FORMAT": "pcm_16000", # Ensure compatibility

    # Piper TTS Settings (Local/Offline)
    "PIPER_MODEL_PATH": "models/piper/en_US-lessac-medium.onnx", # Default path relative to MODELS_DIR
    "PIPER_CONFIG_PATH": None,  # Optional: Path relative to MODELS_DIR, derived if None
    "PIPER_SPEAKER_ID": 0,
    "PIPER_NOISE_SCALE": 0.667,
    "PIPER_LENGTH_SCALE": 1.0,

    # --- Avatar Settings (Pygame) ---
    "AVATAR_WINDOW_WIDTH": 800,
    "AVATAR_WINDOW_HEIGHT": 480,
    "AVATAR_BACKGROUND_COLOR": [0, 0, 0], # Use list for JSON compatibility
    "AVATAR_IDLE_COLOR": [0, 100, 255],
    "AVATAR_LISTENING_COLOR": [255, 255, 0],
    "AVATAR_THINKING_COLOR": [255, 165, 0],
    "AVATAR_SPEAKING_COLOR": [0, 255, 0],
    "AVATAR_ERROR_COLOR": [255, 0, 0],
    "AVATAR_MIN_RADIUS": 20,
    "AVATAR_MAX_RADIUS_FACTOR": 5.0, # Use float
    "AVATAR_FPS": 30,
    "AVATAR_ANIMATION_STYLE": "wave", # "circle", "wave", "particle", "hologram"
    "AVATAR_DISPLAY_STATUS_TEXT": True,
    "AVATAR_FULLSCREEN": False,
    "AVATAR_DEBUG_OVERLAY": False,

    # --- Web Interface Settings ---
    "WEB_INTERFACE_ENABLED": False,
    "WEB_INTERFACE_PORT": 8080,
    "WEB_INTERFACE_HOST": "0.0.0.0",
    "WEB_INTERFACE_USERNAME": "admin",
    "WEB_INTERFACE_PASSWORD": "echocore",
}

# --- Configuration Loading Function ---
def load_config():
    """Loads configuration from defaults, user file, and environment variables."""
    config = DEFAULT_CONFIG.copy()

    # 1. Load from user_config.json
    user_config_path = config["USER_CONFIG_PATH"]
    if user_config_path.exists():
        try:
            with open(user_config_path, 'r') as f:
                user_config = json.load(f)
                # Update config, handling potential type mismatches carefully if necessary
                for key, value in user_config.items():
                    if key in config:
                        # Basic type check/conversion (can be expanded)
                        default_type = type(config[key])
                        if default_type == list and isinstance(value, list):
                            config[key] = value
                        elif default_type == int and isinstance(value, (int, float)):
                             config[key] = int(value)
                        elif default_type == float and isinstance(value, (int, float)):
                             config[key] = float(value)
                        elif default_type == bool and isinstance(value, bool):
                             config[key] = value
                        elif default_type == str and isinstance(value, str):
                             config[key] = value
                        elif config[key] is None: # Allow setting None values
                             config[key] = value
                        elif default_type == Path: # Handle Path objects specially
                            config[key] = Path(value) # Assume user provides string path
                        else:
                             # Only override if type matches or target is None
                             if isinstance(value, default_type) or config[key] is None:
                                 config[key] = value
                             else:
                                 print(f"Warning: Type mismatch for '{key}' in user_config.json. Expected {default_type}, got {type(value)}. Ignoring.")
                    else:
                        # Allow adding new keys from user config, but warn
                        print(f"Warning: Unknown key '{key}' found in user_config.json.")
                        config[key] = value

            print(f"Loaded user configuration from {user_config_path}")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {user_config_path}: {e}. Using defaults.")
        except Exception as e:
            print(f"Error loading user configuration from {user_config_path}: {e}. Using defaults.")

    # 2. Override with Environment Variables (if set)
    # Example: Allow overriding LLM_MODEL via environment
    env_llm_model = os.getenv("ECHOCURE_LLM_MODEL")
    if env_llm_model:
        config["LLM_MODEL"] = env_llm_model
        print(f"Overriding LLM_MODEL with environment variable: {env_llm_model}")

    # Add more environment variable overrides here if needed

    # --- Resolve Paths ---
    # Ensure paths are absolute based on ROOT_DIR
    config["LOGS_DIR"] = ROOT_DIR / config["LOGS_DIR"]
    config["CACHE_DIR"] = ROOT_DIR / config["CACHE_DIR"]
    config["MODELS_DIR"] = ROOT_DIR / config["MODELS_DIR"]
    config["STATIC_DIR"] = ROOT_DIR / config["STATIC_DIR"]
    config["TEMPLATES_DIR"] = ROOT_DIR / config["TEMPLATES_DIR"]

    # Resolve model paths relative to MODELS_DIR if they are not absolute
    for key in ["VOSK_MODEL_PATH", "PIPER_MODEL_PATH", "PORCUPINE_MODEL_PATH"]:
         path_val = config.get(key)
         if path_val and isinstance(path_val, str) and not os.path.isabs(path_val):
             config[key] = config["MODELS_DIR"] / path_val
         elif path_val and isinstance(path_val, Path) and not path_val.is_absolute():
              config[key] = config["MODELS_DIR"] / path_val


    # Resolve Porcupine keyword paths relative to MODELS_DIR
    if isinstance(config.get("PORCUPINE_KEYWORD_PATHS"), list):
        resolved_keyword_paths = []
        for path_str in config["PORCUPINE_KEYWORD_PATHS"]:
            if path_str and not os.path.isabs(path_str):
                 resolved_keyword_paths.append(str(config["MODELS_DIR"] / path_str)) # Keep as strings for pvporcupine
            else:
                 resolved_keyword_paths.append(path_str)
        config["PORCUPINE_KEYWORD_PATHS"] = resolved_keyword_paths


    # Resolve Piper config path relative to MODELS_DIR
    piper_cfg = config.get("PIPER_CONFIG_PATH")
    if piper_cfg and isinstance(piper_cfg, str) and not os.path.isabs(piper_cfg):
         config["PIPER_CONFIG_PATH"] = config["MODELS_DIR"] / piper_cfg
    elif piper_cfg and isinstance(piper_cfg, Path) and not piper_cfg.is_absolute():
        config["PIPER_CONFIG_PATH"] = config["MODELS_DIR"] / piper_cfg

    # --- Create Directories ---
    # Ensure essential directories exist
    for dir_key in ["LOGS_DIR", "CACHE_DIR", "MODELS_DIR", "STATIC_DIR", "TEMPLATES_DIR"]:
        dir_path = config[dir_key]
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as e:
            print(f"Error creating directory {dir_path}: {e}. Exiting.")
            sys.exit(1) # Exit if essential dirs can't be created

    # --- Final Calculations/Formatting ---
    config["LOG_FILE_PATH"] = config["LOGS_DIR"] / config["LOG_FILE"] # Full log file path

    # Convert LOG_LEVEL string to logging constant
    log_level_str = config["LOG_LEVEL"].upper()
    if hasattr(logging, log_level_str):
         config["LOG_LEVEL"] = getattr(logging, log_level_str)
    else:
         print(f"Warning: Invalid LOG_LEVEL '{config['LOG_LEVEL']}'. Defaulting to INFO.")
         config["LOG_LEVEL"] = logging.INFO


    return config

# --- Load Configuration ---
# Load the configuration once when the module is imported
_CONFIG = load_config()

# --- Validation Function ---
def validate_configuration(cfg):
    """Validate critical configuration settings."""
    errors = []
    warnings = []

    # Check API keys based on usage
    if not cfg["PICOVOICE_ACCESS_KEY"]:
        errors.append("PICOVOICE_ACCESS_KEY not set (required for wake word). Check .env file.")
    if cfg["LLM_MODEL"] != 'offline' and not cfg["LLM_OFFLINE_FALLBACK_ENABLED"] and not cfg["OPENAI_API_KEY"]:
         errors.append("OPENAI_API_KEY not set (required for OpenAI LLM unless offline fallback is enabled). Check .env file.")
    if cfg["TTS_ENGINE"] == 'openai' and not cfg["OPENAI_API_KEY"]:
        errors.append("OPENAI_API_KEY not set (required for OpenAI TTS). Check .env file.")
    if cfg["TTS_ENGINE"] == 'elevenlabs' and not cfg["ELEVENLABS_API_KEY"]:
        errors.append("ELEVENLABS_API_KEY not set (required for ElevenLabs TTS). Check .env file.")

    # Check model paths exist
    if not cfg["VOSK_MODEL_PATH"] or not Path(cfg["VOSK_MODEL_PATH"]).exists():
        errors.append(f"VOSK_MODEL_PATH does not exist or is not set: {cfg['VOSK_MODEL_PATH']}")
    if not cfg["PORCUPINE_KEYWORD_PATHS"]:
         warnings.append("PORCUPINE_KEYWORD_PATHS is empty. Wake word detection will not work.")
    else:
         for path in cfg["PORCUPINE_KEYWORD_PATHS"]:
             if not path or not Path(path).exists():
                 errors.append(f"PORCUPINE_KEYWORD_PATH does not exist: {path}")

    # Check optional model paths only if the engine is selected
    if cfg["TTS_ENGINE"] == 'piper':
         if not cfg["PIPER_MODEL_PATH"] or not Path(cfg["PIPER_MODEL_PATH"]).exists():
             errors.append(f"PIPER_MODEL_PATH does not exist or is not set (required for Piper TTS): {cfg['PIPER_MODEL_PATH']}")
         # Config path is optional for Piper, but check if set
         if cfg["PIPER_CONFIG_PATH"] and not Path(cfg["PIPER_CONFIG_PATH"]).exists():
             warnings.append(f"PIPER_CONFIG_PATH is set but does not exist: {cfg['PIPER_CONFIG_PATH']}")

    # Check Porcupine model path if set
    if cfg["PORCUPINE_MODEL_PATH"] and not Path(cfg["PORCUPINE_MODEL_PATH"]).exists():
        warnings.append(f"PORCUPINE_MODEL_PATH is set but does not exist: {cfg['PORCUPINE_MODEL_PATH']}")

    # Check sensitivities list matches keywords list length
    if len(cfg["PORCUPINE_KEYWORD_PATHS"]) != len(cfg["PORCUPINE_SENSITIVITIES"]):
         errors.append("Number of PORCUPINE_KEYWORD_PATHS does not match number of PORCUPINE_SENSITIVITIES.")

    # Check audio device indices (if not None)
    # This requires sounddevice, validation might be better placed in audio_utils or main setup
    # For now, just ensure they are int or None
    if cfg["AUDIO_INPUT_DEVICE_INDEX"] is not None and not isinstance(cfg["AUDIO_INPUT_DEVICE_INDEX"], int):
         errors.append(f"AUDIO_INPUT_DEVICE_INDEX must be an integer or None, got: {cfg['AUDIO_INPUT_DEVICE_INDEX']}")
    if cfg["AUDIO_OUTPUT_DEVICE_INDEX"] is not None and not isinstance(cfg["AUDIO_OUTPUT_DEVICE_INDEX"], int):
         errors.append(f"AUDIO_OUTPUT_DEVICE_INDEX must be an integer or None, got: {cfg['AUDIO_OUTPUT_DEVICE_INDEX']}")


    # --- Print Errors/Warnings ---
    if errors:
        print("\n--- CONFIGURATION ERRORS ---", file=sys.stderr)
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        print("----------------------------\n", file=sys.stderr)
    if warnings:
        print("\n--- CONFIGURATION WARNINGS ---")
        for warning in warnings:
            print(f"[WARNING] {warning}")
        print("------------------------------\n")

    return len(errors) == 0

# --- Validate Loaded Configuration ---
IS_CONFIG_VALID = validate_configuration(_CONFIG)

# --- Expose Configuration ---
# Make loaded config directly accessible
# e.g., from other_module import config; print(config.LLM_MODEL)
def __getattr__(name):
    if name in _CONFIG:
        return _CONFIG[name]
    raise AttributeError(f"'config' module has no attribute '{name}'")

# Optionally, provide a function to get the config dict
def get_config_dict():
    return _CONFIG.copy()

# --- Main block for testing/printing config ---
if __name__ == "__main__":
    print("--- Project EchoCore Configuration ---")
    # Use the get_config_dict() function to get the loaded config
    loaded_config = get_config_dict()
    for key, value in loaded_config.items():
        # Format Path objects nicely for printing
        if isinstance(value, Path):
             print(f"{key}: {value}")
        else:
             print(f"{key}: {value!r}") # Use !r for repr() to show quotes for strings etc.

    print("\n--- Configuration Validation ---")
    if IS_CONFIG_VALID:
        print("Configuration appears valid.")
    else:
        print("Configuration has errors. Please check the messages above.", file=sys.stderr)

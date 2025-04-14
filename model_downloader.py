# model_downloader.py
"""
Utility script for downloading and setting up required machine learning models
for Project EchoCore (Vosk, Piper).

Provides functions to check for existing models, download missing ones from
predefined URLs, and extract archives. Porcupine models require manual download.
"""

import os
import sys
import zipfile
import tarfile
import json
import logging
import time
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, cast # For type hinting

# Attempt to import dependencies
try:
    import requests
    from tqdm import tqdm
except ImportError as e:
    # Log critical error if dependencies are missing
    logging.basicConfig(level=logging.ERROR, format='%(levelname)s: %(message)s')
    logging.critical(f"Required libraries missing: {e}. Please install them: pip install requests tqdm")
    # Set flags or exit if these are absolutely required for the module to load safely elsewhere
    requests = None # type: ignore
    tqdm = None # type: ignore
    # sys.exit(1) # Exit if script cannot run without these


# Import project config - relies on the enhanced config structure
try:
    import config # Assuming config object provides necessary paths/settings
except ImportError:
    logging.error("Configuration module (config.py) not found. Model paths may be incorrect.")
    # Use dummy paths if config fails, but downloads likely won't work correctly
    class MockConfig:
         ROOT_DIR = Path(".")
         MODELS_DIR = Path("./models")
         VOSK_MODEL_PATH = MODELS_DIR / "vosk/vosk-model-small-en-us-0.15"
         PIPER_MODEL_PATH = MODELS_DIR / "piper/en_US-lessac-medium.onnx"
         PORCUPINE_KEYWORD_PATHS = []
         TTS_ENGINE = "openai" # Default assumption
    config = MockConfig() # type: ignore


# Setup logger
# Configure logger here if run as standalone script, or rely on main app config
# For standalone use:
if __name__ == "__main__":
     logging.basicConfig(
         level=logging.INFO, # Or DEBUG for more verbosity
         format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
     )
logger = logging.getLogger(__name__)


# --- Model Definitions ---
# Structure: {'type': {'id': {details...}}}
DEFAULT_MODELS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "vosk": {
        "vosk-model-small-en-us-0.15": { # ID should match the directory name after extraction
            "name": "Vosk Small English (US) Model v0.15",
            "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
            "size_mb": 40,
            "archive_format": "zip",
            "extracted_path": config.MODELS_DIR / "vosk" / "vosk-model-small-en-us-0.15", # Final expected dir
            "download_dir": config.MODELS_DIR / "vosk", # Where to download/extract
        },
        "vosk-model-en-us-0.22": { # Example for a larger model
            "name": "Vosk English (US) Model v0.22",
            "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip",
            "size_mb": 1800,
            "archive_format": "zip",
            "extracted_path": config.MODELS_DIR / "vosk" / "vosk-model-en-us-0.22",
            "download_dir": config.MODELS_DIR / "vosk",
        },
        # Add other Vosk models here if needed
    },
    "piper": {
        "en_US-lessac-medium": { # ID based on model name
            "name": "Piper English US (Female, Lessac Medium)",
            "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
            "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
            "size_mb": 50,
            "archive_format": None, # Direct download
            "model_path": config.MODELS_DIR / "piper" / "en_US-lessac-medium.onnx",
            "config_path": config.MODELS_DIR / "piper" / "en_US-lessac-medium.onnx.json",
            "download_dir": config.MODELS_DIR / "piper",
        },
        "en_GB-southern_english_male-medium": { # Example UK voice
            "name": "Piper English UK (Male, Southern Medium)",
            "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/southern_english_male/medium/en_GB-southern_english_male-medium.onnx",
            "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/southern_english_male/medium/en_GB-southern_english_male-medium.onnx.json",
            "size_mb": 50,
            "archive_format": None,
            "model_path": config.MODELS_DIR / "piper" / "en_GB-southern_english_male-medium.onnx",
            "config_path": config.MODELS_DIR / "piper" / "en_GB-southern_english_male-medium.onnx.json",
            "download_dir": config.MODELS_DIR / "piper",
        }
        # Add other Piper voices here
    }
}

def _get_model_info_from_path(model_type: str, model_path: Path) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Try to find the matching model info in DEFAULT_MODELS based on the expected path."""
    if model_type not in DEFAULT_MODELS:
        return None
    for model_id, info in DEFAULT_MODELS[model_type].items():
        expected_path = info.get("extracted_path") or info.get("model_path")
        if expected_path and Path(expected_path) == Path(model_path):
            return model_id, info
    return None


def check_model_exists(model_type: str, model_path: Path) -> bool:
    """Check if the specific model exists at the expected path."""
    if model_type == "vosk":
        # Vosk model path should be a directory containing specific files
        return model_path.is_dir() and (model_path / "am").exists() and (model_path / "conf").exists()
    elif model_type == "piper":
        # Piper model path should be the .onnx file
        config_path = model_path.with_suffix(".onnx.json")
        return model_path.is_file() and config_path.is_file() # Check both model and config exist
    else:
        logger.warning(f"Existence check not implemented for model type: {model_type}")
        return False # Assume not exists if type is unknown

def download_file_with_progress(url: str, destination: Path, desc: Optional[str] = None) -> bool:
    """
    Downloads a file from a URL to a destination path with a progress bar.

    Args:
        url: The URL to download from.
        destination: The local Path object where the file should be saved.
        desc: Optional description for the progress bar.

    Returns:
        True if the download was successful, False otherwise.
    """
    if requests is None or tqdm is None:
         logger.error("Cannot download: 'requests' or 'tqdm' library not available.")
         return False

    desc = desc or destination.name # Use filename if no description provided
    logger.info(f"Downloading '{desc}' from {url} to {destination}")
    try:
        # Ensure destination directory exists
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Use streaming request
        response = requests.get(url, stream=True, timeout=60) # Increased timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        # Get file size for progress bar (content-length might be missing)
        total_size = int(response.headers.get('content-length', 0))

        # Write to temporary file first, then rename for atomicity
        temp_destination = destination.with_suffix(destination.suffix + ".part")

        with open(temp_destination, 'wb') as file, tqdm(
            desc=desc,
            total=total_size,
            unit='B',
            unit_scale=True,
            unit_divisor=1024,
            disable=not sys.stdout.isatty() # Disable progress bar if not in TTY
        ) as bar:
            for data in response.iter_content(chunk_size=8192): # Larger chunk size
                file.write(data)
                bar.update(len(data))

        # Verify final size if content-length was available
        if total_size != 0 and temp_destination.stat().st_size != total_size:
            logger.error(f"Download size mismatch for {destination.name}. Expected {total_size}, got {temp_destination.stat().st_size}")
            temp_destination.unlink(missing_ok=True) # Clean up partial file
            return False

        # Rename temporary file to final destination
        os.replace(temp_destination, destination) # Atomic replace
        logger.info(f"Successfully downloaded {destination.name}")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Download failed for {url}: {e}")
        # Clean up partial file if it exists
        if 'temp_destination' in locals() and temp_destination.exists():
            temp_destination.unlink(missing_ok=True)
        return False
    except IOError as e:
        logger.error(f"File write error for {destination}: {e}")
        if 'temp_destination' in locals() and temp_destination.exists():
            temp_destination.unlink(missing_ok=True)
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred during download of {url}: {e}")
        if 'temp_destination' in locals() and temp_destination.exists():
            temp_destination.unlink(missing_ok=True)
        return False


def extract_archive(archive_path: Path, extract_dir: Path, archive_format: Optional[str] = None) -> bool:
    """
    Extracts a zip or tar archive to a specified directory.

    Args:
        archive_path: Path object of the archive file.
        extract_dir: Path object of the directory to extract into.
        archive_format: Explicit format ('zip', 'tar.gz', 'tgz'). Auto-detects if None.

    Returns:
        True on successful extraction and cleanup, False otherwise.
    """
    if not archive_path.is_file():
        logger.error(f"Archive file not found: {archive_path}")
        return False

    if archive_format is None:
        # Auto-detect format
        if archive_path.suffix == '.zip':
            archive_format = 'zip'
        elif '.tar.gz' in archive_path.name or archive_path.suffix == '.tgz':
            archive_format = 'tar.gz'
        else:
            logger.error(f"Cannot determine archive format for: {archive_path.name}")
            return False

    logger.info(f"Extracting {archive_path.name} (Format: {archive_format}) to {extract_dir}...")
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        if archive_format == 'zip':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        elif archive_format == 'tar.gz':
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(extract_dir)
        else:
            logger.error(f"Unsupported archive format specified: {archive_format}")
            return False

        logger.info(f"Successfully extracted {archive_path.name}")

        # Clean up the archive file after successful extraction
        try:
            archive_path.unlink()
            logger.debug(f"Removed archive file: {archive_path}")
        except OSError as e:
            logger.warning(f"Could not remove archive file {archive_path}: {e}")

        return True

    except (zipfile.BadZipFile, tarfile.TarError) as e:
        logger.error(f"Error extracting archive {archive_path.name}: {e}")
        return False
    except Exception as e:
        logger.exception(f"An unexpected error occurred during extraction of {archive_path.name}: {e}")
        return False


def download_and_setup_model(model_type: str, model_id: str) -> bool:
    """
    Downloads and sets up a specific model defined in DEFAULT_MODELS.

    Handles direct downloads and archive extraction based on model info.

    Args:
        model_type: The type of model ('vosk', 'piper').
        model_id: The specific ID of the model within DEFAULT_MODELS.

    Returns:
        True on success, False on failure.
    """
    if model_type not in DEFAULT_MODELS or model_id not in DEFAULT_MODELS[model_type]:
        logger.error(f"Unknown model requested: Type='{model_type}', ID='{model_id}'")
        return False

    model_info = DEFAULT_MODELS[model_type][model_id]
    model_name = model_info.get("name", model_id)
    download_dir = Path(model_info["download_dir"])
    download_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"--- Setting up model: {model_name} ---")

    # --- Handle Direct Downloads (like Piper .onnx/.json) ---
    if model_info["archive_format"] is None:
        model_path = Path(model_info["model_path"])
        config_path = Path(model_info["config_path"]) if model_info.get("config_path") else None
        config_url = model_info.get("config_url")

        # Download model file
        model_success = download_file_with_progress(model_info["url"], model_path, f"{model_name} (Model)")
        if not model_success: return False # Stop if model download fails

        # Download config file if URL is provided
        config_success = True # Assume success if no config needed
        if config_path and config_url:
            config_success = download_file_with_progress(config_url, config_path, f"{model_name} (Config)")
            if not config_success:
                 logger.warning(f"Model file downloaded, but failed to download config file for {model_name}.")
                 # Decide whether to return False or True based on whether config is critical
                 return False # Treat config failure as overall failure for Piper


        return model_success and config_success

    # --- Handle Archive Downloads (like Vosk .zip) ---
    else:
        archive_url = model_info["url"]
        archive_format = model_info["archive_format"]
        # Use a temporary name for the downloaded archive
        archive_filename = f"{model_id}.{archive_format}" if archive_format != 'tar.gz' else f"{model_id}.tar.gz"
        temp_archive_path = download_dir / archive_filename

        # Download the archive
        download_success = download_file_with_progress(archive_url, temp_archive_path, f"{model_name} (Archive)")
        if not download_success:
            return False # Stop if archive download fails

        # Extract the archive
        extract_success = extract_archive(temp_archive_path, download_dir, archive_format)
        # No need to remove archive here, extract_archive does it on success

        # Verify final extracted path exists (optional but good)
        final_path = Path(model_info["extracted_path"])
        if extract_success and not check_model_exists(model_type, final_path):
             logger.error(f"Extraction reported success, but final model path {final_path} seems invalid or missing.")
             return False

        return extract_success


def check_and_download_models(interactive: bool = True) -> bool:
    """
    Checks required models based on config and prompts to download missing ones.

    Args:
        interactive: If True, prompt user before downloading. If False, only check/log.

    Returns:
        True if all required models are present or downloaded successfully, False otherwise.
    """
    logger.info("--- Checking Required Models ---")
    missing_models: List[Tuple[str, str, str]] = [] # (type, id, name)

    # 1. Check Vosk Model specified in config
    vosk_path = Path(config.VOSK_MODEL_PATH)
    if not check_model_exists("vosk", vosk_path):
        logger.warning(f"Required Vosk model not found at: {vosk_path}")
        # Try to find which default model this path corresponds to
        model_match = _get_model_info_from_path("vosk", vosk_path)
        if model_match:
            model_id, model_info = model_match
            missing_models.append(("vosk", model_id, model_info["name"]))
            logger.info(f"(Identified as: {model_info['name']})")
        else:
            logger.error(f"Path {vosk_path} does not match any known Vosk model definition in this script.")
            # Cannot offer download if definition is unknown

    # 2. Check Piper Model specified in config (only if TTS_ENGINE is piper)
    if config.TTS_ENGINE == "piper":
        piper_path = Path(config.PIPER_MODEL_PATH)
        if not check_model_exists("piper", piper_path):
            logger.warning(f"Required Piper model not found at: {piper_path}")
            model_match = _get_model_info_from_path("piper", piper_path)
            if model_match:
                model_id, model_info = model_match
                missing_models.append(("piper", model_id, model_info["name"]))
                logger.info(f"(Identified as: {model_info['name']})")
            else:
                logger.error(f"Path {piper_path} does not match any known Piper model definition.")

    # 3. Check Porcupine Models (Manual Download)
    logger.info("--- Checking Porcupine Models ---")
    porcupine_ok = True
    if not config.PORCUPINE_KEYWORD_PATHS:
        logger.warning("No Porcupine keyword paths configured.")
        porcupine_ok = False
    else:
        for path_str in config.PORCUPINE_KEYWORD_PATHS:
            path = Path(path_str)
            if not path.exists():
                logger.warning(f"Porcupine keyword file not found: {path}")
                porcupine_ok = False
            else:
                 logger.info(f"Found Porcupine keyword file: {path}")

    if not porcupine_ok:
         logger.warning("One or more Porcupine keyword files are missing.")
         logger.warning("Porcupine models must be downloaded manually from the Picovoice Console:")
         logger.warning("https://console.picovoice.ai/")
         # Porcupine missing doesn't prevent *other* downloads, but note it

    # --- Handle Missing Downloadable Models ---
    if not missing_models:
        logger.info("All required downloadable models (Vosk/Piper based on config) are present.")
        return porcupine_ok # Return True only if Porcupine is also okay

    logger.warning("The following downloadable models are missing:")
    for i, (_, _, model_name) in enumerate(missing_models, 1):
        logger.warning(f"{i}. {model_name}")

    if not interactive:
        logger.warning("Non-interactive mode: Not attempting download.")
        return False # Missing models, didn't download

    # --- Interactive Download Prompt ---
    try:
         # Use input() which works in most environments
         print("\nDo you want to attempt to download the missing models? (y/n)")
         choice = input("> ").strip().lower()
         if choice not in ['y', 'yes']:
             logger.warning("Download cancelled by user.")
             return False
    except EOFError: # Handle non-interactive environments where input() fails
         logger.warning("Cannot get user input (non-interactive environment?). Skipping download.")
         return False


    # --- Perform Downloads ---
    logger.info("--- Starting Model Downloads ---")
    all_downloads_successful = True
    for model_type, model_id, model_name in missing_models:
        if not download_and_setup_model(model_type, model_id):
            logger.error(f"Failed to download and set up: {model_name}")
            all_downloads_successful = False
            # Decide whether to continue trying other models or stop on first failure
            # break # Option: Stop on first failure

    if all_downloads_successful:
        logger.info("All missing models downloaded successfully.")
    else:
        logger.error("One or more models failed to download or set up.")

    # Final result depends on downloads and Porcupine status
    return all_downloads_successful and porcupine_ok


# --- Main execution block ---
if __name__ == "__main__":
    print("Running Project EchoCore Model Downloader Utility...")
    # Run the check and download process interactively
    check_and_download_models(interactive=True)
    print("Model downloader finished.")

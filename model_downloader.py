# model_downloader.py
"""
Utility module for downloading and extracting models for Vosk, Piper, and Porcupine.
Provides a simple interface for checking, downloading, and setting up required models.
"""
import os
import sys
import requests
import zipfile
import tarfile
import json
import logging
import time
import shutil
from pathlib import Path
from tqdm import tqdm
import config

# Setup logger
logger = logging.getLogger(__name__)

# Model URLs and information
DEFAULT_MODELS = {
    "vosk": {
        "small_en": {
            "name": "Small English Model",
            "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
            "size_mb": 40,
            "path": "models/vosk/vosk-model-small-en-us-0.15",
            "extract_dir": "models/vosk"
        },
        "tiny_en": {
            "name": "Tiny English Model",
            "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
            "size_mb": 15,
            "path": "models/vosk/vosk-model-tiny-en-us-0.15",
            "extract_dir": "models/vosk"
        }
    },
    "piper": {
        "en_US": {
            "name": "English US (Female)",
            "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
            "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
            "size_mb": 50,
            "path": "models/piper/en_US-lessac-medium.onnx",
            "config_path": "models/piper/en_US-lessac-medium.onnx.json",
            "extract_dir": None  # No extraction needed
        },
        "en_UK": {
            "name": "English UK (Male)",
            "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/southern_english_male/medium/en_GB-southern_english_male-medium.onnx",
            "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/southern_english_male/medium/en_GB-southern_english_male-medium.onnx.json",
            "size_mb": 50,
            "path": "models/piper/en_GB-southern_english_male-medium.onnx",
            "config_path": "models/piper/en_GB-southern_english_male-medium.onnx.json",
            "extract_dir": None  # No extraction needed
        }
    }
}

def check_model(model_type, model_id=None):
    """
    Check if a specific model is installed.
    
    Args:
        model_type: "vosk", "piper", or "porcupine"
        model_id: Specific model ID (e.g., "small_en" for Vosk)
        
    Returns:
        True if model is installed, False otherwise
    """
    # For Porcupine, just check if the configured paths exist
    if model_type == "porcupine":
        if not config.PORCUPINE_KEYWORD_PATHS:
            return False
        
        for path in config.PORCUPINE_KEYWORD_PATHS:
            if not os.path.exists(path):
                return False
        
        return True
    
    # For Vosk and Piper, check the specified model
    if model_type not in DEFAULT_MODELS:
        logger.error(f"Unknown model type: {model_type}")
        return False
    
    # If no specific model ID is provided, check the one in config
    if model_id is None:
        if model_type == "vosk":
            # Check the configured Vosk model
            return os.path.exists(config.VOSK_MODEL_PATH)
        elif model_type == "piper":
            # Check the configured Piper model
            return os.path.exists(config.PIPER_MODEL_PATH)
    
    # Check specific model by ID
    if model_id not in DEFAULT_MODELS[model_type]:
        logger.error(f"Unknown model ID: {model_id} for {model_type}")
        return False
    
    model_info = DEFAULT_MODELS[model_type][model_id]
    return os.path.exists(model_info["path"])

def download_file(url, destination, desc=None):
    """
    Download a file with progress bar using tqdm.
    
    Args:
        url: URL to download from
        destination: Local path to save the file
        desc: Description for the progress bar
        
    Returns:
        True on success, False on failure
    """
    try:
        # Ensure destination directory exists
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        
        # Setup request
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        # Get file size for progress
        file_size = int(response.headers.get('content-length', 0))
        
        # Show download progress
        with open(destination, 'wb') as file, tqdm(
            desc=desc if desc else os.path.basename(destination),
            total=file_size,
            unit='B',
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for data in response.iter_content(chunk_size=1024):
                file_size = file.write(data)
                bar.update(len(data))
                
        return True
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Download error: {e}")
        return False
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return False

def extract_archive(archive_path, extract_dir):
    """
    Extract a zip or tar archive.
    
    Args:
        archive_path: Path to the archive file
        extract_dir: Directory to extract into
        
    Returns:
        True on success, False on failure
    """
    try:
        # Ensure extraction directory exists
        os.makedirs(extract_dir, exist_ok=True)
        
        # Extract based on file extension
        if archive_path.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # Get total files for progress
                total_files = len(zip_ref.namelist())
                logger.info(f"Extracting {total_files} files from {archive_path}")
                
                # Extract with progress
                for i, member in enumerate(zip_ref.infolist(), 1):
                    zip_ref.extract(member, extract_dir)
                    if i % 10 == 0 or i == total_files:  # Update every 10 files
                        logger.info(f"Extracted {i}/{total_files} files...")
                
        elif archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                # Get member information
                members = tar_ref.getmembers()
                total_files = len(members)
                logger.info(f"Extracting {total_files} files from {archive_path}")
                
                # Extract with progress
                for i, member in enumerate(members, 1):
                    tar_ref.extract(member, extract_dir)
                    if i % 10 == 0 or i == total_files:  # Update every 10 files
                        logger.info(f"Extracted {i}/{total_files} files...")
        else:
            logger.error(f"Unsupported archive format: {archive_path}")
            return False
        
        # Delete the archive after successful extraction
        os.remove(archive_path)
        return True
        
    except Exception as e:
        logger.error(f"Error extracting archive: {e}")
        return False

def download_model(model_type, model_id):
    """
    Download and set up a specific model.
    
    Args:
        model_type: "vosk", "piper", or "porcupine"
        model_id: Specific model ID (e.g., "small_en" for Vosk)
        
    Returns:
        True on success, False on failure
    """
    # Porcupine models require Picovoice Console to download
    if model_type == "porcupine":
        logger.warning("Porcupine models need to be manually downloaded from the Picovoice Console")
        logger.info("Please visit: https://console.picovoice.ai/ to obtain models")
        return False
    
    # Check if model type is supported
    if model_type not in DEFAULT_MODELS:
        logger.error(f"Unknown model type: {model_type}")
        return False
    
    # Check if model ID is valid
    if model_id not in DEFAULT_MODELS[model_type]:
        logger.error(f"Unknown model ID: {model_id} for {model_type}")
        return False
    
    # Get model information
    model_info = DEFAULT_MODELS[model_type][model_id]
    logger.info(f"Downloading {model_info['name']} ({model_info['size_mb']} MB)...")
    
    # Handle special case for Piper which has separate model and config files
    if model_type == "piper":
        # Download model file
        model_success = download_file(
            model_info["url"], 
            model_info["path"], 
            f"Downloading {model_info['name']} model"
        )
        
        # Download config file
        config_success = download_file(
            model_info["config_url"], 
            model_info["config_path"], 
            f"Downloading {model_info['name']} config"
        )
        
        return model_success and config_success
    
    # For other models, download and extract if needed
    temp_download_path = os.path.join(os.path.dirname(model_info["path"]), "temp_download")
    
    # Download the file
    success = download_file(
        model_info["url"], 
        temp_download_path, 
        f"Downloading {model_info['name']}"
    )
    
    if not success:
        logger.error(f"Failed to download {model_info['name']}")
        return False
    
    # Extract if needed
    if model_info["extract_dir"]:
        logger.info(f"Extracting {model_info['name']}...")
        return extract_archive(temp_download_path, model_info["extract_dir"])
    else:
        # If no extraction needed, just move the file to its final location
        os.rename(temp_download_path, model_info["path"])
        return True

def check_and_download_models(interactive=True):
    """
    Check if all required models are available, and download missing ones.
    
    Args:
        interactive: If True, prompt user for confirmation
        
    Returns:
        True if all required models are available or were downloaded successfully,
        False otherwise
    """
    missing_models = []
    
    # Check Vosk model
    vosk_model_path = config.VOSK_MODEL_PATH
    if not os.path.exists(vosk_model_path):
        model_id = None
        for id, info in DEFAULT_MODELS["vosk"].items():
            if info["path"] == vosk_model_path:
                model_id = id
                break
        
        if model_id:
            missing_models.append(("vosk", model_id, info["name"]))
        else:
            logger.warning(f"Vosk model not found at {vosk_model_path} and no matching default model")
    
    # Check Piper model if enabled
    if config.TTS_ENGINE == "piper":
        piper_model_path = config.PIPER_MODEL_PATH
        if not os.path.exists(piper_model_path):
            model_id = None
            for id, info in DEFAULT_MODELS["piper"].items():
                if info["path"] == piper_model_path:
                    model_id = id
                    break
            
            if model_id:
                missing_models.append(("piper", model_id, info["name"]))
            else:
                logger.warning(f"Piper model not found at {piper_model_path} and no matching default model")
    
    # Check Porcupine keyword files
    if not config.PORCUPINE_KEYWORD_PATHS or any(not os.path.exists(path) for path in config.PORCUPINE_KEYWORD_PATHS):
        logger.warning("Porcupine wake word model(s) not found")
        logger.info("Porcupine models need to be manually downloaded from the Picovoice Console")
        logger.info("Please visit: https://console.picovoice.ai/ to obtain models")
    
    # If no missing models, we're good
    if not missing_models:
        logger.info("All required models are available.")
        return True
    
    # Print missing models
    logger.warning("The following models are missing:")
    for i, (model_type, model_id, model_name) in enumerate(missing_models, 1):
        logger.warning(f"{i}. {model_type}: {model_name}")
    
    # If not interactive, stop here
    if not interactive:
        return False
    
    # Ask user if they want to download missing models
    print("\nWould you like to download the missing models? (y/n)")
    choice = input("> ").lower()
    
    if choice not in ["y", "yes"]:
        logger.warning("Skipping model download.")
        return False
    
    # Download missing models
    success = True
    for model_type, model_id, model_name in missing_models:
        print(f"\nDownloading {model_name}...")
        if not download_model(model_type, model_id):
            logger.error(f"Failed to download {model_name}")
            success = False
        else:
            logger.info(f"Successfully downloaded {model_name}")
    
    return success

# If run directly, download missing models
if __name__ == "__main__":
    # Set up basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    # Run model check and download
    check_and_download_models(interactive=True)

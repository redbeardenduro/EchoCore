# Project EchoCore (Enhanced)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A voice-driven, modular, AI assistant interface featuring wake word detection, STT, LLM interaction, TTS, and a dynamic visual avatar. This enhanced version includes improved robustness, configuration options, a web interface, and more flexible components.

## Overview

Project EchoCore is designed as a modular framework for creating a personal AI assistant, drawing inspiration from concepts like Cortana (Halo) or Jarvis (Iron Man). It uses a wake word to activate, listens for commands, processes them using local or cloud-based AI models, synthesizes a spoken response, and displays a dynamic visual avatar.

This enhanced version builds upon the original concept with significant improvements:

* **Modular Architecture:** Clearly defined components for audio I/O, STT, LLM, state management, avatar display, and web UI.
* **Improved Configuration:** Centralized configuration (`config.py`) with user overrides via `user_config.json`.
* **Enhanced Error Handling:** Better exception handling, thread monitoring, and automatic reconnection attempts for cloud services.
* **Web Interface:** A Flask-based dashboard for monitoring status, viewing logs, adjusting settings, and performing basic actions.
* **Conversation History:** The LLM handler maintains context across multiple turns in a conversation.
* **Flexible TTS:** Supports OpenAI, ElevenLabs, and local Piper TTS engines. Includes streaming support.
* **Enhanced Avatar:** Multiple animation styles (`circle`, `wave`, `particle`, `hologram`) reacting to state and audio amplitude.
* **Model Downloader:** Utility script (`model_downloader.py`) to simplify fetching required Vosk and Piper models.
* **Audio Cues:** Optional sound feedback for events like wake word detection.
* **Robust Installation:** Improved installation script (`install.sh`) for Debian-based systems.

## Features

* **Wake Word Detection:** Picovoice Porcupine engine (requires free Picovoice account/key).
* **Speech-to-Text (STT):** Vosk offline engine with configurable confidence threshold.
* **Language Model (LLM):** OpenAI API (configurable model like GPT-4o-mini) with conversation history and optional offline fallback response.
* **Text-to-Speech (TTS):** Configurable engine:
    * OpenAI TTS (Cloud, requires API key)
    * ElevenLabs TTS (Cloud, requires API key)
    * Piper TTS (Local, requires Piper executable and voice models)
    * Supports streaming playback where available.
* **Audio Handling:** Uses `sounddevice` for audio input/output with device selection.
* **Visual Avatar:** Real-time dynamic avatar rendered using `pygame` with multiple styles.
* **State Management:** Robust, thread-safe state machine manages application flow.
* **Web Dashboard:** Monitor status, view/filter/download logs, change settings, test audio, trigger actions.
* **Configuration:** Defaults in `config.py`, user overrides in `user_config.json`, API keys in `.env`.
* **Logging:** Comprehensive logging with rotation via `RotatingFileHandler`.

## Prerequisites

### Hardware (Recommended)

* Raspberry Pi 4 (4GB+) or Raspberry Pi 5 (Performance significantly better on RPi 5).
* Reliable Power Supply (Official RPi PSU recommended).
* MicroSD Card (32GB+ recommended, A1/A2 rated) or NVMe SSD (for RPi 5).
* Active Cooler/Fan (Especially for RPi 5).
* USB Microphone (Ensure Linux compatibility, e.g., ReSpeaker, Blue Snowball, basic USB mics).
* Speakers (USB, 3.5mm jack, or HDMI audio via display).
* (Optional) Display for Avatar: Monitor, small LCD, or mini projector. Requires appropriate connection (e.g., HDMI, Micro-HDMI).
* (Optional) Frosted Acrylic/Screen: If using a projector for a "holographic" effect.
* Development Computer: For easier setup, coding, and SSH access.

### Software

* OS: Raspberry Pi OS (64-bit recommended, Lite or Desktop), or other Debian-based Linux distribution.
* Python: 3.8 or newer (check specific library compatibilities if using older versions).
* `pip` (Python package installer).
* `git` (for cloning the repository).
* System build tools (`python3-dev`, `build-essential` often useful).
* Audio System: ALSA / PulseAudio correctly configured. `portaudio19-dev`, `libasound2-dev`.
* (Optional) Piper TTS Executable: Must be installed separately if using Piper TTS.

### API Keys & Accounts

* **Picovoice Account:** Required for `PICOVOICE_ACCESS_KEY` (wake word detection). Free tier available. [console.picovoice.ai](https://console.picovoice.ai/)
* **OpenAI Account:** Required for `OPENAI_API_KEY` if using OpenAI for LLM or TTS. [platform.openai.com](https://platform.openai.com/)
* **ElevenLabs Account:** (Optional) Required for `ELEVENLABS_API_KEY` if using ElevenLabs TTS. [elevenlabs.io](https://elevenlabs.io/)

## Setup Instructions

These instructions are primarily for Raspberry Pi OS or similar Debian-based systems.

### 1. Clone Repository

```bash
# Choose a suitable location, e.g., home directory
cd ~
git clone <repository_url> # Replace with your repo URL if you forked
cd project_echocore # Or your repository's directory name
```

### 2. Run Installation Script (Recommended)

The provided script automates dependency installation, directory setup, and service configuration.

```bash
# Navigate to the cloned directory
cd ~/project_echocore # Or your directory

# Run the script with sudo
sudo bash install.sh
```

The script will:

- Update system packages.
- Install required system libraries (git, python3, pip, venv, portaudio, libasound, Pygame deps).
- Create necessary directories (/opt/echocore by default, models, logs, cache, static, templates).
- Set up a Python virtual environment (/opt/echocore/venv).
- Install Python packages from requirements.txt into the venv.
- Attempt to run model_downloader.py.
- Create a .env template file for API keys.
- Create a systemd service file (echocore.service).
- Set appropriate permissions.

Review the script output carefully, especially regarding user detection, dependencies, and any warnings.

### 3. Manual Setup (Alternative)

If you prefer not to use the script:

```bash
# 1. Update System
sudo apt update && sudo apt upgrade -y

# 2. Install System Dependencies
sudo apt install -y git python3-pip python3-venv python3-dev portaudio19-dev libasound2-dev libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev

# 3. Create Directories
mkdir -p models/vosk models/porcupine models/piper logs cache static templates

# 4. Create Virtual Environment
python3 -m venv venv
source venv/bin/activate

# 5. Install Python Dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 6. Deactivate (optional for now)
# deactivate
```

### 4. Configure API Keys

Create or edit the .env file in the project root:

```bash
cp .env.example .env # If .env.example exists and .env doesn't
nano .env # Or use your preferred editor
```

Add your actual API keys obtained from Picovoice, OpenAI, and ElevenLabs (if using):

```
# --- EchoCore Environment Variables ---

# Get from [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
OPENAI_API_KEY="sk-..."

# Get from [https://picovoice.ai/console/](https://picovoice.ai/console/)
PICOVOICE_ACCESS_KEY="..."

# Optional: Get from [https://elevenlabs.io/](https://elevenlabs.io/)
ELEVENLABS_API_KEY="..."
```

Important: Keep this file secure and do not commit it to public repositories (.gitignore should prevent this). Set permissions: `chmod 600 .env`.

### 5. Download Models

The easiest way is using the provided script (ensure the virtual environment is active):

```bash
# Activate venv if not already active
source venv/bin/activate # Or /opt/echocore/venv/bin/activate if using install script location

# Run the downloader
python model_downloader.py
```

This script will check config.py for the required Vosk/Piper models and download missing ones interactively.

Manual Download (Fallback):

- **Vosk:** Download a model (e.g., vosk-model-small-en-us-0.15) from alphacephei.com/vosk/models. Extract the archive. Ensure the contents of the extracted folder (containing am, conf, etc.) are placed inside models/vosk/<model_name>/. Update VOSK_MODEL_PATH in config.py or user_config.json if needed.
- **Piper TTS:** (If using) Download the desired voice .onnx and .onnx.json files from Hugging Face Piper Voices. Place them in models/piper/. Update PIPER_MODEL_PATH in config if needed. Crucially, install the Piper executable separately following its official instructions.
- **Porcupine:** Go to Picovoice Console. Create or select a wake word (.ppn file) for your target platform (e.g., Raspberry Pi). Download the .ppn file(s). Place them in models/porcupine/. Update the PORCUPINE_KEYWORD_PATHS list in config.py or user_config.json with the correct file path(s).

### 6. Configure Application Settings

Review config.py for default settings. To customize without editing config.py, create/edit user_config.json in the project root. Add only the keys you want to override. See user_config.json.example for format and examples.

Key settings to check:
- AUDIO_INPUT_DEVICE_INDEX, AUDIO_OUTPUT_DEVICE_INDEX (use null for default)
- PORCUPINE_KEYWORD_PATHS, PORCUPINE_SENSITIVITIES
- VOSK_MODEL_PATH
- TTS_ENGINE and the corresponding settings (e.g., PIPER_MODEL_PATH if using Piper).
- AVATAR_* settings for visual customization.
- WEB_INTERFACE_* settings to enable/configure the web dashboard.

## Running the Application

### Direct Execution (for Testing/Development)

1. Navigate to the project directory: `cd /path/to/project_echocore`
2. Activate the virtual environment: `source venv/bin/activate`
3. Run the main script: `python main.py`

The application will start, initialize components, and log output to the console and the logs/echocore.log file. If the avatar is enabled, the Pygame window should appear. If the web interface is enabled, access it via http://<your_pi_ip>:<port> (e.g., http://192.168.1.100:8080).

Press Ctrl+C in the terminal to stop the application gracefully.

### Running as a Service (Recommended for Deployment)

If you used install.sh, the echocore.service unit should be configured.

- Enable auto-start on boot: `sudo systemctl enable echocore.service`
- Start the service manually: `sudo systemctl start echocore.service`
- Stop the service: `sudo systemctl stop echocore.service`
- Check service status: `sudo systemctl status echocore.service`
- View live logs: `sudo journalctl -u echocore.service -f`

## Enhanced Project Structure

```
project_echocore/
├── main.py                 # Main application logic, thread management
├── config.py               # Default configuration settings
├── user_config.json.example # Example for user overrides
├── user_config.json        # Optional user overrides (ignored by git)
├── .env.example            # Example for environment variables
├── .env                    # Environment variables (API keys - ignored by git)
├── state_manager.py        # Manages application state (State Enum)
├── audio_input.py          # Handles microphone input & wake word (Porcupine)
├── audio_output.py         # Plays synthesized audio & calculates amplitude
├── audio_utils.py          # Utilities for audio device listing/testing
├── stt_processor.py        # Speech-to-Text processing (Vosk)
├── llm_handler.py          # Language Model interaction (OpenAI) & history
├── tts_synthesizer.py      # Text-to-Speech synthesis (OpenAI/ElevenLabs/Piper)
├── piper_tts.py            # Client wrapper for Piper TTS executable
├── avatar_display.py       # Visual avatar rendering (Pygame)
├── web_interface.py        # Web dashboard implementation (Flask)
├── model_downloader.py     # Utility for downloading Vosk/Piper models
├── requirements.txt        # Python package dependencies
├── install.sh              # Installation script for Debian-based systems
├── uninstall_echocore.sh   # Script to uninstall the service and files (Use with caution!)
├── README.md               # This file
├── Implementation_Plan.md  # Summary of enhancements applied
├── .gitignore              # Specifies files/dirs for Git to ignore
├── logs/                   # Directory for log files (ignored by git)
│   └── echocore.log        # Main log file (rotates)
├── cache/                  # Directory for caching (e.g., TTS audio - ignored by git)
├── static/                 # Static assets for web interface (CSS, JS, images)
│   ├── style.css
│   ├── index.html          # Note: HTML files now served via Flask templates folder
│   ├── logs.html           #  "
│   ├── settings.html       #  "
│   └── favicon.ico
├── templates/              # HTML templates for Flask web interface
│   ├── index.html
│   ├── logs.html
│   └── settings.html
└── models/                 # Directory for local models (ignored by git by default)
    ├── vosk/               # Vosk model files go here
    ├── piper/              # Piper voice files (.onnx, .json) go here
    └── porcupine/          # Porcupine keyword (.ppn) and model (.pv) files go here
```

(Note: HTML files were moved from static/ to templates/ as per Flask convention).

## New Features and Improvements (Enhanced Version)

- **Web Interface:** Monitor status, view/filter logs, change settings, test audio via a browser.
- **Conversation History:** LLM maintains context across multiple interactions.
- **Enhanced Avatar:** Multiple animation styles (circle, wave, particle, hologram) with smoother transitions and reactions.
- **Flexible TTS:** Choose between OpenAI, ElevenLabs, or local Piper TTS engines. Streaming supported.
- **Improved Configuration:** Use user_config.json for easy overrides without editing core files. Settings validation on startup.
- **Model Downloader:** model_downloader.py script simplifies obtaining Vosk and Piper models.
- **Improved Error Handling:** More specific error catching, automatic reconnection attempts for cloud services, thread monitoring in main.py.
- **Audio Cues:** Optional sound feedback for wake word and timeouts.
- **Code Quality:** Added type hinting, improved comments/docstrings, refactored logic for clarity and robustness across modules.
- **Installation Script:** More comprehensive install.sh for easier setup on compatible systems.
- **Logging:** Uses rotating file handler; configurable log level.

## Troubleshooting

### Audio Issues:
- Run `python -m sounddevice` in the activated venv to list devices. Update indices in user_config.json (null for default).
- Use the "Test Audio" buttons in the web interface settings.
- Check ALSA/PulseAudio configuration (alsamixer). Ensure the correct devices are unmuted and have appropriate volume levels.
- If using PipeWire, ensure pipewire-pulse and pipewire-alsa are correctly configured.
- Check logs for PortAudioError messages.

### Wake Word Not Detected:
- Verify PICOVOICE_ACCESS_KEY is correct in .env.
- Ensure .ppn file path(s) in config/user_config.json (PORCUPINE_KEYWORD_PATHS) are correct and files exist in models/porcupine/.
- Check microphone levels and ensure it's the selected input device.
- Adjust PORCUPINE_SENSITIVITIES (0.0 to 1.0). Higher values are more sensitive.

### Vosk Errors:
- Ensure the VOSK_MODEL_PATH points to the correct, fully extracted Vosk model directory.
- Check logs for Vosk initialization errors.

### Piper Errors:
- Verify the piper executable is installed correctly and is in the system's PATH (`which piper`).
- Ensure PIPER_MODEL_PATH points to the correct .onnx file and the corresponding .onnx.json file exists in the same directory.

### API Connection Issues (OpenAI/ElevenLabs):
- Double-check API keys in .env.
- Verify internet connectivity on the device.
- Check the respective service status pages for outages.
- Check logs for specific API errors (rate limits, authentication, etc.).

### Web Interface Issues:
- Ensure WEB_INTERFACE_ENABLED is true in config/user config.
- Check if the configured port (WEB_INTERFACE_PORT) is already in use (`sudo netstat -tulnp | grep <port>`).
- Verify the host address (WEB_INTERFACE_HOST). Use 0.0.0.0 to access from other devices on the network.
- Check browser console and EchoCore logs for Flask errors.

### Pygame/Avatar Issues:
- If running headless (no desktop environment), ensure Pygame can access the display (may require setting DISPLAY=:0 environment variable for the service or running specific commands like startx). Framebuffer drivers (SDL_VIDEODRIVER=kmsdrm) might be needed.
- Check logs for Pygame initialization errors.

### Permission Errors: 
Ensure the user running the application (e.g., pi or the user specified in echocore.service) has read/write permissions for the project directory, logs, cache, and read permissions for models. The install.sh script attempts to set these.

## Using the Web Interface

1. **Enable:** Set WEB_INTERFACE_ENABLED = true in config.py or user_config.json.
2. **Configure:** Adjust WEB_INTERFACE_PORT, WEB_INTERFACE_HOST, WEB_INTERFACE_USERNAME, WEB_INTERFACE_PASSWORD as needed. Change the default password!
3. **Restart:** Restart the EchoCore application (or service).
4. **Access:** Open a web browser and navigate to http://<your_device_ip>:<port> (e.g., http://192.168.1.100:8080).
5. **Login:** Use the configured username and password.

The web interface provides:

- **Dashboard:** System status, resource usage, recent activity/transitions, quick actions.
- **Settings:** View and modify configuration parameters (saved to user_config.json).
- **Logs:** View recent log entries with filtering and download options.

## License

This project is licensed under the MIT License.

## Acknowledgments

- Vosk & Kaldi Project (Offline STT)
- Picovoice (Porcupine Wake Word)
- OpenAI (GPT Models, TTS)
- ElevenLabs (TTS)
- Piper TTS Project & Contributors (Local TTS)
- sounddevice library developers
- pygame library developers
- Flask framework developers

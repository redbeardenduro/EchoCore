################################################################################
#
# Project EchoCore
# (Voice-Driven, Holographic-Style Smart AI Interface)
# README.txt
#
################################################################################

TABLE OF CONTENTS
=================
1. Introduction
2. Features (Phase 1)
3. Prerequisites
   3.1. Hardware
   3.2. Software
   3.3. API Keys & Accounts
4. Setup Instructions
   4.1. Clone Repository
   4.2. Install System Dependencies
   4.3. Create Python Virtual Environment
   4.4. Install Python Dependencies
   4.5. Download Models
   4.6. Configure API Keys
   4.7. Configure Application Settings
5. Running the Application
6. Project Structure
7. Important Notes & Troubleshooting


1. INTRODUCTION
===============
Project EchoCore aims to build a self-contained, AI-powered personal assistant terminal inspired by Cortana. It features natural voice interaction, powered by cloud or local AI models, and a dynamic visual avatar projected onto a screen. This README provides instructions for setting up and running the Phase 1 functional prototype.


2. FEATURES (PHASE 1)
=====================
- Wake word detection using Picovoice Porcupine
- Speech-to-Text (STT) using the offline Vosk engine
- Language Model (LLM) interaction via OpenAI API (GPT-4o/mini) with basic offline fallback
- Text-to-Speech (TTS) using configurable engines: OpenAI API, ElevenLabs API, or local Piper TTS
- Real-time audio playback using sounddevice
- Basic visual avatar rendering using Pygame, synchronized with audio output amplitude
- Multi-threaded architecture for concurrent processing
- State management for controlling application flow


3. PREREQUISITES
===============

3.1. Hardware
-------------
- Raspberry Pi 5 (8GB recommended)
- Reliable Power Supply for RPi 5 (Official 27W recommended)
- MicroSD Card (128GB, A2-rated recommended) or NVMe SSD
- Active Cooler for RPi 5 (Essential)
- USB Microphone (Ensure compatibility, e.g., Samson Go Mic, SunFounder Mini Mic)
- USB Speakers or Speakers with 3.5mm jack
- Mini Projector with HDMI input (e.g., Kodak Luma 150, AAXA P8 Mini)
- Micro-HDMI to HDMI cable/adapter
- Frosted Acrylic Sheet (for projection)
- Mount/Stand for Acrylic Sheet (45-degree angle needed)
- (Optional but Recommended) Development Computer (Windows/macOS/Linux) for easier setup/coding

3.2. Software
-------------
- Raspberry Pi OS Lite (64-bit, Bookworm recommended) installed on the SD card/SSD. Headless setup is sufficient
- Python 3.8 or newer
- pip (Python package installer)
- git (for cloning the repository)
- SSH client on your development computer (e.g., PuTTY, Terminal) for connecting to the Raspberry Pi

3.3. API Keys & Accounts
-----------------------
You will need accounts and API keys for the following services (depending on your configuration choices in config.py):
- Picovoice: For Porcupine wake word detection (free tier available)
- OpenAI: For GPT-4o/mini LLM and/or OpenAI TTS
- ElevenLabs: (Optional) If using ElevenLabs TTS


4. SETUP INSTRUCTIONS
====================
These instructions assume you are running commands on the Raspberry Pi (either directly or via SSH).

4.1. Clone Repository
--------------------
git clone <repository_url> # Replace <repository_url> with the actual URL
cd project_echocore

4.2. Install System Dependencies
------------------------------
These packages are commonly needed for audio processing and building some Python packages.

sudo apt update
sudo apt install -y portaudio19-dev libasound2-dev git python3-pip python3-venv
# Add any other system dependencies needed, e.g., for Piper TTS build if required
# sudo apt install -y libfmt-dev libspdlog-dev # Example for Piper build

4.3. Create Python Virtual Environment
------------------------------------
Using a virtual environment is highly recommended to isolate project dependencies.

python3 -m venv venv
source venv/bin/activate

(You'll need to run 'source venv/bin/activate' every time you open a new terminal session to work on the project).

4.4. Install Python Dependencies
------------------------------
Install the required Python packages listed in requirements.txt.

pip install -r requirements.txt

Note: Installation of some packages, especially those with C extensions like PyAudio or potentially Piper TTS bindings, might take time or require specific build tools not listed here. Check package documentation if errors occur.

4.5. Download Models
------------------
Download the necessary pre-trained models and place them in the correct subdirectories within the models/ folder.

- Vosk: Download a language model (e.g., vosk-model-small-en-us-0.15 from https://alphacephei.com/vosk/models). Extract it and place the model directory inside models/vosk/. Update VOSK_MODEL_PATH in config.py if needed.
- Porcupine: Download the common model file (.pv) and your desired keyword file(s) (.ppn) from the Picovoice Console or the Porcupine GitHub repository. Place them in models/porcupine/. Update PORCUPINE_MODEL_PATH (if not using default) and PORCUPINE_KEYWORD_PATHS in config.py.
- Piper TTS (Optional): If using Piper, download the voice .onnx and .onnx.json files from https://huggingface.co/rhasspy/piper-voices/tree/main. Place them in models/piper/. Update PIPER_MODEL_PATH in config.py.

4.6. Configure API Keys
---------------------
Create a .env file in the project root directory by copying the example:

cp .env.example .env

Edit the .env file and add your actual API keys obtained from Picovoice, OpenAI, and ElevenLabs (if used).

# .env
OPENAI_API_KEY="sk-..."
ELEVENLABS_API_KEY="..."
PICOVOICE_ACCESS_KEY="..."

4.7. Configure Application Settings
---------------------------------
Edit the config.py file to adjust settings as needed:

- Audio Devices: Run 'python -m sounddevice' in your activated virtual environment to list available audio input/output devices and their indices. Update AUDIO_INPUT_DEVICE_INDEX and AUDIO_OUTPUT_DEVICE_INDEX if you don't want to use the system defaults.
- TTS Engine: Set TTS_ENGINE to your desired provider ('openai', 'elevenlabs', or 'piper'). Ensure the corresponding API key (for cloud) or model path (for Piper) is correctly set.
- Model Paths: Double-check that VOSK_MODEL_PATH, PORCUPINE_MODEL_PATH, PORCUPINE_KEYWORD_PATHS, and PIPER_MODEL_PATH point to the correct locations where you downloaded the models.
- Other Settings: Review other settings like LLM_MODEL, AVATAR_* colors/sizes, etc., and adjust if necessary.


5. RUNNING THE APPLICATION
=========================
Ensure your virtual environment is activated ('source venv/bin/activate'). Then, run the main script:

python main.py

The application should start, initialize all components, and begin listening for the wake word. The Pygame window displaying the avatar should appear.


6. PROJECT STRUCTURE
==================
project_echocore/
├── main.py                 # Main application: initializes, manages threads & queues
├── config.py               # Configuration settings (API keys, paths, devices, etc.)
├── state_manager.py        # Manages the application's state (IDLE, LISTENING, etc.)
├── audio_input.py          # Handles microphone input & wake word detection (Porcupine)
├── stt_processor.py        # Processes audio chunks using STT engine (Vosk)
├── llm_handler.py          # Interacts with LLM (OpenAI API), handles basic offline logic
├── tts_synthesizer.py      # Synthesizes speech using cloud (OpenAI/ElevenLabs) or local (Piper)
├── audio_output.py         # Plays synthesized audio & calculates amplitude
├── avatar_display.py       # Renders the Pygame avatar based on state & amplitude
├── requirements.txt        # Python package dependencies
├── .env.example            # Example environment file for API keys
└── models/                 # Directory for local models
    ├── vosk/               # Vosk model files
    ├── piper/              # Piper voice files
    └── porcupine/          # Porcupine keyword & model files


7. IMPORTANT NOTES & TROUBLESHOOTING
==================================

Audio Issues
-----------
Audio setup on Linux/Raspberry Pi can be tricky.
- Ensure your microphone and speakers are correctly detected by the OS ('arecord -l', 'aplay -l').
- Verify the correct device indices are set in config.py.
- If experiencing choppy audio or high latency, experiment with AUDIO_CHUNK_SIZE and AUDIO_OUTPUT_LATENCY in config.py. Low latency often requires careful tuning.
- Ensure portaudio19-dev and libasound2-dev are installed.

API Keys
-------
Ensure your API keys in the .env file are correct and valid. Check for any leading/trailing whitespace.

Model Paths
----------
Double-check that the paths to Vosk, Porcupine, and Piper models in config.py are correct relative to the project root directory. Ensure the model files have been downloaded and placed correctly.

Performance
----------
Running multiple AI models (STT, TTS, potentially local LLM) and Pygame simultaneously can be resource-intensive, even on a Raspberry Pi 5. Ensure adequate cooling (Active Cooler is essential) to prevent thermal throttling.

Kiosk Mode (Raspberry Pi)
------------------------
This setup does not automatically configure kiosk mode. To make the avatar display fullscreen automatically on boot without a desktop environment on Raspberry Pi OS Lite, you will need to configure the OS separately. This typically involves:
- Setting up console autologin ('sudo raspi-config').
- Using systemd to create a service that launches main.py.
- Alternatively, using methods involving .bashrc or minimal X11 setups (more complex).
- Ensuring the correct environment variables are set for Pygame (e.g., 'export SDL_VIDEODRIVER=kmsdrm' for Bookworm Lite).

Exiting
------
Press Ctrl+C in the terminal where main.py is running to gracefully shut down the application. You can also press the ESC key while the Pygame window is focused.

################################################################################
#                           END OF README.txt                                  #
################################################################################
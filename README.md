# Project EchoCore (Enhanced)
### Voice-Driven, Holographic-Style Smart AI Interface

---

## Overview

Project EchoCore is a self-contained, AI-powered personal assistant terminal inspired by Cortana from the Halo franchise. It features natural voice interaction, powered by cloud or local AI models, and a dynamic visual avatar projected onto a screen. 

This enhanced version introduces improvements to the original implementation including:
- Better error handling and recovery mechanisms
- Enhanced visual avatar with animations
- Audio feedback cues for improved user experience
- Conversation history for context-aware interactions
- Improved configuration options and user customization
- Automatic reconnection for cloud services
- Flexible logging with rotation

## Features

- **Wake Word Detection**: Using Picovoice Porcupine with configurable sensitivity
- **Speech-to-Text (STT)**: Using the offline Vosk engine with confidence thresholds
- **Language Model (LLM)**: Interaction via OpenAI API (GPT-4o/mini) with basic offline fallback
- **Text-to-Speech (TTS)**: Using configurable engines:
  - OpenAI API with streaming support
  - ElevenLabs API with voice customization
  - Local Piper TTS for offline operation
- **Real-time Audio Feedback**: Audio cues to indicate system state changes
- **Enhanced Visual Avatar**: Dynamic animations synchronized with audio and system state
- **Conversation Context**: Maintains dialogue history for more natural interactions
- **Error Recovery**: Automatic reconnection and fallback mechanisms
- **Logging & Monitoring**: Comprehensive logging with rotation to prevent disk space issues

## Prerequisites

### Hardware

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
- (Optional but Recommended) Development Computer for easier setup/coding

### Software

- Raspberry Pi OS Lite (64-bit, Bookworm recommended) installed on the SD card/SSD. Headless setup is sufficient
- Python 3.8 or newer
- pip (Python package installer)
- git (for cloning the repository)
- SSH client on your development computer for connecting to the Raspberry Pi

### API Keys & Accounts

You will need accounts and API keys for the following services (depending on your configuration):
- Picovoice: For Porcupine wake word detection (free tier available)
- OpenAI: For GPT-4o/mini LLM and/or OpenAI TTS
- ElevenLabs: (Optional) If using ElevenLabs TTS

## Setup Instructions

These instructions assume you are running commands on the Raspberry Pi (either directly or via SSH).

### 1. Clone Repository

```bash
git clone <repository_url>
cd project_echocore
```

### 2. Install System Dependencies

```bash
sudo apt update
sudo apt install -y portaudio19-dev libasound2-dev git python3-pip python3-venv
# Add any other system dependencies needed, e.g., for Piper TTS
```

### 3. Create Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 5. Download Models

Download the necessary pre-trained models and place them in the correct subdirectories within the `models/` folder:

#### Vosk
Download a language model (e.g., `vosk-model-small-en-us-0.15` from https://alphacephei.com/vosk/models). Extract it and place the model directory inside `models/vosk/`.

#### Porcupine
Download the common model file (`.pv`) and your desired keyword file(s) (`.ppn`) from the Picovoice Console or the Porcupine GitHub repository. Place them in `models/porcupine/`.

#### Piper TTS (Optional)
If using Piper, download the voice `.onnx` and `.onnx.json` files from https://huggingface.co/rhasspy/piper-voices/tree/main. Place them in `models/piper/`.

### 6. Configure API Keys

Create a `.env` file in the project root directory:

```bash
cp .env.example .env
```

Edit the `.env` file and add your actual API keys:

```
OPENAI_API_KEY="sk-..."
ELEVENLABS_API_KEY="..."
PICOVOICE_ACCESS_KEY="..."
```

### 7. Configure Application Settings

Edit the `config.py` file to adjust settings as needed. The enhanced config includes many new options for customizing the behavior of EchoCore.

Alternatively, create a `user_config.json` file to override specific settings without modifying the main configuration file:

```json
{
  "AVATAR_WINDOW_WIDTH": 1024,
  "AVATAR_WINDOW_HEIGHT": 768,
  "AVATAR_ANIMATION_STYLE": "hologram",
  "AUDIO_INPUT_DEVICE_INDEX": 1,
  "AUDIO_OUTPUT_DEVICE_INDEX": 0
}
```

## Running the Application

Ensure your virtual environment is activated, then run the main script:

```bash
source venv/bin/activate
python main.py
```

The application will start, initialize all components, and begin listening for the wake word. The Pygame window displaying the enhanced avatar will appear.

## Enhanced Project Structure

```
project_echocore/
├── main.py                 # Main application with health monitoring
├── config.py               # Enhanced configuration with validation
├── state_manager.py        # Manages application state
├── audio_input.py          # Handles microphone input & wake word with audio cues
├── stt_processor.py        # Processes audio with confidence scoring
├── llm_handler.py          # Interacts with LLM with conversation history
├── tts_synthesizer.py      # Synthesizes speech with streaming support
├── audio_output.py         # Plays audio with amplitude calculation
├── avatar_display.py       # Enhanced avatar with animations
├── requirements.txt        # Python package dependencies
├── .env.example            # Example environment file for API keys
├── user_config.json        # Optional user configuration overrides
├── logs/                   # Directory for log files with rotation
├── cache/                  # Cache for TTS responses to reduce API usage
└── models/                 # Directory for local models
    ├── vosk/               # Vosk model files
    ├── piper/              # Piper voice files
    └── porcupine/          # Porcupine keyword & model files
```

## New Features and Improvements

### Conversation History
The LLM handler now maintains conversation context, allowing for more natural multi-turn interactions. The system remembers previous exchanges, enabling it to understand references to earlier parts of the conversation.

### Enhanced Avatar Visualization
The avatar display now features multiple animation styles based on the current state:
- **Idle**: Gentle pulsing effect with subtle glow
- **Listening**: Expanding ripple effect
- **Thinking**: Orbiting particles around the central circle
- **Speaking**: Audio-reactive wave visualization
- **Error**: Warning indicators with animation

### Audio Feedback
Audio cues now provide immediate feedback when:
- Wake word is detected
- Listening times out
- System encounters an error

### Improved Error Handling
- Automatic reconnection to cloud services
- Graceful degradation when services are unavailable
- Comprehensive logging with rotation

### Configuration Enhancements
- User-specific configuration via `user_config.json`
- Runtime validation of critical settings
- More customization options for all components

### Performance Optimizations
- Lazy loading of models
- Queue size limits to prevent memory issues
- Configurable standby mode for reduced CPU usage

## Troubleshooting

### Audio Issues
- Run `python -m sounddevice` to list available audio devices and update the device indices in your configuration
- If experiencing audio dropouts, try increasing `AUDIO_CHUNK_SIZE` or adjusting `AUDIO_OUTPUT_LATENCY`
- Ensure the microphone is not being used by another application

### Visual Display Issues
- If running on Raspberry Pi OS Lite, ensure the correct display driver is set (e.g., `export SDL_VIDEODRIVER=kmsdrm`)
- For fullscreen mode, set `AVATAR_FULLSCREEN = True` in your configuration

### API Connection Issues
- Verify your API keys are correct
- Check your internet connection
- The system will automatically attempt to reconnect after temporary failures

### Log Files
- Check the logs in the `logs/` directory for detailed error information
- Use `tail -f logs/echocore.log` to watch the logs in real-time

## Future Enhancements

Planned future improvements:
- Web-based configuration interface
- More sophisticated avatar visualizations
- Integration with local smart home systems
- Sentiment analysis for more appropriate responses
- Custom wake word training interface

## License

[Insert your license information here]

## Acknowledgments

- Vosk for the offline speech recognition engine
- Picovoice for the wake word detection
- OpenAI for the language and TTS models
- ElevenLabs for voice synthesis technology
- Piper for the open-source TTS system

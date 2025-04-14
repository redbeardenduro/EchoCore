#!/bin/bash

# Project EchoCore Installation Script
# This script sets up the EchoCore environment on a Raspberry Pi

# Text formatting
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print header
echo -e "${BOLD}${BLUE}"
echo "=========================================================="
echo "       Project EchoCore Installation Script"
echo "=========================================================="
echo -e "${NC}"

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo -e "${YELLOW}Warning: This doesn't appear to be a Raspberry Pi.${NC}"
    echo -e "The script is optimized for Raspberry Pi. Continue at your own risk."
    read -p "Continue installation? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation aborted."
        exit 1
    fi
fi

# Check if root
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}This script needs to install system packages.${NC}"
    echo "Please run with sudo."
    exit 1
fi

# Create log file
LOG_FILE="install_log.txt"
echo "Installation log created on $(date)" > $LOG_FILE

# Function to log and display messages
log() {
    echo -e "$1" | tee -a $LOG_FILE
}

# Function to execute commands and log output
execute() {
    log "${BOLD}Executing: $1${NC}"
    eval $1 >> $LOG_FILE 2>&1
    if [ $? -ne 0 ]; then
        log "${RED}Command failed: $1${NC}"
        log "Check $LOG_FILE for details."
        if [ "$2" != "continue" ]; then
            log "${RED}Installation failed.${NC}"
            exit 1
        fi
    fi
}

# Function to check and create directories
check_directory() {
    if [ ! -d "$1" ]; then
        log "Creating directory: $1"
        mkdir -p "$1"
    else
        log "Directory already exists: $1"
    fi
}

# Step 1: Update system packages
log "${BOLD}${GREEN}Step 1: Updating system packages...${NC}"
execute "apt update"
execute "apt upgrade -y" "continue"

# Step 2: Install system dependencies
log "${BOLD}${GREEN}Step 2: Installing system dependencies...${NC}"
execute "apt install -y git python3-pip python3-venv portaudio19-dev libasound2-dev libfmt-dev libspdlog-dev"

# Step 3: Create project directory structure
log "${BOLD}${GREEN}Step 3: Creating project directory structure...${NC}"
PROJECT_DIR="/opt/echocore"
check_directory "$PROJECT_DIR"
check_directory "$PROJECT_DIR/models/vosk"
check_directory "$PROJECT_DIR/models/porcupine"
check_directory "$PROJECT_DIR/models/piper"
check_directory "$PROJECT_DIR/logs"
check_directory "$PROJECT_DIR/cache"

# Step 4: Setup Python virtual environment
log "${BOLD}${GREEN}Step 4: Setting up Python virtual environment...${NC}"
if [ ! -d "$PROJECT_DIR/venv" ]; then
    execute "python3 -m venv $PROJECT_DIR/venv"
else
    log "Virtual environment already exists, skipping creation."
fi

# Step 5: Clone or download project files
log "${BOLD}${GREEN}Step 5: Downloading project files...${NC}"
USER_REPO_URL=""
read -p "Enter GitHub repository URL (or press Enter to skip): " USER_REPO_URL

if [ -n "$USER_REPO_URL" ]; then
    # Clone from GitHub
    execute "cd $PROJECT_DIR && git clone $USER_REPO_URL ."
else
    # User will copy files manually
    log "${YELLOW}Skipping repository clone.${NC}"
    log "Please copy project files to $PROJECT_DIR manually."
fi

# Step 6: Install Python dependencies
log "${BOLD}${GREEN}Step 6: Installing Python dependencies...${NC}"
execute "cd $PROJECT_DIR && source venv/bin/activate && pip install --upgrade pip"
execute "cd $PROJECT_DIR && source venv/bin/activate && pip install -r requirements.txt" "continue"

# Step 7: Download models (placeholder instructions for manual download)
log "${BOLD}${GREEN}Step 7: Model files information...${NC}"
log "You need to download the following model files manually:"
log "${YELLOW}Vosk Model:${NC}"
log "1. Download a small model from https://alphacephei.com/vosk/models"
log "   (e.g., vosk-model-small-en-us-0.15)"
log "2. Extract and place in $PROJECT_DIR/models/vosk/"
log
log "${YELLOW}Porcupine Wake Word:${NC}"
log "1. Get a free Picovoice access key from https://console.picovoice.ai/"
log "2. Download wake word models (.ppn files) for Raspberry Pi"
log "3. Place files in $PROJECT_DIR/models/porcupine/"
log
log "${YELLOW}Piper TTS (Optional):${NC}"
log "1. Download voice models from https://huggingface.co/rhasspy/piper-voices/tree/main"
log "2. Place .onnx and .onnx.json files in $PROJECT_DIR/models/piper/"

# Step 8: Create configuration files
log "${BOLD}${GREEN}Step 8: Creating configuration files...${NC}"
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cat > "$PROJECT_DIR/.env" << EOF
# .env file for Project EchoCore
# Fill in your API keys

OPENAI_API_KEY=""
ELEVENLABS_API_KEY=""
PICOVOICE_ACCESS_KEY=""
EOF
    log "Created .env template file. Please edit with your API keys."
else
    log ".env file already exists, skipping creation."
fi

# Step 9: Setup systemd service for auto-start
log "${BOLD}${GREEN}Step 9: Setting up systemd service...${NC}"
SERVICE_FILE="/etc/systemd/system/echocore.service"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Project EchoCore AI Assistant
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$PROJECT_DIR
ExportENVIRONMENT=DISPLAY=:0
ExecStart=$PROJECT_DIR/venv/bin/python main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

execute "chmod 644 $SERVICE_FILE"
execute "systemctl daemon-reload"
log "Systemd service created. You can start it with: sudo systemctl start echocore"
log "To enable autostart at boot: sudo systemctl enable echocore"

# Step 10: Setup permissions
log "${BOLD}${GREEN}Step 10: Setting permissions...${NC}"
execute "chown -R pi:pi $PROJECT_DIR"

# Final instructions
log "${BOLD}${GREEN}Installation completed!${NC}"
log
log "${BOLD}Next steps:${NC}"
log "1. Edit $PROJECT_DIR/.env to add your API keys"
log "2. Download model files as described above"
log "3. Test the application: cd $PROJECT_DIR && source venv/bin/activate && python main.py"
log "4. Once tested, enable the service: sudo systemctl enable echocore"
log
log "${BOLD}${BLUE}Thank you for installing Project EchoCore!${NC}"

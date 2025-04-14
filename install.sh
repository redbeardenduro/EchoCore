#!/bin/bash
# shellcheck disable=SC2155 # Allow dynamic variable assignment

# ==========================================================
# Project EchoCore Enhanced Installation Script
# ==========================================================
# This script automates the setup of EchoCore on a
# Debian-based system (like Raspberry Pi OS).
# It installs dependencies, sets up directories, creates a
# virtual environment, and configures a systemd service.
#
# Usage: sudo bash install.sh
# ==========================================================

# --- Configuration ---
# Installation directory
PROJECT_DIR="/opt/echocore"
# User to run the application as (change if needed)
# Attempts to find the primary logged-in non-root user, falls back to 'pi' or 'ubuntu'
DEFAULT_USER="pi" # Fallback 1
DEFAULT_USER2="ubuntu" # Fallback 2
INSTALL_USER=$(who | awk '{print $1}' | sort | uniq | grep -v "root" | head -n 1)
if [ -z "$INSTALL_USER" ]; then
    if id "$DEFAULT_USER" &>/dev/null; then
        INSTALL_USER="$DEFAULT_USER"
    elif id "$DEFAULT_USER2" &>/dev/null; then
         INSTALL_USER="$DEFAULT_USER2"
    else
        echo "WARNING: Could not determine non-root user. Set INSTALL_USER manually."
        # Optionally exit or prompt here
        INSTALL_USER="echocore_user" # Placeholder if needed
    fi
fi

# Repository URL (optional - leave empty to skip clone)
# GIT_REPO_URL="https://github.com/your_username/Project_EchoCore.git"
GIT_REPO_URL=""


# --- Script Setup ---
set -e # Exit immediately if a command exits with a non-zero status.
# set -u # Treat unset variables as an error.
# set -o pipefail # Causes pipelines to fail on the first command that fails.

# Text formatting
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Log file
LOG_FILE="$(pwd)/echocore_install_$(date +%Y%m%d_%H%M%S).log"
touch "$LOG_FILE"

# Function to log messages to console and file
log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

# Function to execute commands, log output, and handle errors
execute() {
    local cmd="$1"
    local allow_failure="${2:-false}" # Set to 'true' to continue on failure

    log "${BLUE}Executing: ${cmd}${NC}"
    # Use eval to handle complex commands with pipes/redirects if needed, but be careful
    # Safer: Use bash -c "$cmd" >> "$LOG_FILE" 2>&1
    if bash -c "$cmd" >> "$LOG_FILE" 2>&1; then
        log "${GREEN}Success.${NC}"
    else
        local exit_code=$?
        log "${RED}Command failed with exit code ${exit_code}:${NC} $cmd"
        log "Check $LOG_FILE for detailed error output."
        if [ "$allow_failure" != "true" ]; then
            log "${RED}Installation cannot proceed. Exiting.${NC}"
            exit 1
        else
            log "${YELLOW}Continuing installation despite command failure (allow_failure=true).${NC}"
        fi
        return $exit_code # Return the actual exit code
    fi
    return 0
}

# --- Pre-flight Checks ---
log "${BOLD}Starting EchoCore Installation...${NC}"
log "Log file: $LOG_FILE"
log "Project Directory: $PROJECT_DIR"
log "Install User: $INSTALL_USER"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    log "${RED}This script needs root privileges to install system packages and setup services.${NC}"
    log "Please run using 'sudo bash install.sh'"
    exit 1
fi

# Check if target user exists
if ! id "$INSTALL_USER" &>/dev/null; then
    log "${YELLOW}User '$INSTALL_USER' does not exist.${NC}"
    read -p "Create user '$INSTALL_USER'? (y/n) " -n 1 -r REPLY
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        execute "useradd -m -s /bin/bash $INSTALL_USER" || exit 1
        log "User '$INSTALL_USER' created."
    else
        log "${RED}Installation requires a valid user. Exiting.${NC}"
        exit 1
    fi
fi

# Check for Raspberry Pi (informational)
if grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    log "Detected Raspberry Pi."
else
    log "${YELLOW}Warning: Not running on a known Raspberry Pi model. Compatibility not guaranteed.${NC}"
fi


# --- Installation Steps ---

# Step 1: Update System Packages
log "\n${BOLD}${GREEN}Step 1: Updating system packages...${NC}"
execute "apt-get update"
execute "apt-get upgrade -y" "true" # Allow upgrade to fail without halting install

# Step 2: Install System Dependencies
log "\n${BOLD}${GREEN}Step 2: Installing system dependencies...${NC}"
# Core: git, python3, pip, venv
# Audio: portaudio, libasound (for sounddevice)
# Pygame: Check common dependencies (might vary slightly by OS version)
PYGAME_DEPS="libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev" # Common deps
# Piper TTS: Requires manual install (remind user later)
execute "apt-get install -y git python3-pip python3-venv python3-dev portaudio19-dev libasound2-dev $PYGAME_DEPS"

# Step 3: Create Project Directory Structure
log "\n${BOLD}${GREEN}Step 3: Creating project directories...${NC}"
execute "mkdir -p $PROJECT_DIR"
execute "mkdir -p $PROJECT_DIR/models/vosk"
execute "mkdir -p $PROJECT_DIR/models/porcupine"
execute "mkdir -p $PROJECT_DIR/models/piper"
execute "mkdir -p $PROJECT_DIR/logs"
execute "mkdir -p $PROJECT_DIR/cache"
execute "mkdir -p $PROJECT_DIR/static"
execute "mkdir -p $PROJECT_DIR/templates"

# Step 4: Clone or Copy Project Files
log "\n${BOLD}${GREEN}Step 4: Obtaining project files...${NC}"
if [ -n "$GIT_REPO_URL" ]; then
    if [ -d "$PROJECT_DIR/.git" ]; then
        log "Git repository already exists. Attempting to pull updates..."
        # Stash local changes, pull, then apply stash if needed
        execute "cd $PROJECT_DIR && git stash push --include-untracked" "true"
        execute "cd $PROJECT_DIR && git pull" "true" # Allow pull to fail if offline etc.
        execute "cd $PROJECT_DIR && git stash pop" "true"
    else
        log "Cloning repository from $GIT_REPO_URL..."
        # Clone into a temporary directory first, then move to avoid issues if PROJECT_DIR isn't empty
        TMP_CLONE_DIR=$(mktemp -d)
        execute "git clone --depth 1 $GIT_REPO_URL $TMP_CLONE_DIR" # Shallow clone
        # Move contents, handle existing files carefully (rsync is good)
        execute "rsync -a --remove-source-files $TMP_CLONE_DIR/ $PROJECT_DIR/"
        rm -rf "$TMP_CLONE_DIR"
    fi
else
    log "${YELLOW}GIT_REPO_URL not set. Skipping clone.${NC}"
    log "Ensure project files (main.py, config.py, etc.) are manually copied to $PROJECT_DIR"
    # Add a pause or check here if needed
    read -p "Press Enter when project files are copied to $PROJECT_DIR..."
fi

# Step 5: Set up Python Virtual Environment
log "\n${BOLD}${GREEN}Step 5: Setting up Python virtual environment...${NC}"
VENV_DIR="$PROJECT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    execute "python3 -m venv $VENV_DIR"
    log "Virtual environment created at $VENV_DIR"
else
    log "Virtual environment already exists at $VENV_DIR."
fi
# Ensure permissions allow the user to use the venv
execute "chown -R $INSTALL_USER:$INSTALL_USER $VENV_DIR"


# Step 6: Install Python Dependencies
log "\n${BOLD}${GREEN}Step 6: Installing Python dependencies...${NC}"
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
if [ -f "$REQUIREMENTS_FILE" ]; then
    # Run pip install as the target user
    execute "sudo -u $INSTALL_USER bash -c 'source $VENV_DIR/bin/activate && pip install --upgrade pip'"
    execute "sudo -u $INSTALL_USER bash -c 'source $VENV_DIR/bin/activate && pip install -r $REQUIREMENTS_FILE'" "true" # Allow failure for optional deps
else
    log "${YELLOW}Warning: requirements.txt not found in $PROJECT_DIR. Skipping Python dependency installation.${NC}"
    log "Ensure required packages (openai, vosk, pvporcupine, sounddevice, etc.) are installed manually."
fi

# Step 7: Download Models using model_downloader.py
log "\n${BOLD}${GREEN}Step 7: Downloading required ML models...${NC}"
MODEL_DOWNLOADER_SCRIPT="$PROJECT_DIR/model_downloader.py"
if [ -f "$MODEL_DOWNLOADER_SCRIPT" ]; then
    log "Running model downloader script (this may take a while)..."
    # Run the script as the target user within the virtual environment
    # Pass --non-interactive if needed? Assume interactive for now.
    execute "sudo -u $INSTALL_USER bash -c 'source $VENV_DIR/bin/activate && python $MODEL_DOWNLOADER_SCRIPT'" "true" # Allow failure if models exist or user cancels
else
    log "${YELLOW}model_downloader.py not found.${NC}"
    log "${YELLOW}Manual model download required:${NC}"
    log " - Vosk: Download model, extract to $PROJECT_DIR/models/vosk/"
    log " - Piper: Download .onnx and .json files to $PROJECT_DIR/models/piper/"
    log " - Porcupine: Download .ppn file(s) from Picovoice Console to $PROJECT_DIR/models/porcupine/"
fi

# Step 8: Configure API Keys and Settings
log "\n${BOLD}${GREEN}Step 8: Configuration reminder...${NC}"
# Create .env file if it doesn't exist
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    log "Creating .env file template..."
    cat > "$ENV_FILE" << EOF
# --- EchoCore Environment Variables ---
# Required for online features

# Get from https://platform.openai.com/api-keys
OPENAI_API_KEY=""

# Get from https://picovoice.ai/console/
PICOVOICE_ACCESS_KEY=""

# Optional: Get from https://elevenlabs.io/
ELEVENLABS_API_KEY=""

EOF
    execute "chown $INSTALL_USER:$INSTALL_USER $ENV_FILE"
    execute "chmod 600 $ENV_FILE" # Restrict permissions
    log "${YELLOW}IMPORTANT: Edit $ENV_FILE and add your API keys.${NC}"
else
    log ".env file already exists. Ensure API keys are set correctly."
    # Ensure permissions are restrictive
    execute "chmod 600 $ENV_FILE" "true"
fi

# Remind about user_config.json
log "User-specific settings can be added to $PROJECT_DIR/user_config.json to override defaults."
USER_CONFIG_EXAMPLE="$PROJECT_DIR/user_config.json.example"
USER_CONFIG_FILE="$PROJECT_DIR/user_config.json"
if [ -f "$USER_CONFIG_EXAMPLE" ] && [ ! -f "$USER_CONFIG_FILE" ]; then
    log "Copying user_config.json.example to user_config.json..."
    execute "cp $USER_CONFIG_EXAMPLE $USER_CONFIG_FILE"
    execute "chown $INSTALL_USER:$INSTALL_USER $USER_CONFIG_FILE"
fi


# Step 9: Piper TTS Executable Reminder (if needed)
# Check config if Piper is the selected engine (requires parsing config/user_config - complex for bash)
# Simpler: Always remind if Piper models directory seems populated or just generally.
if [ -d "$PROJECT_DIR/models/piper" ] && [ "$(ls -A $PROJECT_DIR/models/piper)" ]; then
     log "\n${BOLD}${YELLOW}Step 9: Piper TTS Executable Reminder${NC}"
     log "${YELLOW}If you plan to use Piper TTS (check config), ensure the 'piper' executable is installed${NC}"
     log "${YELLOW}and available in the system PATH. Installation methods vary; see Piper TTS documentation.${NC}"
     # Check if 'piper' command exists
     if command -v piper &> /dev/null; then
          log "${GREEN}'piper' command found in PATH.${NC}"
     else
          log "${RED}'piper' command NOT found in PATH. Manual installation required.${NC}"
     fi
fi


# Step 10: Setup systemd Service
log "\n${BOLD}${GREEN}Step 10: Setting up systemd service (echocore.service)...${NC}"
SERVICE_FILE="/etc/systemd/system/echocore.service"

log "Creating systemd service file at $SERVICE_FILE..."
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Project EchoCore AI Assistant
# Wants=network-online.target # Waits for network config
After=network.target network-online.target sound.target # Start after network and sound system
# If using X11 for Pygame:
# Requires=graphical.target
# After=graphical.target

[Service]
Type=simple
User=$INSTALL_USER
Group=$(id -gn $INSTALL_USER) # Use user's primary group
WorkingDirectory=$PROJECT_DIR
# Environment="DISPLAY=:0" # Uncomment if Pygame requires X11 display
# Environment="PA_ALSA_PLUGHW=1" # Potential ALSA/PulseAudio fix if needed
# Environment="PYTHONUNBUFFERED=1" # Ensure logs appear immediately
ExecStart=$VENV_DIR/bin/python $PROJECT_DIR/main.py
Restart=on-failure # Restart if it fails
RestartSec=10      # Wait 10s before restarting
# StandardOutput=append:$PROJECT_DIR/logs/echocore_stdout.log # Optional: Redirect stdout
# StandardError=append:$PROJECT_DIR/logs/echocore_stderr.log  # Optional: Redirect stderr
# Consider resource limits if needed:
# LimitNOFILE=65536
# CPUQuota=80%

[Install]
WantedBy=multi-user.target # Start on normal boot
# If using X11 for Pygame:
# WantedBy=graphical.target
EOF

execute "chmod 644 $SERVICE_FILE"
execute "systemctl daemon-reload"
log "Systemd service created."
log "To enable auto-start on boot: sudo systemctl enable echocore.service"
log "To start the service now: sudo systemctl start echocore.service"
log "To check status: sudo systemctl status echocore.service"
log "To view logs: sudo journalctl -u echocore.service -f"


# Step 11: Final Permissions
log "\n${BOLD}${GREEN}Step 11: Setting final permissions...${NC}"
execute "chown -R $INSTALL_USER:$INSTALL_USER $PROJECT_DIR"
# Ensure log directory is writable by the user
execute "chown -R $INSTALL_USER:$INSTALL_USER $PROJECT_DIR/logs" || true # Allow failure if dir doesn't exist yet


# --- Completion ---
log "\n${BOLD}${GREEN}--- EchoCore Installation Completed ---${NC}"
log ""
log "${BOLD}Next Steps:${NC}"
log " 1. ${YELLOW}Edit '$PROJECT_DIR/.env'${NC} to add your required API keys."
log " 2. Review '$PROJECT_DIR/user_config.json' for any desired setting overrides."
log " 3. Ensure required models (Vosk, Piper, Porcupine) are in '$PROJECT_DIR/models/'."
log "    (Run 'python model_downloader.py' again if needed)."
log " 4. If using Piper TTS, ensure the 'piper' executable is installed and in the PATH."
log " 5. Enable the service to start on boot: ${BOLD}sudo systemctl enable echocore.service${NC}"
log " 6. Start the service: ${BOLD}sudo systemctl start echocore.service${NC}"
log " 7. Check the status and logs:"
log "    - ${BOLD}sudo systemctl status echocore.service${NC}"
log "    - ${BOLD}sudo journalctl -u echocore.service -f${NC}"
log "    - Or check files in '$PROJECT_DIR/logs/'"
log ""
log "If using the Web Interface (check config), access it at: http://<your-pi-ip>:<port>"
log ""
log "${GREEN}Installation successful!${NC}"

exit 0

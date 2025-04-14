# web_interface.py
"""
Simple web interface for EchoCore configuration and monitoring.
"""
import os
import json
import logging
import threading
import time
import datetime
from pathlib import Path
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, Response, send_from_directory
from flask_httpauth import HTTPBasicAuth
from functools import wraps
import config
from state_manager import StateManager, State
from audio_utils import list_audio_devices, test_audio_device

# Setup logger
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__, 
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), 'static')
)
app.secret_key = os.urandom(24)
auth = HTTPBasicAuth()

# Create directories for templates and static files
os.makedirs(os.path.join(os.path.dirname(__file__), 'templates'), exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), 'static'), exist_ok=True)

# Global variables
start_time = time.time()
recent_activities = []
state_transitions = []
audio_devices_cache = None  # Cache for audio devices list

# Authentication
@auth.verify_password
def verify_password(username, password):
    if not config.WEB_INTERFACE_ENABLED:
        return False
    return username == config.WEB_INTERFACE_USERNAME and password == config.WEB_INTERFACE_PASSWORD

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth.verify_password(auth.get_auth_username(), auth.get_auth_password()):
            return auth.auth_error_callback()
        return f(*args, **kwargs)
    return decorated

# Helper functions
def get_uptime():
    """Return formatted uptime string."""
    uptime_seconds = time.time() - start_time
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if days > 0:
        return f"{int(days)}d {int(hours)}h {int(minutes)}m"
    elif hours > 0:
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
    elif minutes > 0:
        return f"{int(minutes)}m {int(seconds)}s"
    else:
        return f"{int(seconds)}s"

def get_system_stats():
    """Get CPU, memory and temperature stats."""
    try:
        import psutil
        cpu_usage = psutil.cpu_percent()
        memory_usage = psutil.virtual_memory().percent
        
        # Try to get Raspberry Pi temperature
        temperature = None
        try:
            if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temperature = float(f.read()) / 1000.0
        except:
            pass
            
        return {
            'cpu_usage': cpu_usage,
            'memory_usage': memory_usage,
            'temperature': temperature
        }
    except ImportError:
        # If psutil is not installed
        return {
            'cpu_usage': "N/A",
            'memory_usage': "N/A",
            'temperature': "N/A"
        }

def add_activity(description):
    """Add activity to recent activities list."""
    global recent_activities
    timestamp = time.strftime("%H:%M:%S")
    recent_activities.insert(0, {'time': timestamp, 'description': description})
    # Keep only the last 10 activities
    if len(recent_activities) > 10:
        recent_activities = recent_activities[:10]

def add_state_transition(old_state, new_state):
    """Add state transition to history."""
    global state_transitions
    timestamp = time.strftime("%H:%M:%S")
    state_transitions.append({
        'time': timestamp,
        'old_state': old_state.name if old_state else "None",
        'new_state': new_state.name
    })
    # Keep only the last 100 transitions
    if len(state_transitions) > 100:
        state_transitions = state_transitions[1:]

def load_logs(n_lines=100):
    """Load the last n lines from the log file."""
    log_lines = []
    log_path = config.LOG_FILE
    
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r') as f:
                # Get the last n lines efficiently
                lines = []
                for line in f:
                    lines.append(line)
                    if len(lines) > n_lines:
                        lines.pop(0)
                
            for line in lines:
                # Basic parsing of log lines based on format
                parts = line.split(" - ")
                if len(parts) >= 3:
                    timestamp = parts[0]
                    level = parts[1]
                    message = " - ".join(parts[2:])
                    
                    # Determine level class for styling
                    level_class = "info"
                    if "ERROR" in level:
                        level_class = "error"
                    elif "WARNING" in level:
                        level_class = "warning"
                    elif "DEBUG" in level:
                        level_class = "debug"
                        
                    log_lines.append({
                        'timestamp': timestamp,
                        'level': level.strip(),
                        'level_class': level_class,
                        'message': message.strip()
                    })
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            log_lines.append({
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                'level': 'ERROR',
                'level_class': 'error',
                'message': f"Error reading log file: {e}"
            })
    
    return log_lines

def get_audio_devices():
    """Get audio input and output devices."""
    global audio_devices_cache
    
    if audio_devices_cache is None:
        try:
            inputs, outputs = list_audio_devices()
            audio_devices_cache = {
                'inputs': inputs,
                'outputs': outputs
            }
        except Exception as e:
            logger.error(f"Error listing audio devices: {e}")
            audio_devices_cache = {
                'inputs': [],
                'outputs': [],
                'error': str(e)
            }
    
    return audio_devices_cache

def save_user_config(updated_config):
    """Save updated config to user_config.json."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'user_config.json')
        
        # Read existing config if it exists
        existing_config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    existing_config = json.load(f)
            except json.JSONDecodeError:
                # If file exists but is not valid JSON, start fresh
                existing_config = {}
        
        # Update with new values
        existing_config.update(updated_config)
        
        # Write back to file
        with open(config_path, 'w') as f:
            json.dump(existing_config, f, indent=2)
            
        return True, "Settings saved successfully"
    except Exception as e:
        logger.exception(f"Error saving user config: {e}")
        return False, f"Error saving settings: {str(e)}"

# Routes
@app.route('/')
@login_required
def index():
    stats = get_system_stats()
    state_obj = getattr(app, 'state_manager', None)
    current_state = "UNKNOWN"
    
    if state_obj:
        current_state = state_obj.get_state().name
    
    # Get error message if in ERROR state
    error_message = None
    if state_obj and current_state == "ERROR":
        error_message = state_obj.get_error_message()
    
    return render_template('index.html', 
        status=current_state,
        error_message=error_message,
        uptime=get_uptime(),
        cpu_usage=stats['cpu_usage'],
        memory_usage=stats['memory_usage'],
        temperature=stats['temperature'],
        recent_activities=recent_activities,
        recent_transitions=state_transitions[-5:] if state_transitions else []
    )

@app.route('/settings', methods=['GET'])
@login_required
def settings():
    # Get audio devices
    audio_devices = get_audio_devices()
    
    # Read user_config.json if it exists
    user_config_path = os.path.join(os.path.dirname(__file__), 'user_config.json')
    user_config = {}
    if os.path.exists(user_config_path):
        try:
            with open(user_config_path, 'r') as f:
                user_config = json.load(f)
        except Exception as e:
            flash(f"Error reading user config: {e}", "danger")
    
    return render_template('settings.html', 
        config=config,
        user_config=user_config,
        audio_inputs=audio_devices.get('inputs', []),
        audio_outputs=audio_devices.get('outputs', [])
    )

@app.route('/settings', methods=['POST'])
@login_required
def save_settings():
    updated_config = {}
    
    # Process form data - convert types appropriately
    for key, value in request.form.items():
        # Skip keys that start with "#" (comments in JSON)
        if key.startswith('#'):
            continue
        
        # Handle numeric values
        if key in ['LISTENING_TIMEOUT', 'STT_CONFIDENCE_THRESHOLD', 'LLM_TEMPERATURE',
                  'ELEVENLABS_STABILITY', 'ELEVENLABS_SIMILARITY', 'AUDIO_AMPLITUDE_SCALING_DIVISOR']:
            try:
                updated_config[key] = float(value)
            except ValueError:
                flash(f"Invalid value for {key}", "danger")
                return redirect(url_for('settings'))
                
        elif key in ['LLM_MAX_CONVERSATION_TURNS', 'LLM_MAX_TOKENS', 'LOG_MAX_SIZE', 
                    'LOG_BACKUP_COUNT', 'AVATAR_WINDOW_WIDTH', 'AVATAR_WINDOW_HEIGHT',
                    'AVATAR_MIN_RADIUS', 'AVATAR_FPS', 'WEB_INTERFACE_PORT']:
            try:
                updated_config[key] = int(value)
            except ValueError:
                flash(f"Invalid value for {key}", "danger")
                return redirect(url_for('settings'))
                
        # Handle boolean values  
        elif key in ['ENABLE_AUDIO_CUES', 'TTS_STREAMING', 'TTS_CACHE_ENABLED',
                    'AVATAR_DISPLAY_STATUS_TEXT', 'AVATAR_FULLSCREEN', 'AVATAR_DEBUG_OVERLAY',
                    'WEB_INTERFACE_ENABLED', 'LLM_OFFLINE_FALLBACK_ENABLED']:
            updated_config[key] = value == 'true'
            
        # Handle special device index values
        elif key in ['AUDIO_INPUT_DEVICE_INDEX', 'AUDIO_OUTPUT_DEVICE_INDEX']:
            if value == 'null' or value == '':
                updated_config[key] = None
            else:
                try:
                    updated_config[key] = int(value)
                except ValueError:
                    flash(f"Invalid device index for {key}", "danger")
                    return redirect(url_for('settings'))
            
        # Handle all other string values
        else:
            updated_config[key] = value
    
    # Save config
    success, message = save_user_config(updated_config)
    
    if success:
        flash(message, "success")
        add_activity("Settings updated")
        # Note: Config changes will take effect after restart
    else:
        flash(message, "danger")
        
    return redirect(url_for('settings'))

@app.route('/audio-test', methods=['POST'])
@login_required
def audio_test():
    """Test an audio device."""
    device_type = request.form.get('device_type', 'output')
    device_index = request.form.get('device_index', 'null')
    
    # Convert device_index to proper type
    if device_index == 'null':
        device_index = None
    else:
        try:
            device_index = int(device_index)
        except ValueError:
            return jsonify({
                'success': False,
                'message': 'Invalid device index'
            })
    
    # Perform audio test
    try:
        result = test_audio_device(device_index=device_index, mode=device_type)
        if result:
            add_activity(f"Audio {device_type} test successful on device {device_index}")
            return jsonify({
                'success': True,
                'message': f'Audio {device_type} test successful'
            })
        else:
            return jsonify({
                'success': False,
                'message': f'Audio {device_type} test failed'
            })
    except Exception as e:
        logger.exception(f"Error during audio test: {e}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@app.route('/logs')
@login_required
def logs():
    log_data = load_logs(100)  # Load last 100 log lines
    return render_template('logs.html', logs=log_data)

@app.route('/download_logs')
@login_required
def download_logs():
    log_path = config.LOG_FILE
    
    if not os.path.exists(log_path):
        flash("Log file not found", "danger")
        return redirect(url_for('logs'))
    
    try:
        # Create a generator to stream the file
        def generate():
            with open(log_path, 'rb') as f:
                yield from f
                
        return Response(
            generate(),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment;filename=echocore_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"}
        )
    except Exception as e:
        flash(f"Error downloading logs: {str(e)}", "danger")
        return redirect(url_for('logs'))

@app.route('/actions', methods=['POST'])
@login_required
def perform_action():
    action = request.form.get('action')
    
    if action == 'restart':
        # Get references to needed components
        llm_handler = getattr(app, 'llm_handler', None)
        state_manager = getattr(app, 'state_manager', None)
        
        # Reset state and conversation if available
        if state_manager:
            state_manager.clear_error()
            if state_manager.get_state() != State.IDLE:
                state_manager.set_state(State.IDLE)
        
        if llm_handler:
            try:
                llm_handler.reset_conversation()
            except Exception as e:
                logger.error(f"Error resetting conversation: {e}")
                
        add_activity("System reset requested")
        flash("Reset request sent. System state has been reset.", "success")
    
    elif action == 'reset_conversation':
        # Reset LLM conversation history
        llm_handler = getattr(app, 'llm_handler', None)
        if llm_handler:
            try:
                llm_handler.reset_conversation()
                add_activity("Conversation history reset")
                flash("Conversation history has been reset.", "success")
            except Exception as e:
                flash(f"Error resetting conversation: {str(e)}", "danger")
        else:
            flash("Could not access LLM handler.", "danger")
    
    elif action == 'test_audio':
        # Test audio output with default device
        try:
            result = test_audio_device()
            add_activity("Audio test executed")
            
            if result:
                flash("Audio test completed successfully.", "success")
            else:
                flash("Audio test failed. Check logs for details.", "danger")
        except Exception as e:
            flash(f"Audio test error: {str(e)}", "danger")
    
    return redirect(url_for('index'))

@app.route('/favicon.ico')
def favicon():
    """Serve favicon to prevent 404 errors in logs."""
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico', mimetype='image/vnd.microsoft.icon'
    )

# API endpoints for programmatic access
@app.route('/api/status')
@login_required
def api_status():
    stats = get_system_stats()
    state_obj = getattr(app, 'state_manager', None)
    current_state = "UNKNOWN"
    
    if state_obj:
        current_state = state_obj.get_state().name
        
    return jsonify({
        'status': current_state,
        'uptime': get_uptime(),
        'stats': stats,
        'activities': recent_activities
    })

@app.route('/api/logs')
@login_required
def api_logs():
    count = request.args.get('count', '50')
    try:
        count = int(count)
    except ValueError:
        count = 50
    
    log_data = load_logs(count)
    return jsonify({
        'logs': log_data
    })

@app.route('/api/devices')
@login_required
def api_devices():
    # Force refresh of device cache
    global audio_devices_cache
    audio_devices_cache = None
    
    audio_devices = get_audio_devices()
    return jsonify(audio_devices)

# Web interface thread
class WebInterfaceThread(threading.Thread):
    def __init__(self, state_manager=None, llm_handler=None, stop_event=None):
        super().__init__(daemon=True)
        self.state_manager = state_manager
        self.llm_handler = llm_handler
        self.stop_event = stop_event
        self.previous_state = None
        
    def run(self):
        if not config.WEB_INTERFACE_ENABLED:
            logger.info("Web interface disabled in config.")
            return
            
        try:
            # Attach references to Flask application context
            app.state_manager = self.state_manager
            app.llm_handler = self.llm_handler
            
            # Setup state change monitoring
            if self.state_manager:
                self.previous_state = self.state_manager.get_state()
                
                # Use a separate thread to monitor state changes
                def monitor_state_changes():
                    while not (self.stop_event and self.stop_event.is_set()):
                        current_state = self.state_manager.get_state()
                        if current_state != self.previous_state:
                            # Record the transition
                            add_state_transition(self.previous_state, current_state)
                            self.previous_state = current_state
                        time.sleep(0.1)  # Check frequently but not too often
                
                monitor_thread = threading.Thread(
                    target=monitor_state_changes, 
                    daemon=True
                )
                monitor_thread.start()
            
            # Create basic favicon.ico if it doesn't exist
            favicon_path = os.path.join(app.static_folder, 'favicon.ico')
            if not os.path.exists(favicon_path):
                # This is a minimal 16x16 blue favicon
                with open(favicon_path, 'wb') as f:
                    f.write(bytes.fromhex('00000100010010100000010020006804000016000000280000001000000020000000010020000000000000040000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000073E9FF0073E9FF1173E9FF6373E9FFA273E9FFCE73E9FFDC73E9FFDC73E9FFCE73E9FFA273E9FF6373E9FF1173E9FF000000000000000000000000000000000073E9FF0073E9FF5A73E9FFD673E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFD673E9FF5A0000000000000000000000000073E9FF1173E9FFD673E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFD673E9FF1100000000000000000073E9FF6373E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000A273E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000CE73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000DC73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000DC73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000CE73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000A273E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000000073E9FF6373E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FF63000000000000000000000000000073E9FF1173E9FFD673E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFD673E9FF11000000000000000000000000000000000073E9FF0073E9FF5A73E9FFD673E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFD673E9FF5A73E9FF00000000000000000000000000000000000000000000000073E9FF0073E9FF1173E9FF6373E9FFA273E9FFCE73E9FFDC73E9FFDC73E9FFCE73E9FFA273E9FF6373E9FF1173E9FF0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'))
            
            # Run the Flask application
            logger.info(f"Starting web interface on {config.WEB_INTERFACE_HOST}:{config.WEB_INTERFACE_PORT}")
            app.run(
                host=config.WEB_INTERFACE_HOST, 
                port=config.WEB_INTERFACE_PORT,
                debug=False,
                use_reloader=False
            )
        except Exception as e:
            logger.exception(f"Error in web interface: {e}")
        finally:
            if self.stop_event and not self.stop_event.is_set():
                logger.info("Web interface stopped.")

# Create the necessary CSS and JS files
def create_static_files():
    # Create CSS file
    css_path = os.path.join(app.static_folder, 'style.css')
    if not os.path.exists(css_path):
        with open(css_path, 'w') as f:
            f.write("""
/* EchoCore Web Interface */
:root {
    --primary-color: #3498db;
    --primary-dark: #2980b9;
    --secondary-color: #2ecc71;
    --error-color: #e74c3c;
    --warning-color: #f39c12;
    --background-dark: #121212;
    --background-card: #1e1e1e;
    --background-nav: #282828;
    --text-color: #ecf0f1;
    --text-muted: #95a5a6;
    --border-color: #333;
}

body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    margin: 0;
    padding: 0;
    background-color: var(--background-dark);
    color: var(--text-color);
    line-height: 1.6;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}

header {
    background-color: var(--background-card);
    padding: 20px;
    border-bottom: 1px solid var(--border-color);
    margin-bottom: 20px;
}

header h1 {
    margin: 0;
    color: var(--primary-color);
    font-size: 28px;
}

nav {
    background-color: var(--background-nav);
    padding: 10px 20px;
    margin-bottom: 20px;
}

nav a {
    color: var(--text-color);
    text-decoration: none;
    margin-right: 20px;
    font-weight: bold;
    padding: 5px 10px;
    border-radius: 4px;
    transition: background-color 0.2s;
}

nav a:hover {
    background-color: rgba(255, 255, 255, 0.1);
    color: var(--primary-color);
}

.card {
    background-color: var(--background-card);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 20px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
}

.card h2 {
    margin-top: 0;
    color: var(--primary-color);
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 10px;
    margin-bottom: 20px;
    font-size: 20px;
}

.card h3 {
    color: var(--text-color);
    font-size: 18px;
    margin-top: 25px;
    margin-bottom: 15px;
}

label {
    display: block;
    margin-bottom: 5px;
    font-weight: bold;
    color: var(--text-color);
}

input, select, textarea {
    width: 100%;
    padding: 10px;
    margin-bottom: 15px;
    background-color: #333;
    border: 1px solid #444;
    border-radius: 4px;
    color: var(--text-color);
    font-family: inherit;
    font-size: 14px;
}

button, .btn {
    background-color: var(--primary-color);
    color: white;
    border: none;
    padding: 10px 15px;
    border-radius: 4px;
    cursor: pointer;
    font-weight: bold;
    transition: background-color 0.2s;
    font-size: 14px;
    display: inline-block;
    text-decoration: none;
}

button:hover, .btn:hover {
    background-color: var(--primary-dark);
}

.btn-small {
    padding: 5px 10px;
    font-size: 12px;
}

.btn-danger {
    background-color: var(--error-color);
}

.btn-secondary {
    background-color: var(--secondary-color);
}

.btn-warning {
    background-color: var(--warning-color);
}

.alert {
    padding: 15px;
    border-radius: 4px;
    margin-bottom: 20px;
    border: 1px solid transparent;
}

.alert-success {
    background-color: rgba(46, 204, 113, 0.2);
    border-color: var(--secondary-color);
    color: #27ae60;
}

.alert-danger {
    background-color: rgba(231, 76, 60, 0.2);
    border-color: var(--error-color);
    color: #e74c3c;
}

.alert-warning {
    background-color: rgba(243, 156, 18, 0.2);
    border-color: var(--warning-color);
    color: #f39c12;
}

.status-indicator {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 8px;
}

.status-idle { background-color: var(--primary-color); }
.status-listening { background-color: #f1c40f; } /* Yellow */
.status-processing_stt { background-color: #9b59b6; } /* Purple */
.status-thinking { background-color: #e67e22; } /* Orange */
.status-synthesizing_tts { background-color: #1abc9c; } /* Teal */
.status-speaking { background-color: var(--secondary-color); } /* Green */
.status-error { background-color: var(--error-color); } /* Red */
.status-unknown { background-color: var(--text-muted); } /* Gray */

.log-container {
    background-color: #0d0d0d;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 10px;
    height: 500px;
    overflow-y: auto;
    font-family: 'Courier New', monospace;
    margin-bottom: 15px;
    font-size: 13px;
}

.log-line {
    margin: 0;
    padding: 3px 0;
    border-bottom: 1px solid #1a1a1a;
    white-space: pre-wrap;
    word-break: break-word;
}

.log-error {
    color: #e74c3c;
}

.log-warning {
    color: #f39c12;
}

.log-info {
    color: #3498db;
}

.log-debug {
    color: #95a5a6;
}

.form-group {
    margin-bottom: 20px;
}

.form-check {
    display: flex;
    align-items: center;
    margin-bottom: 15px;
}

.form-check input[type="checkbox"] {
    width: auto;
    margin-right: 10px;
    margin-bottom: 0;
}

.grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}

.flex {
    display: flex;
    gap: 10px;
}

.flex-between {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.stat-box {
    display: flex;
    align-items: center;
    background-color: rgba(255, 255, 255, 0.05);
    padding: 15px;
    border-radius: 5px;
    margin-bottom: 10px;
}

.stat-icon {
    margin-right: 15px;
    font-size: 24px;
    color: var(--primary-color);
}

.stat-info h4 {
    margin: 0;
    font-size: 14px;
    color: var(--text-muted);
}

.stat-info p {
    margin: 5px 0 0 0;
    font-size: 18px;
    font-weight: bold;
}

.activity-list {
    list-style: none;
    padding: 0;
    margin: 0;
}

.activity-list li {
    padding: 8px 0;
    border-bottom: 1px solid var(--border-color);
}

.activity-list .time {
    color: var(--text-muted);
    font-size: 12px;
    margin-right: 10px;
}

.transitions-list {
    padding: 0;
    margin: 0;
    list-style: none;
}

.transitions-list li {
    padding: 8px 0;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
}

.transitions-list .time {
    color: var(--text-muted);
    font-size: 12px;
    width: 80px;
}

.transitions-list .arrow {
    margin: 0 10px;
    color: var(--primary-color);
}

.transitions-list .state {
    padding: 3px 8px;
    border-radius: 3px;
    background-color: rgba(255, 255, 255, 0.1);
    font-size: 12px;
}

.filter-controls {
    margin-bottom: 15px;
    display: flex;
    gap: 10px;
}

.settings-section {
    margin-bottom: 30px;
}

.collapsible {
    cursor: pointer;
    background-color: var(--background-nav);
    padding: 10px 15px;
    margin-bottom: 10px;
    border-radius: 4px;
    position: relative;
}

.collapsible::after {
    content: "+";
    position: absolute;
    right: 15px;
    top: 10px;
}

.collapsible.active::after {
    content: "-";
}

.collapsible-content {
    display: none;
    padding: 15px;
    background-color: rgba(255, 255, 255, 0.05);
    border-radius: 4px;
    margin-bottom: 15px;
}

.device-list {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 20px;
}

.device-card {
    background-color: rgba(255, 255, 255, 0.05);
    padding: 15px;
    border-radius: 5px;
    position: relative;
}

.device-card h4 {
    margin-top: 0;
    margin-bottom: 10px;
    font-size: 16px;
}

.device-card .device-id {
    position: absolute;
    top: 10px;
    right: 10px;
    background-color: var(--primary-color);
    color: white;
    padding: 2px 6px;
    border-radius: 10px;
    font-size: 12px;
}

.device-card p {
    color: var(--text-muted);
    margin: 5px 0;
    font-size: 14px;
}

.device-card .btn {
    margin-top: 10px;
}

/* Error message styling */
.error-message {
    background-color: rgba(231, 76, 60, 0.2);
    border: 1px solid var(--error-color);
    padding: 15px;
    border-radius: 4px;
    margin-bottom: 20px;
    color: #e74c3c;
}

.error-message h3 {
    margin-top: 0;
    color: #e74c3c;
}

/* Responsive adjustments */
@media (max-width: 768px) {
    .grid {
        grid-template-columns: 1fr;
    }
    
    .device-list {
        grid-template-columns: 1fr;
    }
    
    .flex {
        flex-direction: column;
    }
    
    .container {
        padding: 10px;
    }
}

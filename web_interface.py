# web_interface.py
"""
Simple web interface for EchoCore configuration and monitoring.
"""
import os
import json
import logging
import threading
import time
from pathlib import Path
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, Response
from flask_httpauth import HTTPBasicAuth
from functools import wraps
import config
from state_manager import StateManager, State

# Setup logger
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__, 
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), 'static')
)
app.secret_key = os.urandom(24)
auth = HTTPBasicAuth()

# Directory creation
os.makedirs(os.path.join(os.path.dirname(__file__), 'templates'), exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), 'static'), exist_ok=True)

# Create simple CSS file
css_path = os.path.join(os.path.dirname(__file__), 'static', 'style.css')
if not os.path.exists(css_path):
    with open(css_path, 'w') as f:
        f.write("""
body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    margin: 0;
    padding: 0;
    background-color: #121212;
    color: #e0e0e0;
}
.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}
header {
    background-color: #1e1e1e;
    padding: 20px;
    border-bottom: 1px solid #333;
}
header h1 {
    margin: 0;
    color: #5c9ce6;
}
nav {
    background-color: #282828;
    padding: 10px 20px;
}
nav a {
    color: #e0e0e0;
    text-decoration: none;
    margin-right: 20px;
    font-weight: bold;
}
nav a:hover {
    color: #5c9ce6;
}
.card {
    background-color: #1e1e1e;
    border-radius: 5px;
    padding: 20px;
    margin-bottom: 20px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}
.card h2 {
    margin-top: 0;
    color: #5c9ce6;
    border-bottom: 1px solid #333;
    padding-bottom: 10px;
}
label {
    display: block;
    margin-bottom: 5px;
    font-weight: bold;
}
input, select, textarea {
    width: 100%;
    padding: 8px;
    margin-bottom: 15px;
    background-color: #333;
    border: 1px solid #444;
    border-radius: 4px;
    color: #e0e0e0;
}
button {
    background-color: #5c9ce6;
    color: white;
    border: none;
    padding: 10px 15px;
    border-radius: 4px;
    cursor: pointer;
    font-weight: bold;
}
button:hover {
    background-color: #4a7dbb;
}
.alert {
    padding: 10px;
    border-radius: 4px;
    margin-bottom: 15px;
}
.alert-success {
    background-color: #2e7d32;
    color: white;
}
.alert-danger {
    background-color: #c62828;
    color: white;
}
.status-indicator {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 8px;
}
.status-idle { background-color: #4a7dbb; }
.status-listening { background-color: #ffd700; }
.status-thinking { background-color: #ff9800; }
.status-speaking { background-color: #4caf50; }
.status-error { background-color: #f44336; }
.log-container {
    background-color: #121212;
    border: 1px solid #333;
    border-radius: 4px;
    padding: 10px;
    height: 300px;
    overflow-y: auto;
    font-family: monospace;
    margin-bottom: 15px;
}
.log-line {
    margin: 0;
    padding: 2px 0;
    border-bottom: 1px solid #222;
}
.form-group {
    margin-bottom: 20px;
}
.grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}
@media (max-width: 768px) {
    .grid {
        grid-template-columns: 1fr;
    }
}
""")

# Create template files
templates_dir = os.path.join(os.path.dirname(__file__), 'templates')

# Index template
index_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EchoCore Dashboard</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
    <meta http-equiv="refresh" content="10">
</head>
<body>
    <header>
        <div class="container">
            <h1>EchoCore Dashboard</h1>
        </div>
    </header>
    <nav>
        <div class="container">
            <a href="{{ url_for('index') }}">Dashboard</a>
            <a href="{{ url_for('settings') }}">Settings</a>
            <a href="{{ url_for('logs') }}">Logs</a>
        </div>
    </nav>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="card">
            <h2>System Status</h2>
            <p>
                <span class="status-indicator status-{{ status.lower() }}"></span>
                Current State: <strong>{{ status }}</strong>
            </p>
            <p>Uptime: {{ uptime }}</p>
            <p>CPU Usage: {{ cpu_usage }}%</p>
            <p>Memory Usage: {{ memory_usage }}%</p>
            <p>Temperature: {{ temperature }}°C</p>
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>State Transitions</h2>
                <canvas id="stateChart" width="400" height="200"></canvas>
            </div>
            
            <div class="card">
                <h2>Recent Activity</h2>
                <ul>
                    {% for activity in recent_activities %}
                        <li>{{ activity.time }}: {{ activity.description }}</li>
                    {% endfor %}
                </ul>
            </div>
        </div>
        
        <div class="card">
            <h2>Quick Actions</h2>
            <form method="post" action="{{ url_for('perform_action') }}">
                <button type="submit" name="action" value="restart">Restart EchoCore</button>
                <button type="submit" name="action" value="reset_conversation">Reset Conversation</button>
                <button type="submit" name="action" value="test_audio">Test Audio</button>
            </form>
        </div>
    </div>
    
    <script>
        // Simple placeholder for chart - would use Chart.js in production
        const ctx = document.getElementById('stateChart').getContext('2d');
        // Chart rendering code would go here
    </script>
</body>
</html>
"""

# Settings template
settings_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EchoCore Settings</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <header>
        <div class="container">
            <h1>EchoCore Settings</h1>
        </div>
    </header>
    <nav>
        <div class="container">
            <a href="{{ url_for('index') }}">Dashboard</a>
            <a href="{{ url_for('settings') }}">Settings</a>
            <a href="{{ url_for('logs') }}">Logs</a>
        </div>
    </nav>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="post" action="{{ url_for('save_settings') }}">
            <div class="card">
                <h2>General Settings</h2>
                <div class="form-group">
                    <label for="LISTENING_TIMEOUT">Listening Timeout (seconds)</label>
                    <input type="number" id="LISTENING_TIMEOUT" name="LISTENING_TIMEOUT" value="{{ config.LISTENING_TIMEOUT }}" step="0.1" min="1">
                </div>
                <div class="form-group">
                    <label for="STT_CONFIDENCE_THRESHOLD">Speech Recognition Confidence Threshold</label>
                    <input type="number" id="STT_CONFIDENCE_THRESHOLD" name="STT_CONFIDENCE_THRESHOLD" value="{{ config.STT_CONFIDENCE_THRESHOLD }}" step="0.01" min="0" max="1">
                </div>
                <div class="form-group">
                    <label for="AVATAR_ANIMATION_STYLE">Avatar Animation Style</label>
                    <select id="AVATAR_ANIMATION_STYLE" name="AVATAR_ANIMATION_STYLE">
                        <option value="circle" {% if config.AVATAR_ANIMATION_STYLE == 'circle' %}selected{% endif %}>Circle</option>
                        <option value="wave" {% if config.AVATAR_ANIMATION_STYLE == 'wave' %}selected{% endif %}>Wave</option>
                        <option value="particle" {% if config.AVATAR_ANIMATION_STYLE == 'particle' %}selected{% endif %}>Particle</option>
                        <option value="hologram" {% if config.AVATAR_ANIMATION_STYLE == 'hologram' %}selected{% endif %}>Hologram</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="ENABLE_AUDIO_CUES">Enable Audio Cues</label>
                    <input type="checkbox" id="ENABLE_AUDIO_CUES" name="ENABLE_AUDIO_CUES" {% if config.ENABLE_AUDIO_CUES %}checked{% endif %}>
                </div>
            </div>
            
            <div class="card">
                <h2>LLM Settings</h2>
                <div class="form-group">
                    <label for="LLM_MODEL">OpenAI Model</label>
                    <select id="LLM_MODEL" name="LLM_MODEL">
                        <option value="gpt-4o" {% if config.LLM_MODEL == 'gpt-4o' %}selected{% endif %}>GPT-4o</option>
                        <option value="gpt-4o-mini" {% if config.LLM_MODEL == 'gpt-4o-mini' %}selected{% endif %}>GPT-4o Mini</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="LLM_MAX_CONVERSATION_TURNS">Max Conversation History</label>
                    <input type="number" id="LLM_MAX_CONVERSATION_TURNS" name="LLM_MAX_CONVERSATION_TURNS" value="{{ config.LLM_MAX_CONVERSATION_TURNS }}" min="1" max="20">
                </div>
                <div class="form-group">
                    <label for="LLM_SYSTEM_PROMPT">System Prompt</label>
                    <textarea id="LLM_SYSTEM_PROMPT" name="LLM_SYSTEM_PROMPT" rows="4">{{ config.LLM_SYSTEM_PROMPT }}</textarea>
                </div>
            </div>
            
            <div class="card">
                <h2>TTS Settings</h2>
                <div class="form-group">
                    <label for="TTS_ENGINE">TTS Engine</label>
                    <select id="TTS_ENGINE" name="TTS_ENGINE">
                        <option value="openai" {% if config.TTS_ENGINE == 'openai' %}selected{% endif %}>OpenAI</option>
                        <option value="elevenlabs" {% if config.TTS_ENGINE == 'elevenlabs' %}selected{% endif %}>ElevenLabs</option>
                        <option value="piper" {% if config.TTS_ENGINE == 'piper' %}selected{% endif %}>Piper (Local)</option>
                    </select>
                </div>
                <div class="form-group openai-options" {% if config.TTS_ENGINE != 'openai' %}style="display:none;"{% endif %}>
                    <label for="OPENAI_TTS_VOICE">OpenAI Voice</label>
                    <select id="OPENAI_TTS_VOICE" name="OPENAI_TTS_VOICE">
                        <option value="alloy" {% if config.OPENAI_TTS_VOICE == 'alloy' %}selected{% endif %}>Alloy</option>
                        <option value="echo" {% if config.OPENAI_TTS_VOICE == 'echo' %}selected{% endif %}>Echo</option>
                        <option value="fable" {% if config.OPENAI_TTS_VOICE == 'fable' %}selected{% endif %}>Fable</option>
                        <option value="onyx" {% if config.OPENAI_TTS_VOICE == 'onyx' %}selected{% endif %}>Onyx</option>
                        <option value="nova" {% if config.OPENAI_TTS_VOICE == 'nova' %}selected{% endif %}>Nova</option>
                        <option value="shimmer" {% if config.OPENAI_TTS_VOICE == 'shimmer' %}selected{% endif %}>Shimmer</option>
                    </select>
                </div>
                <div class="form-group elevenlabs-options" {% if config.TTS_ENGINE != 'elevenlabs' %}style="display:none;"{% endif %}>
                    <label for="ELEVENLABS_VOICE">ElevenLabs Voice</label>
                    <input type="text" id="ELEVENLABS_VOICE" name="ELEVENLABS_VOICE" value="{{ config.ELEVENLABS_VOICE }}">
                </div>
            </div>
            
            <button type="submit">Save Settings</button>
        </form>
    </div>
    
    <script>
        document.getElementById('TTS_ENGINE').addEventListener('change', function() {
            const engine = this.value;
            document.querySelectorAll('.openai-options, .elevenlabs-options').forEach(el => {
                el.style.display = 'none';
            });
            if (engine === 'openai') {
                document.querySelectorAll('.openai-options').forEach(el => {
                    el.style.display = 'block';
                });
            } else if (engine === 'elevenlabs') {
                document.querySelectorAll('.elevenlabs-options').forEach(el => {
                    el.style.display = 'block';
                });
            }
        });
    </script>
</body>
</html>
"""

# Logs template
logs_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EchoCore Logs</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <header>
        <div class="container">
            <h1>EchoCore Logs</h1>
        </div>
    </header>
    <nav>
        <div class="container">
            <a href="{{ url_for('index') }}">Dashboard</a>
            <a href="{{ url_for('settings') }}">Settings</a>
            <a href="{{ url_for('logs') }}">Logs</a>
        </div>
    </nav>
    
    <div class="container">
        <div class="card">
            <h2>System Logs</h2>
            <div class="form-group">
                <label for="log-level">Log Level</label>
                <select id="log-level" onchange="filterLogs()">
                    <option value="all">All</option>
                    <option value="info">Info</option>
                    <option value="warning">Warning</option>
                    <option value="error">Error</option>
                </select>
            </div>
            <div class="log-container" id="log-container">
                {% for log in logs %}
                    <pre class="log-line log-{{ log.level|lower }}">{{ log.timestamp }} [{{ log.level }}] {{ log.message }}</pre>
                {% endfor %}
            </div>
            <button onclick="clearLogs()">Clear Logs</button>
            <button onclick="downloadLogs()">Download Logs</button>
        </div>
    </div>
    
    <script>
        function filterLogs() {
            const level = document.getElementById('log-level').value;
            const logs = document.querySelectorAll('.log-line');
            
            logs.forEach(log => {
                if (level === 'all' || log.classList.contains('log-' + level)) {
                    log.style.display = 'block';
                } else {
                    log.style.display = 'none';
                }
            });
        }
        
        function clearLogs() {
            if (confirm('Are you sure you want to clear the logs display? This does not delete log files.')) {
                document.getElementById('log-container').innerHTML = '';
            }
        }
        
        function downloadLogs() {
            window.location.href = "{{ url_for('download_logs') }}";
        }
    </script>
</body>
</html>
"""

# Save template files
with open(os.path.join(templates_dir, 'index.html'), 'w') as f:
    f.write(index_template)
    
with open(os.path.join(templates_dir, 'settings.html'), 'w') as f:
    f.write(settings_template)
    
with open(os.path.join(templates_dir, 'logs.html'), 'w') as f:
    f.write(logs_template)

# Global variables
start_time = time.time()
recent_activities = []
state_transitions = []

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

def load_logs(n_lines=100):
    """Load the last n lines from the log file."""
    log_lines = []
    log_path = config.LOG_FILE
    
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()[-n_lines:]
                
            for line in lines:
                # Basic parsing, would need to be adjusted based on actual log format
                parts = line.split(" - ")
                if len(parts) >= 3:
                    timestamp = parts[0]
                    level = parts[1]
                    message = " - ".join(parts[2:])
                    log_lines.append({
                        'timestamp': timestamp,
                        'level': level.strip(),
                        'message': message.strip()
                    })
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            log_lines.append({
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                'level': 'ERROR',
                'message': f"Error reading log file: {e}"
            })
    
    return log_lines

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
            json.dump(existing_config, f, indent=4)
            
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
    
    return render_template('index.html', 
        status=current_state,
        uptime=get_uptime(),
        cpu_usage=stats['cpu_usage'],
        memory_usage=stats['memory_usage'],
        temperature=stats['temperature'],
        recent_activities=recent_activities
    )

@app.route('/settings', methods=['GET'])
@login_required
def settings():
    return render_template('settings.html', config=config)

@app.route('/settings', methods=['POST'])
@login_required
def save_settings():
    updated_config = {}
    
    # Process form data - convert types appropriately
    for key, value in request.form.items():
        if key in ['LISTENING_TIMEOUT', 'STT_CONFIDENCE_THRESHOLD']:
            try:
                updated_config[key] = float(value)
            except ValueError:
                flash(f"Invalid value for {key}", "danger")
                return redirect(url_for('settings'))
                
        elif key in ['LLM_MAX_CONVERSATION_TURNS']:
            try:
                updated_config[key] = int(value)
            except ValueError:
                flash(f"Invalid value for {key}", "danger")
                return redirect(url_for('settings'))
                
        elif key in ['ENABLE_AUDIO_CUES']:
            updated_config[key] = 'ENABLE_AUDIO_CUES' in request.form
            
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
            headers={"Content-Disposition": "attachment;filename=echocore.log"}
        )
    except Exception as e:
        flash(f"Error downloading logs: {str(e)}", "danger")
        return redirect(url_for('logs'))

@app.route('/actions', methods=['POST'])
@login_required
def perform_action():
    action = request.form.get('action')
    
    if action == 'restart':
        # In a real implementation, this would restart the application
        add_activity("System restart requested")
        flash("Restart request sent. System will restart momentarily.", "success")
    
    elif action == 'reset_conversation':
        # Reset LLM conversation history
        llm_handler = getattr(app, 'llm_handler', None)
        if llm_handler:
            llm_handler.reset_conversation()
            add_activity("Conversation history reset")
            flash("Conversation history has been reset.", "success")
        else:
            flash("Could not access LLM handler.", "danger")
    
    elif action == 'test_audio':
        # In a real implementation, this would play a test sound
        add_activity("Audio test requested")
        flash("Audio test signal sent.", "success")
    
    return redirect(url_for('index'))

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
        'stats': stats
    })

# Web interface thread
class WebInterfaceThread(threading.Thread):
    def __init__(self, state_manager=None, llm_handler=None, stop_event=None):
        super().__init__(daemon=True)
        self.state_manager = state_manager
        self.llm_handler = llm_handler
        self.stop_event = stop_event
        
    def run(self):
        if not config.WEB_INTERFACE_ENABLED:
            logger.info("Web interface disabled in config.")
            return
            
        try:
            # Attach references to Flask application context
            app.state_manager = self.state_manager
            app.llm_handler = self.llm_handler
            
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

# For testing standalone
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting web interface in standalone mode...")
    
    # Enable web interface for testing
    config.WEB_INTERFACE_ENABLED = True
    
    web_thread = WebInterfaceThread()
    web_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")

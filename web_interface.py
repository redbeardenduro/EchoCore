# web_interface.py
"""
Provides a web-based interface for EchoCore monitoring and configuration using Flask.
Runs as a separate thread and interacts with other system components.
"""

import os
import json
import logging
import threading
import time
import datetime
import sys
from pathlib import Path
from functools import wraps
from typing import List, Dict, Any, Optional, Tuple, Callable # For type hinting

# Flask and related imports
try:
    from flask import (
        Flask, request, render_template, redirect, url_for,
        flash, jsonify, Response, send_from_directory, abort
    )
    from flask_httpauth import HTTPBasicAuth
    # Consider adding CSRF protection if using forms extensively without other mitigations
    # from flask_wtf.csrf import CSRFProtect
except ImportError:
    logging.critical("Flask or Flask-HTTPAuth not found. Web interface cannot function.")
    logging.critical("Please install them: pip install Flask Flask-HTTPAuth")
    # Define dummy classes/functions if needed to prevent load errors elsewhere
    Flask = None # type: ignore
    HTTPBasicAuth = None # type: ignore
    # raise # Or raise if Flask is critical

# Import project modules
try:
    import config # Use enhanced config module
    from state_manager import StateManager, State
    from audio_utils import list_audio_devices, test_audio_device
    # Import LLMHandler type for type hinting if needed, careful with circular imports
    # from llm_handler import LLMHandler # Might cause circular dependency
except ImportError as e:
    logging.error(f"Error importing project modules in web_interface.py: {e}")
    raise

# Setup logger
logger = logging.getLogger(__name__)

# --- Flask App Setup ---
# Check if Flask loaded correctly
if Flask is None or HTTPBasicAuth is None:
     # If Flask didn't import, define a dummy class to avoid NameErrors
     # This allows the rest of the application to potentially run without the web UI
     class WebInterfaceThread(threading.Thread): # type: ignore
         def __init__(self, *args, **kwargs):
             super().__init__(daemon=True)
             logger.error("Flask/Flask-HTTPAuth not available. Web Interface thread disabled.")
         def run(self):
             pass # Do nothing if Flask is missing
else:
    # --- Flask App Initialization ---
    # Use template/static folders defined in config
    app = Flask(
        __name__,
        template_folder=str(config.TEMPLATES_DIR),
        static_folder=str(config.STATIC_DIR)
    )
    app.secret_key = os.urandom(32) # Use a strong secret key
    auth = HTTPBasicAuth()
    # Optional: Add CSRF protection
    # csrf = CSRFProtect(app)

    # --- Global Variables & Thread Safety ---
    # Shared data structures accessed by multiple threads (Flask requests + monitor thread)
    # Need locks for thread-safe access
    _shared_data_lock = threading.Lock()
    _start_time: float = time.monotonic() # Use monotonic clock for uptime
    _recent_activities: List[Dict[str, str]] = [] # Store {'time': 'HH:MM:SS', 'description': '...'}
    _state_transitions: List[Dict[str, str]] = [] # Store {'time': 'HH:MM:SS', 'old_state': '...', 'new_state': '...'}
    _audio_devices_cache: Optional[Dict[str, Any]] = None # Cache for audio devices

    # --- Authentication ---
    @auth.verify_password
    def verify_password(username: str, password: str) -> bool:
        """Verify username and password against config."""
        # Always check if web interface is enabled first
        if not config.WEB_INTERFACE_ENABLED:
            logger.warning("Web interface access attempt denied (disabled in config).")
            return False
        # Compare with configured credentials
        is_valid = (username == config.WEB_INTERFACE_USERNAME and
                    password == config.WEB_INTERFACE_PASSWORD)
        if not is_valid:
             logger.warning(f"Failed login attempt for user: {username}")
        return is_valid

    # Decorator for requiring authentication
    login_required = auth.login_required

    # --- Helper Functions ---

    def get_uptime() -> str:
        """Return formatted uptime string."""
        uptime_seconds = time.monotonic() - _start_time
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        if days >= 1:
            return f"{int(days)}d {int(hours)}h {int(minutes)}m"
        elif hours >= 1:
            return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        else: # minutes >= 0 or seconds >= 0
            return f"{int(minutes)}m {int(seconds)}s"

    def get_system_stats() -> Dict[str, Any]:
        """Get CPU, memory, and temperature stats using psutil."""
        stats: Dict[str, Any] = {
            'cpu_usage': "N/A",
            'memory_usage': "N/A",
            'temperature': "N/A"
        }
        try:
            import psutil
            stats['cpu_usage'] = psutil.cpu_percent()
            stats['memory_usage'] = psutil.virtual_memory().percent

            # Try to get Raspberry Pi temperature (or other system temps)
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                # Look for common thermal zone names
                for name, entries in temps.items():
                     if 'coretemp' in name or 'cpu_thermal' in name or 'thermal_zone0' in name:
                         if entries:
                             stats['temperature'] = entries[0].current # Take first sensor reading
                             break # Found a likely CPU temp
            # Fallback for sysfs method (often on RPi)
            elif os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                 try:
                     with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                         stats['temperature'] = float(f.read()) / 1000.0
                 except (IOError, ValueError) as e:
                      logger.debug(f"Could not read temperature from sysfs: {e}")

        except ImportError:
            logger.warning("psutil library not found. System stats unavailable in web UI.")
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")

        return stats

    def add_activity(description: str) -> None:
        """Add activity to recent activities list (thread-safe)."""
        global _recent_activities
        timestamp = time.strftime("%H:%M:%S") # Consider using datetime for timezone awareness if needed
        with _shared_data_lock:
            _recent_activities.insert(0, {'time': timestamp, 'description': description})
            # Keep only the last N activities (e.g., 20)
            _recent_activities = _recent_activities[:20]

    def add_state_transition(old_state: Optional[State], new_state: State) -> None:
        """Add state transition to history (thread-safe)."""
        global _state_transitions
        timestamp = time.strftime("%H:%M:%S")
        old_state_name = old_state.name if old_state else "None"
        new_state_name = new_state.name

        # Avoid adding duplicate transitions if state flaps quickly
        with _shared_data_lock:
            if not _state_transitions or \
               (_state_transitions[-1]['old_state'] != old_state_name or
                _state_transitions[-1]['new_state'] != new_state_name):

                _state_transitions.append({
                    'time': timestamp,
                    'old_state': old_state_name,
                    'new_state': new_state_name
                })
                # Keep only the last N transitions (e.g., 50)
                if len(_state_transitions) > 50:
                     _state_transitions = _state_transitions[-50:] # Keep most recent


    def load_logs(n_lines: int = 100) -> List[Dict[str, str]]:
        """Load the last n lines from the log file."""
        log_lines: List[Dict[str, str]] = []
        log_path = config.LOG_FILE_PATH # Use resolved path from config

        if not log_path.exists():
            logger.warning(f"Log file not found at: {log_path}")
            return [{'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                     'level': 'WARNING', 'level_class': 'warning',
                     'message': f"Log file not found: {log_path}"}]

        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # More efficient way to get last N lines might involve seeking from end,
                # but this is simpler for moderate N.
                lines = f.readlines() # Read all lines (can be memory intensive for large files)
                last_lines = lines[-n_lines:]

            for line in last_lines:
                # Basic parsing assuming 'TIME - LEVEL - THREAD - NAME - MESSAGE' format
                parts = line.strip().split(' - ', 4) # Split max 4 times
                if len(parts) >= 5:
                    timestamp, level, thread, name, message = parts
                    level = level.strip()
                    level_class = level.lower() # Use log level name for CSS class
                    if level_class not in ['debug', 'info', 'warning', 'error', 'critical']:
                        level_class = 'info' # Default class

                    log_lines.append({
                        'timestamp': timestamp.strip(),
                        'level': level,
                        'level_class': level_class,
                        # Include thread/name if desired: 'message': f"[{thread}][{name}] {message.strip()}"
                        'message': message.strip()
                    })
                elif len(parts) >= 3: # Fallback for simpler format
                     timestamp, level, message = parts[0], parts[1], " - ".join(parts[2:])
                     level = level.strip()
                     level_class = level.lower()
                     if level_class not in ['debug', 'info', 'warning', 'error', 'critical']: level_class = 'info'
                     log_lines.append({'timestamp': timestamp.strip(), 'level': level, 'level_class': level_class, 'message': message.strip()})
                elif line.strip(): # Add non-empty lines that don't match format
                     log_lines.append({'timestamp': '?', 'level': 'UNKNOWN', 'level_class': 'info', 'message': line.strip()})

        except Exception as e:
            logger.error(f"Error reading log file {log_path}: {e}")
            log_lines.append({
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"), 'level': 'ERROR', 'level_class': 'error',
                'message': f"Error reading log file: {e}"})

        return log_lines

    def get_audio_devices() -> Dict[str, Any]:
        """Get audio devices using audio_utils (with caching)."""
        global _audio_devices_cache
        # Simple time-based cache invalidation (e.g., refresh every 60s)
        # Or invalidate based on some event? For now, cache until explicitly refreshed.
        if _audio_devices_cache is None:
            logger.debug("Audio device cache empty, fetching fresh list.")
            try:
                inputs, outputs = list_audio_devices()
                _audio_devices_cache = {'inputs': inputs, 'outputs': outputs, 'error': None}
            except Exception as e:
                logger.error(f"Error listing audio devices for web UI: {e}")
                _audio_devices_cache = {'inputs': [], 'outputs': [], 'error': str(e)}
        return _audio_devices_cache.copy() # Return a copy

    def save_user_config(updated_values: Dict[str, Any]) -> Tuple[bool, str]:
        """Save updated config values to user_config.json."""
        config_path = config.USER_CONFIG_PATH
        try:
            existing_config = {}
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        existing_config = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Could not read existing user config at {config_path}: {e}. Starting fresh.")
                    existing_config = {} # Reset if file is corrupt

            # Update with new values (only store keys that differ from default or are new)
            # This prevents bloating user_config.json, but requires access to defaults.
            # Simpler approach: just update/overwrite keys present in updated_values.
            existing_config.update(updated_values)

            # Write back to file atomically (write to temp then rename)
            temp_path = config_path.with_suffix(".tmp")
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(existing_config, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, config_path) # Atomic replace

            logger.info(f"User configuration saved to {config_path}")
            return True, "Settings saved successfully. Restart required for some changes."
        except Exception as e:
            logger.exception(f"Error saving user config to {config_path}: {e}")
            return False, f"Error saving settings: {str(e)}"

    # --- Flask Routes ---

    @app.route('/')
    @login_required
    def index():
        """Render the main dashboard page."""
        stats = get_system_stats()
        state_mgr = app.config.get('STATE_MANAGER') # Get from app context
        current_state_name = "UNKNOWN"
        error_message = None

        if state_mgr:
             current_state = state_mgr.get_state()
             current_state_name = current_state.name
             if current_state == State.ERROR:
                 error_message = state_mgr.get_error_message()

        # Get copies of shared data under lock
        with _shared_data_lock:
             recent_activities_copy = _recent_activities[:]
             # Get last 5 transitions in reverse order for display
             recent_transitions_copy = _state_transitions[-5:][::-1]


        return render_template('index.html',
            status=current_state_name,
            error_message=error_message,
            uptime=get_uptime(),
            cpu_usage=stats['cpu_usage'],
            memory_usage=stats['memory_usage'],
            temperature=stats['temperature'],
            recent_activities=recent_activities_copy,
            recent_transitions=recent_transitions_copy
        )

    @app.route('/settings', methods=['GET'])
    @login_required
    def settings():
        """Render the settings page."""
        audio_devices = get_audio_devices() # Uses cache
        user_config = {}
        config_path = config.USER_CONFIG_PATH
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
            except Exception as e:
                flash(f"Error reading user config ({config_path}): {e}", "danger")

        # Provide the base config module as well, so defaults can be displayed
        return render_template('settings.html',
            config=config, # Pass the whole config module
            user_config=user_config,
            audio_inputs=audio_devices.get('inputs', []),
            audio_outputs=audio_devices.get('outputs', []),
            audio_error=audio_devices.get('error')
        )

    @app.route('/settings', methods=['POST'])
    @login_required
    def save_settings():
        """Handle saving settings from the form post."""
        updated_config: Dict[str, Any] = {}
        errors: List[str] = []

        # Iterate through form data and attempt type conversion based on expected types
        # This requires knowledge of the expected types (could be derived from defaults)
        for key, value in request.form.items():
            if key.startswith('#'): continue # Skip comments if used in form

            # Try to determine expected type from default config
            expected_type = type(getattr(config, key, None)) # Get type from original config module

            try:
                 if expected_type == bool:
                     # HTML checkboxes only submit if checked, with value 'true' or 'on'
                     # Need to handle unchecked case - check if key exists in form
                     updated_config[key] = key in request.form # More reliable way for checkboxes
                 elif key in ['AUDIO_INPUT_DEVICE_INDEX', 'AUDIO_OUTPUT_DEVICE_INDEX']:
                     # Handle device index (None or int)
                     updated_config[key] = None if value == 'null' or value == '' else int(value)
                 elif expected_type == int:
                     updated_config[key] = int(value)
                 elif expected_type == float:
                     updated_config[key] = float(value)
                 elif expected_type == list:
                      # Handle lists if needed (e.g., comma-separated strings?) - Complex
                      # For now, assume lists aren't directly edited this way simply
                      logger.warning(f"List configuration ('{key}') cannot be directly edited via basic form.")
                      continue # Skip list types for now
                 elif expected_type == Path:
                      # Assume paths are strings in the form/user_config.json
                      updated_config[key] = str(value) # Store as string in user_config
                 else: # Default to string
                     updated_config[key] = str(value)

                 # Add basic range validation if possible (requires defining ranges)
                 # Example:
                 # if key == 'WEB_INTERFACE_PORT' and not (1024 <= updated_config[key] <= 65535):
                 #     errors.append(f"Port number for {key} must be between 1024 and 65535.")

            except ValueError:
                errors.append(f"Invalid value type for '{key}'. Expected {expected_type.__name__}, got '{value}'.")
            except Exception as e:
                 errors.append(f"Error processing field '{key}': {e}")


        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            # Save the collected values
            success, message = save_user_config(updated_config)
            if success:
                flash(message, "success")
                add_activity("Settings updated via web interface")
            else:
                flash(message, "danger")

        return redirect(url_for('settings'))


    @app.route('/audio-test', methods=['POST'])
    @login_required
    def audio_test():
        """Endpoint to trigger an audio device test."""
        device_type = request.form.get('device_type', 'output')
        device_index_str = request.form.get('device_index', 'null')
        device_index: Optional[int] = None

        try:
            if device_index_str != 'null' and device_index_str != '':
                device_index = int(device_index_str)
        except ValueError:
            logger.warning(f"Invalid device index received for audio test: {device_index_str}")
            return jsonify({'success': False, 'message': 'Invalid device index format.'}), 400 # Bad request

        # Perform audio test using audio_utils
        try:
            # Run test in a separate thread? Short tests might be okay inline.
            test_successful = test_audio_device(device_index=device_index, mode=device_type)
            if test_successful:
                 add_activity(f"Audio {device_type} test successful (Device: {device_index_str})")
                 return jsonify({'success': True, 'message': f'Audio {device_type} test successful'})
            else:
                 add_activity(f"Audio {device_type} test failed (Device: {device_index_str})")
                 return jsonify({'success': False, 'message': f'Audio {device_type} test failed. Check logs.'})
        except Exception as e:
             logger.exception(f"Error during audio test via web UI: {e}")
             return jsonify({'success': False, 'message': f'Error during test: {str(e)}'}), 500 # Internal server error


    @app.route('/logs')
    @login_required
    def logs():
        """Render the logs page."""
        log_data = load_logs(200) # Load more lines for the log page
        return render_template('logs.html', logs=log_data)


    @app.route('/download_logs')
    @login_required
    def download_logs():
        """Provide the main log file for download."""
        log_path = config.LOG_FILE_PATH
        if not log_path.exists():
            flash("Log file not found.", "danger")
            return redirect(url_for('logs'))

        try:
            # Ensure filename is safe for download headers
            download_name = f"echocore_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            return send_from_directory(
                directory=log_path.parent,
                path=log_path.name, # Use path= instead of filename= for Flask >= 2.0
                as_attachment=True,
                download_name=download_name # Set custom download filename
            )
        except Exception as e:
            logger.exception(f"Error serving log file for download: {e}")
            flash(f"Error downloading logs: {str(e)}", "danger")
            return redirect(url_for('logs'))


    @app.route('/actions', methods=['POST'])
    @login_required
    def perform_action():
        """Handle quick actions from the dashboard."""
        action = request.form.get('action')
        state_mgr = app.config.get('STATE_MANAGER')
        llm_handler = app.config.get('LLM_HANDLER') # Get LLM handler if needed

        if not state_mgr:
             flash("System components not available to perform action.", "danger")
             return redirect(url_for('index'))

        if action == 'restart': # Renamed 'reset_system' in template? Keep consistent. Let's call it 'reset_state'
             logger.info("System state reset requested via web interface.")
             # Reset state (clears error, goes to IDLE)
             state_mgr.clear_error()
             if not state_mgr.is_state(State.IDLE):
                  state_mgr.set_state(State.IDLE)
             # Reset conversation if LLM handler is available
             if llm_handler and hasattr(llm_handler, 'reset_conversation'):
                 try:
                     llm_handler.reset_conversation()
                     add_activity("Conversation history reset via web")
                 except Exception as e:
                     logger.error(f"Error resetting conversation via web action: {e}")
                     flash(f"System state reset, but failed to reset conversation: {e}", "warning")
                 else:
                      flash("System state and conversation history reset.", "success")
             else:
                  flash("System state reset.", "success")
             add_activity("System state reset via web")

        elif action == 'reset_conversation':
             logger.info("Conversation reset requested via web interface.")
             if llm_handler and hasattr(llm_handler, 'reset_conversation'):
                 try:
                     llm_handler.reset_conversation()
                     flash("Conversation history reset successfully.", "success")
                     add_activity("Conversation history reset via web")
                 except Exception as e:
                      logger.error(f"Error resetting conversation via web action: {e}")
                      flash(f"Failed to reset conversation history: {e}", "danger")
             else:
                 flash("LLM Handler not available to reset conversation.", "warning")

        elif action == 'test_audio':
             logger.info("Audio test requested via web interface.")
             # Test default output device
             try:
                  test_successful = test_audio_device(mode='output') # Test default output
                  add_activity("Default audio output test executed via web")
                  if test_successful:
                       flash("Default audio output test completed successfully.", "success")
                  else:
                       flash("Default audio output test failed. Check system logs.", "danger")
             except Exception as e:
                  logger.exception("Error running default audio test via web UI.")
                  flash(f"Audio test error: {str(e)}", "danger")
        else:
            flash(f"Unknown action received: {action}", "warning")

        return redirect(url_for('index'))


    @app.route('/favicon.ico')
    def favicon():
        """Serve the favicon."""
        # Use resolved path from config
        return send_from_directory(config.STATIC_DIR, 'favicon.ico', mimetype='image/vnd.microsoft.icon')


    # --- API Endpoints (Example) ---

    @app.route('/api/status')
    @login_required
    def api_status():
        """Return current system status as JSON."""
        stats = get_system_stats()
        state_mgr = app.config.get('STATE_MANAGER')
        current_state_name = "UNKNOWN"
        error_message = None
        if state_mgr:
            current_state = state_mgr.get_state()
            current_state_name = current_state.name
            if current_state == State.ERROR:
                 error_message = state_mgr.get_error_message()

        with _shared_data_lock:
            activities_copy = _recent_activities[:]
            transitions_copy = _state_transitions[:]

        return jsonify({
            'status': current_state_name,
            'error_message': error_message,
            'uptime': get_uptime(),
            'stats': stats,
            'activities': activities_copy,
            'transitions': transitions_copy,
            'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
        })

    @app.route('/api/logs')
    @login_required
    def api_logs():
        """Return recent log entries as JSON."""
        try:
            count = int(request.args.get('count', 50)) # Default 50 lines
            count = max(1, min(count, 500)) # Clamp count
        except ValueError:
            count = 50

        log_data = load_logs(count)
        return jsonify({'logs': log_data})


    @app.route('/api/devices')
    @login_required
    def api_devices():
        """Return cached audio device list as JSON. Allows forcing refresh."""
        global _audio_devices_cache
        force_refresh = request.args.get('refresh', 'false').lower() == 'true'

        if force_refresh:
             logger.info("Forcing refresh of audio devices list via API.")
             _audio_devices_cache = None # Invalidate cache

        devices = get_audio_devices() # Fetches if cache was invalidated
        return jsonify(devices)


    # --- Web Interface Thread ---
    class WebInterfaceThread(threading.Thread):
        """Runs the Flask web server in a separate thread."""
        def __init__(
            self,
            state_manager: Optional[StateManager] = None,
            llm_handler: Optional[Any] = None, # Use Any to avoid circular import
            stop_event: Optional[threading.Event] = None
        ):
            super().__init__(name="WebInterfaceThread", daemon=True)
            self.flask_app = app # Reference the global app
            self.state_manager = state_manager
            self.llm_handler = llm_handler
            self.stop_event = stop_event or threading.Event()
            self._previous_state: Optional[State] = None


        def _monitor_state_changes(self):
            """
            Monitors state changes from StateManager and logs transitions.
            Runs in a loop within the main thread run method.
            NOTE: This polling approach is simple but less efficient than
                  using threading Events or other signaling mechanisms.
            """
            if not self.state_manager: return

            try:
                 current_state = self.state_manager.get_state()
                 if current_state != self._previous_state:
                     logger.debug(f"WebUI detected state change: {self._previous_state} -> {current_state}")
                     # Add transition to shared list (thread-safe)
                     add_state_transition(self._previous_state, current_state)
                     self._previous_state = current_state
            except Exception as e:
                 logger.error(f"Error in state monitoring loop: {e}")


        def run(self):
            """Start the Flask development server."""
            if not config.WEB_INTERFACE_ENABLED:
                logger.info("Web interface is disabled in configuration. Thread exiting.")
                return

            logger.info("Web Interface thread started.")
            try:
                # Pass references to other components into the Flask app context
                # This makes them accessible within route handlers (use app.config.get)
                self.flask_app.config['STATE_MANAGER'] = self.state_manager
                self.flask_app.config['LLM_HANDLER'] = self.llm_handler

                # Initialize previous state for monitoring
                if self.state_manager:
                     self._previous_state = self.state_manager.get_state()

                # Check/create favicon if needed (basic one)
                favicon_path = config.STATIC_DIR / 'favicon.ico'
                if not favicon_path.exists():
                     logger.info("Creating minimal favicon.ico...")
                     try:
                          # Minimal 16x16 blue favicon bytes
                          favicon_bytes = bytes.fromhex('00000100010010100000010020006804000016000000280000001000000020000000010020000000000000040000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000073E9FF0073E9FF1173E9FF6373E9FFA273E9FFCE73E9FFDC73E9FFDC73E9FFCE73E9FFA273E9FF6373E9FF1173E9FF000000000000000000000000000000000073E9FF0073E9FF5A73E9FFD673E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFD673E9FF5A0000000000000000000000000073E9FF1173E9FFD673E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFD673E9FF1100000000000000000073E9FF6373E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000A273E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000CE73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000DC73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000DC73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000CE73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000A273E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF000000000000000000000000000073E9FF6373E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FF63000000000000000000000000000073E9FF1173E9FFD673E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFD673E9FF11000000000000000000000000000000000073E9FF0073E9FF5A73E9FFD673E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFFF73E9FFD673E9FF5A73E9FF00000000000000000000000000000000000000000000000073E9FF0073E9FF1173E9FF6373E9FFA273E9FFCE73E9FFDC73E9FFDC73E9FFCE73E9FFA273E9FF6373E9FF1173E9FF0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000')
                          with open(favicon_path, 'wb') as f:
                               f.write(favicon_bytes)
                     except OSError as e:
                          logger.error(f"Failed to create favicon.ico: {e}")

                # --- Start Flask Server ---
                host = config.WEB_INTERFACE_HOST
                port = config.WEB_INTERFACE_PORT
                logger.info(f"Starting Flask web server on http://{host}:{port}")

                # Use waitress or gunicorn for production instead of Flask's dev server
                # For simplicity, we use the dev server here.
                # WARNING: Flask's built-in server is NOT suitable for production.
                self.flask_app.run(
                    host=host,
                    port=port,
                    debug=False, # DO NOT run with debug=True in production
                    use_reloader=False # Reloader interferes with threading/stop_event
                    # Consider adding SSL context for HTTPS if needed: ssl_context='adhoc' or paths
                )

            except Exception as e:
                 # Catch errors during Flask app setup or run
                 logger.exception(f"Fatal error in Web Interface thread: {e}")
                 if self.state_manager:
                     self.state_manager.set_state(State.ERROR, f"Web Interface failed: {e}")
            finally:
                 logger.info("Flask web server stopped.")
                 # No explicit stop needed for dev server when run finishes/crashes


# --- Conditional Execution ---
# Only run setup if Flask was imported successfully
if Flask is not None:
     # Any setup code needed for Flask app before thread starts can go here
     pass
else:
     # Ensure WebInterfaceThread is the dummy version if Flask failed import
     WebInterfaceThread = type("WebInterfaceThread", (threading.Thread,), { # type: ignore
         "__init__": lambda self, *args, **kwargs: super(threading.Thread, self).__init__(daemon=True),
         "run": lambda self: logger.error("Flask not available, Web Interface disabled.")
     })


# Example of how to potentially stop the Flask server cleanly (requires Werkzeug)
# This is complex and often not necessary if the thread is a daemon.
# def shutdown_server():
#     func = request.environ.get('werkzeug.server.shutdown')
#     if func is None:
#         logger.warning('Not running with the Werkzeug Server, cannot shutdown programmatically.')
#         return
#     logger.info('Attempting to shut down Flask server...')
#     func()

# @app.route('/shutdown', methods=['POST'])
# @login_required # Secure this endpoint
# def shutdown():
#     add_activity("Shutdown requested via web interface")
#     shutdown_server()
#     # Signal the main application to stop as well
#     main_stop_event = app.config.get('STOP_EVENT_MAIN') # Needs main stop_event passed in
#     if main_stop_event:
#         main_stop_event.set()
#     return 'Server shutting down...'

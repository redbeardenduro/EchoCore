# main.py
"""
Main application script for Project EchoCore.

Initializes all system components (audio, STT, LLM, TTS, avatar, web UI),
manages communication queues, starts and monitors component threads,
handles graceful shutdown signals, and performs health checks.
"""

import queue
import threading
import time
import signal
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Optional, Type # For type hinting

# --- Early Initialization: Config and Logging ---
# It's crucial to configure logging and load config before importing other modules
# that might rely on them (especially logging).

try:
    import config # Load enhanced configuration
except ImportError:
    # Use basic logging if config fails, hoping config provides defaults later
    logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.critical("Failed to import configuration (config.py). Application cannot start.")
    sys.exit(1)
except Exception as e:
     logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
     logging.critical(f"An error occurred during initial config import: {e}", exc_info=True)
     sys.exit(1)


# Setup Logging (using values from the loaded config)
try:
    # Ensure logs directory exists (config loader should handle this, but double-check)
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_formatter = logging.Formatter(config.LOG_FORMAT)
    log_handler_file = RotatingFileHandler(
        config.LOG_FILE_PATH,
        maxBytes=config.LOG_MAX_SIZE,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding='utf-8' # Specify encoding
    )
    log_handler_file.setFormatter(log_formatter)

    log_handler_stream = logging.StreamHandler(sys.stdout) # Log to stdout as well
    log_handler_stream.setFormatter(log_formatter)

    # Get the root logger and configure it
    root_logger = logging.getLogger()
    root_logger.setLevel(config.LOG_LEVEL) # Set level from config
    root_logger.addHandler(log_handler_file)
    root_logger.addHandler(log_handler_stream)

    logger = logging.getLogger(__name__) # Logger for this module
    logger.info("Logging configured successfully.")

except Exception as e:
     # Fallback basic logging if file handler setup fails
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
     logger = logging.getLogger(__name__)
     logger.error(f"Failed to configure file logging: {e}", exc_info=True)
     logger.warning("Logging to console only.")


# --- Validate Configuration ---
if not config.IS_CONFIG_VALID:
     logger.critical("Configuration validation failed. Please check errors/warnings above.")
     logger.critical("Application cannot start with invalid configuration. Exiting.")
     sys.exit(1)
else:
     logger.info("Configuration validation successful.")


# --- Import Project Modules (after logging is set up) ---
# Wrap imports in try-except to catch issues early
try:
    from state_manager import StateManager, State
    from audio_input import AudioInputHandler
    from stt_processor import STTProcessor
    from llm_handler import LLMHandler
    from tts_synthesizer import TTSSynthesizer
    from audio_output import AudioOutputHandler
    from avatar_display import AvatarDisplay
    # Web interface thread class is defined within web_interface.py after Flask check
    from web_interface import WebInterfaceThread
except ImportError as e:
    logger.critical(f"Failed to import one or more core modules: {e}", exc_info=True)
    logger.critical("Ensure all project Python files are present and dependencies are installed.")
    sys.exit(1)
except Exception as e:
     logger.critical(f"An unexpected error occurred during module imports: {e}", exc_info=True)
     sys.exit(1)


# --- Global Variables & Setup ---
logger.debug("Setting up global variables and communication queues.")
stop_event = threading.Event()
state_manager = StateManager() # Central state management instance

# Queues for inter-thread communication with max sizes
# Define types more specifically if possible, e.g., Queue[bytes], Queue[str]
# Using 'Any' for simplicity here if exact types vary or cause issues
audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=config.AUDIO_CHUNK_SIZE * 10) # Approx 1-2s buffer?
stt_queue: queue.Queue[str] = queue.Queue(maxsize=10)   # Queue for text transcriptions
llm_queue: queue.Queue[str] = queue.Queue(maxsize=10)   # Queue for text prompts to TTS
tts_queue: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=100) # Queue for audio bytes to output
avatar_queue: queue.Queue[float] = queue.Queue(maxsize=50) # Queue for amplitude data


# List to hold all running threads for management
_running_threads: List[threading.Thread] = []


# --- Signal Handling ---
def signal_handler(sig: int, frame: Optional[Any]) -> None:
    """Handle termination signals (like Ctrl+C) gracefully."""
    signal_name = signal.Signals(sig).name if sys.version_info >= (3, 8) else f"Signal {sig}"
    logger.warning(f"\n{signal_name} received. Initiating graceful shutdown...")
    # Set the event to signal all threads to stop their loops
    stop_event.set()
    # Optional: Add a small delay here if needed before main loop potentially exits
    # time.sleep(0.1)

# Register signal handlers early
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler) # Termination signal

# --- Health and Thread Monitoring ---

def _check_component_health() -> bool:
    """Check if any component has set the global ERROR state."""
    if state_manager.is_state(State.ERROR):
        error_msg = state_manager.get_error_message() or "No specific error message."
        logger.error(f"System in ERROR state: {error_msg}")
        logger.warning("Attempting basic recovery: Resetting state to IDLE.")
        # Basic recovery: Just reset the state. More complex recovery could be added.
        # Consider only resetting if the error is deemed recoverable.
        state_manager.clear_error() # This resets state to IDLE
        return False # Indicate health check failed
    return True

def _check_thread_liveness(threads: List[threading.Thread]) -> Tuple[bool, List[str]]:
    """
    Check if all managed threads are alive.

    Args:
        threads: A list of the expected running threads.

    Returns:
        A tuple: (all_threads_alive: bool, dead_thread_names: List[str]).
    """
    all_alive = True
    dead_thread_names: List[str] = []
    active_threads_count = 0

    for thread in threads:
        if thread.is_alive():
             active_threads_count += 1
        else:
            thread_name = thread.name or thread.__class__.__name__
            # Avoid logging errors immediately on shutdown sequence
            if not stop_event.is_set():
                 all_alive = False
                 dead_thread_names.append(thread_name)
                 logger.error(f"THREAD FAILED: Thread '{thread_name}' is no longer alive!")

    logger.debug(f"Thread liveness check: {active_threads_count}/{len(threads)} threads active.")
    return all_alive, dead_thread_names

def _attempt_thread_recovery(dead_threads: List[str]) -> None:
    """
    Handles the situation when one or more threads have died unexpectedly.
    Currently sets ERROR state and logs. Could be expanded to restart threads.
    """
    error_message = f"Critical thread failure detected: {', '.join(dead_threads)}. System may be unstable."
    logger.critical(error_message)
    # Set error state, indicating a potentially unrecoverable situation
    state_manager.set_state(State.ERROR, error_message=error_message)

    # --- Advanced Recovery (Placeholder) ---
    # Restarting specific threads is complex due to shared state, queues, and dependencies.
    # It would require:
    # 1. Identifying which thread class failed (e.g., by name).
    # 2. Cleaning up resources associated with the failed thread (if possible).
    # 3. Re-initializing the specific component class.
    # 4. Starting the new thread instance and adding it back to the managed list.
    # 5. Resetting relevant states or clearing queues as needed.
    logger.error("Automatic thread recovery is not implemented. Manual restart recommended.")
    # Signal application shutdown if recovery is deemed impossible
    # stop_event.set()


# --- Initialization Function ---
def initialize_components() -> Optional[List[threading.Thread]]:
    """
    Initialize all application components and return a list of threads.

    Returns:
        A list of initialized thread objects, or None if initialization fails critically.
    """
    logger.info("--- Initializing EchoCore Components ---")
    threads: List[threading.Thread] = []
    component_map: Dict[str, Optional[Any]] = {} # To hold component instances

    # Define component classes and their args in order of dependency
    # Use tuples: (Name, Class, Args_Tuple)
    component_defs: List[Tuple[str, Type[threading.Thread], tuple]] = [
        ("AudioInput", AudioInputHandler, (audio_queue, state_manager, stop_event)),
        ("STTProcessor", STTProcessor, (audio_queue, stt_queue, state_manager, stop_event)),
        ("LLMHandler", LLMHandler, (stt_queue, llm_queue, state_manager, stop_event)),
        ("TTSSynthesizer", TTSSynthesizer, (llm_queue, tts_queue, state_manager, stop_event)),
        ("AudioOutput", AudioOutputHandler, (tts_queue, avatar_queue, state_manager, stop_event)),
        # Avatar and Web UI are often less critical, initialize last
        ("AvatarDisplay", AvatarDisplay, (avatar_queue, state_manager, stop_event)),
    ]

    # Add Web Interface only if enabled in config
    if config.WEB_INTERFACE_ENABLED:
        # Note: LLMHandler instance needed for Web UI, ensure it's created first
        llm_handler_instance = component_map.get("LLMHandler") # Will be populated below
        component_defs.append(
            ("WebInterface", WebInterfaceThread, (state_manager, llm_handler_instance, stop_event))
        )


    # Instantiate components sequentially, handling errors
    initialization_successful = True
    for name, component_class, args in component_defs:
        logger.info(f"Initializing {name}...")
        try:
             # Special handling for WebInterface args dependency
             if name == "WebInterface":
                 # Get the actual LLMHandler instance created earlier
                 llm_handler_instance = component_map.get("LLMHandler")
                 if llm_handler_instance is None and "LLMHandler" in [d[0] for d in component_defs]:
                      logger.error("LLMHandler instance not available for WebInterface initialization!")
                      # Decide how to handle: skip web ui, error out?
                      # Let's try skipping it for now
                      logger.warning("Skipping WebInterface initialization due to missing LLMHandler.")
                      continue # Skip this component
                 args = (state_manager, llm_handler_instance, stop_event) # Reconstruct args


             instance = component_class(*args)
             threads.append(instance)
             component_map[name] = instance # Store instance if needed by others (like Web UI)
             logger.info(f"{name} initialized successfully.")

             # Check if component set ERROR state during its init
             if state_manager.is_state(State.ERROR):
                  logger.critical(f"{name} initialization failed (set ERROR state). Aborting.")
                  initialization_successful = False
                  break # Stop initialization

        except Exception as e:
            logger.critical(f"CRITICAL ERROR initializing {name}: {e}", exc_info=True)
            state_manager.set_state(State.ERROR, f"Initialization failed for {name}: {e}")
            initialization_successful = False
            break # Stop initialization on critical error

    if not initialization_successful:
         logger.critical("One or more components failed to initialize. Application cannot start.")
         # Signal stop event early to prevent partially started threads?
         stop_event.set()
         return None # Indicate failure

    logger.info("--- All Components Initialized ---")
    return threads


# --- Main Application Logic ---
def main():
    """Main application function."""
    logger.info("--- Starting Project EchoCore ---")
    global _running_threads # Allow modification of the global list

    _running_threads = initialize_components()

    if _running_threads is None:
        logger.critical("Application initialization failed. Exiting.")
        sys.exit(1)

    # --- Start Threads ---
    logger.info("Starting component threads...")
    for thread in _running_threads:
        try:
            thread.start()
            logger.info(f"Thread '{thread.name}' started.")
        except RuntimeError as e:
             logger.error(f"Failed to start thread '{thread.name}': {e}")
             # Signal shutdown if a critical thread fails to start?
             stop_event.set()
             break # Stop trying to start threads

    # Check if any thread failed to start right after loop
    if stop_event.is_set():
         logger.critical("Failed to start all threads cleanly. Initiating shutdown.")
    else:
         logger.info("All component threads started. Application running.")
         # Set initial state after startup? Or let components manage it?
         # state_manager.set_state(State.IDLE) # Ensure starting in IDLE


    # --- Main Loop (Keep main thread alive & Monitor) ---
    last_health_check_time = time.monotonic()
    last_thread_check_time = time.monotonic()
    recovery_attempts = 0

    while not stop_event.is_set():
        current_time = time.monotonic()

        # 1. Periodic Health Check (based on StateManager)
        if current_time - last_health_check_time > config.HEALTH_CHECK_INTERVAL:
             _check_component_health()
             last_health_check_time = current_time

        # 2. Periodic Thread Liveness Check
        if current_time - last_thread_check_time > 10.0: # Check every 10 seconds
            all_alive, dead_threads = _check_thread_liveness(_running_threads)
            if not all_alive:
                recovery_attempts += 1
                logger.warning(f"Thread failure detected! Recovery attempt {recovery_attempts}/{config.RECOVERY_ATTEMPTS}")
                if recovery_attempts <= config.RECOVERY_ATTEMPTS:
                     _attempt_thread_recovery(dead_threads) # Sets ERROR state
                else:
                    logger.critical(f"Maximum recovery attempts ({config.RECOVERY_ATTEMPTS}) reached for thread failures.")
                    logger.critical("System is likely unrecoverable. Initiating shutdown.")
                    stop_event.set() # Trigger shutdown
            else:
                 recovery_attempts = 0 # Reset recovery attempts if all threads are okay
            last_thread_check_time = current_time

        # Main thread sleeps briefly; actual work happens in component threads
        # Use wait with timeout on the stop_event for responsiveness
        stop_event.wait(timeout=0.5) # Wait up to 0.5s for stop signal


    # --- Cleanup Phase ---
    logger.info("Shutdown signal received. Waiting for threads to finish...")

    # Wait for threads to complete (with a timeout)
    # Iterate over a copy in case the list is modified elsewhere (shouldn't happen now)
    active_threads = [t for t in _running_threads if t.is_alive()]
    join_timeout = 10.0 # Max seconds to wait per thread
    start_join_time = time.monotonic()

    for thread in active_threads:
         try:
             # Calculate remaining timeout
             elapsed = time.monotonic() - start_join_time
             remaining_timeout = max(0.1, join_timeout - elapsed) # Ensure small positive timeout

             logger.debug(f"Joining thread '{thread.name}' (timeout: {remaining_timeout:.1f}s)...")
             thread.join(timeout=remaining_timeout)
             if thread.is_alive():
                 logger.warning(f"Warning: Thread '{thread.name}' did not exit cleanly after {join_timeout:.1f}s.")
                 # Consider more forceful termination if needed, though often not recommended
             else:
                  logger.info(f"Thread '{thread.name}' finished.")
         except Exception as e:
             logger.error(f"Error joining thread '{thread.name}': {e}")

    # Final check
    lingering_threads = [t.name for t in _running_threads if t.is_alive()]
    if lingering_threads:
         logger.error(f"The following threads are still alive after shutdown attempt: {lingering_threads}")
    else:
         logger.info("All managed threads have finished.")


    logger.info("--- Project EchoCore Shutdown Complete ---")
    # Explicit exit might be needed if non-daemon threads linger
    sys.exit(0)


if __name__ == "__main__":
    main()

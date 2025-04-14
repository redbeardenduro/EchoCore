# main.py
"""
Main application script for Project EchoCore.
Initializes components, manages threads, and handles state transitions.
"""

import queue
import threading
import time
import signal
import sys
import logging
from logging.handlers import RotatingFileHandler

# Import project modules
import config
from state_manager import StateManager, State
from audio_input import AudioInputHandler
from stt_processor import STTProcessor
from llm_handler import LLMHandler
from tts_synthesizer import TTSSynthesizer
from audio_output import AudioOutputHandler
from avatar_display import AvatarDisplay
from web_interface import WebInterfaceThread  # Add this import

# --- Setup Logging ---
logging.basicConfig(
    level=config.LOG_LEVEL, 
    format=config.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=config.LOG_MAX_SIZE,
            backupCount=config.LOG_BACKUP_COUNT
        )
    ]
)
logger = logging.getLogger(__name__)

# --- Global Variables ---
stop_event = threading.Event()
state_manager = StateManager()

# Queues for inter-thread communication with max sizes to prevent memory issues
audio_queue = queue.Queue(maxsize=100)
stt_queue = queue.Queue(maxsize=10)
llm_queue = queue.Queue(maxsize=10)
tts_queue = queue.Queue(maxsize=100)
avatar_queue = queue.Queue(maxsize=50)

def signal_handler(sig, frame):
    """Handle termination signals (like Ctrl+C)."""
    logger.info("\nTermination signal received. Shutting down...")
    stop_event.set()

def clear_queues():
    """Clear all queues to prevent backlog."""
    for q in [audio_queue, stt_queue, llm_queue, tts_queue, avatar_queue]:
        try:
            while not q.empty():
                q.get_nowait()
        except queue.Empty:
            pass

def check_component_health():
    """Check if any component is in error state."""
    if state_manager.is_state(State.ERROR):
        logger.error("System in ERROR state. Attempting recovery...")
        # Basic recovery: clear queues and reset to IDLE
        clear_queues()
        state_manager.set_state(State.IDLE)
        return False
    return True

def check_thread_liveness(threads):
    """
    Check if all threads are alive and attempt recovery if needed.
    Returns a tuple (all_alive, dead_thread_names).
    """
    all_alive = True
    dead_thread_names = []
    
    for thread in threads:
        if not thread.is_alive():
            thread_name = thread.__class__.__name__
            all_alive = False
            dead_thread_names.append(thread_name)
            logger.error(f"Thread {thread_name} is not alive!")
    
    return all_alive, dead_thread_names

def attempt_thread_recovery(dead_thread_names, threads):
    """
    Attempt to recover from dead threads. This is a basic implementation
    that currently just logs the issue and sets error state.
    In a more advanced version, this could restart specific threads.
    """
    logger.warning(f"The following threads have died: {', '.join(dead_thread_names)}")
    logger.warning("Setting ERROR state and initiating recovery...")
    
    # Set error state with informative message
    state_manager.set_state(State.ERROR, 
                           error_message=f"Thread failure detected: {', '.join(dead_thread_names)}")
    
    # Clear queues to prevent backlog during recovery
    clear_queues()
    
    # Note: Actual thread restarting would be more complex and depends on your architecture
    # For now, we'll just recommend a manual restart
    logger.error("Thread recovery is limited - a manual restart may be required.")
    
    # Return False to indicate recovery wasn't fully successful
    return False

def main():
    """Initialize and start all application threads."""
    logger.info("--- Project EchoCore Starting ---")

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize threads list
    threads = []

    try:
        # --- Initialize Components ---
        # Order matters for dependencies (e.g., state manager first)
        logger.info("Initializing components...")
        audio_input = AudioInputHandler(audio_queue, state_manager, stop_event)
        stt_processor = STTProcessor(audio_queue, stt_queue, state_manager, stop_event)
        llm_handler = LLMHandler(stt_queue, llm_queue, state_manager, stop_event)
        tts_synthesizer = TTSSynthesizer(llm_queue, tts_queue, state_manager, stop_event)
        audio_output = AudioOutputHandler(tts_queue, avatar_queue, state_manager, stop_event)
        avatar_display = AvatarDisplay(avatar_queue, state_manager, stop_event)

        # Web interface (optional, based on config)
        web_interface = None
        if config.WEB_INTERFACE_ENABLED:
            logger.info("Initializing web interface...")
            web_interface = WebInterfaceThread(state_manager, llm_handler, stop_event)

        threads = [
            audio_input,
            stt_processor,
            llm_handler,
            tts_synthesizer,
            audio_output,
            avatar_display
        ]

        # Add web interface thread if enabled
        if web_interface:
            threads.append(web_interface)

        # --- Start Threads ---
        logger.info("Starting threads...")
        for thread in threads:
            thread.start()

        # --- Main Loop (Keep main thread alive) ---
        logger.info("Application running. Press Ctrl+C to exit.")
        health_check_interval = config.HEALTH_CHECK_INTERVAL  # Seconds
        last_health_check = time.time()
        
        # Thread liveness check setup
        thread_check_interval = 10  # Seconds (check thread liveness every 10 seconds)
        last_thread_check = time.time()
        recovery_attempts = 0
        max_recovery_attempts = config.RECOVERY_ATTEMPTS
        
        while not stop_event.is_set():
            current_time = time.time()
            
            # Periodically check system health
            if current_time - last_health_check > health_check_interval:
                check_component_health()
                last_health_check = current_time
            
            # Periodically check thread liveness
            if current_time - last_thread_check > thread_check_interval:
                logger.debug("Performing thread liveness check...")
                all_alive, dead_thread_names = check_thread_liveness(threads)
                
                if not all_alive:
                    recovery_attempts += 1
                    logger.warning(f"Thread failure detected! Recovery attempt {recovery_attempts}/{max_recovery_attempts}")
                    
                    if recovery_attempts <= max_recovery_attempts:
                        recovery_success = attempt_thread_recovery(dead_thread_names, threads)
                        if recovery_success:
                            logger.info("Thread recovery successful")
                            recovery_attempts = 0
                    else:
                        logger.error(f"Maximum recovery attempts ({max_recovery_attempts}) reached.")
                        logger.error("System is in an unrecoverable state. Manual restart required.")
                        # In a production system, you might want to trigger a full system restart here
                        # or implement a more advanced recovery mechanism
                
                last_thread_check = current_time
                
            # Main thread sleeps to reduce CPU usage
            time.sleep(0.5)  # More responsive sleep interval

    except Exception as e:
        logger.exception(f"FATAL ERROR during initialization or main loop: {e}")
        stop_event.set() # Signal all threads to stop on fatal error
    finally:
        # --- Cleanup ---
        logger.info("Waiting for threads to finish...")
        # Wait for threads to complete (with a timeout)
        for thread in threads:
            try:
                # Check if thread was started before joining
                if thread.is_alive():
                     thread.join(timeout=5.0)
                     if thread.is_alive():
                         logger.warning(f"Warning: Thread {thread.name} did not exit cleanly.")
            except Exception as e:
                 logger.error(f"Error joining thread {thread.name}: {e}")

        logger.info("--- Project EchoCore Shutdown Complete ---")
        sys.exit(0)

if __name__ == "__main__":
    main()

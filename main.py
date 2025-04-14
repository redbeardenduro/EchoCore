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

# Import project modules
import config
from state_manager import StateManager, State
from audio_input import AudioInputHandler
from stt_processor import STTProcessor
from llm_handler import LLMHandler
from tts_synthesizer import TTSSynthesizer
from audio_output import AudioOutputHandler
from avatar_display import AvatarDisplay

# --- Setup Logging ---
logging.basicConfig(
    level=config.LOG_LEVEL, 
    format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("echocore.log")
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

        threads = [
            audio_input,
            stt_processor,
            llm_handler,
            tts_synthesizer,
            audio_output,
            avatar_display
        ]

        # --- Start Threads ---
        logger.info("Starting threads...")
        for thread in threads:
            thread.start()

        # --- Main Loop (Keep main thread alive) ---
        logger.info("Application running. Press Ctrl+C to exit.")
        health_check_interval = 30  # seconds
        last_health_check = time.time()
        
        while not stop_event.is_set():
            # Periodically check system health
            if time.time() - last_health_check > health_check_interval:
                check_component_health()
                last_health_check = time.time()
                
            # Main thread sleeps to reduce CPU usage
            time.sleep(1)

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

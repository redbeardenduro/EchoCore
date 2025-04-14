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
logging.basicConfig(level=config.LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s')

# --- Global Variables ---
stop_event = threading.Event()
state_manager = StateManager()

# Queues for inter-thread communication
audio_queue = queue.Queue()
stt_queue = queue.Queue()
llm_queue = queue.Queue()
tts_queue = queue.Queue()
avatar_queue = queue.Queue()

def signal_handler(sig, frame):
    """Handle termination signals (like Ctrl+C)."""
    print("\nTermination signal received. Shutting down...")
    stop_event.set()

def main():
    """Initialize and start all application threads."""
    print("--- Project EchoCore Starting ---")

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    threads =

    try:
        # --- Initialize Components ---
        # Order matters for dependencies (e.g., state manager first)
        print("Initializing components...")
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
        print("Starting threads...")
        for thread in threads:
            thread.start()

        # --- Main Loop (Keep main thread alive) ---
        print("Application running. Press Ctrl+C to exit.")
        while not stop_event.is_set():
            # Main thread can monitor state or perform other tasks if needed
            # For now, just wait for stop signal
            time.sleep(1)

    except Exception as e:
        print(f"FATAL ERROR during initialization or main loop: {e}")
        logging.exception("Fatal error occurred.")
        stop_event.set() # Signal all threads to stop on fatal error
    finally:
        # --- Cleanup ---
        print("Waiting for threads to finish...")
        # Wait for threads to complete (with a timeout)
        for thread in threads:
            try:
                # Check if thread was started before joining
                if thread.is_alive():
                     thread.join(timeout=5.0)
                     if thread.is_alive():
                         print(f"Warning: Thread {thread.name} did not exit cleanly.")
            except Exception as e:
                 print(f"Error joining thread {thread.name}: {e}")

        print("--- Project EchoCore Shutdown Complete ---")
        sys.exit(0)

if __name__ == "__main__":
    main()

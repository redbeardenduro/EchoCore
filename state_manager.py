# state_manager.py
"""
Manages the global state of the application.
"""
import threading
from enum import Enum, auto
import logging

# Setup logger
logger = logging.getLogger(__name__)

class State(Enum):
    """Enumeration for application states."""
    IDLE = auto()
    LISTENING = auto()
    PROCESSING_STT = auto()
    THINKING = auto()
    SYNTHESIZING_TTS = auto()
    SPEAKING = auto()
    ERROR = auto()

class StateManager:
    """
    Thread-safe class to manage the application state.
    Uses a lock to ensure atomic updates and reads.
    """
    def __init__(self, initial_state=State.IDLE):
        self._state = initial_state
        self._lock = threading.Lock()
        self._state_changed = threading.Event() # Event to signal state changes
        self._error_message = None  # Store the latest error message when in ERROR state

    def get_state(self):
        """Get the current state."""
        with self._lock:
            return self._state

    def set_state(self, new_state, error_message=None):
        """Set a new state and notify listeners. Optionally store an error message."""
        if not isinstance(new_state, State):
            raise ValueError("Invalid state type")
        with self._lock:
            if self._state != new_state:
                logger.info(f"State changed: {self._state.name} -> {new_state.name}")
                self._state = new_state
                
                # Store error message if transitioning to ERROR state
                if new_state == State.ERROR and error_message:
                    self._error_message = error_message
                    logger.error(f"Error message: {error_message}")
                
                self._state_changed.set() # Signal that state has changed
                self._state_changed.clear() # Reset event immediately

    def wait_for_state_change(self, timeout=None):
        """Wait for the state to change."""
        return self._state_changed.wait(timeout)

    def is_state(self, state):
        """Check if the current state matches the given state."""
        with self._lock:
            return self._state == state
            
    def get_error_message(self):
        """Get the current error message."""
        with self._lock:
            return self._error_message
            
    def clear_error(self):
        """Clear the error message and reset state to IDLE."""
        with self._lock:
            if self._state == State.ERROR:
                self._error_message = None
                self._state = State.IDLE
                logger.info("Error cleared, state reset to IDLE")
                self._state_changed.set()
                self._state_changed.clear()

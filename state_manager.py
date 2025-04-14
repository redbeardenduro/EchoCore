# state_manager.py
"""
Manages the global state of the application.
"""
import threading
from enum import Enum, auto

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

    def get_state(self):
        """Get the current state."""
        with self._lock:
            return self._state

    def set_state(self, new_state):
        """Set a new state and notify listeners."""
        if not isinstance(new_state, State):
            raise ValueError("Invalid state type")
        with self._lock:
            if self._state!= new_state:
                print(f"State changed: {self._state.name} -> {new_state.name}") # Basic logging
                self._state = new_state
                self._state_changed.set() # Signal that state has changed
                self._state_changed.clear() # Reset event immediately

    def wait_for_state_change(self, timeout=None):
        """Wait for the state to change."""
        return self._state_changed.wait(timeout)

    def is_state(self, state):
        """Check if the current state matches the given state."""
        with self._lock:
            return self._state == state

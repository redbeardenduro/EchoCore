# state_manager.py
"""
Manages the global state of the application in a thread-safe manner.
Provides mechanisms to set, get, and wait for state changes.
"""

import threading
from enum import Enum, auto, unique
import logging
from typing import Optional, Union # For type hinting

# Setup logger
# It's generally better practice for libraries/modules not to configure
# logging directly but let the main application handle it.
# However, since it's here, we'll keep it but use __name__.
logger = logging.getLogger(__name__)

# Use @unique to ensure no duplicate values in the Enum
@unique
class State(Enum):
    """Enumeration for application states."""
    IDLE = auto()
    LISTENING = auto()          # Actively capturing audio for wake word or speech
    PROCESSING_STT = auto()     # Running speech-to-text on captured audio
    THINKING = auto()           # Processing STT result and querying LLM
    SYNTHESIZING_TTS = auto()   # Generating audio from LLM response
    SPEAKING = auto()           # Playing back synthesized audio
    ERROR = auto()              # An error occurred, requires intervention or reset

class StateManager:
    """
    Thread-safe class to manage the application state (singleton-like).

    Uses a reentrant lock (RLock) to allow the same thread to acquire the
    lock multiple times, which can be useful in complex state transition logic.
    Uses a threading.Event to efficiently signal state changes to waiting threads.
    """
    def __init__(self, initial_state: State = State.IDLE):
        """
        Initializes the StateManager.

        Args:
            initial_state: The starting state for the application.
                           Defaults to State.IDLE.
        """
        if not isinstance(initial_state, State):
            raise TypeError("initial_state must be an instance of State Enum")

        self._state: State = initial_state
        self._lock: threading.RLock = threading.RLock() # Use RLock
        self._state_changed: threading.Event = threading.Event()
        self._error_message: Optional[str] = None # Store the latest error message

        logger.info(f"StateManager initialized with state: {self._state.name}")

    def get_state(self) -> State:
        """
        Get the current application state in a thread-safe manner.

        Returns:
            The current state (Enum member).
        """
        with self._lock:
            return self._state

    def set_state(self, new_state: State, error_message: Optional[str] = None) -> None:
        """
        Set a new application state and notify waiting threads.

        If transitioning to the ERROR state, an optional error message
        can be provided.

        Args:
            new_state: The new state to set (must be a State Enum member).
            error_message: An optional descriptive error message if new_state is ERROR.
                           This message will be logged and stored.
        """
        if not isinstance(new_state, State):
            raise TypeError("new_state must be an instance of State Enum")

        with self._lock:
            old_state = self._state
            if old_state != new_state:
                self._state = new_state
                logger.info(f"State changed: {old_state.name} -> {new_state.name}")

                # Store or clear error message
                if new_state == State.ERROR:
                    if error_message:
                        self._error_message = str(error_message) # Ensure it's a string
                        logger.error(f"Error state set. Message: {self._error_message}")
                    else:
                        self._error_message = "An unspecified error occurred."
                        logger.error("Error state set with no specific message.")
                else:
                    # Clear error message when transitioning out of ERROR state
                    if old_state == State.ERROR:
                        self._error_message = None
                        logger.info("Error message cleared.")

                # Signal that the state has changed
                # Set must be called *before* clear in case a waiting thread
                # immediately calls wait() again.
                self._state_changed.set()
                # Clear the event immediately so future waits will block until the *next* change.
                self._state_changed.clear()
            # If the state is already the desired state, do nothing.
            # Optionally, log if setting to ERROR state again with a new message:
            elif new_state == State.ERROR and error_message and self._error_message != error_message:
                 self._error_message = str(error_message)
                 logger.error(f"Error state updated. New message: {self._error_message}")


    def wait_for_state_change(self, timeout: Optional[float] = None) -> bool:
        """
        Block the calling thread until the state changes.

        Args:
            timeout: Maximum time in seconds to wait. If None (default),
                     waits indefinitely.

        Returns:
            True if the state changed within the timeout, False if the timeout occurred.
        """
        return self._state_changed.wait(timeout)

    def is_state(self, state: Union[State, tuple[State, ...]]) -> bool:
        """
        Check if the current state matches the given state or one of the states in a tuple.

        Args:
            state: A single State Enum member or a tuple of State Enum members.

        Returns:
            True if the current state matches the provided state(s), False otherwise.
        """
        with self._lock:
            if isinstance(state, tuple):
                 return self._state in state
            elif isinstance(state, State):
                 return self._state == state
            else:
                 raise TypeError("state argument must be a State Enum member or a tuple of State Enum members")


    def get_error_message(self) -> Optional[str]:
        """
        Get the stored error message (only relevant if the current state is ERROR).

        Returns:
            The stored error message string, or None if not in ERROR state or no
            message was set.
        """
        with self._lock:
            # Return message only if currently in ERROR state for clarity
            return self._error_message if self._state == State.ERROR else None

    def clear_error(self) -> None:
        """
        If the system is in the ERROR state, clear the error message
        and transition the state back to IDLE.
        """
        with self._lock:
            if self._state == State.ERROR:
                logger.info("Attempting to clear error state...")
                # Call set_state to handle logging and event notification consistently
                self.set_state(State.IDLE)
            else:
                logger.debug("clear_error called but system not in ERROR state.")

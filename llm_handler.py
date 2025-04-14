# llm_handler.py
"""
Handles interaction with the configured Large Language Model (LLM),
primarily using the OpenAI API. Manages conversation history for context
and includes basic offline fallback and reconnection logic.
"""

import threading
import queue
import time
import logging
from typing import Optional, List, Dict, Any # For type hinting

# Attempt to import OpenAI library
try:
    # Use v1.x API style
    from openai import OpenAI, APITimeoutError, APIConnectionError, AuthenticationError, RateLimitError, APIStatusError, OpenAIError
except ImportError:
    logging.critical("OpenAI library not found. Please install it: pip install openai>=1.0.0")
    # Depending on requirements, might raise or allow fallback if configured
    raise

# Import project modules
try:
    import config
    from state_manager import StateManager, State
except ImportError as e:
    logging.error(f"Error importing project modules in llm_handler.py: {e}")
    raise

# Setup logger
logger = logging.getLogger(__name__)

# Type alias for conversation history messages
ChatMessage = Dict[str, str] # e.g., {"role": "user", "content": "Hello"}

class LLMHandler(threading.Thread):
    """
    Thread to manage interactions with the Large Language Model (LLM).

    Takes text prompts (str) from the stt_queue, sends them to the configured
    LLM (currently OpenAI API), manages conversation history, handles API errors
    and potential offline fallbacks, and puts the LLM's response (str) onto
    the llm_queue.
    """
    def __init__(
        self,
        stt_queue: queue.Queue[str],      # Receives transcribed user input
        llm_queue: queue.Queue[str],      # Outputs LLM text response
        state_manager: StateManager,
        stop_event: threading.Event
    ):
        """
        Initializes the LLMHandler.

        Args:
            stt_queue: Queue receiving transcriptions from STTProcessor.
            llm_queue: Queue to put LLM text responses onto for TTS.
            state_manager: The application's state manager instance.
            stop_event: Threading event to signal when to stop processing.

        Raises:
            ValueError: If essential configuration (like API key when needed) is missing.
        """
        super().__init__(name="LLMHandlerThread", daemon=True)
        self.stt_queue = stt_queue
        self.llm_queue = llm_queue
        self.state_manager = state_manager
        self.stop_event = stop_event

        # --- OpenAI Client & State ---
        self.client: Optional[OpenAI] = None
        self._online_mode: bool = False # Determined during init/reconnect
        self._reconnect_attempt_time: float = 0.0
        self._reconnect_cooldown: float = 60.0 # Seconds between reconnect attempts
        self._last_api_error: Optional[str] = None # Store last known API error

        # --- Configuration ---
        self.api_key: Optional[str] = config.OPENAI_API_KEY
        self.model: str = config.LLM_MODEL
        self.timeout: float = config.LLM_TIMEOUT
        self.max_history_turns: int = config.LLM_MAX_CONVERSATION_TURNS
        self.temperature: float = config.LLM_TEMPERATURE
        self.max_tokens: int = config.LLM_MAX_TOKENS
        self.system_prompt: str = config.LLM_SYSTEM_PROMPT
        self.offline_fallback_enabled: bool = config.LLM_OFFLINE_FALLBACK_ENABLED
        self.offline_response: str = config.LLM_OFFLINE_RESPONSE

        # --- Conversation History ---
        # Initialize with the system prompt
        self.conversation_history: List[ChatMessage] = [
            {"role": "system", "content": self.system_prompt}
        ]

        # --- Initialization ---
        self._validate_config()
        self._initialize_client()

    def _validate_config(self) -> None:
        """Validate necessary LLM configuration."""
        if not self.api_key and not self.offline_fallback_enabled:
             # Critical error if no API key AND offline mode is disabled
             logger.error("OPENAI_API_KEY is missing and LLM offline fallback is disabled. LLM cannot function.")
             # No need to set error state here, _initialize_client will handle it
             # But raising helps prevent thread start if config is fundamentally broken
             raise ValueError("LLM configuration error: API key required or offline fallback must be enabled.")
        elif not self.api_key:
             logger.warning("OPENAI_API_KEY is missing. LLM will operate in offline fallback mode only.")
        logger.debug("LLM configuration validated.")


    def _initialize_client(self) -> None:
        """Initialize the OpenAI client if an API key is provided."""
        if not self.api_key:
            logger.warning("Cannot initialize OpenAI client: API key not provided.")
            self._online_mode = False
            # Set error state only if offline fallback is also disabled
            if not self.offline_fallback_enabled:
                 self.state_manager.set_state(State.ERROR, "LLM Error: API Key missing & Offline Fallback disabled.")
            return

        try:
            logger.info(f"Initializing OpenAI client (Model: {self.model}, Timeout: {self.timeout}s)...")
            self.client = OpenAI(api_key=self.api_key, timeout=self.timeout)
            # Optional: Perform a simple test call like listing models to verify the key early
            # self.client.models.list()
            logger.info("OpenAI client initialized successfully.")
            self._online_mode = True
            self._last_api_error = None # Clear last error on successful init
        except AuthenticationError as e:
            logger.error(f"OpenAI Authentication Failed: {e}. Please check your API Key.")
            self._online_mode = False
            self._last_api_error = f"AuthenticationError: {e}"
            self.state_manager.set_state(State.ERROR, f"OpenAI Auth Error: {e}")
        except OpenAIError as e: # Catch broader OpenAI specific errors
            logger.error(f"Failed to initialize OpenAI client: {e}")
            self._online_mode = False
            self._last_api_error = f"OpenAIError: {e}"
            self.state_manager.set_state(State.ERROR, f"OpenAI Init Error: {e}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred during OpenAI client initialization: {e}")
            self._online_mode = False
            self._last_api_error = f"Unexpected Init Error: {e}"
            # Setting ERROR state might be too aggressive for unexpected init errors,
            # consider just logging unless it's clearly fatal.
            # self.state_manager.set_state(State.ERROR, f"Unexpected LLM Init Error: {e}")

    def _attempt_reconnect(self) -> None:
        """Attempt to re-initialize the OpenAI client after a cooldown period."""
        current_time = time.monotonic()
        if self._online_mode:
            return # Already online
        if not self.api_key:
             return # Cannot reconnect without an API key

        if current_time - self._reconnect_attempt_time >= self._reconnect_cooldown:
            logger.info("Attempting to reconnect to OpenAI API...")
            self._reconnect_attempt_time = current_time
            self._initialize_client() # Re-run initialization logic
            if self._online_mode:
                 logger.info("Reconnected to OpenAI API successfully.")
            else:
                 logger.warning(f"Reconnection attempt failed. Last error: {self._last_api_error}")
        # else: cooldown period not met


    def _manage_conversation_history(self, user_message: str, assistant_response: str) -> None:
        """
        Adds the latest user message and assistant response to the history.
        Trims the history if it exceeds the configured maximum length,
        preserving the system prompt and the most recent turns.
        """
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "assistant", "content": assistant_response})

        # Calculate maximum number of messages (system + user/assistant pairs)
        max_messages = 1 + (self.max_history_turns * 2)

        if len(self.conversation_history) > max_messages:
            # Keep the system message (index 0) and the most recent turns
            # Calculate how many messages to keep (excluding system message)
            messages_to_keep = self.max_history_turns * 2
            # Slice to get the most recent messages
            recent_messages = self.conversation_history[-messages_to_keep:]
            # Reconstruct history
            self.conversation_history = [self.conversation_history[0]] + recent_messages
            logger.debug(f"Trimmed conversation history to {len(self.conversation_history)} messages ({self.max_history_turns} turns).")

    def reset_conversation(self) -> None:
        """Resets the conversation history back to only the system prompt."""
        logger.info("Resetting conversation history.")
        # Ensure system prompt exists, handle edge case of empty initial history
        system_message = self.conversation_history[0] if self.conversation_history and self.conversation_history[0]["role"] == "system" else {"role": "system", "content": self.system_prompt}
        self.conversation_history = [system_message]

    def _get_llm_response(self, prompt: str) -> Optional[str]:
        """
        Attempts to get a response from the online LLM API.

        Handles various API errors and updates the online status.

        Args:
            prompt: The user's input prompt.

        Returns:
            The LLM's response string, or None if an error occurred or
            the client is not available/online.
        """
        if not self._online_mode or self.client is None:
            logger.warning("Cannot query LLM: Client not initialized or not online.")
            return None

        logger.info("Querying OpenAI API...")
        # Create message list for the current request, including history
        messages_for_api = self.conversation_history + [{"role": "user", "content": prompt}]

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages_for_api,
                temperature=self.temperature,
                max_tokens=self.max_tokens
                # stream=False # Explicitly not streaming here, TTS handles streaming
            )
            response_text = completion.choices[0].message.content
            if response_text:
                 response_text = response_text.strip()

            # Log usage if available (v1.x API)
            if completion.usage:
                 logger.debug(f"OpenAI API Usage: Prompt={completion.usage.prompt_tokens}, Completion={completion.usage.completion_tokens}, Total={completion.usage.total_tokens}")

            logger.info("Received response from OpenAI API.")
            self._last_api_error = None # Clear last error on success
            return response_text

        except AuthenticationError as e:
            logger.error(f"OpenAI Authentication Error: {e}. Check API Key.")
            self._online_mode = False
            self._last_api_error = f"AuthenticationError: {e}"
            self.state_manager.set_state(State.ERROR, f"OpenAI Auth Error: {e}")
        except APITimeoutError:
            logger.error("OpenAI API request timed out.")
            self._online_mode = False
            self._last_api_error = "APITimeoutError"
        except APIConnectionError as e:
            logger.error(f"OpenAI API connection error: {e}")
            self._online_mode = False
            self._last_api_error = f"APIConnectionError: {e}"
        except RateLimitError:
            logger.error("OpenAI API rate limit exceeded. Please check your plan and usage.")
            self._online_mode = False # May recover later, but offline for now
            self._last_api_error = "RateLimitError"
        except APIStatusError as e: # Handles 4xx/5xx errors from OpenAI
            logger.error(f"OpenAI API returned an error status: {e.status_code} - {e.response}")
            self._online_mode = False # Assume offline on API errors
            self._last_api_error = f"APIStatusError: {e.status_code}"
            if e.status_code == 500 or e.status_code == 503: # Server error
                 logger.warning("OpenAI may be having temporary issues.")
            elif e.status_code == 400: # Bad request (e.g., prompt too long after history)
                 logger.error("Bad request sent to OpenAI. Check prompt/history length.")
                 # Consider resetting history if this error occurs?
                 # self.reset_conversation()
        except OpenAIError as e: # Catch other potential OpenAI specific errors
            logger.error(f"An OpenAI specific error occurred: {e}")
            self._online_mode = False
            self._last_api_error = f"OpenAIError: {e}"
        except Exception as e:
            logger.exception(f"An unexpected error occurred during OpenAI API call: {e}")
            self._online_mode = False # Fallback on unexpected errors
            self._last_api_error = f"Unexpected API Error: {e}"

        # Return None if any error occurred
        return None

    def run(self) -> None:
        """Main loop for the LLM handler thread."""
        if not self._online_mode and not self.offline_fallback_enabled:
             # If we start in a broken state (no key, no fallback), log and exit thread
             logger.error("LLMHandler cannot start: No API key and offline fallback disabled.")
             return # Exit thread cleanly

        logger.info("LLMHandler thread started.")
        while not self.stop_event.is_set():
            current_state = self.state_manager.get_state()

            if current_state == State.THINKING:
                try:
                    # Get prompt from STT queue with timeout
                    prompt = self.stt_queue.get(block=True, timeout=0.5)
                    logger.info(f"LLM Handler received prompt: '{prompt[:100]}{'...' if len(prompt)>100 else ''}'")

                    # Attempt reconnection if needed
                    if not self._online_mode:
                        self._attempt_reconnect()

                    # Attempt to get response from online LLM
                    response_text: Optional[str] = self._get_llm_response(prompt)

                    # --- Handle Offline Fallback ---
                    if response_text is None: # If online attempt failed or was skipped
                        if self.offline_fallback_enabled:
                            logger.warning(f"LLM Online request failed or skipped (Last API Error: {self._last_api_error}). Using offline fallback.")
                            response_text = self.offline_response
                            # ** Placeholder for actual local LLM integration **
                            # Example: response_text = local_llm.generate(prompt, history=self.conversation_history)
                            # Add the offline interaction to history *only* if it represents a meaningful exchange
                            # For a canned response, maybe don't add it, or add a specific note.
                            # self._manage_conversation_history(prompt, "[Offline Response Triggered]")
                        else:
                            logger.error("LLM Online request failed and offline fallback is disabled. Cannot generate response.")
                            # Maybe provide a generic error response to TTS?
                            response_text = "I encountered an issue and cannot respond right now."
                            # Ensure state moves away from THINKING, maybe back to IDLE or ERROR
                            if self.state_manager.is_state(State.THINKING):
                                self.state_manager.set_state(State.IDLE) # Or ERROR? IDLE might be less disruptive.

                    # --- Queue Response for TTS ---
                    if response_text:
                        logger.info(f"LLM Response: '{response_text[:100]}{'...' if len(response_text)>100 else ''}'")
                        try:
                            self.llm_queue.put_nowait(response_text)
                            # Update conversation history *only* if the response was from the actual LLM
                            # Don't add canned offline responses unless desired.
                            if self._online_mode and self._last_api_error is None: # Check if response was likely from successful API call
                                self._manage_conversation_history(prompt, response_text)

                            # Transition state to TTS synthesis
                            if self.state_manager.is_state(State.THINKING):
                                self.state_manager.set_state(State.SYNTHESIZING_TTS)
                        except queue.Full:
                             logger.error("LLM output queue (for TTS) is full. LLM response lost!")
                             # Revert state if we can't send response to TTS
                             if self.state_manager.is_state(State.THINKING):
                                 self.state_manager.set_state(State.IDLE)
                    else:
                        # Should generally not happen if fallback provides a response
                        logger.warning("LLM Handler: No response generated (online and offline failed).")
                        if self.state_manager.is_state(State.THINKING):
                             self.state_manager.set_state(State.IDLE) # Go back to idle if stuck

                except queue.Empty:
                    # No prompt received from STT queue within timeout
                    # If still THINKING, means STT finished but maybe queue was slow? Or state changed?
                    # Simply continue loop, let state manager handle overall flow.
                    continue
                except Exception as e:
                    logger.exception(f"An unexpected error occurred in LLM Handler loop: {e}")
                    if self.state_manager.is_state(State.THINKING):
                         self.state_manager.set_state(State.ERROR, f"LLM Handler loop error: {e}")
                    time.sleep(1) # Avoid busy-looping on unexpected errors
            else:
                # Not in THINKING state, sleep briefly
                time.sleep(0.1)

        logger.info("LLMHandler thread stopping.")
        # No explicit cleanup needed for OpenAI client object AFAIK

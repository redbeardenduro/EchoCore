# tts_synthesizer.py
"""
Synthesizes speech from text using the configured TTS engine.

Supports OpenAI TTS, ElevenLabs TTS (cloud), and Piper TTS (local).
Handles API errors, reconnection, and streaming audio output.
"""

import threading
import queue
import time
import io # For handling stream iterators
import logging
from typing import Optional, Iterator, Any # For type hinting

# Import project modules
try:
    import config
    from state_manager import StateManager, State
    # Import specific TTS clients if needed, or handle import errors gracefully
    from piper_tts import PiperClient # Assumes piper_tts.py is available
except ImportError as e:
    logging.error(f"Error importing project modules in tts_synthesizer.py: {e}")
    raise

# Attempt to import cloud TTS libraries only if configured
openai_client_class = None
elevenlabs_client_class = None
elevenlabs_errors = None
openai_errors = None

try:
    from openai import OpenAI, APIConnectionError, APITimeoutError, AuthenticationError, OpenAIError
    openai_client_class = OpenAI
    openai_errors = (APIConnectionError, APITimeoutError, AuthenticationError, OpenAIError)
    logging.debug("OpenAI library loaded successfully.")
except ImportError:
    if config.TTS_ENGINE == 'openai':
        logging.error("OpenAI library not found, but TTS_ENGINE is set to 'openai'. Please install it: pip install openai>=1.0.0")
        # Set error state early if configured engine is unavailable
        # state_manager.set_state(State.ERROR, "OpenAI library missing for TTS") # Cannot access state_manager here yet

try:
    from elevenlabs.client import ElevenLabs
    from elevenlabs import ApiError as ElevenLabsApiError # Use specific error type
    elevenlabs_client_class = ElevenLabs
    elevenlabs_errors = (ElevenLabsApiError,) # Tuple of specific errors
    logging.debug("ElevenLabs library loaded successfully.")
except ImportError:
    if config.TTS_ENGINE == 'elevenlabs':
        logging.error("ElevenLabs library not found, but TTS_ENGINE is set to 'elevenlabs'. Please install it: pip install elevenlabs")
        # Set error state early if configured engine is unavailable
        # state_manager.set_state(State.ERROR, "ElevenLabs library missing for TTS")


# Setup logger
logger = logging.getLogger(__name__)


class TTSSynthesizer(threading.Thread):
    """
    Thread to convert text from llm_queue to audio data onto tts_queue.

    Initializes the TTS client specified in the configuration. Handles text
    synthesis, manages online/offline status for cloud services, attempts
    reconnection, and streams audio byte chunks to the tts_queue.
    Sends None to the tts_queue to signal the end of speech.
    """
    def __init__(
        self,
        llm_queue: queue.Queue[str],            # Receives text prompts
        tts_queue: queue.Queue[Optional[bytes]],# Outputs audio bytes or None
        state_manager: StateManager,
        stop_event: threading.Event
    ):
        """
        Initializes the TTSSynthesizer.

        Args:
            llm_queue: Queue receiving text prompts from LLMHandler.
            tts_queue: Queue to put synthesized audio chunks (bytes) or None onto.
            state_manager: The application's state manager instance.
            stop_event: Threading event to signal when to stop processing.
        """
        super().__init__(name="TTSSynthesizerThread", daemon=True)
        self.llm_queue = llm_queue
        self.tts_queue = tts_queue
        self.state_manager = state_manager
        self.stop_event = stop_event

        # --- TTS Clients ---
        self.openai_client: Optional[OpenAI] = None
        self.elevenlabs_client: Optional[ElevenLabs] = None
        self.piper_client: Optional[PiperClient] = None

        # --- State & Config ---
        self.tts_engine: str = config.TTS_ENGINE
        self._online_mode: bool = True # Assume online unless init fails for cloud services
        self._reconnect_attempt_time: float = 0.0
        self._reconnect_cooldown: float = 60.0 # Seconds
        self._last_error: Optional[str] = None # Store last significant error message

        # --- Streaming Config ---
        # Use a chunk size appropriate for audio processing (e.g., matching output handler)
        # OpenAI/ElevenLabs iterators might yield variable sizes, but this helps downstream.
        self.audio_chunk_size: int = config.AUDIO_CHUNK_SIZE * config.AUDIO_OUTPUT_CHANNELS * 2 # Bytes for int16

        # --- Initialization ---
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize the TTS client based on configuration."""
        logger.info(f"Initializing TTS engine: {self.tts_engine}")
        init_success = False
        if self.tts_engine == 'openai':
            init_success = self._init_openai_client()
        elif self.tts_engine == 'elevenlabs':
            init_success = self._init_elevenlabs_client()
        elif self.tts_engine == 'piper':
            init_success = self._init_piper_client()
        else:
            self._last_error = f"Unknown TTS_ENGINE configured: {self.tts_engine}"
            logger.error(self._last_error)
            self.state_manager.set_state(State.ERROR, self._last_error)
            self._online_mode = False # Treat unknown engine as offline/error
            return

        # Update online status based on initialization result
        # Piper is considered "online" in the sense that it's functional if init succeeded.
        self._online_mode = init_success

        if not init_success and self.tts_engine != 'piper':
             # Cloud service failed init
            error_msg = f"Failed to initialize cloud TTS engine '{self.tts_engine}'. Last error: {self._last_error}"
            logger.error(error_msg)
            # Avoid overwriting specific error state if already set by init methods
            if not self.state_manager.is_state(State.ERROR):
                 self.state_manager.set_state(State.ERROR, error_msg)

    def _init_openai_client(self) -> bool:
        """Initialize the OpenAI client for TTS."""
        if openai_client_class is None:
             self._last_error = "OpenAI library not loaded."
             logger.error(self._last_error)
             return False
        if not config.OPENAI_API_KEY:
            self._last_error = "OPENAI_API_KEY not found for OpenAI TTS."
            logger.warning(self._last_error)
            return False # Cannot initialize without key

        try:
            self.openai_client = openai_client_class(
                api_key=config.OPENAI_API_KEY,
                timeout=config.LLM_TIMEOUT # Reuse LLM timeout for consistency?
            )
            # Optional: Test connection? e.g., list models if needed.
            logger.info("OpenAI TTS client initialized.")
            return True
        except AuthenticationError as e:
            self._last_error = f"OpenAI Authentication Failed for TTS: {e}. Check API Key."
            logger.error(self._last_error)
            self.state_manager.set_state(State.ERROR, self._last_error)
            return False
        except OpenAIError as e:
             self._last_error = f"OpenAI API Error initializing TTS client: {e}"
             logger.error(self._last_error)
             # Don't necessarily set ERROR state for non-auth init errors? Depends on policy.
             return False
        except Exception as e:
            self._last_error = f"Unexpected error initializing OpenAI TTS client: {e}"
            logger.exception(self._last_error) # Log full traceback for unexpected
            return False

    def _init_elevenlabs_client(self) -> bool:
        """Initialize the ElevenLabs client for TTS."""
        if elevenlabs_client_class is None:
             self._last_error = "ElevenLabs library not loaded."
             logger.error(self._last_error)
             return False
        if not config.ELEVENLABS_API_KEY:
            self._last_error = "ELEVENLABS_API_KEY not found for ElevenLabs TTS."
            logger.warning(self._last_error)
            return False

        try:
            self.elevenlabs_client = elevenlabs_client_class(api_key=config.ELEVENLABS_API_KEY)
            # Test connection by listing voices (or another simple API call)
            _ = self.elevenlabs_client.voices.get_all()
            logger.info("ElevenLabs TTS client initialized and authenticated.")
            return True
        except ElevenLabsApiError as e:
            # Handle specific ElevenLabs errors (like auth, rate limits during init check)
            self._last_error = f"ElevenLabs API Error initializing client: {e}"
            logger.error(self._last_error)
            if "Authentication" in str(e): # Check if it's an auth error
                 self.state_manager.set_state(State.ERROR, f"ElevenLabs Auth Error: {e}")
            return False
        except Exception as e:
            self._last_error = f"Unexpected error initializing ElevenLabs client: {e}"
            logger.exception(self._last_error)
            return False

    def _init_piper_client(self) -> bool:
        """Initialize the Piper TTS client."""
        try:
            logger.info("Initializing Piper TTS client...")
            self.piper_client = PiperClient() # Uses piper_tts.py

            if self.piper_client.last_error:
                self._last_error = f"Piper client initialization failed: {self.piper_client.last_error}"
                logger.error(self._last_error)
                self.state_manager.set_state(State.ERROR, self._last_error)
                return False

            voice_info = self.piper_client.get_voice_info()
            if voice_info:
                logger.info(f"Piper TTS client initialized successfully. Voice: {voice_info.get('model_name', 'Unknown')}")
            else:
                 logger.warning("Piper TTS client initialized, but could not get voice info.")
            return True # Piper is functional if init succeeded

        except Exception as e:
            self._last_error = f"Unexpected error initializing Piper TTS client: {e}"
            logger.exception(self._last_error)
            self.state_manager.set_state(State.ERROR, self._last_error)
            return False

    def _attempt_reconnect(self) -> None:
        """Try to reconnect to cloud services if offline."""
        if self._online_mode or self.tts_engine == 'piper':
            return # Already online or using local Piper

        current_time = time.monotonic()
        if current_time - self._reconnect_attempt_time >= self._reconnect_cooldown:
            logger.info(f"Attempting to reconnect to TTS service ({self.tts_engine})...")
            self._reconnect_attempt_time = current_time
            # Re-run the specific initialization logic
            init_success = False
            if self.tts_engine == 'openai':
                 init_success = self._init_openai_client()
            elif self.tts_engine == 'elevenlabs':
                 init_success = self._init_elevenlabs_client()

            self._online_mode = init_success # Update status
            if self._online_mode:
                 logger.info("Reconnected to TTS service successfully.")
            else:
                 logger.warning(f"Reconnection attempt failed. Last error: {self._last_error}")

    def _synthesize_audio(self, text: str) -> Optional[Iterator[bytes]]:
        """
        Calls the appropriate synthesis method based on the configured engine.

        Args:
            text: The text to synthesize.

        Returns:
            An iterator yielding audio chunks (bytes), or None if synthesis fails.
        """
        logger.info(f"Synthesizing text (Engine: {self.tts_engine}): '{text[:50]}{'...' if len(text)>50 else ''}'")
        self._last_error = None # Clear last error before attempting synthesis

        try:
            if self.tts_engine == 'openai' and self.openai_client and self._online_mode:
                return self._synthesize_openai(text)
            elif self.tts_engine == 'elevenlabs' and self.elevenlabs_client and self._online_mode:
                return self._synthesize_elevenlabs(text)
            elif self.tts_engine == 'piper' and self.piper_client:
                # Piper client handles its own online/offline status internally
                return self._synthesize_piper(text)
            else:
                # Fallback if engine is misconfigured, offline, or client failed init
                self._last_error = f"TTS engine '{self.tts_engine}' is not available or not online."
                logger.warning(self._last_error)
                # Attempt reconnect for cloud services if appropriate
                if self.tts_engine != 'piper':
                    self._attempt_reconnect()
                return None
        except Exception as e:
             # Catch unexpected errors during the selection/call process
             self._last_error = f"Unexpected error during TTS synthesis dispatch: {e}"
             logger.exception(self._last_error)
             return None


    def _synthesize_openai(self, text: str) -> Optional[Iterator[bytes]]:
        """Synthesize speech using OpenAI TTS API stream."""
        if not self.openai_client: return None
        try:
            response = self.openai_client.audio.speech.create(
                model=config.OPENAI_TTS_MODEL,
                voice=config.OPENAI_TTS_VOICE,
                input=text,
                response_format=config.OPENAI_TTS_FORMAT, # e.g., "pcm" requires config rate
                # speed=1.0 # Optional speed control
            )
            # Use iter_bytes for streaming
            # Use configured chunk size for consistency, though API might yield different sizes
            return response.iter_bytes(chunk_size=self.audio_chunk_size)
        except openai_errors as e: # Catch specific OpenAI errors
             self._last_error = f"OpenAI TTS Error: {type(e).__name__} - {e}"
             logger.error(self._last_error)
             self._online_mode = False # Assume offline on API errors
             if isinstance(e, AuthenticationError):
                  self.state_manager.set_state(State.ERROR, f"OpenAI Auth Error: {e}")
             return None
        except Exception as e:
             self._last_error = f"Unexpected OpenAI TTS Error: {e}"
             logger.exception(self._last_error)
             self._online_mode = False
             return None

    def _synthesize_elevenlabs(self, text: str) -> Optional[Iterator[bytes]]:
        """Synthesize speech using ElevenLabs API stream."""
        if not self.elevenlabs_client: return None
        try:
            audio_stream = self.elevenlabs_client.generate(
                text=text,
                voice=config.ELEVENLABS_VOICE,
                model=config.ELEVENLABS_MODEL,
                stream=True,
                output_format=config.ELEVENLABS_OUTPUT_FORMAT, # e.g., "pcm_16000"
                latency=3, # Optional latency optimization (0-4)
                # Consider stability/similarity settings here if needed
                # stability=config.ELEVENLABS_STABILITY,
                # similarity_boost=config.ELEVENLABS_SIMILARITY
            )
            # The generator itself is the iterator
            return audio_stream
        except elevenlabs_errors as e: # Catch specific ElevenLabs errors
             self._last_error = f"ElevenLabs TTS Error: {type(e).__name__} - {e}"
             logger.error(self._last_error)
             self._online_mode = False # Assume offline on API errors
             if "Authentication" in str(e): # Basic check for auth errors
                  self.state_manager.set_state(State.ERROR, f"ElevenLabs Auth Error: {e}")
             return None
        except Exception as e:
             self._last_error = f"Unexpected ElevenLabs TTS Error: {e}"
             logger.exception(self._last_error)
             self._online_mode = False
             return None

    def _synthesize_piper(self, text: str) -> Optional[Iterator[bytes]]:
        """Synthesize speech using local Piper TTS client stream."""
        if not self.piper_client: return None
        try:
            # Use the PiperClient's generate method which handles streaming
            audio_stream = self.piper_client.generate(
                text=text,
                stream=True,
                output_format="pcm_16000" # Request raw PCM
            )
            if audio_stream is None:
                # Error occurred within PiperClient, get the error message
                self._last_error = self.piper_client.get_last_error() or "Piper synthesis failed (no error detail)."
                logger.error(self._last_error)
                # Potentially set ERROR state if Piper fails consistently
                # self.state_manager.set_state(State.ERROR, self._last_error)
            return audio_stream # Returns the stdout stream iterator or None on error

        except Exception as e:
            # Catch errors in the interaction with PiperClient itself
            self._last_error = f"Unexpected Piper TTS interaction Error: {e}"
            logger.exception(self._last_error)
            self.state_manager.set_state(State.ERROR, self._last_error) # Error likely fatal
            return None


    def _stream_audio_to_queue(self, audio_stream: Iterator[bytes]) -> bool:
         """Reads chunks from the audio stream iterator and puts them on the tts_queue."""
         stream_successful = False
         first_chunk = True
         try:
             for chunk in audio_stream:
                 if self.stop_event.is_set():
                     logger.warning("Stop event set during TTS audio streaming.")
                     return False # Abort streaming

                 if chunk:
                     if first_chunk:
                         logger.debug("TTS Synthesizer: First audio chunk received from stream.")
                         # Transition state only once first chunk arrives
                         if self.state_manager.is_state(State.SYNTHESIZING_TTS):
                             self.state_manager.set_state(State.SPEAKING)
                         first_chunk = False

                     try:
                         # Put chunk onto the queue for the audio output handler
                         self.tts_queue.put(chunk, block=True, timeout=1.0) # Timeout helps prevent deadlocks
                         stream_successful = True # Mark success if at least one chunk sent
                     except queue.Full:
                          logger.error("TTS output queue is full! Audio data lost. Aborting stream.")
                          # If output queue is full, downstream handler is stuck, abort.
                          return False # Abort streaming

             # End of stream reached
             logger.info("TTS Synthesizer: Finished consuming audio stream.")
             return stream_successful # True if any chunks were successfully queued

         except Exception as e:
              # Catch potential errors during stream iteration (e.g., network issues for cloud)
              self._last_error = f"Error during TTS audio stream iteration: {e}"
              logger.exception(self._last_error)
              # If error happens mid-stream, try to signal end, but mark failure
              return False
         finally:
              # IMPORTANT: Signal end of speech to the output queue *after* the loop/exception handling.
              # This happens whether the stream completed successfully, failed, or was aborted.
              try:
                  logger.debug("TTS Synthesizer: Putting None marker onto TTS queue.")
                  self.tts_queue.put(None, block=True, timeout=1.0)
              except queue.Full:
                   logger.error("TTS output queue full! Could not queue None marker.")
              except Exception as e:
                   logger.error(f"Error queueing None marker: {e}")


    def run(self) -> None:
        """Main loop for the TTS synthesizer thread."""
        # Check initial state - exit early if configured TTS engine failed critically
        if not self._online_mode and not (self.tts_engine == 'piper' and self.piper_client is not None):
             logger.error(f"TTS Synthesizer cannot start: Engine '{self.tts_engine}' failed to initialize and is required.")
             return # Exit thread

        logger.info("TTSSynthesizer thread started, waiting for text...")
        while not self.stop_event.is_set():
            current_state = self.state_manager.get_state()

            if current_state == State.SYNTHESIZING_TTS:
                try:
                    # Wait for text prompt from the LLM queue
                    text_to_speak = self.llm_queue.get(block=True, timeout=0.5) # Timeout helps check stop_event
                    logger.debug(f"TTS Synthesizer received text from LLM queue.")

                    # Synthesize audio (this might fail and return None)
                    audio_stream = self._synthesize_audio(text_to_speak)

                    # Stream the audio (or handle synthesis failure)
                    synthesis_successful = False
                    if audio_stream:
                        logger.info("TTS Synthesizer: Streaming audio to output queue...")
                        # _stream_audio_to_queue handles state transition to SPEAKING
                        # and queueing the final None marker.
                        synthesis_successful = self._stream_audio_to_queue(audio_stream)
                        if not synthesis_successful and not self.stop_event.is_set():
                             logger.warning(f"TTS Synthesizer: Streaming failed or aborted. Last error: {self._last_error}")
                             # If streaming failed but we weren't stopped, revert state
                             if self.state_manager.is_state(State.SPEAKING):
                                  self.state_manager.set_state(State.IDLE)
                    else:
                        # Synthesis failed before streaming could start
                        logger.error(f"TTS Synthesizer: Synthesis failed. Last error: {self._last_error}")
                        # Ensure state moves away from SYNTHESIZING_TTS if synthesis fails
                        if self.state_manager.is_state(State.SYNTHESIZING_TTS):
                             self.state_manager.set_state(State.IDLE) # Revert to IDLE

                except queue.Empty:
                    # No text received from LLM queue within timeout
                    if self.state_manager.is_state(State.SYNTHESIZING_TTS):
                        logger.debug("TTS Synthesizer: LLM queue empty.")
                    # Continue loop to check state/stop_event
                    continue
                except Exception as e:
                    logger.exception(f"An unexpected error occurred in TTS Synthesizer loop: {e}")
                    if self.state_manager.is_state((State.SYNTHESIZING_TTS, State.SPEAKING)):
                         self.state_manager.set_state(State.ERROR, f"TTS loop error: {e}")
                    time.sleep(1) # Avoid busy-looping on unexpected errors
            else:
                # Not in SYNTHESIZING_TTS state, sleep briefly
                time.sleep(0.1)

        logger.info("TTSSynthesizer thread stopping.")
        # Cleanup TTS client resources if necessary (most SDKs handle this)
        # self._cleanup() # Add if specific cleanup needed

    # def _cleanup(self):
    #     # Add cleanup here if TTS clients have specific close/delete methods
    #     logger.info("Cleaning up TTSSynthesizer resources...")
    #     pass

# tts_synthesizer.py
"""
Synthesizes speech from text using the configured TTS engine.
Supports OpenAI TTS, ElevenLabs TTS (cloud), and Piper TTS (local).
"""
import threading
import queue
import time
import io
import os
import wave  # For Piper WAV output handling
import logging
from openai import OpenAI, APIConnectionError, APITimeoutError, AuthenticationError
import config
from state_manager import StateManager, State
from piper_tts import PiperClient  # Add this import

# Setup logger
logger = logging.getLogger(__name__)

# Try to import elevenlabs only if needed
if config.TTS_ENGINE == 'elevenlabs':
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import play as elevenlabs_play, stream as elevenlabs_stream, save as elevenlabs_save
    except ImportError:
        logger.warning("ElevenLabs package not installed, but elevenlabs TTS engine selected")

class TTSSynthesizer(threading.Thread):
    """
    Thread to convert text from llm_queue to audio data onto tts_queue.
    Supports multiple TTS backends.
    """
    def __init__(self, llm_queue: queue.Queue, tts_queue: queue.Queue, state_manager: StateManager, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.llm_queue = llm_queue
        self.tts_queue = tts_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.openai_client = None
        self.elevenlabs_client = None
        self.piper_client = None  # Add this for Piper client
        self.online_mode = True  # Assume online unless API keys missing or errors occur
        self.reconnect_attempt_time = 0
        self.reconnect_cooldown = 60  # seconds between reconnection attempts
        self.last_error = None  # Track the last error for reporting

        # Initialize the selected TTS engine
        self._init_client()

    def _init_openai_client(self):
        """Initialize the OpenAI client for TTS."""
        if config.OPENAI_API_KEY:
            try:
                self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.LLM_TIMEOUT)
                logger.info("OpenAI TTS client initialized.")
                return True
            except AuthenticationError:
                self.last_error = "OpenAI Authentication Failed for TTS. Check API Key."
                logger.error(f"ERROR: {self.last_error}")
                self.state_manager.set_state(State.ERROR)
                return False
            except Exception as e:
                self.last_error = f"Error initializing OpenAI TTS client: {e}"
                logger.error(f"ERROR: {self.last_error}")
                self.state_manager.set_state(State.ERROR)
                return False
        else:
            self.last_error = "OPENAI_API_KEY not found for OpenAI TTS."
            logger.warning(f"Warning: {self.last_error}")
            return False

    def _init_elevenlabs_client(self):
        """Initialize the ElevenLabs client for TTS."""
        if config.ELEVENLABS_API_KEY:
            try:
                self.elevenlabs_client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
                # Test connection by listing voices
                _ = self.elevenlabs_client.voices.get_all()
                logger.info("ElevenLabs TTS client initialized.")
                return True
            except Exception as e:
                self.last_error = f"Error initializing ElevenLabs client: {e}"
                logger.error(f"ERROR: {self.last_error}")
                self.state_manager.set_state(State.ERROR)
                return False
        else:
            self.last_error = "ELEVENLABS_API_KEY not found for ElevenLabs TTS."
            logger.warning(f"Warning: {self.last_error}")
            return False
            
    def _init_piper_client(self):
        """Initialize the Piper TTS client."""
        try:
            logger.info("Initializing Piper TTS client...")
            self.piper_client = PiperClient()
            
            # Check if initialization was successful
            if self.piper_client.last_error:
                self.last_error = self.piper_client.last_error
                logger.error(f"Piper initialization error: {self.last_error}")
                self.state_manager.set_state(State.ERROR)
                return False
                
            # Get voice info for logging
            voice_info = self.piper_client.get_voice_info()
            if voice_info:
                logger.info(f"Piper voice initialized: {voice_info.get('model_name', 'Unknown')}")
                
            # Piper is offline but functional if we reached here
            logger.info("Piper TTS client initialized successfully (offline mode).")
            return True
            
        except Exception as e:
            self.last_error = f"Error initializing Piper TTS client: {e}"
            logger.exception(self.last_error)
            self.state_manager.set_state(State.ERROR)
            return False

    def _init_client(self):
        """Initialize the selected TTS engine."""
        if config.TTS_ENGINE == 'openai':
            self.online_mode = self._init_openai_client()
        elif config.TTS_ENGINE == 'elevenlabs':
            self.online_mode = self._init_elevenlabs_client()
        elif config.TTS_ENGINE == 'piper':
            self.online_mode = self._init_piper_client()
        else:
            self.last_error = f"Unknown TTS_ENGINE configured: {config.TTS_ENGINE}"
            logger.error(f"ERROR: {self.last_error}")
            self.state_manager.set_state(State.ERROR)
            self.online_mode = False

        if not self.online_mode and config.TTS_ENGINE != 'piper':
            self.last_error = "Selected cloud TTS engine but cannot initialize. Cannot synthesize speech."
            logger.error(f"ERROR: {self.last_error}")
            if not self.state_manager.is_state(State.ERROR):  # Avoid overwriting other errors
                self.state_manager.set_state(State.ERROR)

    def _attempt_reconnect(self):
        """Try to reconnect to cloud services if offline."""
        current_time = time.time()
        if current_time - self.reconnect_attempt_time < self.reconnect_cooldown:
            return False
            
        logger.info("Attempting to reconnect to TTS service...")
        self.reconnect_attempt_time = current_time
        self._init_client()
        return self.online_mode

    def run(self):
        """Main loop for the TTS synthesizer thread."""
        if self.state_manager.is_state(State.ERROR) and config.TTS_ENGINE != 'piper':
             logger.warning("TTSSynthesizer cannot start due to configuration error.")
             return

        logger.info("TTS Synthesizer waiting for text...")
        while not self.stop_event.is_set():
            if self.state_manager.is_state(State.SYNTHESIZING_TTS):
                try:
                    text_to_speak = self.llm_queue.get(block=True, timeout=1.0)
                    logger.info(f"TTS Synthesizer received text: '{text_to_speak[:50]}...'")
                    
                    # Check if we need to attempt reconnecting to cloud service
                    if not self.online_mode and config.TTS_ENGINE != 'piper':
                        self._attempt_reconnect()

                    audio_stream = None
                    synthesis_successful = False

                    # Play a quick audio cue to indicate processing started
                    self._play_processing_cue()

                    # --- Synthesize Audio ---
                    if config.TTS_ENGINE == 'openai' and self.openai_client and self.online_mode:
                        audio_stream = self._synthesize_openai(text_to_speak)
                    elif config.TTS_ENGINE == 'elevenlabs' and self.elevenlabs_client and self.online_mode:
                        audio_stream = self._synthesize_elevenlabs(text_to_speak)
                    elif config.TTS_ENGINE == 'piper' and self.piper_client:
                        audio_stream = self._synthesize_piper(text_to_speak)
                    else:
                        # Fallback if online failed or Piper selected but failed init
                        self.last_error = "TTS Synthesizer: Cannot synthesize - engine not available."
                        logger.warning(self.last_error)
                        self.state_manager.set_state(State.ERROR)

                    # --- Stream Audio Chunks to Output Queue ---
                    if audio_stream:
                        logger.info("TTS Synthesizer: Streaming audio to output queue...")
                        self.state_manager.set_state(State.SPEAKING) # Signal speaking has started
                        chunk_size = config.AUDIO_CHUNK_SIZE * 2 # Read enough bytes for int16
                        first_chunk = True
                        while True:
                            chunk = audio_stream.read(chunk_size)
                            if not chunk:
                                break
                            if first_chunk:
                                logger.info("TTS Synthesizer: First audio chunk received.")
                                first_chunk = False
                            self.tts_queue.put(chunk)
                        logger.info("TTS Synthesizer: Finished streaming audio.")
                        synthesis_successful = True
                        # Signal end of speech by putting None or a special marker
                        self.tts_queue.put(None)

                    # --- Handle Synthesis Failure ---
                    if not synthesis_successful:
                        logger.warning(f"TTS Synthesizer: Synthesis failed. Error: {self.last_error}")
                        # Avoid getting stuck - transition back to IDLE or ERROR
                        if not self.state_manager.is_state(State.ERROR):
                            self.state_manager.set_state(State.IDLE)


                except queue.Empty:
                    # No text received, check state again
                    if not self.state_manager.is_state(State.SYNTHESIZING_TTS):
                        logger.debug("TTS Synthesizer: State changed while waiting for text.")
                    continue
                except Exception as e:
                    self.last_error = f"An unexpected error occurred in TTS Synthesizer: {e}"
                    logger.exception(self.last_error)
                    self.state_manager.set_state(State.ERROR)
                    time.sleep(1)
            else:
                # Not in SYNTHESIZING_TTS state, sleep briefly
                time.sleep(0.1)

        logger.info("TTS Synthesizer stopping.")
    
    def _play_processing_cue(self):
        """Play a short audio cue to indicate processing has started."""
        # For now, just a placeholder. You would implement a short tone generator here.
        # Could be implemented with a simple sine wave generator or pre-recorded file
        logger.debug("Processing audio cue would play here")
        pass

    def _synthesize_openai(self, text):
        """Synthesize speech using OpenAI TTS API and return audio stream."""
        try:
            logger.info("Synthesizing with OpenAI TTS...")
            # Use streaming response
            response = self.openai_client.audio.speech.with_streaming_response.create(
                model=config.OPENAI_TTS_MODEL,
                voice=config.OPENAI_TTS_VOICE,
                input=text,
                response_format=config.OPENAI_TTS_FORMAT, # e.g., "pcm", "mp3", "opus"
                # speed=1.0 # Optional speed control
            )
            # Return the raw stream content iterator
            return response.iter_bytes(chunk_size=config.AUDIO_CHUNK_SIZE * 2) # Read enough bytes for int16
        except APIConnectionError:
            self.last_error = "OpenAI TTS Error: Connection failed."
            logger.error(self.last_error)
            self.online_mode = False
        except APITimeoutError:
            self.last_error = "OpenAI TTS Error: Request timed out."
            logger.error(self.last_error)
            self.online_mode = False
        except AuthenticationError:
            self.last_error = "OpenAI TTS Error: Authentication failed."
            logger.error(self.last_error)
            self.online_mode = False
            self.state_manager.set_state(State.ERROR)
        except Exception as e:
            self.last_error = f"OpenAI TTS Error: {e}"
            logger.exception(self.last_error)
            self.online_mode = False
        return None # Indicate failure

    def _synthesize_elevenlabs(self, text):
        """Synthesize speech using ElevenLabs API and return audio stream."""
        try:
            logger.info("Synthesizing with ElevenLabs TTS...")
            # Use the stream function
            audio_stream = self.elevenlabs_client.generate(
                text=text,
                voice=config.ELEVENLABS_VOICE,
                model=config.ELEVENLABS_MODEL,
                stream=True,
                output_format="pcm_16000" # Request PCM for direct playback
                # latency=3 # Optional latency optimization level
            )
            return audio_stream # Returns an iterator
        except Exception as e:
            self.last_error = f"ElevenLabs TTS Error: {e}"
            logger.exception(self.last_error)
            self.online_mode = False
            # Check for specific API errors if needed
            if "Authentication" in str(e):
                self.state_manager.set_state(State.ERROR)
        return None # Indicate failure

    def _synthesize_piper(self, text):
        """Synthesize speech using local Piper TTS client and return audio stream."""
        try:
            logger.info("Synthesizing with Piper TTS (local)...")
            
            # Use the PiperClient to handle synthesis with streaming
            audio_stream = self.piper_client.generate(
                text=text,
                stream=True,
                output_format="pcm_16000"
            )
            
            if not audio_stream:
                self.last_error = self.piper_client.get_last_error() or "Piper synthesis failed with no error details"
                logger.error(self.last_error)
                return None
                
            return audio_stream

        except Exception as e:
            self.last_error = f"Piper TTS Error: {e}"
            logger.exception(self.last_error)
            self.state_manager.set_state(State.ERROR)
        return None # Indicate failure

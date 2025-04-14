# audio_input.py
"""
Handles audio input using sounddevice and wake word detection using Porcupine.
Includes audio feedback cues for state changes.
"""
import threading
import queue
import time
import struct
import numpy as np
import sounddevice as sd
import pvporcupine
import logging
import math
import config
from state_manager import StateManager, State
from audio_utils import list_audio_devices, find_optimal_device
from typing import Optional, List, Tuple

# Setup logger
logger = logging.getLogger(__name__)

class AudioInputHandler(threading.Thread):
    """
    Thread to capture audio, detect wake word, and manage LISTENING state.

    Captures audio from the microphone using sounddevice.
    Uses Porcupine to detect a wake word ('Hey Echo', 'Computer', etc.).
    When the wake word is detected and the system is IDLE, it changes the state
    to LISTENING, plays a confirmation cue, and starts forwarding audio chunks
    to the audio_queue for STT processing.
    Implements a timeout mechanism to return to IDLE if no speech is detected.
    Plays audio cues for wake word detection, timeout, and errors.
    """
    def __init__(self, audio_queue: queue.Queue, state_manager: StateManager, stop_event: threading.Event):
        """
        Initializes the AudioInputHandler.

        Args:
            audio_queue: Queue to put raw audio chunks onto for STT when listening.
            state_manager: The shared StateManager instance.
            stop_event: Event to signal thread termination.
        """
        super().__init__(daemon=True, name="AudioInputThread")
        self.audio_queue = audio_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.porcupine: Optional[pvporcupine.Porcupine] = None
        self.audio_stream: Optional[sd.InputStream] = None
        self.listening_timeout: float = config.LISTENING_TIMEOUT
        self.listening_start_time: float = 0.0
        self.is_timeout_check_enabled: bool = False # Enable check only after wake word
        self.selected_device: Optional[int] = None

        # Audio cue variables
        self.wake_cue: Optional[np.ndarray] = None
        self.timeout_cue: Optional[np.ndarray] = None
        self.error_cue: Optional[np.ndarray] = None
        self.should_play_cue: bool = False
        self.current_cue: Optional[np.ndarray] = None

        self._initialize_components()

    def _initialize_components(self):
        """Initializes Porcupine, audio device selection, and audio cues."""
        # Validate Porcupine configuration
        if not config.PICOVOICE_ACCESS_KEY:
            logger.error("PICOVOICE_ACCESS_KEY is not configured. Wake word detection disabled.")
            self.state_manager.set_state(State.ERROR, error_message="Picovoice Access Key missing.")
            return
        if not config.PORCUPINE_KEYWORD_PATHS:
            logger.error("PORCUPINE_KEYWORD_PATHS is not configured. Wake word detection disabled.")
            self.state_manager.set_state(State.ERROR, error_message="Porcupine keyword paths missing.")
            return

        # Check audio devices and select optimal input device
        self._check_and_select_audio_device()

        try:
            # Initialize Porcupine
            logger.info("Initializing Porcupine wake word engine...")
            self.porcupine = pvporcupine.create(
                access_key=config.PICOVOICE_ACCESS_KEY,
                keyword_paths=config.PORCUPINE_KEYWORD_PATHS,
                model_path=config.PORCUPINE_MODEL_PATH, # Can be None for default
                sensitivities=config.PORCUPINE_SENSITIVITIES
            )
            logger.info(f"Porcupine initialized. Listening for keywords in: {config.PORCUPINE_KEYWORD_PATHS}")
            logger.info(f"Porcupine expected sample rate: {self.porcupine.sample_rate}, Frame length: {self.porcupine.frame_length}")

            # Ensure config sample rate matches Porcupine
            if config.AUDIO_SAMPLE_RATE != self.porcupine.sample_rate:
                logger.warning(f"Configured sample rate ({config.AUDIO_SAMPLE_RATE} Hz) differs from Porcupine's ({self.porcupine.sample_rate} Hz). Using Porcupine's rate.")
                config.AUDIO_SAMPLE_RATE = self.porcupine.sample_rate # Override config

            # Generate audio cues if enabled
            if config.ENABLE_AUDIO_CUES:
                self._generate_audio_cues()

        except pvporcupine.PorcupineError as e:
            logger.error(f"Error initializing Porcupine: {e}")
            self.state_manager.set_state(State.ERROR, error_message=f"Porcupine init failed: {e}")
        except ValueError as e:
             logger.error(f"Configuration error for Porcupine: {e}")
             self.state_manager.set_state(State.ERROR, error_message=f"Porcupine config error: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error during Porcupine initialization: {e}")
            self.state_manager.set_state(State.ERROR, error_message="Unexpected Porcupine init error.")

    def _check_and_select_audio_device(self):
        """Checks available audio devices and selects the optimal input device."""
        logger.info("Checking available audio input devices...")
        list_audio_devices() # Log all devices for debugging

        self.selected_device = find_optimal_device(
            mode='input',
            preferred_index=config.AUDIO_INPUT_DEVICE_INDEX,
        )

        if self.selected_device is None:
            logger.warning("Could not find a suitable audio input device. Using system default.")
            # Attempt to use default device index if needed by sounddevice
            try:
                default_device_info = sd.query_devices(kind='input')
                self.selected_device = default_device_info['index']
                logger.info(f"Using system default input device: [{self.selected_device}] {default_device_info['name']}")
            except Exception as e:
                 logger.error(f"Could not determine system default input device: {e}")
                 self.state_manager.set_state(State.ERROR, error_message="No suitable input device found.")
                 return
        else:
            try:
                device_info = sd.query_devices(self.selected_device)
                logger.info(f"Selected audio input device: [{self.selected_device}] {device_info['name']}")
            except Exception as e:
                logger.error(f"Error getting info for selected device index {self.selected_device}: {e}")
                # Fallback to default if info query fails
                self.selected_device = None
                logger.warning("Falling back to system default input device due to query error.")


    def _generate_audio_cues(self):
        """Generates simple audio cues (tones) for feedback."""
        logger.info("Generating audio cues...")
        # Wake word detected cue (ascending tones)
        self.wake_cue = self._generate_tone_sequence(
            frequencies=[440, 660, 880], # A4, E5, A5
            durations=[0.08, 0.08, 0.15],
            volume=config.AUDIO_CUE_VOLUME
        )
        # Timeout cue (descending tone)
        self.timeout_cue = self._generate_tone_sequence(
            frequencies=[660, 440], # E5, A4
            durations=[0.1, 0.2],
            volume=config.AUDIO_CUE_VOLUME
        )
        # Error cue (short low buzz)
        self.error_cue = self._generate_tone_sequence(
            frequencies=[110, 110], # A2
            durations=[0.1, 0.1],
            volume=config.AUDIO_CUE_VOLUME * 0.8 # Slightly lower volume for error
        )
        logger.info("Audio cues generated.")

    def _generate_tone_sequence(self, frequencies: List[float], durations: List[float], volume: float = 0.3) -> np.ndarray:
        """
        Generates a sequence of sine wave tones with fades.

        Args:
            frequencies: List of frequencies for each tone.
            durations: List of durations for each tone.
            volume: Amplitude of the tones (0.0 to 1.0).

        Returns:
            A NumPy array containing the audio data in int16 format.
        """
        sample_rate = config.AUDIO_SAMPLE_RATE
        samples = []
        fade_duration_ms = 10 # Fade duration in milliseconds

        for freq, duration in zip(frequencies, durations):
            if duration <= 0: continue # Skip zero or negative duration tones

            num_samples = int(sample_rate * duration)
            t = np.linspace(0., duration, num_samples, endpoint=False)
            tone = (np.sin(freq * 2. * np.pi * t) * volume).astype(np.float32)

            # Apply fade-in/fade-out envelope to prevent clicks
            fade_len = int(sample_rate * (fade_duration_ms / 1000.0))
            fade_len = min(fade_len, num_samples // 2) # Ensure fade isn't longer than half the tone

            if fade_len > 0:
                fade_in = np.linspace(0., 1., fade_len)
                fade_out = np.linspace(1., 0., fade_len)
                tone[:fade_len] *= fade_in
                tone[-fade_len:] *= fade_out

            # Convert to int16
            int16_tone = np.int16(tone * 32767)
            samples.append(int16_tone)

        if not samples:
             return np.array([], dtype=np.int16) # Return empty array if no tones generated

        return np.concatenate(samples)

    def _play_cue(self, cue_type: str):
        """Plays the specified audio cue if enabled."""
        if not config.ENABLE_AUDIO_CUES:
            return

        cue_to_play = None
        if cue_type == "wake" and self.wake_cue is not None:
            cue_to_play = self.wake_cue
        elif cue_type == "timeout" and self.timeout_cue is not None:
            cue_to_play = self.timeout_cue
        elif cue_type == "error" and self.error_cue is not None:
            cue_to_play = self.error_cue
        else:
             logger.warning(f"Requested unknown or ungenerated audio cue: {cue_type}")
             return

        if cue_to_play.size > 0:
            try:
                # Play asynchronously
                sd.play(cue_to_play, config.AUDIO_SAMPLE_RATE, blocking=False)
                logger.debug(f"Playing '{cue_type}' audio cue.")
            except Exception as e:
                logger.error(f"Error playing audio cue '{cue_type}': {e}")


    def _wake_word_callback(self, keyword_index: int):
        """Callback executed when a wake word is detected by Porcupine."""
        logger.info(f"Wake word detected (Keyword Index: {keyword_index})!")
        if self.state_manager.is_state(State.IDLE):
            self._play_cue("wake")
            self.state_manager.set_state(State.LISTENING)
            self.listening_start_time = time.monotonic()
            self.is_timeout_check_enabled = True # Start checking for timeout
            logger.debug("Timeout check enabled.")
        else:
            logger.info(f"Wake word detected but ignored - current state: {self.state_manager.get_state().name}")

    def _check_listening_timeout(self):
        """Checks if the listening state has timed out due to silence."""
        if not self.is_timeout_check_enabled:
             return

        if self.state_manager.is_state(State.LISTENING) and \
           (time.monotonic() - self.listening_start_time > self.listening_timeout):

            logger.info(f"Listening timeout after {self.listening_timeout:.1f} seconds. Returning to IDLE.")
            self._play_cue("timeout")
            self.state_manager.set_state(State.IDLE)
            self.is_timeout_check_enabled = False # Disable check until next wake word
            logger.debug("Timeout check disabled.")


    def run(self):
        """Main loop for the audio input thread."""
        if self.state_manager.is_state(State.ERROR):
            logger.error("AudioInputHandler cannot start due to prior initialization error.")
            return
        if self.porcupine is None:
            logger.error("AudioInputHandler cannot start: Porcupine not initialized.")
            if not self.state_manager.is_state(State.ERROR):
                 self.state_manager.set_state(State.ERROR, error_message="Porcupine failed to initialize.")
            return

        try:
            # Initialize and start the audio stream
            self.audio_stream = sd.InputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                blocksize=self.porcupine.frame_length, # Process audio in chunks matching Porcupine's frame size
                device=self.selected_device,
                channels=config.AUDIO_INPUT_CHANNELS,
                dtype=config.AUDIO_DTYPE,
                callback=self._audio_callback,
                latency='low' # Request low latency
            )
            self.audio_stream.start()
            device_name = self.audio_stream.device if isinstance(self.audio_stream.device, str) else f"Index {self.audio_stream.device}"
            logger.info(f"Audio stream started on device '{device_name}'...")

            # Keep the thread alive, processing happens in the callback
            while not self.stop_event.is_set():
                # Check for listening timeout periodically
                self._check_listening_timeout()

                # Brief sleep to prevent high CPU usage in the main loop
                time.sleep(0.1)

        except sd.PortAudioError as e:
            error_msg = f"Sounddevice/PortAudio Error in Audio Input: {e}"
            logger.error(error_msg)
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
            self._play_cue("error")
        except Exception as e:
            error_msg = f"An unexpected error occurred in Audio Input thread: {e}"
            logger.exception(error_msg) # Log the full traceback
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
            self._play_cue("error")
        finally:
            self._cleanup()

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status: sd.CallbackFlags):
        """
        Audio callback function invoked by sounddevice for each audio buffer.

        Args:
            indata: Input audio buffer (NumPy array).
            frames: Number of frames in the buffer.
            time_info: Timing information (not typically used here).
            status: Callback status flags.
        """
        if status:
            logger.warning(f"Audio input status flags: {status}")
            if status.input_overflow:
                 logger.error("Input overflow detected! Audio data may have been lost.")
            if status.input_underflow:
                 logger.warning("Input underflow detected.") # Less critical usually

        if self.porcupine and self.state_manager.get_state() != State.ERROR:
            try:
                # Porcupine expects a list or tuple of int16 samples
                # Ensure the input data is 1D if it's multichannel
                if indata.ndim > 1:
                    pcm = indata[:, 0].astype(np.int16).tolist()
                else:
                    pcm = indata.astype(np.int16).tolist()

                # Process the frame with Porcupine
                keyword_index = self.porcupine.process(pcm)
                if keyword_index >= 0:
                    # Wake word detected - trigger the callback
                    # Run the callback in a separate thread to avoid blocking the audio stream
                    threading.Thread(target=self._wake_word_callback, args=(keyword_index,), daemon=True).start()

                # If in LISTENING state, forward audio data to the STT queue
                current_state = self.state_manager.get_state()
                if current_state == State.LISTENING or current_state == State.PROCESSING_STT:
                     # Add raw bytes to the queue for the STT processor
                     try:
                          self.audio_queue.put_nowait(indata.tobytes())
                          # Reset listening timeout timer if we are receiving audio in the listening state
                          self.listening_start_time = time.monotonic()
                     except queue.Full:
                          logger.warning("Audio queue is full. Dropping audio data.")

            except Exception as e:
                logger.exception(f"Error during audio callback processing: {e}")
                # Consider setting ERROR state only if errors are persistent

    def _cleanup(self):
        """Cleans up resources like the audio stream and Porcupine instance."""
        logger.info("Cleaning up Audio Input Handler...")
        if self.audio_stream is not None:
            try:
                if not self.audio_stream.closed:
                    self.audio_stream.stop()
                    self.audio_stream.close()
                logger.info("Audio stream stopped and closed.")
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
            finally:
                 self.audio_stream = None

        if self.porcupine is not None:
            try:
                self.porcupine.delete()
                logger.info("Porcupine instance deleted.")
            except Exception as e:
                 logger.error(f"Error deleting Porcupine instance: {e}")
            finally:
                 self.porcupine = None

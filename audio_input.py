# audio_input.py
"""
Handles audio input using sounddevice and wake word detection using Porcupine.

Captures audio from the microphone, passes frames to Porcupine for wake word
detection, and forwards audio chunks to the STT processor when in the
LISTENING state. Also handles simple audio cue playback upon state changes.
"""

import threading
import queue
import time
import struct # Keep for potential future use, though numpy handles conversion now
import numpy as np
import sounddevice as sd
import pvporcupine
import logging
import math # Keep for tone generation
from typing import Optional, List, Any # For type hinting

# Import project modules - use absolute imports if structure allows, otherwise relative
try:
    import config # Assuming config.py is in the same directory or Python path
    from state_manager import StateManager, State
    from audio_utils import find_optimal_device # Keep list_audio_devices for debugging if needed
except ImportError as e:
     # Handle potential import errors if structure changes
    logging.error(f"Error importing project modules in audio_input.py: {e}")
    raise

# Setup logger
logger = logging.getLogger(__name__)

class AudioInputHandler(threading.Thread):
    """
    Thread to manage audio input, wake word detection, and audio queuing.

    Initializes Porcupine wake word engine and a sounddevice InputStream.
    Listens for the wake word when IDLE. When LISTENING, sends audio chunks
    to the audio_queue. Handles timeouts and basic audio feedback cues.
    """
    def __init__(
        self,
        audio_queue: queue.Queue[bytes], # Queue for raw audio bytes
        state_manager: StateManager,
        stop_event: threading.Event
    ):
        """
        Initializes the AudioInputHandler.

        Args:
            audio_queue: Thread-safe queue to put raw audio chunks (bytes) for STT.
            state_manager: The application's state manager instance.
            stop_event: Threading event to signal when to stop processing.

        Raises:
            ValueError: If required configuration (API keys, paths) is missing.
            pvporcupine.PorcupineError: If Porcupine initialization fails.
            sd.PortAudioError: If audio device query or stream creation fails.
        """
        super().__init__(name="AudioInputThread", daemon=True) # Set thread name
        self.audio_queue = audio_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.porcupine: Optional[pvporcupine.Porcupine] = None
        self.audio_stream: Optional[sd.InputStream] = None
        self.listening_start_time: float = 0.0
        self.is_timeout_check_active: bool = False # Renamed for clarity

        # --- Configuration dependent initializations ---
        self.access_key: Optional[str] = config.PICOVOICE_ACCESS_KEY
        self.keyword_paths: List[str] = config.PORCUPINE_KEYWORD_PATHS
        self.model_path: Optional[str] = config.PORCUPINE_MODEL_PATH
        self.sensitivities: List[float] = config.PORCUPINE_SENSITIVITIES
        self.sample_rate: int = config.AUDIO_SAMPLE_RATE
        self.frame_length: int = 0 # Will be set by Porcupine
        self.listening_timeout: float = config.LISTENING_TIMEOUT
        self.selected_device_index: Optional[int] = config.AUDIO_INPUT_DEVICE_INDEX

        # --- Audio Cue Setup ---
        self.play_audio_cues: bool = config.ENABLE_AUDIO_CUES
        self.cue_volume: float = config.AUDIO_CUE_VOLUME
        self._wake_cue: Optional[np.ndarray] = None
        self._timeout_cue: Optional[np.ndarray] = None
        self._error_cue: Optional[np.ndarray] = None
        self._should_play_cue: bool = False
        self._current_cue: Optional[np.ndarray] = None

        # --- Initialization Steps ---
        self._validate_config()
        self.selected_device_index = self._select_audio_device()
        self._initialize_porcupine()
        if self.play_audio_cues:
            self._generate_audio_cues()

    def _validate_config(self) -> None:
        """Validate necessary configuration settings."""
        if not self.access_key:
            raise ValueError("PICOVOICE_ACCESS_KEY is not configured.")
        if not self.keyword_paths:
            raise ValueError("PORCUPINE_KEYWORD_PATHS is not configured or empty.")
        if len(self.keyword_paths) != len(self.sensitivities):
            raise ValueError("Number of Porcupine keyword paths does not match sensitivities.")
        logger.debug("Configuration validated.")

    def _select_audio_device(self) -> Optional[int]:
        """Select the audio input device using audio_utils."""
        logger.debug(f"Finding optimal input device (Preferred: {self.selected_device_index})")
        # Returns None if default is preferred or specific index is invalid/not found
        return find_optimal_device(mode='input', preferred_index=self.selected_device_index)

    def _initialize_porcupine(self) -> None:
        """Initialize the Porcupine wake word engine."""
        try:
            self.porcupine = pvporcupine.create(
                access_key=self.access_key, # type: ignore # Access key validated earlier
                keyword_paths=self.keyword_paths,
                model_path=self.model_path, # None uses default model
                sensitivities=self.sensitivities
            )
            # Store frame_length required by Porcupine
            self.frame_length = self.porcupine.frame_length

            # Ensure config sample rate matches Porcupine's expectation
            if self.sample_rate != self.porcupine.sample_rate:
                logger.warning(
                    f"Configured sample rate ({self.sample_rate}Hz) differs from Porcupine's required rate "
                    f"({self.porcupine.sample_rate}Hz). Adjusting to Porcupine's rate."
                )
                self.sample_rate = self.porcupine.sample_rate # Adjust internal rate

            logger.info(f"Porcupine initialized (v{pvporcupine.VERSION}).")
            logger.info(f"Listening for keywords: {self.keyword_paths}")
            logger.info(f"Using sensitivities: {self.sensitivities}")
            logger.info(f"Required sample rate: {self.sample_rate}Hz, Frame length: {self.frame_length} samples")

        except pvporcupine.PorcupineError as e:
            logger.error(f"Failed to initialize Porcupine: {e}")
            # Set state to ERROR, preventing thread from starting stream
            self.state_manager.set_state(State.ERROR, error_message=f"Porcupine init failed: {e}")
            raise # Re-raise to prevent thread start

    def _generate_audio_cues(self) -> None:
        """Generate audio cues using numpy."""
        logger.debug("Generating audio cues...")
        self._wake_cue = self._generate_tone_sequence([440, 660, 880], [0.08, 0.08, 0.15])
        self._timeout_cue = self._generate_tone_sequence([880, 660, 440], [0.1, 0.1, 0.2])
        self._error_cue = self._generate_tone_sequence([220, 220], [0.1, 0.1], volume=self.cue_volume * 0.8) # Slightly softer error
        logger.info("Audio cues generated.")

    def _generate_tone_sequence(self, frequencies: List[float], durations: List[float], volume: Optional[float] = None) -> np.ndarray:
        """Generate a sequence of tones with fade."""
        if volume is None:
            volume = self.cue_volume

        samples_list: List[np.ndarray] = []
        total_duration = sum(durations)
        fade_samples = int(self.sample_rate * 0.01) # 10ms fade

        for freq, duration in zip(frequencies, durations):
            num_samples = int(self.sample_rate * duration)
            t = np.linspace(0., duration, num_samples, endpoint=False)
            tone = (np.sin(2 * np.pi * freq * t) * volume * 32767).astype(np.int16) # Scale to int16

            # Apply fade only if tone is long enough
            if num_samples > 2 * fade_samples:
                fade_in = np.linspace(0., 1., fade_samples)
                fade_out = np.linspace(1., 0., fade_samples)
                tone[:fade_samples] = (tone[:fade_samples] * fade_in).astype(np.int16)
                tone[-fade_samples:] = (tone[-fade_samples:] * fade_out).astype(np.int16)

            samples_list.append(tone)

        return np.concatenate(samples_list) if samples_list else np.array([], dtype=np.int16)

    def _trigger_audio_cue(self, cue_type: str) -> None:
        """Flags that an audio cue should be played."""
        if not self.play_audio_cues:
            return

        if cue_type == "wake" and self._wake_cue is not None:
            self._current_cue = self._wake_cue
            self._should_play_cue = True
            logger.debug("Wake cue triggered.")
        elif cue_type == "timeout" and self._timeout_cue is not None:
            self._current_cue = self._timeout_cue
            self._should_play_cue = True
            logger.debug("Timeout cue triggered.")
        elif cue_type == "error" and self._error_cue is not None:
            self._current_cue = self._error_cue
            self._should_play_cue = True
            logger.debug("Error cue triggered.")
        else:
            logger.warning(f"Requested unknown or non-generated cue type: {cue_type}")

    def _wake_word_detected(self, keyword_index: int) -> None:
        """Handles actions upon wake word detection."""
        keyword_name = self.keyword_paths[keyword_index].split('/')[-1].split('.')[0] # Extract name
        logger.info(f"Wake word '{keyword_name}' detected (Index: {keyword_index})!")

        if self.state_manager.is_state(State.IDLE):
            self._trigger_audio_cue("wake")
            self.state_manager.set_state(State.LISTENING)
            self.listening_start_time = time.monotonic() # Use monotonic clock for intervals
            self.is_timeout_check_active = True
            logger.info("Transitioned to LISTENING state.")
        else:
            logger.debug(f"Wake word detected but ignored - current state: {self.state_manager.get_state().name}")

    def _check_listening_timeout(self) -> None:
        """Checks for listening timeout and resets state if necessary."""
        if not self.is_timeout_check_active:
            return

        # Check only applicable states for timeout
        if self.state_manager.is_state((State.LISTENING, State.PROCESSING_STT)):
            elapsed_time = time.monotonic() - self.listening_start_time
            if elapsed_time > self.listening_timeout:
                logger.info(f"Listening timeout after {elapsed_time:.1f} seconds. Returning to IDLE.")
                self._trigger_audio_cue("timeout")
                self.state_manager.set_state(State.IDLE)
                self.is_timeout_check_active = False # Disable check until next wake word
        else:
             # If state moved beyond listening/processing, disable timeout check
             self.is_timeout_check_active = False


    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        """
        Sounddevice callback function. Processes audio frames for wake word
        and queues audio data if listening. Also handles playing audio cues.
        """
        if status:
            logger.warning(f"Audio input status flags: {status}")
            if status.input_overflow:
                 logger.error("Input overflow detected! Audio data may have been lost.")
            if status.priming_output: # Should not happen on input stream
                 logger.warning("Priming output detected on input stream callback?")


        if self.porcupine is None:
            logger.error("Porcupine not initialized in audio callback.")
            return

        try:
            # Porcupine expects a list or tuple of int16 samples
            # indata is likely float32 from sounddevice, need to scale and convert
            # Assuming input is mono, take the first channel if stereo
            if indata.shape[1] > 1:
                 mono_data = indata[:, 0]
            else:
                 mono_data = indata.flatten()

            # Convert float32 range [-1.0, 1.0] to int16 range [-32767, 32767]
            pcm = (mono_data * 32767.0).astype(np.int16).tolist()

            # Ensure frame length matches Porcupine's requirement
            if len(pcm) != self.frame_length:
                 logger.warning(f"Audio frame length mismatch. Expected {self.frame_length}, got {len(pcm)}. Skipping frame.")
                 # Padding/truncating might be an option but could affect detection
                 return


            # --- Wake Word Detection ---
            keyword_index = self.porcupine.process(pcm)
            if keyword_index >= 0:
                # Run wake word logic in the main thread context if possible,
                # or ensure state changes are thread-safe. Here, we call directly.
                self._wake_word_detected(keyword_index)

            # --- Queue Audio if Listening ---
            # Use is_state for thread-safe check
            if self.state_manager.is_state(State.LISTENING):
                try:
                    # Convert the original numpy array (int16 or float32 based on stream dtype) to bytes
                    # Use indata directly as configured by sd.InputStream dtype='int16'
                    audio_bytes = indata.tobytes()
                    self.audio_queue.put_nowait(audio_bytes)
                    # Reset listening timer on receiving audio while listening? Optional.
                    # self.listening_start_time = time.monotonic()
                except queue.Full:
                    logger.warning("Audio input queue is full. Dropping audio frame.")

            # --- Play Pending Audio Cue ---
            # WARNING: Playing audio directly in the input callback is generally discouraged.
            # It can block the callback, lead to audio glitches, or conflicts.
            # A better design sends cues to the AudioOutputHandler via a queue.
            # This is kept for functional similarity to the original code but should be refactored.
            if self._should_play_cue and self._current_cue is not None:
                 current_cue_data = self._current_cue # Copy ref before clearing
                 self._should_play_cue = False # Reset flag immediately
                 self._current_cue = None
                 try:
                     # Use default output device for cues for simplicity
                     logger.debug(f"Playing audio cue ({len(current_cue_data)} samples) in callback...")
                     sd.play(current_cue_data, self.sample_rate, device=None, blocking=False)
                     # Note: blocking=False helps, but contention can still occur.
                 except sd.PortAudioError as pae:
                     logger.error(f"PortAudioError playing audio cue in callback: {pae}")
                 except Exception as e:
                     logger.exception(f"Error playing audio cue in callback: {e}")


        except Exception as e:
            logger.exception(f"Error during audio callback processing: {e}")
            # Consider triggering error state via state_manager if errors persist
            # self._trigger_audio_cue("error") # Play error cue if possible
            # self.state_manager.set_state(State.ERROR, "Error in audio callback")

    def run(self) -> None:
        """Main thread execution loop."""
        if self.state_manager.is_state(State.ERROR) or self.porcupine is None:
            logger.error("AudioInputHandler cannot start due to initialization errors.")
            self._cleanup() # Ensure cleanup if init failed partially
            return

        logger.info("AudioInputHandler thread started.")
        try:
            # Create and start the audio stream
            logger.info(f"Attempting to start audio stream (Device: {self.selected_device_index}, "
                        f"SR: {self.sample_rate}Hz, Frame: {self.frame_length})...")
            self.audio_stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.frame_length, # Crucial: Match Porcupine's frame length
                device=self.selected_device_index, # None uses default
                channels=config.AUDIO_INPUT_CHANNELS,
                dtype=config.AUDIO_DTYPE, # e.g., 'int16'
                latency='low',
                callback=self._audio_callback
            )
            self.audio_stream.start()
            logger.info(f"Audio stream started successfully on device index: {self.audio_stream.device}.")
            self.state_manager.set_state(State.IDLE) # Ensure starting state is IDLE

            # Main loop: Keep thread alive and check for timeouts
            while not self.stop_event.is_set():
                self._check_listening_timeout()
                # Sleep prevents busy-waiting, responsiveness depends on sleep duration
                time.sleep(0.05) # Check timeouts fairly often

        except sd.PortAudioError as pae:
            error_msg = f"Failed to start audio stream: {pae}"
            logger.error(error_msg)
            logger.error("Check audio device availability and configuration.")
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
        except Exception as e:
            error_msg = f"An unexpected error occurred in Audio Input thread run loop: {e}"
            logger.exception(error_msg)
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
        finally:
            logger.info("AudioInputHandler thread stopping...")
            self._cleanup()
            logger.info("AudioInputHandler thread finished.")


    def _cleanup(self) -> None:
        """Clean up audio stream and Porcupine resources."""
        logger.info("Cleaning up AudioInputHandler resources...")

        # Stop and close audio stream
        if self.audio_stream is not None:
            try:
                if self.audio_stream.active: # Check if stream is active before stopping
                    self.audio_stream.stop()
                    logger.debug("Audio stream stopped.")
                self.audio_stream.close()
                logger.debug("Audio stream closed.")
            except sd.PortAudioError as pae:
                 logger.error(f"PortAudioError during audio stream cleanup: {pae}")
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
            finally:
                 self.audio_stream = None # Ensure stream object is cleared


        # Delete Porcupine instance
        if self.porcupine is not None:
            try:
                self.porcupine.delete()
                logger.info("Porcupine instance deleted.")
            except Exception as e:
                 logger.error(f"Error deleting Porcupine instance: {e}")
            finally:
                 self.porcupine = None # Ensure Porcupine object is cleared

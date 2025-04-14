# audio_input.py
"""
Handles audio input using sounddevice and wake word detection using Porcupine.
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

# Setup logger
logger = logging.getLogger(__name__)

class AudioInputHandler(threading.Thread):
    """
    Thread to capture audio from the microphone, detect wake word,
    and put audio chunks onto a queue when listening.
    """
    def __init__(self, audio_queue: queue.Queue, state_manager: StateManager, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.audio_queue = audio_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.porcupine = None
        self.audio_stream = None
        self._pa = None # PyAudio instance if needed by Porcupine's chosen backend
        self.listening_timeout = 10.0  # Timeout in seconds
        self.listening_start_time = 0.0
        self.is_timeout_check_enabled = True
        self.selected_device = None  # Will be set during initialization

        # Audio cue variables
        self.feedback_queue = queue.Queue()
        self.should_play_cue = False
        self.current_cue = None

        # Validate Porcupine paths
        if config.PORCUPINE_KEYWORD_PATHS is None or not config.PORCUPINE_KEYWORD_PATHS:
             raise ValueError("PORCUPINE_KEYWORD_PATHS must be configured.")
        if config.PICOVOICE_ACCESS_KEY is None:
            raise ValueError("PICOVOICE_ACCESS_KEY must be configured.")

        # Check audio devices and select optimal input device
        self._check_and_select_audio_device()

        try:
            # Initialize Porcupine
            self.porcupine = pvporcupine.create(
                access_key=config.PICOVOICE_ACCESS_KEY,
                keyword_paths=config.PORCUPINE_KEYWORD_PATHS,
                model_path=config.PORCUPINE_MODEL_PATH,
                sensitivities=config.PORCUPINE_SENSITIVITIES
            )
            logger.info(f"Porcupine initialized. Listening for: {self.porcupine.keyword_paths}")
            logger.info(f"Expected sample rate: {self.porcupine.sample_rate}, Frame length: {self.porcupine.frame_length}")

            # Ensure config sample rate matches Porcupine
            if config.AUDIO_SAMPLE_RATE != self.porcupine.sample_rate:
                logger.warning(f"Warning: Configured sample rate ({config.AUDIO_SAMPLE_RATE}) does not match Porcupine ({self.porcupine.sample_rate}). Using Porcupine's rate.")
                config.AUDIO_SAMPLE_RATE = self.porcupine.sample_rate

            # Generate audio cues
            self._generate_audio_cues()

        except pvporcupine.PorcupineError as e:
            logger.error(f"Error initializing Porcupine: {e}")
            self.state_manager.set_state(State.ERROR, error_message=f"Porcupine initialization failed: {e}")
            raise

    def _check_and_select_audio_device(self):
        """Check available audio devices and select the optimal input device."""
        # First, list available audio devices for logging purposes
        list_audio_devices()
        
        # Find optimal input device
        self.selected_device = find_optimal_device(
            mode='input',
            preferred_index=config.AUDIO_INPUT_DEVICE_INDEX,
            fallback_index=None  # Use system default as fallback
        )
        
        # Log the selected device
        if self.selected_device is None:
            logger.info("Using system default audio input device")
        else:
            try:
                device_info = sd.query_devices(self.selected_device)
                logger.info(f"Selected audio input device: [{self.selected_device}] {device_info['name']}")
            except Exception as e:
                logger.error(f"Error getting info for selected device {self.selected_device}: {e}")

    def _generate_audio_cues(self):
        """Generate audio cues for wake word detection and timeout."""
        # Wake word detected cue (ascending tones)
        self.wake_cue = self._generate_tone_sequence(
            frequencies=[440, 880, 1320],  # A4, A5, E6
            durations=[0.1, 0.1, 0.2],
            volume=0.3
        )
        
        # Timeout cue (descending tones)
        self.timeout_cue = self._generate_tone_sequence(
            frequencies=[880, 660, 440],  # A5, E5, A4
            durations=[0.1, 0.1, 0.2],
            volume=0.3
        )
        
        # Error cue (two quick low tones)
        self.error_cue = self._generate_tone_sequence(
            frequencies=[220, 220],  # A3, A3
            durations=[0.1, 0.1],
            volume=0.3
        )
        
        logger.info("Audio cues generated.")

    def _generate_tone_sequence(self, frequencies, durations, volume=0.3):
        """Generate a sequence of tones as an audio cue."""
        sample_rate = config.AUDIO_SAMPLE_RATE
        samples = []
        
        for freq, duration in zip(frequencies, durations):
            # Generate sine wave
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            tone = np.sin(2 * np.pi * freq * t) * volume
            
            # Apply simple envelope to avoid clicks
            fade_len = int(sample_rate * 0.01)  # 10ms fade
            fade_in = np.linspace(0, 1, fade_len)
            fade_out = np.linspace(1, 0, fade_len)
            
            if len(tone) > 2 * fade_len:
                tone[:fade_len] *= fade_in
                tone[-fade_len:] *= fade_out
                
            # Convert to int16
            tone = (tone * 32767).astype(np.int16)
            samples.append(tone)
            
        # Combine all tones
        return np.concatenate(samples)

    def _wake_word_callback(self, keyword_index):
        """Callback function when a wake word is detected."""
        logger.info(f"Wake word detected (Index: {keyword_index})!")
        if self.state_manager.is_state(State.IDLE):
            # Play wake sound cue - enqueue it for playback
            self.should_play_cue = True
            self.current_cue = self.wake_cue
            
            # Set state to LISTENING
            self.state_manager.set_state(State.LISTENING)
            
            # Start listening timeout
            self.listening_start_time = time.time()
            self.is_timeout_check_enabled = True
        else:
            logger.debug(f"Wake word detected but ignored - current state: {self.state_manager.get_state()}")

    def _check_listening_timeout(self):
        """Check if listening has timed out and reset to IDLE if needed."""
        if (self.is_timeout_check_enabled and 
            self.state_manager.is_state(State.LISTENING) and 
            time.time() - self.listening_start_time > self.listening_timeout):
            
            logger.info(f"Listening timeout after {self.listening_timeout} seconds. Returning to IDLE state.")
            
            # Play timeout sound cue
            self.should_play_cue = True
            self.current_cue = self.timeout_cue
            
            # Reset state
            self.state_manager.set_state(State.IDLE)
            
            # Pause timeout checks until next wake word
            self.is_timeout_check_enabled = False

    def run(self):
        """Main loop for the audio input thread."""
        if self.state_manager.is_state(State.ERROR):
            logger.error("AudioInputHandler cannot start due to initialization error.")
            return

        try:
            # Use sounddevice InputStream
            self.audio_stream = sd.InputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                blocksize=self.porcupine.frame_length, # Use Porcupine's frame length
                device=self.selected_device,
                channels=config.AUDIO_INPUT_CHANNELS,
                dtype=config.AUDIO_DTYPE,
                callback=self._audio_callback,
                latency='low' # Attempt low latency
            )
            self.audio_stream.start()
            logger.info(f"Audio stream started on device {self.audio_stream.device}...")

            # Keep the thread alive while the stop event is not set
            while not self.stop_event.is_set():
                # Check for listening timeout
                self._check_listening_timeout()
                
                # Sleep briefly to avoid busy loop
                time.sleep(0.1)

        except sd.PortAudioError as e:
            error_msg = f"Sounddevice/PortAudio Error in Audio Input: {e}"
            logger.error(error_msg)
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
        except Exception as e:
            error_msg = f"An unexpected error occurred in Audio Input thread: {e}"
            logger.exception(error_msg)
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
        finally:
            self._cleanup()

    def _audio_callback(self, indata, frames, time, status):
        """
        This callback is invoked by sounddevice when a new block of audio data is available.
        """
        if status:
            logger.warning(f"Audio input status: {status}")

        if self.porcupine:
            try:
                # Ensure data is in the correct format (list of int16)
                # sounddevice provides numpy array, Porcupine expects list/tuple
                pcm = indata[:, 0].astype(np.int16).tolist()

                # Process audio frame with Porcupine
                keyword_index = self.porcupine.process(pcm)
                if keyword_index >= 0:
                    # Wake word detected, trigger callback (which changes state)
                    self._wake_word_callback(keyword_index)

                # If in LISTENING state, put audio data onto the queue for STT
                if self.state_manager.is_state(State.LISTENING):
                    # Put raw bytes onto the queue for Vosk
                    self.audio_queue.put(indata.tobytes())
                
                # If we need to play an audio cue
                if self.should_play_cue and self.current_cue is not None:
                    # We'd normally send this to the audio output handler,
                    # but for simplicity, we'll directly create a sound here
                    # In a real implementation, this would go through the proper channels
                    try:
                        sd.play(self.current_cue, config.AUDIO_SAMPLE_RATE, blocking=False)
                        logger.debug("Playing audio cue")
                    except Exception as e:
                        logger.error(f"Error playing audio cue: {e}")
                    
                    # Reset cue state after attempting to play
                    self.should_play_cue = False
                    self.current_cue = None

            except Exception as e:
                logger.exception(f"Error during audio callback processing: {e}")
                # Consider setting ERROR state here if persistent

    def _cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up Audio Input Handler...")
        if self.audio_stream is not None:
            try:
                if not self.audio_stream.closed:
                    self.audio_stream.stop()
                    self.audio_stream.close()
                logger.info("Audio stream stopped and closed.")
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
        if self.porcupine is not None:
            self.porcupine.delete()
            logger.info("Porcupine instance deleted.")

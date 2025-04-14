# audio_input.py
"""
Handles audio input using sounddevice and wake word detection using Porcupine.
"""
import threading
import queue
import time
import struct
import sounddevice as sd
import pvporcupine
import numpy as np
import config
from state_manager import StateManager, State

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

        # Validate Porcupine paths
        if config.PORCUPINE_KEYWORD_PATHS is None or not config.PORCUPINE_KEYWORD_PATHS:
             raise ValueError("PORCUPINE_KEYWORD_PATHS must be configured.")
        if config.PICOVOICE_ACCESS_KEY is None:
            raise ValueError("PICOVOICE_ACCESS_KEY must be configured.")

        try:
            # Initialize Porcupine [8, 9, 10, 11, 12]
            self.porcupine = pvporcupine.create(
                access_key=config.PICOVOICE_ACCESS_KEY,
                keyword_paths=config.PORCUPINE_KEYWORD_PATHS,
                model_path=config.PORCUPINE_MODEL_PATH,
                sensitivities=config.PORCUPINE_SENSITIVITIES
            )
            print(f"Porcupine initialized. Listening for: {self.porcupine.keyword_paths}")
            print(f"Expected sample rate: {self.porcupine.sample_rate}, Frame length: {self.porcupine.frame_length}")

            # Ensure config sample rate matches Porcupine
            if config.AUDIO_SAMPLE_RATE!= self.porcupine.sample_rate:
                print(f"Warning: Configured sample rate ({config.AUDIO_SAMPLE_RATE}) does not match Porcupine ({self.porcupine.sample_rate}). Using Porcupine's rate.")
                config.AUDIO_SAMPLE_RATE = self.porcupine.sample_rate

        except pvporcupine.PorcupineError as e:
            print(f"Error initializing Porcupine: {e}")
            self.state_manager.set_state(State.ERROR)
            raise

    def _wake_word_callback(self, keyword_index):
        """Callback function when a wake word is detected."""
        print(f"Wake word detected (Index: {keyword_index})!")
        if self.state_manager.is_state(State.IDLE):
            self.state_manager.set_state(State.LISTENING)
            # Potentially add a sound cue here

    def run(self):
        """Main loop for the audio input thread."""
        if self.state_manager.is_state(State.ERROR):
            print("AudioInputHandler cannot start due to initialization error.")
            return

        try:
            # Use sounddevice InputStream [13, 14, 15, 16, 17, 18, 19]
            self.audio_stream = sd.InputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                blocksize=self.porcupine.frame_length, # Use Porcupine's frame length
                device=config.AUDIO_INPUT_DEVICE_INDEX,
                channels=config.AUDIO_INPUT_CHANNELS,
                dtype=config.AUDIO_DTYPE,
                callback=self._audio_callback,
                latency='low' # Attempt low latency [15, 17]
            )
            self.audio_stream.start()
            print(f"Audio stream started on device {self.audio_stream.device}...")

            # Keep the thread alive while the stop event is not set
            while not self.stop_event.is_set():
                time.sleep(0.1)

        except sd.PortAudioError as e:
            print(f"Sounddevice/PortAudio Error in Audio Input: {e}")
            self.state_manager.set_state(State.ERROR)
        except Exception as e:
            print(f"An unexpected error occurred in Audio Input thread: {e}")
            self.state_manager.set_state(State.ERROR)
        finally:
            self._cleanup()

    def _audio_callback(self, indata, frames, time, status):
        """
        This callback is invoked by sounddevice when a new block of audio data is available.
        """
        if status:
            print(f"Audio input status: {status}")

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

            except Exception as e:
                print(f"Error during audio callback processing: {e}")
                # Consider setting ERROR state here if persistent

    def _cleanup(self):
        """Clean up resources."""
        print("Cleaning up Audio Input Handler...")
        if self.audio_stream is not None:
            try:
                if not self.audio_stream.closed:
                    self.audio_stream.stop()
                    self.audio_stream.close()
                print("Audio stream stopped and closed.")
            except Exception as e:
                print(f"Error closing audio stream: {e}")
        if self.porcupine is not None:
            self.porcupine.delete()
            print("Porcupine instance deleted.")
        # sd._terminate() # Generally not needed unless debugging PortAudio issues

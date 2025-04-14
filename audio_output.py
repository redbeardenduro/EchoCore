# audio_output.py
"""
Handles playing synthesized audio data using sounddevice.
Calculates audio amplitude for avatar visualization.
"""
import threading
import queue
import time
import sounddevice as sd
import numpy as np
import logging
import config
from state_manager import StateManager, State
from audio_utils import find_optimal_device

# Setup logger
logger = logging.getLogger(__name__)

class AudioOutputHandler(threading.Thread):
    """
    Thread to play audio chunks from tts_queue using sounddevice.
    Sends amplitude data to avatar_queue.
    """
    def __init__(self, tts_queue: queue.Queue, avatar_queue: queue.Queue, state_manager: StateManager, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.tts_queue = tts_queue
        self.avatar_queue = avatar_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.output_stream = None
        self.selected_device = None  # Will be set during initialization
        
        # Check audio devices and select optimal output device
        self._check_and_select_audio_device()

    def _check_and_select_audio_device(self):
        """Check available audio devices and select the optimal output device."""
        # Find optimal output device
        self.selected_device = find_optimal_device(
            mode='output',
            preferred_index=config.AUDIO_OUTPUT_DEVICE_INDEX,
            fallback_index=None  # Use system default as fallback
        )
        
        # Log the selected device
        if self.selected_device is None:
            logger.info("Using system default audio output device")
        else:
            try:
                device_info = sd.query_devices(self.selected_device)
                logger.info(f"Selected audio output device: [{self.selected_device}] {device_info['name']}")
            except Exception as e:
                logger.error(f"Error getting info for selected device {self.selected_device}: {e}")

    def run(self):
        """Main loop for the audio output thread."""
        logger.info("Audio Output Handler waiting for audio...")
        try:
            # Setup output stream using the selected device
            self.output_stream = sd.OutputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                blocksize=config.AUDIO_CHUNK_SIZE,
                device=self.selected_device,
                channels=config.AUDIO_OUTPUT_CHANNELS,
                dtype=config.AUDIO_DTYPE,
                latency=config.AUDIO_OUTPUT_LATENCY
            )
            self.output_stream.start()
            logger.info(f"Audio output stream started on device {self.output_stream.device}...")

            while not self.stop_event.is_set():
                if self.state_manager.is_state(State.SPEAKING):
                    try:
                        audio_chunk = self.tts_queue.get(block=True, timeout=1.0)

                        if audio_chunk is None:
                            # End of speech signal received
                            logger.info("Audio Output: End of speech detected.")
                            self.state_manager.set_state(State.IDLE) # Transition back to IDLE
                            self.avatar_queue.put(0.0) # Send zero amplitude
                            continue

                        # Play the audio chunk
                        # Ensure chunk is numpy array of correct dtype for sounddevice
                        try:
                            # Assuming PCM int16 data from TTS
                            numpy_chunk = np.frombuffer(audio_chunk, dtype=np.int16)
                            if numpy_chunk.size > 0:
                                self.output_stream.write(numpy_chunk)

                                # Calculate amplitude for avatar
                                amplitude = np.sqrt(np.mean(numpy_chunk.astype(np.float32)**2))
                                
                                # Normalize amplitude using config parameter instead of hardcoded value
                                normalized_amplitude = min(amplitude / config.AUDIO_AMPLITUDE_SCALING_DIVISOR, 1.0)
                                self.avatar_queue.put(normalized_amplitude)
                            else:
                                self.avatar_queue.put(0.0) # Send zero if chunk empty

                        except ValueError as ve:
                             logger.error(f"Audio Output: Error processing chunk - {ve}. Chunk size: {len(audio_chunk)}")
                             self.avatar_queue.put(0.0) # Send zero amplitude on error
                        except sd.PortAudioError as pae:
                             logger.error(f"Audio Output: PortAudioError during write - {pae}")
                             # Attempt to recover or set error state
                             self.state_manager.set_state(State.ERROR, error_message=f"Audio output error: {pae}")
                             time.sleep(1) # Avoid busy loop on error

                    except queue.Empty:
                        # If SPEAKING but queue is empty, maybe TTS finished unexpectedly?
                        logger.debug("Audio Output: Queue empty while in SPEAKING state.")
                        # Timeout logic: if empty for too long, assume TTS ended/failed
                        # For now, just continue waiting, rely on None marker or state change
                        self.avatar_queue.put(0.0) # Send zero amplitude
                        pass
                    except Exception as e:
                        logger.exception(f"An unexpected error occurred in Audio Output Handler: {e}")
                        self.state_manager.set_state(State.ERROR, error_message=f"Audio output error: {e}")
                        self.avatar_queue.put(0.0) # Send zero amplitude
                        time.sleep(1)
                else:
                    # Not speaking, ensure amplitude is zero
                    self.avatar_queue.put(0.0)
                    time.sleep(0.1)

        except sd.PortAudioError as e:
            error_msg = f"Sounddevice/PortAudio Error in Audio Output: {e}"
            logger.error(error_msg)
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
        except Exception as e:
            error_msg = f"An unexpected error occurred initializing Audio Output: {e}"
            logger.exception(error_msg)
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
        finally:
            self._cleanup()

    def _cleanup(self):
        """Clean up audio output resources."""
        logger.info("Cleaning up Audio Output Handler...")
        if self.output_stream is not None:
            try:
                if not self.output_stream.closed:
                    self.output_stream.stop()
                    self.output_stream.close()
                logger.info("Audio output stream stopped and closed.")
            except Exception as e:
                logger.error(f"Error closing output stream: {e}")

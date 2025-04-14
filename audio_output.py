# audio_output.py
"""
Handles playing synthesized audio data using sounddevice and calculating
audio amplitude for avatar visualization.
"""

import threading
import queue
import time
import sounddevice as sd
import numpy as np
import logging
from typing import Optional, Any # For type hinting

# Import project modules
try:
    import config # Assuming config.py is in the same directory or Python path
    from state_manager import StateManager, State
    from audio_utils import find_optimal_device
except ImportError as e:
     logging.error(f"Error importing project modules in audio_output.py: {e}")
     raise

# Setup logger
logger = logging.getLogger(__name__)

class AudioOutputHandler(threading.Thread):
    """
    Thread to play audio chunks from tts_queue using sounddevice.

    Receives audio chunks (expected as bytes containing int16 PCM data)
    from the tts_queue, plays them through the selected audio output device,
    calculates the RMS amplitude of each chunk, normalizes it, and sends
    it to the avatar_queue. Stops playback and transitions state upon
    receiving a None marker in the tts_queue.
    """
    def __init__(
        self,
        tts_queue: queue.Queue[Optional[bytes]], # Expects bytes or None marker
        avatar_queue: queue.Queue[float],       # Sends float amplitude
        state_manager: StateManager,
        stop_event: threading.Event
    ):
        """
        Initializes the AudioOutputHandler.

        Args:
            tts_queue: Queue receiving audio chunks (bytes) or None from TTS.
            avatar_queue: Queue to send calculated normalized amplitude (float) to.
            state_manager: The application's state manager instance.
            stop_event: Threading event to signal when to stop processing.

        Raises:
            sd.PortAudioError: If audio device query or stream creation fails.
        """
        super().__init__(name="AudioOutputThread", daemon=True)
        self.tts_queue = tts_queue
        self.avatar_queue = avatar_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.output_stream: Optional[sd.OutputStream] = None

        # --- Configuration ---
        self.selected_device_index: Optional[int] = config.AUDIO_OUTPUT_DEVICE_INDEX
        self.sample_rate: int = config.AUDIO_SAMPLE_RATE
        self.chunk_size: int = config.AUDIO_CHUNK_SIZE # For stream blocksize
        self.channels: int = config.AUDIO_OUTPUT_CHANNELS
        self.dtype: str = config.AUDIO_DTYPE # e.g., 'int16'
        self.latency: Any = config.AUDIO_OUTPUT_LATENCY # Can be str or float
        self.amplitude_scaling_divisor: float = config.AUDIO_AMPLITUDE_SCALING_DIVISOR

        # --- Initialization ---
        self.selected_device_index = self._select_audio_device()
        # Stream initialization moved to run() to handle potential errors better

    def _select_audio_device(self) -> Optional[int]:
        """Select the audio output device using audio_utils."""
        logger.debug(f"Finding optimal output device (Preferred: {self.selected_device_index})")
        return find_optimal_device(mode='output', preferred_index=self.selected_device_index)

    def _calculate_normalized_amplitude(self, audio_chunk: np.ndarray) -> float:
        """Calculate normalized RMS amplitude for a numpy audio chunk."""
        if audio_chunk.size == 0:
            return 0.0
        try:
            # Ensure calculation uses float to avoid overflow/underflow
            # Use float64 for potentially better precision in RMS calculation
            rms_amplitude = np.sqrt(np.mean(audio_chunk.astype(np.float64)**2))

            # Normalize amplitude (clamp between 0.0 and 1.0)
            # Ensure divisor is not zero
            divisor = self.amplitude_scaling_divisor if self.amplitude_scaling_divisor > 0 else 1024.0
            normalized_amplitude = min(rms_amplitude / divisor, 1.0)
            return normalized_amplitude
        except Exception as e:
            # Catch potential numerical errors
            logger.error(f"Error calculating amplitude: {e}")
            return 0.0

    def _send_amplitude(self, amplitude: float) -> None:
        """Send amplitude data to the avatar queue, handling potential fullness."""
        try:
            # Use non-blocking put with a small timeout to avoid indefinite blocking
            # if the avatar queue becomes permanently full.
            self.avatar_queue.put(amplitude, block=True, timeout=0.1)
        except queue.Full:
            logger.warning("Avatar queue is full. Dropping amplitude update.")
        except Exception as e:
             logger.error(f"Error putting amplitude onto queue: {e}")


    def run(self) -> None:
        """Main thread execution loop."""
        logger.info("AudioOutputHandler thread started.")
        try:
            # --- Initialize Audio Stream ---
            logger.info(f"Attempting to start audio output stream (Device: {self.selected_device_index}, "
                        f"SR: {self.sample_rate}Hz, Blocksize: {self.chunk_size})...")
            self.output_stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                device=self.selected_device_index, # None uses default
                channels=self.channels,
                dtype=self.dtype,
                latency=self.latency
            )
            self.output_stream.start()
            logger.info(f"Audio output stream started successfully on device index: {self.output_stream.device}.")

            # --- Main Processing Loop ---
            while not self.stop_event.is_set():
                # Check state before attempting to get from queue
                if self.state_manager.is_state(State.SPEAKING):
                    try:
                        # Wait for audio data from the TTS queue
                        audio_chunk_bytes = self.tts_queue.get(block=True, timeout=0.5) # Timeout helps check stop_event

                        if audio_chunk_bytes is None:
                            # End of speech signal received from TTS
                            logger.info("Audio Output: End of speech marker received.")
                            # Ensure any buffered audio is played before stopping
                            # Note: output_stream.stop() might not be sufficient if latency is high.
                            # A more robust solution might involve waiting for buffer completion.
                            self.state_manager.set_state(State.IDLE) # Transition state first
                            self._send_amplitude(0.0) # Signal silence to avatar
                            logger.debug("Transitioning to IDLE state.")
                            # Optional: Wait briefly for buffer to clear? sd.wait() might block too long.
                            # time.sleep(self.latency if isinstance(self.latency, float) else 0.1)
                            continue # Continue loop to check stop_event or new state

                        # Process the valid audio chunk
                        try:
                            # Convert bytes to numpy array based on configured dtype
                            numpy_chunk = np.frombuffer(audio_chunk_bytes, dtype=self.dtype)

                            if numpy_chunk.size > 0:
                                # Write audio data to the output stream
                                self.output_stream.write(numpy_chunk)

                                # Calculate and send amplitude
                                amplitude = self._calculate_normalized_amplitude(numpy_chunk)
                                self._send_amplitude(amplitude)
                            else:
                                # Handle empty chunk case
                                self._send_amplitude(0.0)

                        except ValueError as ve:
                            logger.error(f"Audio Output: Error converting audio chunk bytes - {ve}. Chunk size: {len(audio_chunk_bytes)}")
                            self._send_amplitude(0.0)
                        except sd.PortAudioError as pae:
                            logger.error(f"Audio Output: PortAudioError during write: {pae}")
                            # Attempt to recover or set error state
                            self.state_manager.set_state(State.ERROR, error_message=f"Audio output error: {pae}")
                            self._send_amplitude(0.0)
                            time.sleep(0.5) # Avoid busy loop on PortAudio error

                    except queue.Empty:
                        # Queue was empty within the timeout.
                        # If still in SPEAKING state, it might mean TTS is slow or finished unexpectedly.
                        # We rely on the None marker or state change to exit SPEAKING.
                        logger.debug("Audio Output: TTS queue empty while SPEAKING.")
                        # Send zero amplitude to indicate potential silence/gap
                        self._send_amplitude(0.0)
                        continue # Continue loop to check state/stop_event
                    except Exception as e:
                        logger.exception(f"An unexpected error occurred processing TTS queue: {e}")
                        self.state_manager.set_state(State.ERROR, error_message=f"Audio output processing error: {e}")
                        self._send_amplitude(0.0)
                        time.sleep(0.5)
                else:
                    # Not in SPEAKING state, ensure amplitude is zero and wait
                    self._send_amplitude(0.0)
                    # Wait for state change or stop signal
                    # Use a timeout to remain responsive to stop_event
                    time.sleep(0.1) # Relatively short sleep when idle

        except sd.PortAudioError as pae:
            error_msg = f"Failed to initialize or start audio output stream: {pae}"
            logger.error(error_msg)
            logger.error("Check audio device availability and configuration.")
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
        except Exception as e:
            error_msg = f"An unexpected error occurred in Audio Output thread run loop: {e}"
            logger.exception(error_msg)
            self.state_manager.set_state(State.ERROR, error_message=error_msg)
        finally:
            logger.info("AudioOutputHandler thread stopping...")
            self._cleanup()
            logger.info("AudioOutputHandler thread finished.")

    def _cleanup(self) -> None:
        """Clean up audio output stream resources."""
        logger.info("Cleaning up AudioOutputHandler resources...")
        if self.output_stream is not None:
            try:
                 # Check if stream was successfully opened and not already closed
                if not self.output_stream.closed:
                    # Abort can help stop playback immediately and clear buffers
                    self.output_stream.abort(ignore_errors=True)
                    logger.debug("Audio output stream aborted.")
                    self.output_stream.close()
                    logger.debug("Audio output stream closed.")
                else:
                     logger.debug("Audio output stream already closed.")

            except sd.PortAudioError as pae:
                 logger.error(f"PortAudioError during audio stream cleanup: {pae}")
            except Exception as e:
                logger.error(f"Error during audio stream cleanup: {e}")
            finally:
                 self.output_stream = None # Ensure stream object is cleared

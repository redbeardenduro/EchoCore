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
import config
from state_manager import StateManager, State

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

    def run(self):
        """Main loop for the audio output thread."""
        print("Audio Output Handler waiting for audio...")
        try:
            # Setup output stream [13, 14, 15, 16, 17, 19]
            self.output_stream = sd.OutputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                blocksize=config.AUDIO_CHUNK_SIZE, # Can be adjusted
                device=config.AUDIO_OUTPUT_DEVICE_INDEX,
                channels=config.AUDIO_OUTPUT_CHANNELS,
                dtype=config.AUDIO_DTYPE,
                latency=config.AUDIO_OUTPUT_LATENCY
            )
            self.output_stream.start()
            print(f"Audio output stream started on device {self.output_stream.device}...")

            while not self.stop_event.is_set():
                if self.state_manager.is_state(State.SPEAKING):
                    try:
                        audio_chunk = self.tts_queue.get(block=True, timeout=1.0)

                        if audio_chunk is None:
                            # End of speech signal received
                            print("Audio Output: End of speech detected.")
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

                                # Calculate amplitude for avatar [14, 34, 18]
                                amplitude = np.sqrt(np.mean(numpy_chunk.astype(np.float32)**2))
                                # Normalize amplitude (simple approach, needs tuning)
                                normalized_amplitude = min(amplitude / (2**10), 1.0) # Adjust divisor based on testing
                                self.avatar_queue.put(normalized_amplitude)
                            else:
                                self.avatar_queue.put(0.0) # Send zero if chunk empty

                        except ValueError as ve:
                             print(f"Audio Output: Error processing chunk - {ve}. Chunk size: {len(audio_chunk)}")
                             self.avatar_queue.put(0.0) # Send zero amplitude on error
                        except sd.PortAudioError as pae:
                             print(f"Audio Output: PortAudioError during write - {pae}")
                             # Attempt to recover or set error state
                             self.state_manager.set_state(State.ERROR)
                             time.sleep(1) # Avoid busy loop on error

                    except queue.Empty:
                        # If SPEAKING but queue is empty, maybe TTS finished unexpectedly?
                        print("Audio Output: Queue empty while in SPEAKING state.")
                        # Timeout logic: if empty for too long, assume TTS ended/failed
                        # For now, just continue waiting, rely on None marker or state change
                        self.avatar_queue.put(0.0) # Send zero amplitude
                        pass
                    except Exception as e:
                        print(f"An unexpected error occurred in Audio Output Handler: {e}")
                        self.state_manager.set_state(State.ERROR)
                        self.avatar_queue.put(0.0) # Send zero amplitude
                        time.sleep(1)
                else:
                    # Not speaking, ensure amplitude is zero
                    self.avatar_queue.put(0.0)
                    time.sleep(0.1)

        except sd.PortAudioError as e:
            print(f"Sounddevice/PortAudio Error in Audio Output: {e}")
            self.state_manager.set_state(State.ERROR)
        except Exception as e:
            print(f"An unexpected error occurred initializing Audio Output: {e}")
            self.state_manager.set_state(State.ERROR)
        finally:
            self._cleanup()

    def _cleanup(self):
        """Clean up audio output resources."""
        print("Cleaning up Audio Output Handler...")
        if self.output_stream is not None:
            try:
                if not self.output_stream.closed:
                    self.output_stream.stop()
                    self.output_stream.close()
                print("Audio output stream stopped and closed.")
            except Exception as e:
                print(f"Error closing output stream: {e}")
        # sd._terminate() # Generally not needed

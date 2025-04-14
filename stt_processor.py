# stt_processor.py
"""
Processes audio chunks using the Vosk STT engine.
"""
import threading
import queue
import json
import time
from vosk import Model, KaldiRecognizer, SetLogLevel
import config
from state_manager import StateManager, State

class STTProcessor(threading.Thread):
    """
    Thread to perform Speech-to-Text using Vosk.
    Takes audio chunks from a queue and puts transcriptions onto another queue.
    """
    def __init__(self, audio_queue: queue.Queue, stt_queue: queue.Queue, state_manager: StateManager, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.audio_queue = audio_queue
        self.stt_queue = stt_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.recognizer = None
        self.is_listening = False # Internal flag to track active listening phase

        try:
            # Initialize Vosk Model and Recognizer [20, 21, 22, 23, 24, 25, 26]
            SetLogLevel(config.VOSK_LOG_LEVEL)
            model = Model(config.VOSK_MODEL_PATH)
            self.recognizer = KaldiRecognizer(model, config.AUDIO_SAMPLE_RATE)
            self.recognizer.SetWords(True) # Enable word timestamps if needed later
            print("Vosk STT Processor initialized.")
        except Exception as e:
            print(f"Error initializing Vosk: {e}")
            self.state_manager.set_state(State.ERROR)
            raise

    def run(self):
        """Main loop for the STT processing thread."""
        if self.state_manager.is_state(State.ERROR):
            print("STTProcessor cannot start due to initialization error.")
            return

        print("STT Processor waiting for audio...")
        while not self.stop_event.is_set():
            current_state = self.state_manager.get_state()

            if current_state == State.LISTENING:
                if not self.is_listening:
                    print("STT Processor: Started listening phase.")
                    self.is_listening = True
                try:
                    # Get audio data from the queue (non-blocking)
                    audio_data = self.audio_queue.get(block=True, timeout=0.1)

                    # Feed audio data to Vosk recognizer
                    if self.recognizer.AcceptWaveform(audio_data):
                        # Full result obtained (likely end of utterance)
                        result_json = self.recognizer.Result()
                        result_dict = json.loads(result_json)
                        final_text = result_dict.get('text', '')
                        if final_text:
                            print(f"STT Final Result: {final_text}")
                            self.stt_queue.put(final_text)
                            self.state_manager.set_state(State.THINKING) # Transition state
                    else:
                        # Partial result (optional processing)
                        partial_result_json = self.recognizer.PartialResult()
                        partial_dict = json.loads(partial_result_json)
                        partial_text = partial_dict.get('partial', '')
                        if partial_text:
                             print(f"STT Partial: {partial_text}", end='\r') # Overwrite line

                except queue.Empty:
                    # No audio data currently available, continue loop
                    # Check if we should stop listening (e.g., timeout or explicit stop signal)
                    # Basic timeout implementation: If LISTENING but no data for a while, assume end of speech
                    # More robust silence detection would be better here.
                    # For now, rely on AcceptWaveform returning True or state change.
                    pass
                except Exception as e:
                    print(f"Error during STT processing: {e}")
                    self.state_manager.set_state(State.ERROR)
                    time.sleep(1) # Avoid busy-looping on error

            elif self.is_listening and current_state!= State.LISTENING:
                # State changed away from LISTENING, finalize any pending recognition
                print("\nSTT Processor: Ended listening phase.")
                self.is_listening = False
                final_result_json = self.recognizer.FinalResult()
                final_dict = json.loads(final_result_json)
                final_text = final_dict.get('text', '')
                if final_text:
                    print(f"STT Final Result (on state change): {final_text}")
                    self.stt_queue.put(final_text)
                    # Ensure state moves forward if not already THINKING or beyond
                    if self.state_manager.is_state(State.IDLE) or self.state_manager.is_state(State.LISTENING):
                         self.state_manager.set_state(State.THINKING)
                self.recognizer.Reset() # Reset recognizer for next time

            else:
                # Not listening, sleep briefly
                time.sleep(0.1)

        print("STT Processor stopping.")

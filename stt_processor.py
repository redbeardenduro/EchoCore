# stt_processor.py
"""
Processes audio chunks using the Vosk Speech-to-Text engine.
Receives audio data, performs transcription, applies confidence filtering,
and manages silence timeouts.
"""

import threading
import queue
import json
import time
import logging
import os
from typing import Optional, Dict, Any # For type hinting

# Attempt to import Vosk
try:
    from vosk import Model, KaldiRecognizer, SetLogLevel
except ImportError:
    logging.critical("Vosk library not found. Please install it: pip install vosk")
    # Re-raise or exit if Vosk is essential for the application to even load
    raise

# Import project modules
try:
    import config
    from state_manager import StateManager, State
except ImportError as e:
    logging.error(f"Error importing project modules in stt_processor.py: {e}")
    raise

# Setup logger
logger = logging.getLogger(__name__)

class STTProcessor(threading.Thread):
    """
    Thread to perform Speech-to-Text (STT) using the Vosk engine.

    Takes audio chunks (bytes) from an input queue, performs transcription,
    filters results based on confidence, handles silence timeouts, and puts
    accepted transcriptions (str) onto an output queue. Uses lazy loading
    for the Vosk model to reduce initial startup time.
    """
    def __init__(
        self,
        audio_queue: queue.Queue[bytes], # Expects raw audio bytes
        stt_queue: queue.Queue[str],     # Outputs transcribed strings
        state_manager: StateManager,
        stop_event: threading.Event
    ):
        """
        Initializes the STTProcessor.

        Args:
            audio_queue: Queue receiving raw audio chunks (bytes).
            stt_queue: Queue to put successful transcriptions (str) onto.
            state_manager: The application's state manager instance.
            stop_event: Threading event to signal when to stop processing.
        """
        super().__init__(name="STTProcessorThread", daemon=True)
        self.audio_queue = audio_queue
        self.stt_queue = stt_queue
        self.state_manager = state_manager
        self.stop_event = stop_event

        # --- Vosk specific ---
        self.model: Optional[Model] = None
        self.recognizer: Optional[KaldiRecognizer] = None
        self.model_path: str = config.VOSK_MODEL_PATH
        self.sample_rate: int = config.AUDIO_SAMPLE_RATE
        self.vosk_log_level: int = config.VOSK_LOG_LEVEL

        # --- State & Timing ---
        self._is_actively_listening: bool = False # Internal flag for active processing phase
        self.no_speech_timeout: float = config.LISTENING_TIMEOUT # Use config value
        self.last_speech_time: float = 0.0 # Time of last partial/full result
        self.silence_duration: float = 0.0 # Current accumulated silence

        # --- Confidence ---
        self.confidence_threshold: float = config.STT_CONFIDENCE_THRESHOLD

        # --- Initialization Control ---
        self._model_initialized: bool = False
        self._initialization_attempts: int = 0
        self._max_initialization_attempts: int = 3 # Max retries for loading model

    def _initialize_vosk(self) -> bool:
        """
        Initializes the Vosk model and recognizer (lazy loading).

        Attempts to load the model from the configured path. Retries on failure
        up to a maximum limit before setting the ERROR state.

        Returns:
            True if initialization was successful, False otherwise.
        """
        if self._model_initialized:
            return True

        self._initialization_attempts += 1
        logger.info(f"Attempting to initialize Vosk model (Attempt {self._initialization_attempts}/{self._max_initialization_attempts})...")

        try:
            # 1. Check if model path exists
            if not os.path.exists(self.model_path):
                logger.error(f"Vosk model path does not exist: {self.model_path}")
                # Set error state immediately if path is missing
                self.state_manager.set_state(State.ERROR, f"Vosk model path missing: {self.model_path}")
                return False

            # 2. Set Vosk log level (suppresses internal logs)
            SetLogLevel(self.vosk_log_level)

            # 3. Load the model
            logger.info(f"Loading Vosk model from: {self.model_path}")
            self.model = Model(self.model_path)

            # 4. Create the recognizer instance
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True) # Enable word timestamps and confidence
            # self.recognizer.SetPartialWords(True) # Optional: Get word details in partial results

            logger.info(f"Vosk model loaded and recognizer created successfully.")
            self._model_initialized = True
            self._initialization_attempts = 0 # Reset attempts on success
            return True

        except Exception as e:
            logger.exception(f"Error initializing Vosk (Attempt {self._initialization_attempts}): {e}")
            if self._initialization_attempts >= self._max_initialization_attempts:
                logger.error("Maximum Vosk initialization attempts reached. Setting ERROR state.")
                self.state_manager.set_state(State.ERROR, f"Vosk init failed after {self._max_initialization_attempts} attempts: {e}")
            return False

    def _reset_recognizer(self) -> None:
        """Resets the recognizer state, typically after an utterance or error."""
        if self.recognizer:
            try:
                self.recognizer.Reset()
                logger.debug("Vosk recognizer reset.")
            except Exception as e:
                 logger.error(f"Error resetting Vosk recognizer: {e}")
        self._is_actively_listening = False # Ensure listening flag is reset


    def _process_final_result(self, result_json: str) -> None:
        """Processes a final Vosk result string."""
        try:
            result_dict: Dict[str, Any] = json.loads(result_json)
            final_text: str = result_dict.get('text', '').strip()

            if final_text:
                confidence = self._calculate_confidence(result_dict)
                logger.info(f"STT Final Result: '{final_text}' (Confidence: {confidence:.2f})")

                if confidence >= self.confidence_threshold:
                    logger.info("Result confidence above threshold, queuing transcription.")
                    try:
                         self.stt_queue.put_nowait(final_text)
                         # Signal that STT is done, ready for LLM
                         # Important: Only transition state if we are currently processing
                         if self.state_manager.is_state((State.LISTENING, State.PROCESSING_STT)):
                             self.state_manager.set_state(State.THINKING)
                    except queue.Full:
                         logger.error("STT output queue is full. Transcription lost!")
                         # If queue is full, likely a downstream issue, maybe revert state?
                         if self.state_manager.is_state((State.LISTENING, State.PROCESSING_STT)):
                             self.state_manager.set_state(State.IDLE) # Revert if cannot proceed
                else:
                    logger.warning(f"Rejected low confidence result ({confidence:.2f} < {self.confidence_threshold}).")
                    # If confidence is low, stay listening but maybe reset silence timer?
                    # Or transition back to IDLE? Let's reset timer and stay LISTENING for now.
                    self.last_speech_time = time.monotonic()
                    if self.state_manager.is_state((State.LISTENING, State.PROCESSING_STT)):
                        self.state_manager.set_state(State.LISTENING) # Ensure we are listening

            else:
                # Empty final result, might happen on timeout or very short utterance
                logger.info("STT Final Result was empty.")
                # If we were processing, go back to IDLE
                if self.state_manager.is_state((State.LISTENING, State.PROCESSING_STT)):
                     self.state_manager.set_state(State.IDLE)

        except json.JSONDecodeError:
            logger.error(f"Failed to decode Vosk final result JSON: {result_json}")
            if self.state_manager.is_state((State.LISTENING, State.PROCESSING_STT)):
                self.state_manager.set_state(State.IDLE) # Revert on decode error
        except Exception as e:
            logger.exception(f"Error processing final result: {e}")
            if self.state_manager.is_state((State.LISTENING, State.PROCESSING_STT)):
                self.state_manager.set_state(State.IDLE) # Revert on unexpected error


    def _finalize_speech(self, reason: str = "state change") -> None:
        """
        Finalizes speech recognition when listening stops (due to state change,
        timeout, or other reasons). Processes any remaining buffered audio.
        """
        if not self._is_actively_listening or not self.recognizer:
            return # Nothing to finalize if not actively listening or no recognizer

        logger.info(f"Finalizing STT recognition (Reason: {reason})...")
        try:
            final_result_json = self.recognizer.FinalResult()
            logger.debug(f"Vosk FinalResult() output: {final_result_json}")
            self._process_final_result(final_result_json)
        except Exception as e:
            logger.exception(f"Error getting FinalResult from Vosk: {e}")
            # Ensure state moves back to IDLE even if FinalResult fails
            if self.state_manager.is_state((State.LISTENING, State.PROCESSING_STT)):
                self.state_manager.set_state(State.IDLE)
        finally:
             # Always reset the recognizer and listening flag after finalization
            self._reset_recognizer()


    def _calculate_confidence(self, result_dict: Dict[str, Any]) -> float:
        """
        Calculate an overall confidence score from a Vosk result dictionary.

        Averages word confidences if available.

        Args:
            result_dict: The dictionary parsed from Vosk's JSON result.

        Returns:
            The calculated confidence score (0.0 to 1.0). Returns 0.0 if
            confidence cannot be determined.
        """
        # Vosk result structure can vary, check for common patterns
        word_confidences = []
        if 'result' in result_dict and isinstance(result_dict['result'], list):
            # Structure usually includes word timings and conf
            word_confidences = [word.get('conf', 0.0) for word in result_dict['result'] if isinstance(word, dict)]
        elif 'conf' in result_dict:
             # Sometimes top-level confidence might be present (less common)
             return float(result_dict['conf'])

        if word_confidences:
            # Average confidence across all words with a confidence score
            valid_confidences = [c for c in word_confidences if isinstance(c, (int, float))]
            if valid_confidences:
                average_conf = sum(valid_confidences) / len(valid_confidences)
                return float(average_conf) # Ensure float
            else:
                 logger.warning("Found 'result' list but no valid 'conf' values.")
                 return 0.0 # Indicate failure to calculate confidence
        else:
             # If no word-level confidence found, we cannot reliably determine confidence
             logger.debug("No word-level confidence ('result' with 'conf') found in Vosk result.")
             return 0.0 # Fallback: Indicate low/unknown confidence


    def run(self) -> None:
        """Main loop for the STT processing thread."""
        logger.info("STTProcessor thread started.")

        while not self.stop_event.is_set():
            current_state = self.state_manager.get_state()

            # --- Handle LISTENING State ---
            if current_state == State.LISTENING:
                # Initialize Vosk model if not already done (lazy loading)
                if not self._model_initialized and not self._initialize_vosk():
                    # Initialization failed, wait before retrying or stopping
                    logger.warning("Vosk not initialized, waiting...")
                    time.sleep(1.0)
                    continue # Skip to next loop iteration

                # If initialization is successful, ensure recognizer exists
                if self.recognizer is None:
                     logger.error("Vosk model initialized but recognizer is None. This should not happen.")
                     self.state_manager.set_state(State.ERROR, "STT Recognizer failed post-init")
                     time.sleep(1.0)
                     continue


                # Mark start of active listening phase
                if not self._is_actively_listening:
                    logger.info("STT Processor entering active listening phase.")
                    self._is_actively_listening = True
                    self.last_speech_time = time.monotonic() # Reset silence timer
                    self.silence_duration = 0.0
                    # Transition to PROCESSING_STT state to indicate active work
                    self.state_manager.set_state(State.PROCESSING_STT)
                    # Re-fetch state in case it changed during transition
                    current_state = self.state_manager.get_state()


                # --- Process Audio from Queue ---
                if current_state == State.PROCESSING_STT: # Check state again after potential transition
                    try:
                        # Get audio data with a timeout to remain responsive
                        audio_data = self.audio_queue.get(block=True, timeout=0.1)

                        # Feed audio data to Vosk recognizer
                        # AcceptWaveform returns True if an utterance endpoint is detected
                        if self.recognizer.AcceptWaveform(audio_data):
                            final_result_json = self.recognizer.Result()
                            logger.debug(f"Vosk Result() output (endpoint detected): {final_result_json}")
                            self._process_final_result(final_result_json)
                            # Recognizer is implicitly reset after Result(), but explicit reset might be safer
                            self._reset_recognizer() # Reset for next utterance
                        else:
                            # Process partial result
                            partial_result_json = self.recognizer.PartialResult()
                            try:
                                partial_dict = json.loads(partial_result_json)
                                partial_text = partial_dict.get('partial', '').strip()
                                if partial_text:
                                    # Detected speech, reset silence timer
                                    self.last_speech_time = time.monotonic()
                                    if len(partial_text) > 2: # Log only non-trivial partials
                                        logger.debug(f"STT Partial: '{partial_text}'")
                                else:
                                     # No partial text, check silence timeout
                                     self.silence_duration = time.monotonic() - self.last_speech_time
                                     if self.silence_duration > self.no_speech_timeout:
                                         logger.info(f"Silence timeout ({self.silence_duration:.1f}s > {self.no_speech_timeout:.1f}s). Finalizing speech.")
                                         self._finalize_speech(reason="silence timeout")

                            except json.JSONDecodeError:
                                 logger.warning(f"Failed to decode Vosk partial result JSON: {partial_result_json}")


                    except queue.Empty:
                        # No audio data, check for silence timeout if actively listening
                        if self._is_actively_listening:
                             self.silence_duration = time.monotonic() - self.last_speech_time
                             if self.silence_duration > self.no_speech_timeout:
                                 logger.info(f"Silence timeout ({self.silence_duration:.1f}s > {self.no_speech_timeout:.1f}s) during queue wait. Finalizing speech.")
                                 self._finalize_speech(reason="silence timeout")
                        continue # Continue loop

                    except Exception as e:
                        logger.exception(f"Error during STT audio processing loop: {e}")
                        self._reset_recognizer() # Reset recognizer on error
                        self.state_manager.set_state(State.IDLE) # Go back to IDLE on unexpected error
                        time.sleep(0.5) # Pause briefly after error

            # --- Handle State Change Away From Listening ---
            elif self._is_actively_listening and current_state not in (State.LISTENING, State.PROCESSING_STT):
                # If we were actively listening but state changed externally, finalize any pending speech
                logger.info(f"State changed externally from LISTENING/PROCESSING_STT to {current_state.name}. Finalizing STT.")
                self._finalize_speech(reason="external state change")

            # --- Idle State ---
            else:
                # Not listening, ensure flag is clear and sleep
                if self._is_actively_listening:
                     self._is_actively_listening = False # Ensure flag consistency
                time.sleep(0.1) # Sleep briefly when not actively processing

        logger.info("STTProcessor thread stopping.")
        # No explicit cleanup needed for Vosk model/recognizer objects AFAIK

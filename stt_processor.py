# stt_processor.py
"""
Processes audio chunks using the Vosk STT engine.
"""
import threading
import queue
import json
import time
import logging
import os
from vosk import Model, KaldiRecognizer, SetLogLevel
import config
from state_manager import StateManager, State

# Setup logger
logger = logging.getLogger(__name__)

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
        self.is_listening = False  # Internal flag to track active listening phase
        self.no_speech_timeout = config.LISTENING_TIMEOUT  # Seconds of silence before timing out
        self.last_speech_time = 0  # Time when last partial result was detected
        self.silence_duration = 0  # Duration of current silence

        # Lazy loading flag - only initialize model when needed
        self.model_initialized = False
        self.initialization_attempts = 0
        self.max_initialization_attempts = 3

    def _initialize_model(self):
        """Initialize Vosk model - lazy loading to reduce startup time."""
        if self.model_initialized:
            return True
            
        try:
            # Check if model path exists
            if not os.path.exists(config.VOSK_MODEL_PATH):
                logger.error(f"Vosk model path does not exist: {config.VOSK_MODEL_PATH}")
                self.state_manager.set_state(State.ERROR)
                return False
                
            # Initialize Vosk Model and Recognizer
            logger.info(f"Loading Vosk model from {config.VOSK_MODEL_PATH}...")
            SetLogLevel(config.VOSK_LOG_LEVEL)
            model = Model(config.VOSK_MODEL_PATH)
            self.recognizer = KaldiRecognizer(model, config.AUDIO_SAMPLE_RATE)
            self.recognizer.SetWords(True)  # Enable word timestamps if needed later
            logger.info("Vosk STT Processor initialized.")
            self.model_initialized = True
            return True
            
        except Exception as e:
            logger.exception(f"Error initializing Vosk (attempt {self.initialization_attempts + 1}): {e}")
            self.initialization_attempts += 1
            if self.initialization_attempts >= self.max_initialization_attempts:
                logger.error("Maximum initialization attempts reached. Setting ERROR state.")
                self.state_manager.set_state(State.ERROR)
            return False

    def run(self):
        """Main loop for the STT processing thread."""
        logger.info("STT Processor starting...")
        
        while not self.stop_event.is_set():
            current_state = self.state_manager.get_state()

            if current_state == State.LISTENING:
                # Initialize model if not already done
                if not self.model_initialized and not self._initialize_model():
                    time.sleep(1)  # Wait before trying again
                    continue
                
                if not self.is_listening:
                    logger.info("STT Processor: Started listening phase.")
                    self.is_listening = True
                    self.last_speech_time = time.time()
                    self.silence_duration = 0
                    # Set state to actively processing
                    self.state_manager.set_state(State.PROCESSING_STT)
                    
                try:
                    # Get audio data from the queue (non-blocking)
                    try:
                        audio_data = self.audio_queue.get(block=True, timeout=0.1)
                    except queue.Empty:
                        # Check for silence timeout
                        current_time = time.time()
                        self.silence_duration = current_time - self.last_speech_time
                        
                        if self.silence_duration > self.no_speech_timeout:
                            logger.info(f"Speech timeout after {self.silence_duration:.1f} seconds of silence.")
                            # If we've been silent for too long, finalize and go back to IDLE
                            self._finalize_speech()
                            self.state_manager.set_state(State.IDLE)
                        continue

                    # Feed audio data to Vosk recognizer
                    if self.recognizer.AcceptWaveform(audio_data):
                        # Full result obtained (likely end of utterance)
                        result_json = self.recognizer.Result()
                        result_dict = json.loads(result_json)
                        final_text = result_dict.get('text', '')
                        
                        if final_text:
                            confidence = self._calculate_confidence(result_dict)
                            logger.info(f"STT Final Result: '{final_text}' (confidence: {confidence:.2f})")
                            
                            if confidence >= config.STT_CONFIDENCE_THRESHOLD:
                                self.stt_queue.put(final_text)
                                self.state_manager.set_state(State.THINKING)  # Transition state
                            else:
                                logger.warning(f"Rejected low confidence result: {confidence:.2f} < {config.STT_CONFIDENCE_THRESHOLD}")
                                # Stay in listening mode but reset timer
                                self.last_speech_time = time.time()
                        else:
                            # Empty final result, just update timer
                            self.last_speech_time = time.time()
                    else:
                        # Partial result
                        partial_result_json = self.recognizer.PartialResult()
                        partial_dict = json.loads(partial_result_json)
                        partial_text = partial_dict.get('partial', '')
                        
                        if partial_text:
                            # Update last speech time when we get partial results
                            self.last_speech_time = time.time()
                            if len(partial_text) > 3:  # Only log substantial partials
                                logger.debug(f"STT Partial: {partial_text}")

                except Exception as e:
                    logger.exception(f"Error during STT processing: {e}")
                    # Try to recover by resetting the recognizer
                    try:
                        if self.recognizer:
                            self.recognizer.Reset()
                    except:
                        pass
                    self.is_listening = False
                    time.sleep(1)  # Avoid busy-looping on error

            elif self.is_listening and current_state != State.PROCESSING_STT and current_state != State.LISTENING:
                # State changed away from LISTENING, finalize any pending recognition
                self._finalize_speech()
            else:
                # Not listening, sleep briefly
                time.sleep(0.1)

        logger.info("STT Processor stopping.")

    def _finalize_speech(self):
        """Finalize speech recognition and process any pending results."""
        if not self.is_listening or not self.recognizer:
            return
            
        logger.info("STT Processor: Ended listening phase.")
        self.is_listening = False
        
        # Get final result
        final_result_json = self.recognizer.FinalResult()
        final_dict = json.loads(final_result_json)
        final_text = final_dict.get('text', '')
        
        if final_text:
            confidence = self._calculate_confidence(final_dict)
            logger.info(f"STT Final Result (on state change): '{final_text}' (confidence: {confidence:.2f})")
            
            if confidence >= config.STT_CONFIDENCE_THRESHOLD:
                self.stt_queue.put(final_text)
                # Ensure state moves forward if not already THINKING or beyond
                if self.state_manager.is_state(State.IDLE) or self.state_manager.is_state(State.LISTENING) or self.state_manager.is_state(State.PROCESSING_STT):
                    self.state_manager.set_state(State.THINKING)
            else:
                logger.warning(f"Rejected low confidence final result: {confidence:.2f} < {config.STT_CONFIDENCE_THRESHOLD}")
                self.state_manager.set_state(State.IDLE)
        else:
            # No text recognized, go back to IDLE
            logger.info("No speech detected, returning to IDLE state.")
            self.state_manager.set_state(State.IDLE)
            
        # Reset recognizer for next time
        self.recognizer.Reset()

    def _calculate_confidence(self, result_dict):
        """Calculate confidence score from Vosk result."""
        # Check if we have word-level confidence scores
        if 'result' in result_dict and result_dict['result']:
            word_confidences = [word.get('conf', 0) for word in result_dict['result']]
            if word_confidences:
                # Average confidence across all words
                return sum(word_confidences) / len(word_confidences)
                
        # If no word-level confidence or empty result, use default
        return 1.0  # Default high confidence when no score available

# llm_handler.py
"""
Handles interaction with the Large Language Model (OpenAI API).
Includes basic offline fallback logic.
"""
import threading
import queue
import time
import logging
from openai import OpenAI, APITimeoutError, APIConnectionError, AuthenticationError
import config
from state_manager import StateManager, State

# Setup logger
logger = logging.getLogger(__name__)

class LLMHandler(threading.Thread):
    """
    Thread to send text prompts to the LLM and get responses.
    Takes text from stt_queue and puts responses onto llm_queue.
    """
    def __init__(self, stt_queue: queue.Queue, llm_queue: queue.Queue, state_manager: StateManager, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.stt_queue = stt_queue
        self.llm_queue = llm_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.client = None
        self.online_mode = True # Assume online initially
        self.reconnect_attempt_time = 0
        self.reconnect_cooldown = 60  # seconds
        
        # Conversation history for context
        self.conversation_history = [
            {"role": "system", "content": config.LLM_SYSTEM_PROMPT}
        ]
        self.max_history_length = config.LLM_MAX_CONVERSATION_TURNS
        
        # Initialize client
        self._init_client()

    def _init_client(self):
        """Initialize the OpenAI client."""
        if config.OPENAI_API_KEY:
            try:
                self.client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.LLM_TIMEOUT)
                logger.info("OpenAI client initialized.")
                self.online_mode = True
            except AuthenticationError:
                logger.error("ERROR: OpenAI Authentication Failed. Check API Key.")
                self.state_manager.set_state(State.ERROR)
                self.online_mode = False
            except Exception as e:
                logger.error(f"Error initializing OpenAI client: {e}")
                self.state_manager.set_state(State.ERROR)
                self.online_mode = False
        else:
            logger.warning("Warning: OPENAI_API_KEY not found. LLM will operate in offline mode only.")
            self.online_mode = False
            if not config.LLM_OFFLINE_FALLBACK_ENABLED:
                logger.error("ERROR: Offline fallback is disabled, and no API key provided. LLM cannot function.")
                self.state_manager.set_state(State.ERROR)

    def _attempt_reconnect(self):
        """Try to reconnect to OpenAI API if offline."""
        current_time = time.time()
        if current_time - self.reconnect_attempt_time < self.reconnect_cooldown:
            return False
            
        logger.info("Attempting to reconnect to OpenAI API...")
        self.reconnect_attempt_time = current_time
        
        # Use the initialization method for reconnection
        self._init_client()
        return self.online_mode

    def _manage_conversation_history(self, user_message, assistant_response):
        """Add new messages to conversation history and trim if needed."""
        # Add the new exchange
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "assistant", "content": assistant_response})
        
        # Trim history if it exceeds the maximum length
        # Keep system message and the most recent exchanges
        if len(self.conversation_history) > self.max_history_length * 2 + 1:  # +1 for system message
            system_message = self.conversation_history[0]
            # Keep only the most recent exchanges
            recent_messages = self.conversation_history[-(self.max_history_length * 2):]
            self.conversation_history = [system_message] + recent_messages
            logger.debug(f"Trimmed conversation history to {len(self.conversation_history)} messages")

    def run(self):
        """Main loop for the LLM handler thread."""
        if self.state_manager.is_state(State.ERROR) and self.online_mode is False and not config.LLM_OFFLINE_FALLBACK_ENABLED:
             logger.warning("LLMHandler cannot start due to configuration error.")
             return

        logger.info("LLM Handler waiting for text...")
        while not self.stop_event.is_set():
            if self.state_manager.is_state(State.THINKING):
                try:
                    prompt = self.stt_queue.get(block=True, timeout=1.0)
                    logger.info(f"LLM Handler received prompt: '{prompt}'")

                    # Check if we need to attempt reconnection
                    if not self.online_mode:
                        self._attempt_reconnect()

                    response_text = None
                    if self.online_mode and self.client:
                        try:
                            # --- Online Mode ---
                            logger.info("LLM Handler: Querying OpenAI...")
                            
                            # Create a copy of the conversation history and add the new user message
                            messages = self.conversation_history.copy()
                            messages.append({"role": "user", "content": prompt})
                            
                            # Send to OpenAI with conversation history for context
                            completion = self.client.chat.completions.create(
                                model=config.LLM_MODEL,
                                messages=messages,
                                temperature=config.LLM_TEMPERATURE,
                                max_tokens=config.LLM_MAX_TOKENS
                            )
                            response_text = completion.choices[0].message.content
                            logger.info(f"LLM Handler: Received response from OpenAI.")
                            
                            # Add the exchange to conversation history
                            if response_text:
                                self._manage_conversation_history(prompt, response_text)

                        except APITimeoutError:
                            logger.error("LLM Handler: OpenAI API request timed out.")
                            self.online_mode = False # Switch to offline on timeout
                        except APIConnectionError:
                            logger.error("LLM Handler: OpenAI API connection error.")
                            self.online_mode = False # Switch to offline on connection error
                        except AuthenticationError:
                             logger.error("LLM Handler: OpenAI Authentication Error. Check API Key.")
                             self.online_mode = False
                             self.state_manager.set_state(State.ERROR)
                        except Exception as e:
                            logger.exception(f"LLM Handler: Error during OpenAI API call: {e}")
                            self.online_mode = False # Fallback on other errors

                    # --- Offline Fallback ---
                    if response_text is None: # If online failed or was never enabled
                        if config.LLM_OFFLINE_FALLBACK_ENABLED:
                            logger.info("LLM Handler: Using offline fallback response.")
                            response_text = config.LLM_OFFLINE_RESPONSE
                            # ** Placeholder for actual local LLM call **
                            # This is where you would integrate llama.cpp, GPT4All, etc.
                            # Be aware of significant performance limitations on RPi
                        else:
                             logger.warning("LLM Handler: Offline fallback disabled, cannot generate response.")
                             response_text = "I am currently offline and cannot respond."
                             self.state_manager.set_state(State.ERROR) # Indicate inability to respond

                    # --- Send Response ---
                    if response_text:
                        logger.info(f"LLM Response: {response_text[:100]}...")
                        self.llm_queue.put(response_text)
                        self.state_manager.set_state(State.SYNTHESIZING_TTS)
                    else:
                        # If no response generated (shouldn't happen with fallback logic)
                        logger.warning("LLM Handler: No response generated.")
                        self.state_manager.set_state(State.IDLE) # Go back to idle if stuck

                except queue.Empty:
                    # No prompt received, check state again
                    if not self.state_manager.is_state(State.THINKING):
                         logger.debug("LLM Handler: State changed while waiting for prompt.")
                    continue # Go back to start of loop
                except Exception as e:
                    logger.exception(f"An unexpected error occurred in LLM Handler thread: {e}")
                    self.state_manager.set_state(State.ERROR)
                    time.sleep(1)
            else:
                # Not in THINKING state, sleep briefly
                time.sleep(0.1)

        logger.info("LLM Handler stopping.")
        
    def reset_conversation(self):
        """Reset the conversation history to initial state."""
        system_message = self.conversation_history[0] if self.conversation_history else {
            "role": "system", 
            "content": config.LLM_SYSTEM_PROMPT
        }
        self.conversation_history = [system_message]
        logger.info("Conversation history has been reset.")

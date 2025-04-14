# llm_handler.py
"""
Handles interaction with the Large Language Model (OpenAI API).
Includes basic offline fallback logic.
"""
import threading
import queue
import time
from openai import OpenAI, APITimeoutError, APIConnectionError, AuthenticationError
import config
from state_manager import StateManager, State

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

        if config.OPENAI_API_KEY:
            try:
                self.client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.LLM_TIMEOUT)
                print("OpenAI client initialized.")
            except AuthenticationError:
                 print("ERROR: OpenAI Authentication Failed. Check API Key.")
                 self.state_manager.set_state(State.ERROR)
                 self.online_mode = False
            except Exception as e:
                print(f"Error initializing OpenAI client: {e}")
                self.state_manager.set_state(State.ERROR)
                self.online_mode = False
        else:
            print("Warning: OPENAI_API_KEY not found. LLM will operate in offline mode only.")
            self.online_mode = False
            if not config.LLM_OFFLINE_FALLBACK_ENABLED:
                 print("ERROR: Offline fallback is disabled, and no API key provided. LLM cannot function.")
                 self.state_manager.set_state(State.ERROR)


    def run(self):
        """Main loop for the LLM handler thread."""
        if self.state_manager.is_state(State.ERROR) and self.online_mode is False and not config.LLM_OFFLINE_FALLBACK_ENABLED:
             print("LLMHandler cannot start due to configuration error.")
             return

        print("LLM Handler waiting for text...")
        while not self.stop_event.is_set():
            if self.state_manager.is_state(State.THINKING):
                try:
                    prompt = self.stt_queue.get(block=True, timeout=1.0)
                    print(f"LLM Handler received prompt: '{prompt}'")

                    response_text = None
                    if self.online_mode and self.client:
                        try:
                            # --- Online Mode ---
                            print("LLM Handler: Querying OpenAI...")
                            # Basic chat completion example [27, 28]
                            # TODO: Implement conversation history management for context
                            completion = self.client.chat.completions.create(
                                model=config.LLM_MODEL,
                                messages=[
                                    {"role": "system", "content": "You are a helpful assistant."},
                                    {"role": "user", "content": prompt}
                                ]
                            )
                            response_text = completion.choices.message.content
                            print(f"LLM Handler: Received response from OpenAI.")

                        except APITimeoutError:
                            print("LLM Handler: OpenAI API request timed out.")
                            self.online_mode = False # Switch to offline on timeout
                        except APIConnectionError:
                            print("LLM Handler: OpenAI API connection error.")
                            self.online_mode = False # Switch to offline on connection error
                        except AuthenticationError:
                             print("LLM Handler: OpenAI Authentication Error. Check API Key.")
                             self.online_mode = False
                             self.state_manager.set_state(State.ERROR)
                        except Exception as e:
                            print(f"LLM Handler: Error during OpenAI API call: {e}")
                            self.online_mode = False # Fallback on other errors

                    # --- Offline Fallback ---
                    if response_text is None: # If online failed or was never enabled
                        if config.LLM_OFFLINE_FALLBACK_ENABLED:
                            print("LLM Handler: Using offline fallback response.")
                            response_text = config.LLM_OFFLINE_RESPONSE
                            # ** Placeholder for actual local LLM call **
                            # This is where you would integrate llama.cpp, GPT4All, etc.
                            # Be aware of significant performance limitations on RPi [29, 30]
                            # Example:
                            # try:
                            #    response_text = local_llm_function(prompt)
                            # except Exception as local_e:
                            #    print(f"Local LLM error: {local_e}")
                            #    response_text = "I encountered an error processing that locally."
                        else:
                             print("LLM Handler: Offline fallback disabled, cannot generate response.")
                             response_text = "I am currently offline and cannot respond."
                             self.state_manager.set_state(State.ERROR) # Indicate inability to respond

                    # --- Send Response ---
                    if response_text:
                        print(f"LLM Response: {response_text}")
                        self.llm_queue.put(response_text)
                        self.state_manager.set_state(State.SYNTHESIZING_TTS)
                    else:
                        # If no response generated (shouldn't happen with fallback logic)
                        print("LLM Handler: No response generated.")
                        self.state_manager.set_state(State.IDLE) # Go back to idle if stuck

                except queue.Empty:
                    # No prompt received, check state again
                    if not self.state_manager.is_state(State.THINKING):
                         print("LLM Handler: State changed while waiting for prompt.")
                    continue # Go back to start of loop
                except Exception as e:
                    print(f"An unexpected error occurred in LLM Handler thread: {e}")
                    self.state_manager.set_state(State.ERROR)
                    time.sleep(1)
            else:
                # Not in THINKING state, sleep briefly
                # TODO: Add logic to periodically check connectivity if offline
                time.sleep(0.1)

        print("LLM Handler stopping.")

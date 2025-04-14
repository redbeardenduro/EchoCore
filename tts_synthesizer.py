# tts_synthesizer.py
"""
Synthesizes speech from text using the configured TTS engine.
Supports OpenAI TTS, ElevenLabs TTS (cloud), and Piper TTS (local).
"""
import threading
import queue
import time
import io
import wave # For Piper WAV output handling
import subprocess # For Piper executable interaction
from openai import OpenAI, APIConnectionError, APITimeoutError, AuthenticationError
from elevenlabs.client import ElevenLabs
from elevenlabs import play as elevenlabs_play, stream as elevenlabs_stream, save as elevenlabs_save
import config
from state_manager import StateManager, State

class TTSSynthesizer(threading.Thread):
    """
    Thread to convert text from llm_queue to audio data onto tts_queue.
    Supports multiple TTS backends.
    """
    def __init__(self, llm_queue: queue.Queue, tts_queue: queue.Queue, state_manager: StateManager, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.llm_queue = llm_queue
        self.tts_queue = tts_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.openai_client = None
        self.elevenlabs_client = None
        self.online_mode = True # Assume online unless API keys missing or errors occur

        # --- Initialize Clients based on Config ---
        if config.TTS_ENGINE == 'openai':
            if config.OPENAI_API_KEY:
                try:
                    self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.LLM_TIMEOUT)
                    print("OpenAI TTS client initialized.")
                except AuthenticationError:
                     print("ERROR: OpenAI Authentication Failed for TTS. Check API Key.")
                     self.state_manager.set_state(State.ERROR)
                     self.online_mode = False
                except Exception as e:
                    print(f"Error initializing OpenAI TTS client: {e}")
                    self.state_manager.set_state(State.ERROR)
                    self.online_mode = False
            else:
                print("Warning: OPENAI_API_KEY not found for OpenAI TTS.")
                self.online_mode = False

        elif config.TTS_ENGINE == 'elevenlabs':
            if config.ELEVENLABS_API_KEY:
                try:
                    self.elevenlabs_client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
                    # Test connection by listing voices
                    _ = self.elevenlabs_client.voices.get_all()
                    print("ElevenLabs TTS client initialized.")
                except Exception as e:
                    print(f"Error initializing ElevenLabs client: {e}")
                    self.state_manager.set_state(State.ERROR)
                    self.online_mode = False
            else:
                print("Warning: ELEVENLABS_API_KEY not found for ElevenLabs TTS.")
                self.online_mode = False

        elif config.TTS_ENGINE == 'piper':
            print("Piper TTS selected (local engine).")
            # Check if model file exists? Basic check.
            if not os.path.exists(config.PIPER_MODEL_PATH):
                 print(f"ERROR: Piper model not found at {config.PIPER_MODEL_PATH}")
                 self.state_manager.set_state(State.ERROR)
            self.online_mode = False # Piper is always offline

        else:
            print(f"ERROR: Unknown TTS_ENGINE configured: {config.TTS_ENGINE}")
            self.state_manager.set_state(State.ERROR)

        if not self.online_mode and config.TTS_ENGINE!= 'piper':
             print("ERROR: Selected cloud TTS engine but cannot initialize. Cannot synthesize speech.")
             if not self.state_manager.is_state(State.ERROR): # Avoid overwriting other errors
                 self.state_manager.set_state(State.ERROR)


    def run(self):
        """Main loop for the TTS synthesizer thread."""
        if self.state_manager.is_state(State.ERROR) and config.TTS_ENGINE!= 'piper':
             print("TTSSynthesizer cannot start due to configuration error.")
             return

        print("TTS Synthesizer waiting for text...")
        while not self.stop_event.is_set():
            if self.state_manager.is_state(State.SYNTHESIZING_TTS):
                try:
                    text_to_speak = self.llm_queue.get(block=True, timeout=1.0)
                    print(f"TTS Synthesizer received text: '{text_to_speak}'")

                    audio_stream = None
                    synthesis_successful = False

                    # --- Synthesize Audio ---
                    if config.TTS_ENGINE == 'openai' and self.openai_client:
                        audio_stream = self._synthesize_openai(text_to_speak)
                    elif config.TTS_ENGINE == 'elevenlabs' and self.elevenlabs_client:
                        audio_stream = self._synthesize_elevenlabs(text_to_speak)
                    elif config.TTS_ENGINE == 'piper':
                        audio_stream = self._synthesize_piper(text_to_speak)
                    else:
                         # Fallback if online failed or Piper selected but failed init
                         print("TTS Synthesizer: Cannot synthesize - engine not available.")
                         self.state_manager.set_state(State.ERROR)


                    # --- Stream Audio Chunks to Output Queue ---
                    if audio_stream:
                        print("TTS Synthesizer: Streaming audio to output queue...")
                        self.state_manager.set_state(State.SPEAKING) # Signal speaking has started
                        chunk_size = config.AUDIO_CHUNK_SIZE * 2 # Read enough bytes for int16
                        first_chunk = True
                        while True:
                            chunk = audio_stream.read(chunk_size)
                            if not chunk:
                                break
                            if first_chunk:
                                print("TTS Synthesizer: First audio chunk received.")
                                first_chunk = False
                            self.tts_queue.put(chunk)
                        print("TTS Synthesizer: Finished streaming audio.")
                        synthesis_successful = True
                        # Signal end of speech by putting None or a special marker
                        self.tts_queue.put(None)

                    # --- Handle Synthesis Failure ---
                    if not synthesis_successful:
                         print("TTS Synthesizer: Synthesis failed.")
                         # Avoid getting stuck - transition back to IDLE or ERROR
                         if not self.state_manager.is_state(State.ERROR):
                             self.state_manager.set_state(State.IDLE)


                except queue.Empty:
                    # No text received, check state again
                    if not self.state_manager.is_state(State.SYNTHESIZING_TTS):
                         print("TTS Synthesizer: State changed while waiting for text.")
                    continue
                except Exception as e:
                    print(f"An unexpected error occurred in TTS Synthesizer thread: {e}")
                    self.state_manager.set_state(State.ERROR)
                    time.sleep(1)
            else:
                # Not in SYNTHESIZING_TTS state, sleep briefly
                time.sleep(0.1)

        print("TTS Synthesizer stopping.")

    def _synthesize_openai(self, text):
        """Synthesize speech using OpenAI TTS API and return audio stream."""
        try:
            print("Synthesizing with OpenAI TTS...")
            # Use streaming response [3]
            response = self.openai_client.audio.speech.with_streaming_response.create(
                model=config.OPENAI_TTS_MODEL,
                voice=config.OPENAI_TTS_VOICE,
                input=text,
                response_format=config.OPENAI_TTS_FORMAT, # e.g., "pcm", "mp3", "opus"
                # speed=1.0 # Optional speed control
            )
            # Return the raw stream content iterator
            return response.iter_bytes(chunk_size=config.AUDIO_CHUNK_SIZE * 2) # Read enough bytes for int16
        except APIConnectionError:
            print("OpenAI TTS Error: Connection failed.")
            self.online_mode = False
        except APITimeoutError:
            print("OpenAI TTS Error: Request timed out.")
            self.online_mode = False
        except AuthenticationError:
             print("OpenAI TTS Error: Authentication failed.")
             self.online_mode = False
             self.state_manager.set_state(State.ERROR)
        except Exception as e:
            print(f"OpenAI TTS Error: {e}")
            self.online_mode = False
        return None # Indicate failure

    def _synthesize_elevenlabs(self, text):
        """Synthesize speech using ElevenLabs API and return audio stream."""
        try:
            print("Synthesizing with ElevenLabs TTS...")
            # Use the stream function [6, 31]
            audio_stream = self.elevenlabs_client.generate(
                text=text,
                voice=config.ELEVENLABS_VOICE,
                model=config.ELEVENLABS_MODEL,
                stream=True,
                output_format="pcm_16000" # Request PCM for direct playback
                # latency=3 # Optional latency optimization level
            )
            return audio_stream # Returns an iterator
        except Exception as e:
            print(f"ElevenLabs TTS Error: {e}")
            self.online_mode = False
            # Check for specific API errors if needed
            if "Authentication" in str(e):
                 self.state_manager.set_state(State.ERROR)
        return None # Indicate failure

    def _synthesize_piper(self, text):
        """Synthesize speech using local Piper TTS executable and return audio stream."""
        try:
            print("Synthesizing with Piper TTS (local)...")
            # Piper command line usage: echo 'text' | piper --model <model.onnx> --output_raw
            # We use subprocess to pipe text and capture raw PCM audio output [32, 7, 33]

            command =
            if config.PIPER_CONFIG_PATH:
                command.extend()
            if config.PIPER_SPEAKER_ID is not None:
                 command.extend()

            # Start the Piper process
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Send text to Piper's stdin (ensure correct encoding)
            # Add newline as Piper often expects it
            process.stdin.write((text + '\n').encode('utf-8'))
            process.stdin.close() # Signal end of input

            # Return the stdout stream for reading audio data
            # Note: stderr could be monitored for errors: process.stderr.read()
            return process.stdout

        except FileNotFoundError:
             print("ERROR: 'piper' command not found. Is Piper TTS installed and in PATH?")
             self.state_manager.set_state(State.ERROR)
        except Exception as e:
            print(f"Piper TTS Error: {e}")
            self.state_manager.set_state(State.ERROR)
        return None # Indicate failure

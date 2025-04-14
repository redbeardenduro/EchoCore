# piper_tts.py
"""
Wrapper class for interacting with the Piper Text-to-Speech (TTS) engine
via its command-line interface.

Provides methods to synthesize speech to a file, return audio bytes,
or provide a streaming interface. Also includes functionality to check
for the Piper executable and retrieve voice model information.
"""

import os
import subprocess
import io
import tempfile # Keep if temporary file generation is needed elsewhere
import logging
import shutil
import json
import time
from pathlib import Path
from typing import Optional, Union, BinaryIO, Dict, Any, Iterator, List # For type hinting

# Import project config - assumes config object is loaded elsewhere or accessible
try:
    import config # Assuming config object provides necessary paths/settings
except ImportError:
     # Fallback or raise error if config is mandatory for this module
     logging.error("Configuration module not found. PiperClient may not function correctly.")
     # Define minimal defaults if config is missing, though this isn't ideal
     class MockConfig:
         PIPER_MODEL_PATH = "models/piper/en_US-lessac-medium.onnx"
         PIPER_CONFIG_PATH = None
         PIPER_SPEAKER_ID = 0
         PIPER_NOISE_SCALE = 0.667
         PIPER_LENGTH_SCALE = 1.0
     config = MockConfig()


# Setup logger
logger = logging.getLogger(__name__)

# Define the expected type for the streaming output
PiperAudioStream = BinaryIO # Type alias for the process stdout stream

class PiperClient:
    """
    Client class for interacting with the Piper TTS command-line executable.

    Handles constructing commands, executing Piper, and managing output
    (file, bytes, or stream).
    """

    def __init__(self):
        """
        Initialize the Piper TTS client.

        Loads configuration settings and checks for Piper availability.
        """
        # Configuration - Prefer loading from a central config object
        # Ensure paths are handled correctly (Path objects recommended)
        self.model_path: Optional[Path] = Path(config.PIPER_MODEL_PATH) if config.PIPER_MODEL_PATH else None
        self.config_path: Optional[Path] = Path(config.PIPER_CONFIG_PATH) if config.PIPER_CONFIG_PATH else None
        self.speaker_id: Optional[int] = config.PIPER_SPEAKER_ID
        self.noise_scale: Optional[float] = config.PIPER_NOISE_SCALE
        self.length_scale: Optional[float] = config.PIPER_LENGTH_SCALE

        self.last_error: Optional[str] = None
        self.piper_executable_path: Optional[str] = None # Store path once found

        # --- Initialization Steps ---
        self._find_piper_executable()
        self._resolve_config_path()
        self._validate_paths()


    def _find_piper_executable(self) -> None:
        """Locate the 'piper' executable in the system's PATH."""
        self.piper_executable_path = shutil.which("piper")
        if self.piper_executable_path:
            logger.info(f"Found Piper executable at: {self.piper_executable_path}")
        else:
             # Set error state immediately if executable isn't found
            self.last_error = "Piper executable ('piper') not found in system PATH."
            logger.error(self.last_error)


    def _resolve_config_path(self) -> None:
        """Automatically find the config path if not explicitly set."""
        if self.model_path and not self.config_path:
            # Assume config file has the same name as the model but with .json extension
            potential_config = self.model_path.with_suffix(".onnx.json")
            if potential_config.exists():
                self.config_path = potential_config
                logger.info(f"Automatically detected Piper config file: {self.config_path}")
            else:
                logger.debug(f"No automatic config file found at {potential_config}, proceeding without explicit config.")


    def _validate_paths(self) -> None:
        """Check if the required model path exists."""
        if not self.model_path or not self.model_path.exists():
            error_msg = f"Piper model file not found or not configured: {self.model_path}"
            logger.error(error_msg)
            # If executable was found but model is missing, set error
            if self.piper_executable_path and not self.last_error:
                 self.last_error = error_msg
        else:
            logger.debug(f"Piper model path validated: {self.model_path}")

        # Optional: Check config path if set
        if self.config_path and not self.config_path.exists():
             logger.warning(f"Piper config path specified but not found: {self.config_path}")
             # Don't set self.last_error here, as config is often optional

    def is_available(self) -> bool:
        """Check if Piper executable and model are available."""
        return self.piper_executable_path is not None and \
               self.model_path is not None and \
               self.model_path.exists()

    def get_voice_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the currently configured Piper voice model.

        Reads details from the model's associated JSON config file if available.

        Returns:
            A dictionary containing voice information (model path, config path,
            speaker id, name, language, scales, etc.), or None if unavailable.
        """
        if not self.is_available():
            logger.warning("Cannot get voice info: Piper is not available (check executable and model path).")
            return None

        voice_info: Dict[str, Any] = {
            "model_path": str(self.model_path), # Return string representation
            "config_path": str(self.config_path) if self.config_path else None,
            "speaker_id": self.speaker_id,
            "model_name": self.model_path.stem if self.model_path else "Unknown", # type: ignore # Checked by is_available
            # Include configured scales, might differ from defaults in JSON
            "configured_noise_scale": self.noise_scale,
            "configured_length_scale": self.length_scale,
        }

        # Try to load additional details from the JSON config file
        if self.config_path and self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

                # Extract relevant fields (handle potential missing keys)
                voice_info["language"] = config_data.get("espeak", {}).get("voice")
                voice_info["quality"] = config_data.get("quality")
                voice_info["num_speakers"] = config_data.get("num_speakers", 1) # Default to 1 if not specified
                # Add default scales from config if not overridden by instance config
                inference_config = config_data.get("inference", {})
                voice_info["default_noise_scale"] = inference_config.get("noise_scale", 0.667)
                voice_info["default_length_scale"] = inference_config.get("length_scale", 1.0)

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Piper config file {self.config_path}: {e}")
            except Exception as e:
                logger.exception(f"Error reading Piper config file {self.config_path}: {e}")
        else:
            logger.debug("No Piper JSON config file found or specified, voice info limited.")

        return voice_info

    def synthesize(
        self,
        text: str,
        output_file: Optional[Union[str, Path]] = None,
        streaming: bool = False,
        output_format: str = "pcm_16000" # Primarily for generate compatibility
    ) -> Optional[Union[bool, bytes, PiperAudioStream]]:
        """
        Synthesize speech from text using the Piper command-line tool.

        Args:
            text: The text to synthesize.
            output_file: If provided, save audio directly to this WAV file path.
            streaming: If True, return the raw audio stream (subprocess stdout).
            output_format: Controls the output type ('pcm_16000' implies raw for streaming).

        Returns:
            - If output_file is set: Returns True on success, False on failure.
            - If streaming is True: Returns a readable binary stream object
              (subprocess.PIPE) on success, None on failure.
            - Otherwise (default): Returns the synthesized audio data as bytes
              (raw PCM) on success, None on failure.
            Returns None if Piper is not available or if synthesis fails.
        """
        if not self.is_available():
            self.last_error = "Piper is not available (check executable and model path)."
            logger.error(self.last_error)
            return None

        # --- Build Command ---
        command: List[str] = [self.piper_executable_path] # type: ignore # Checked by is_available
        command.extend(["--model", str(self.model_path)]) # type: ignore # Checked by is_available

        if self.config_path and self.config_path.exists():
            command.extend(["--config", str(self.config_path)])
        if self.speaker_id is not None:
            command.extend(["--speaker", str(self.speaker_id)])
        # Use configured scales if they are not None
        if self.noise_scale is not None:
            command.extend(["--noise-scale", str(self.noise_scale)])
        if self.length_scale is not None:
            command.extend(["--length-scale", str(self.length_scale)])

        # --- Determine Output Mode ---
        process_stdout = None # Default stdout handling
        if output_file:
            output_path = Path(output_file)
            command.extend(["--output-file", str(output_path)]) # Use --output-file for WAV
            logger.debug(f"Piper command configured for file output: {output_path}")
            # Piper handles file writing, stdout/stderr can be captured for errors
            process_stdout = subprocess.PIPE
        elif streaming or output_format == "pcm_16000":
            # Request raw PCM audio stream via stdout
            command.append("--output-raw")
            process_stdout = subprocess.PIPE # Capture stdout for streaming
            logger.debug("Piper command configured for raw streaming output.")
        else:
             # Default: Capture raw bytes in memory (treat like streaming internally)
             command.append("--output-raw")
             process_stdout = subprocess.PIPE
             logger.debug("Piper command configured for raw byte output (in memory).")

        # --- Execute Piper Subprocess ---
        self.last_error = None # Clear previous error
        try:
            logger.debug(f"Running Piper command: {' '.join(command)}")
            # Use Popen for non-blocking execution, especially for streaming
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=process_stdout,
                stderr=subprocess.PIPE,
                # Ensure clean process termination on Windows if needed:
                # creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # Send text to Piper's stdin (ensure correct encoding)
            # Adding a newline might be necessary depending on Piper version
            stdin_data = (text.strip() + '\n').encode('utf-8')
            stdout_data, stderr_data = process.communicate(input=stdin_data)
            # process.communicate waits for the process to finish

            stderr_str = stderr_data.decode('utf-8', errors='ignore').strip()
            if stderr_str:
                 # Log Piper's stderr output, might contain useful info or warnings
                 logger.warning(f"Piper stderr output:\n{stderr_str}")


            # --- Process Results ---
            if process.returncode != 0:
                self.last_error = f"Piper process failed with exit code {process.returncode}. Stderr: {stderr_str}"
                logger.error(self.last_error)
                return None # Indicate failure for all modes

            # Success cases based on mode
            if output_file:
                logger.info(f"Successfully synthesized speech to file: {output_file}")
                return True # File writing handled by Piper
            elif streaming:
                 # Need to return a stream-like object containing the stdout_data
                 # Since communicate() already read it, wrap it in BytesIO
                 logger.info(f"Successfully synthesized {len(stdout_data)} bytes for streaming.")
                 return io.BytesIO(stdout_data)
            else:
                 # Default: return raw bytes
                 logger.info(f"Successfully synthesized {len(stdout_data)} bytes of audio.")
                 return stdout_data


        except FileNotFoundError:
            self.last_error = f"Piper executable not found at path: {command[0]}"
            logger.error(self.last_error)
            return None
        except subprocess.TimeoutExpired:
             self.last_error = "Piper process timed out."
             logger.error(self.last_error)
             # Ensure process is killed if timeout occurs with communicate
             process.kill()
             return None
        except Exception as e:
            self.last_error = f"Unexpected error during Piper synthesis: {e}"
            logger.exception(self.last_error) # Log full traceback
            return None


    # Compatibility method for TTS Synthesizer
    def generate(
        self,
        text: str,
        stream: bool = True,
        output_format: str = "pcm_16000" # This hints the desired output type
    ) -> Optional[Iterator[bytes]]:
        """
        Generates audio stream using Piper, compatible with TTS Synthesizer pattern.

        Args:
            text: Text to synthesize.
            stream: If True, requests a streaming response.
            output_format: Expected audio format (currently only supports PCM).

        Returns:
            An iterator yielding audio chunks (bytes) if stream=True and successful.
            Returns None on failure.
            (Note: Current implementation returns BytesIO, needs adaptation for true iterator)
        """
        if output_format != "pcm_16000":
            logger.warning(f"PiperClient currently only supports raw PCM output, ignoring format: {output_format}")

        # Call synthesize, requesting streaming mode
        result = self.synthesize(text=text, streaming=True, output_format="pcm_16000")

        if isinstance(result, io.BytesIO):
             # To make it a true iterator yielding chunks:
             # Need to read from BytesIO in chunks. This adapts the output.
             def chunk_iterator(bytes_io: io.BytesIO, chunk_size: int = 4096) -> Iterator[bytes]:
                 while True:
                     chunk = bytes_io.read(chunk_size)
                     if not chunk:
                         break
                     yield chunk
                 bytes_io.close() # Close BytesIO when done

             logger.debug("Returning chunk iterator from Piper BytesIO result.")
             # Define a reasonable chunk size, could be passed from config if needed
             return chunk_iterator(result, chunk_size=config.AUDIO_CHUNK_SIZE * 2)
        else:
            # Synthesis failed or returned unexpected type
            logger.error("Piper generate() failed to produce a valid audio stream.")
            return None

    def get_last_error(self) -> Optional[str]:
        """Return the last recorded error message."""
        return self.last_error

# --- Test function ---
if __name__ == "__main__":
    # Configure basic logging for direct script execution
    logging.basicConfig(
        level=logging.DEBUG, # Use DEBUG to see detailed logs
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )

    logger.info("--- Testing PiperClient ---")
    client = PiperClient()

    if not client.is_available():
        logger.error("PiperClient is not available. Check Piper installation and model paths.")
        logger.error(f"Last error: {client.get_last_error()}")
    else:
        # 1. Get Voice Info
        logger.info("\n--- Getting Voice Info ---")
        voice_info = client.get_voice_info()
        if voice_info:
            # Pretty print the dictionary
            import pprint
            pprint.pprint(voice_info)
        else:
            logger.warning("Could not retrieve voice info.")

        # 2. Test Synthesis to File
        logger.info("\n--- Testing Synthesis to File ---")
        test_text = "Hello from Piper TTS via the Python client."
        output_wav_file = Path("./piper_test_output.wav")
        success = client.synthesize(test_text, output_file=output_wav_file)
        logger.info(f"File synthesis {'successful' if success else 'failed'}. Output: {output_wav_file}")
        if success:
             logger.info(f"File size: {output_wav_file.stat().st_size} bytes")
        # Don't delete immediately if user wants to check the file
        # if success and output_wav_file.exists(): os.remove(output_wav_file)


        # 3. Test Synthesis to Bytes (In Memory)
        logger.info("\n--- Testing Synthesis to Bytes ---")
        audio_bytes = client.synthesize(test_text)
        if audio_bytes:
             logger.info(f"Byte synthesis successful. Received {len(audio_bytes)} bytes.")
             # Optional: Save bytes to file for verification
             # with open("piper_test_bytes.raw", "wb") as f:
             #     f.write(audio_bytes)
        else:
            logger.error("Byte synthesis failed.")


        # 4. Test Streaming Synthesis (via generate method)
        logger.info("\n--- Testing Streaming Synthesis (generate) ---")
        stream_iterator = client.generate(test_text, stream=True)
        if stream_iterator:
            logger.info("Streaming synthesis successful. Reading chunks...")
            total_bytes_streamed = 0
            chunk_count = 0
            try:
                for chunk in stream_iterator:
                    chunk_count += 1
                    total_bytes_streamed += len(chunk)
                    # logger.debug(f"Received chunk {chunk_count}, size: {len(chunk)}")
                logger.info(f"Finished reading stream. Total chunks: {chunk_count}, Total bytes: {total_bytes_streamed}")
            except Exception as e:
                 logger.exception(f"Error reading from stream iterator: {e}")
        else:
            logger.error("Streaming synthesis failed.")

        logger.info("\n--- PiperClient Testing Complete ---")

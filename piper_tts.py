# piper_tts.py
"""
Wrapper class for Piper TTS functionality.
This module provides a consistent interface for the local Piper TTS engine,
similar to the cloud-based TTS services.
"""
import os
import subprocess
import io
import tempfile
import logging
import shutil
import json
import time
from pathlib import Path
import config

# Setup logger
logger = logging.getLogger(__name__)

class PiperClient:
    """
    Client class for interacting with the Piper TTS engine.
    Provides a consistent API similar to cloud TTS services.
    """
    
    def __init__(self):
        """Initialize the Piper TTS client."""
        self.model_path = config.PIPER_MODEL_PATH
        self.config_path = config.PIPER_CONFIG_PATH
        self.speaker_id = config.PIPER_SPEAKER_ID
        self.noise_scale = config.PIPER_NOISE_SCALE
        self.length_scale = config.PIPER_LENGTH_SCALE
        self.last_error = None
        
        # Determine config path if not specified
        if not self.config_path and self.model_path:
            # Piper config is usually the same filename with .json extension
            potential_config = Path(str(self.model_path).replace('.onnx', '.onnx.json'))
            if potential_config.exists():
                self.config_path = str(potential_config)
                logger.info(f"Using detected config file: {self.config_path}")
        
        # Check if piper is available
        self._check_piper_available()
    
    def _check_piper_available(self):
        """Check if the piper executable is available in PATH."""
        if shutil.which("piper") is None:
            self.last_error = "Piper executable not found in PATH"
            logger.error(f"ERROR: {self.last_error}")
            return False
        
        # Check model file
        if not self.model_path or not os.path.exists(self.model_path):
            self.last_error = f"Piper model not found at {self.model_path}"
            logger.error(f"ERROR: {self.last_error}")
            return False
        
        return True
    
    def get_voice_info(self):
        """Get information about the current voice model."""
        if not self._check_piper_available():
            return None
        
        try:
            # Try to load the model config to get voice info
            config_info = {}
            if self.config_path and os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config_info = json.load(f)
            
            # Extract voice information
            voice_info = {
                "model_path": self.model_path,
                "config_path": self.config_path,
                "speaker_id": self.speaker_id,
                "model_name": Path(self.model_path).stem
            }
            
            # Add details from config if available
            if config_info:
                if "espeak" in config_info:
                    voice_info["language"] = config_info["espeak"].get("voice", "Unknown")
                if "inference" in config_info:
                    voice_info["noise_scale"] = config_info["inference"].get("noise_scale", 0.667)
                    voice_info["length_scale"] = config_info["inference"].get("length_scale", 1.0)
                if "num_speakers" in config_info:
                    voice_info["num_speakers"] = config_info["num_speakers"]
                
            return voice_info
        
        except Exception as e:
            self.last_error = f"Error getting voice info: {e}"
            logger.exception(self.last_error)
            return None
    
    def synthesize(self, text, output_file=None, streaming=False):
        """
        Synthesize speech from text using Piper.
        
        Args:
            text: The text to synthesize
            output_file: Optional path to save the audio (WAV format)
            streaming: If True, returns a stream-like object
            
        Returns:
            If streaming is True, returns a file-like object for streaming
            If output_file is specified, returns True on success
            Otherwise, returns the audio data as bytes
        """
        if not self._check_piper_available():
            return None
        
        try:
            # Build the command with proper parameters
            command = ["piper", "--model", self.model_path]
            
            # Add optional arguments
            if self.config_path:
                command.extend(["--config", self.config_path])
            if self.speaker_id is not None:
                command.extend(["--speaker", str(self.speaker_id)])
            if self.noise_scale is not None:
                command.extend(["--noise-scale", str(self.noise_scale)])
            if self.length_scale is not None:
                command.extend(["--length-scale", str(self.length_scale)])
            
            # Determine output format
            if output_file:
                # Output to WAV file
                command.extend(["--output", output_file])
            elif streaming:
                # Output raw PCM for streaming
                command.append("--output-raw")
            else:
                # Output WAV to stdout
                command.append("--output-raw")
            
            logger.debug(f"Running Piper command: {' '.join(command)}")
            
            # Start the Piper process
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Send text to Piper's stdin
            process.stdin.write((text + '\n').encode('utf8'))
            process.stdin.close()
            
            # Handle different output modes
            if output_file:
                # Wait for process to complete
                stderr = process.stderr.read().decode('utf8')
                process.wait()
                
                if process.returncode != 0:
                    self.last_error = f"Piper synthesis failed with code {process.returncode}: {stderr}"
                    logger.error(self.last_error)
                    return False
                
                logger.info(f"Successfully synthesized speech to {output_file}")
                return True
                
            elif streaming:
                # For streaming, return stdout directly
                return process.stdout
                
            else:
                # Read all output data
                audio_data = process.stdout.read()
                stderr = process.stderr.read().decode('utf8')
                process.wait()
                
                if process.returncode != 0:
                    self.last_error = f"Piper synthesis failed with code {process.returncode}: {stderr}"
                    logger.error(self.last_error)
                    return None
                
                logger.info(f"Successfully synthesized {len(audio_data)} bytes of audio")
                return audio_data
                
        except Exception as e:
            self.last_error = f"Error in Piper synthesis: {e}"
            logger.exception(self.last_error)
            return None

    def generate(self, text, stream=True, output_format="pcm_16000"):
        """
        Compatibility method to match ElevenLabs' API pattern.
        
        Args:
            text: The text to synthesize
            stream: Whether to return a streaming response
            output_format: Audio format (only pcm is supported)
            
        Returns:
            A file-like object if stream=True, otherwise bytes
        """
        if output_format != "pcm_16000":
            logger.warning(f"Piper only supports pcm_16000 output format, ignoring format: {output_format}")
        
        return self.synthesize(text, streaming=stream)
    
    def get_last_error(self):
        """Get the last error message."""
        return self.last_error

# Test function
if __name__ == "__main__":
    # Set up basic logging
    logging.basicConfig(level=logging.INFO)
    
    # Create client
    client = PiperClient()
    
    # Get voice info
    voice_info = client.get_voice_info()
    print("Voice Info:", voice_info)
    
    # Test synthesis
    test_text = "Hello, this is a test of the Piper text to speech system."
    
    # Test file output
    output_file = "test_output.wav"
    success = client.synthesize(test_text, output_file=output_file)
    print(f"File synthesis {'successful' if success else 'failed'}: {output_file}")
    
    # Test streaming
    stream = client.synthesize(test_text, streaming=True)
    if stream:
        print("Streaming synthesis successful, reading first 100 bytes:", stream.read(100))
        stream.close()

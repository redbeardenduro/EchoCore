# audio_utils.py
"""
Utility functions for audio device management in Project EchoCore.
"""
import logging
import sounddevice as sd
import numpy as np

logger = logging.getLogger(__name__)

def list_audio_devices():
    """
    List all available audio input and output devices.
    Returns a tuple of (input_devices, output_devices)
    """
    try:
        devices = sd.query_devices()
        input_devices = []
        output_devices = []
        
        logger.info("Available audio devices:")
        
        for i, device in enumerate(devices):
            device_info = f"[{i}] {device['name']}"
            if device.get('max_input_channels', 0) > 0:
                input_devices.append((i, device['name'], device.get('default_samplerate')))
                logger.info(f"Input Device: {device_info} (Channels: {device['max_input_channels']}, Default SR: {device.get('default_samplerate')})")
            
            if device.get('max_output_channels', 0) > 0:
                output_devices.append((i, device['name'], device.get('default_samplerate')))
                logger.info(f"Output Device: {device_info} (Channels: {device['max_output_channels']}, Default SR: {device.get('default_samplerate')})")
        
        # Log default devices
        try:
            default_input = sd.query_devices(kind='input')
            default_output = sd.query_devices(kind='output')
            logger.info(f"Default input device: [{default_input['index']}] {default_input['name']}")
            logger.info(f"Default output device: [{default_output['index']}] {default_output['name']}")
        except Exception as e:
            logger.warning(f"Couldn't determine default devices: {e}")
            
        return input_devices, output_devices
        
    except Exception as e:
        logger.error(f"Error listing audio devices: {e}")
        return [], []

def find_optimal_device(mode='input', preferred_index=None, fallback_index=None):
    """
    Find the optimal audio device based on preferences.
    
    Args:
        mode: 'input' or 'output'
        preferred_index: Preferred device index from config
        fallback_index: Fallback device index if preferred not available
        
    Returns:
        Best matching device index, or None for system default
    """
    try:
        # If preferred index is explicitly None, user wants system default
        if preferred_index is None:
            return None
            
        devices = sd.query_devices()
        kind_filter = 'max_input_channels' if mode == 'input' else 'max_output_channels'
        
        # Check if preferred device exists and is of correct type
        if 0 <= preferred_index < len(devices):
            device = devices[preferred_index]
            if device.get(kind_filter, 0) > 0:
                logger.info(f"Using configured {mode} device: [{preferred_index}] {device['name']}")
                return preferred_index
            else:
                logger.warning(f"Configured {mode} device index {preferred_index} is not a {mode} device")
        
        # Try fallback if provided
        if fallback_index is not None and 0 <= fallback_index < len(devices):
            device = devices[fallback_index]
            if device.get(kind_filter, 0) > 0:
                logger.info(f"Using fallback {mode} device: [{fallback_index}] {device['name']}")
                return fallback_index
        
        # Get system default for this mode
        try:
            default_device = sd.query_devices(kind=mode)
            logger.info(f"Using system default {mode} device: [{default_device['index']}] {default_device['name']}")
            return default_device['index']
        except Exception as e:
            logger.warning(f"Couldn't determine default {mode} device: {e}")
            
        # Last resort: find first device of appropriate type
        for i, device in enumerate(devices):
            if device.get(kind_filter, 0) > 0:
                logger.info(f"Using first available {mode} device: [{i}] {device['name']}")
                return i
                
        logger.error(f"No suitable {mode} device found!")
        return None
        
    except Exception as e:
        logger.error(f"Error finding optimal audio device: {e}")
        return None

def test_audio_device(device_index=None, mode='output', duration=1.0, frequency=440):
    """
    Test an audio device by playing a simple tone (output) or recording (input).
    
    Args:
        device_index: Device index to test, None for default
        mode: 'input' or 'output'
        duration: Test duration in seconds
        frequency: Tone frequency for output test
        
    Returns:
        True if test passed, False otherwise
    """
    try:
        sample_rate = 44100  # Standard sample rate
        
        if mode == 'output':
            # Generate a simple sine wave tone
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            tone = 0.5 * np.sin(2 * np.pi * frequency * t)  # 0.5 amplitude
            
            # Apply fade in/out to avoid clicks
            fade_len = int(sample_rate * 0.05)  # 50ms fade
            fade_in = np.linspace(0, 1, fade_len)
            fade_out = np.linspace(1, 0, fade_len)
            tone[:fade_len] *= fade_in
            tone[-fade_len:] *= fade_out
            
            # Convert to int16
            output_data = (tone * 32767).astype(np.int16)
            
            # Play the tone
            logger.info(f"Testing output device {device_index} with {frequency}Hz tone...")
            sd.play(output_data, sample_rate, device=device_index, blocking=True)
            logger.info("Output test complete")
            return True
            
        elif mode == 'input':
            logger.info(f"Testing input device {device_index} with {duration}s recording...")
            
            # Record audio
            recording = sd.rec(
                int(duration * sample_rate), 
                samplerate=sample_rate, 
                channels=1, 
                dtype='int16', 
                device=device_index, 
                blocking=True
            )
            
            # Basic analysis
            if recording is not None and len(recording) > 0:
                # Calculate RMS volume
                rms = np.sqrt(np.mean(recording.astype(np.float32)**2))
                logger.info(f"Recording complete. RMS volume: {rms:.2f}")
                return True
            else:
                logger.error("Recording failed, no data captured")
                return False
    
    except Exception as e:
        logger.error(f"Audio device test failed: {e}")
        return False

# If run directly, list available devices
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    input_devices, output_devices = list_audio_devices()
    
    print("\nInput Devices:")
    for idx, name, sr in input_devices:
        print(f"[{idx}] {name}")
    
    print("\nOutput Devices:")
    for idx, name, sr in output_devices:
        print(f"[{idx}] {name}")

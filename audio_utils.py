# audio_utils.py
"""
Utility functions for audio device management using the sounddevice library.
Provides functions to list, find, and test audio input/output devices.
"""

import logging
import sounddevice as sd
import numpy as np
from typing import List, Tuple, Optional, Dict, Any

# Setup logger
logger = logging.getLogger(__name__)

# Define a type alias for device info for clarity
DeviceInfo = Tuple[int, str, Optional[float]] # (index, name, default_samplerate)

def list_audio_devices() -> Tuple[List[DeviceInfo], List[DeviceInfo]]:
    """
    Lists all available audio input and output devices.

    Logs the found devices and attempts to identify the default devices.

    Returns:
        A tuple containing two lists: (input_devices, output_devices).
        Each list contains tuples of (index, name, default_samplerate).
        Returns empty lists if an error occurs.
    """
    input_devices: List[DeviceInfo] = []
    output_devices: List[DeviceInfo] = []

    try:
        devices: List[Dict[str, Any]] = sd.query_devices() # type: ignore # sounddevice types might be incomplete
        logger.info("--- Available Audio Devices ---")

        for i, device in enumerate(devices):
            device_name = device.get('name', 'Unknown Device')
            device_sr = device.get('default_samplerate')
            device_info_str = f"[{i}] {device_name}"

            # Check for input capabilities
            max_in_channels = device.get('max_input_channels', 0)
            if max_in_channels > 0:
                input_devices.append((i, device_name, device_sr))
                logger.info(f"  Input : {device_info_str} (Channels: {max_in_channels}, Default SR: {device_sr})")

            # Check for output capabilities
            max_out_channels = device.get('max_output_channels', 0)
            if max_out_channels > 0:
                output_devices.append((i, device_name, device_sr))
                logger.info(f"  Output: {device_info_str} (Channels: {max_out_channels}, Default SR: {device_sr})")

        # Log default devices separately for clarity
        logger.info("--- Default Audio Devices ---")
        try:
            # Explicitly query for default input and output devices
            default_input_info = sd.query_devices(kind='input') # type: ignore
            default_output_info = sd.query_devices(kind='output') # type: ignore
            logger.info(f"  Default Input : [{default_input_info['index']}] {default_input_info['name']}") # type: ignore
            logger.info(f"  Default Output: [{default_output_info['index']}] {default_output_info['name']}") # type: ignore
        except (sd.PortAudioError, ValueError, TypeError) as e:
             # Catches cases where no default device is found or query fails
            logger.warning(f"Could not determine default audio devices: {e}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred while querying default devices: {e}")

        logger.info("-----------------------------")
        return input_devices, output_devices

    except sd.PortAudioError as pae:
        logger.error(f"PortAudioError listing audio devices: {pae}")
        logger.error("Ensure PortAudio library is correctly installed and audio system is running.")
        return [], []
    except Exception as e:
        logger.exception(f"An unexpected error occurred listing audio devices: {e}")
        return [], []


def find_optimal_device(
    mode: str = 'input',
    preferred_index: Optional[int] = None
) -> Optional[int]:
    """
    Finds the most suitable audio device index based on user preference and system defaults.

    Args:
        mode: 'input' or 'output' specifying the device type.
        preferred_index: The user's preferred device index from configuration (e.g., config.AUDIO_INPUT_DEVICE_INDEX).
                         If None, the system default will be preferred.

    Returns:
        The index of the best matching device, or None if the intention is to use
        the system default explicitly managed by sounddevice (when preferred_index is None).
        Returns an integer index if a specific device is found and validated.
        Logs errors if no suitable device can be identified.
    """
    if mode not in ('input', 'output'):
        raise ValueError("Mode must be 'input' or 'output'")

    logger.debug(f"Attempting to find optimal {mode} device (Preferred index: {preferred_index})")

    try:
        # If preferred_index is None, the user explicitly wants the system default.
        # Let sounddevice handle this by returning None.
        if preferred_index is None:
            logger.info(f"Using system default {mode} device (requested by config).")
            return None

        devices: List[Dict[str, Any]] = sd.query_devices() # type: ignore
        kind_filter = 'max_input_channels' if mode == 'input' else 'max_output_channels'

        # Validate the preferred device index
        if 0 <= preferred_index < len(devices):
            device = devices[preferred_index]
            if device.get(kind_filter, 0) > 0:
                logger.info(f"Using configured {mode} device: [{preferred_index}] {device.get('name', 'Unknown')}")
                return preferred_index
            else:
                # The preferred device exists but doesn't support the required mode (input/output)
                logger.warning(f"Configured {mode} device index {preferred_index} ({device.get('name', 'Unknown')}) "
                               f"does not support {mode} operations. Falling back to system default.")
        else:
            # The preferred index is out of bounds
             logger.warning(f"Configured {mode} device index {preferred_index} is invalid. Falling back to system default.")


        # Fallback: Let sounddevice determine the default if the preferred device wasn't valid/found
        # Returning None achieves this.
        logger.info(f"Falling back to system default {mode} device.")
        return None

    except sd.PortAudioError as pae:
        logger.error(f"PortAudioError finding optimal {mode} device: {pae}")
        return None # Indicate failure or fallback to default handling
    except Exception as e:
        logger.exception(f"An unexpected error occurred finding optimal {mode} device: {e}")
        return None # Indicate failure or fallback to default handling


def test_audio_device(
    device_index: Optional[int] = None,
    mode: str = 'output',
    duration: float = 1.5,
    frequency: float = 440.0,
    sample_rate: int = 44100 # Use a standard rate for testing
) -> bool:
    """
    Tests an audio device by playing a tone (output) or recording briefly (input).

    Args:
        device_index: Specific device index to test. If None, tests the system default.
        mode: 'input' or 'output'.
        duration: Test duration in seconds.
        frequency: Tone frequency (Hz) for output test.
        sample_rate: Sample rate to use for the test.

    Returns:
        True if the test appears successful, False otherwise.
    """
    if mode not in ('input', 'output'):
        raise ValueError("Mode must be 'input' or 'output'")

    device_id_str = f"device {device_index}" if device_index is not None else "default device"
    logger.info(f"--- Testing {mode} on {device_id_str} ---")

    try:
        if mode == 'output':
            logger.info(f"Generating {duration:.1f}s tone at {frequency:.0f}Hz (Sample rate: {sample_rate}Hz)...")
            # Generate a sine wave tone
            t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
            tone = 0.5 * np.sin(2 * np.pi * frequency * t)  # Amplitude 0.5

            # Apply a short fade in/out to prevent clicks
            fade_duration_samples = int(sample_rate * 0.05)  # 50ms fade
            if len(tone) > 2 * fade_duration_samples:
                fade_in = np.linspace(0, 1, fade_duration_samples)
                fade_out = np.linspace(1, 0, fade_duration_samples)
                tone[:fade_duration_samples] *= fade_in
                tone[-fade_duration_samples:] *= fade_out
            else:
                 logger.warning("Test tone duration too short for full fade envelope.")


            # Convert to int16 for playback
            output_data = (tone * 32767).astype(np.int16)

            logger.info(f"Playing test tone on {device_id_str}...")
            sd.play(output_data, samplerate=sample_rate, device=device_index, blocking=True)
            sd.wait() # Ensure playback finishes
            logger.info(f"Output test on {device_id_str} completed.")
            return True

        elif mode == 'input':
            logger.info(f"Recording {duration:.1f}s from {device_id_str} (Sample rate: {sample_rate}Hz)...")

            # Record audio
            recording = sd.rec(
                frames=int(duration * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype='int16',
                device=device_index,
                blocking=True
            )
            sd.wait() # Ensure recording finishes

            if recording is not None and recording.size > 0:
                # Basic analysis: check if there's non-zero signal
                max_amplitude = np.max(np.abs(recording))
                rms_amplitude = np.sqrt(np.mean(recording.astype(np.float64)**2)) # Use float64 for rms calculation
                logger.info(f"Recording complete. Max Amplitude: {max_amplitude}, RMS Amplitude: {rms_amplitude:.2f}")
                if max_amplitude > 0: # Simple check for any signal captured
                    logger.info(f"Input test on {device_id_str} likely successful (signal detected).")
                    return True
                else:
                    logger.warning(f"Input test on {device_id_str} captured only silence.")
                    return False # Consider silence a potential issue
            else:
                logger.error(f"Input test on {device_id_str} failed: No data recorded.")
                return False

    except sd.PortAudioError as pae:
        logger.error(f"PortAudioError during {mode} test on {device_id_str}: {pae}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error during {mode} test on {device_id_str}: {e}")
        return False
    finally:
         logger.info(f"--- Finished testing {mode} on {device_id_str} ---")


# --- Main block for listing devices if run directly ---
if __name__ == "__main__":
    # Configure basic logging when run directly for utility use
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    list_audio_devices()

    # Example of testing the default output device
    # print("\nTesting default output device...")
    # test_audio_device(mode='output')

    # Example of testing the default input device
    # print("\nTesting default input device...")
    # test_audio_device(mode='input')

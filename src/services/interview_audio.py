"""
Adaptive audio capture using Silero VAD for natural speech boundaries.
Instead of fixed chunks, we detect when someone stops talking and process complete utterances.
"""
import numpy as np
import threading
import time

import sounddevice as sd
import torch

from src.config import settings
from src.utils.logger import custom_print


def list_audio_devices():
    """List available input devices. Returns list of (id, name) tuples."""
    devices = sd.query_devices()
    input_devices = []
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            input_devices.append((i, dev['name']))
    return input_devices


def select_audio_device():
    """Interactive device selection. Returns device ID or None for default."""
    devices = list_audio_devices()
    if not devices:
        custom_print("ERROR", "No input devices found!")
        return None

    print("\nAvailable microphones:")
    print("  [0] Default")
    for i, (dev_id, name) in enumerate(devices, 1):
        print(f"  [{i}] {name}")

    choice = input("\nSelect microphone [0]: ").strip()
    if not choice or choice == "0":
        return None  # Use default

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(devices):
            return devices[idx][0]  # Return device ID
    except ValueError:
        pass

    return None  # Default on invalid input


class AdaptiveAudioCapture:
    """
    VAD-based audio capture that detects speech boundaries.

    Instead of processing every N seconds:
    - Continuously buffers audio
    - Uses Silero VAD to detect speech vs silence
    - When speech -> silence transition detected, processes the utterance
    - Results in complete sentences, not cut-off chunks

    Args:
        on_utterance_callback: Called with (audio_chunk: np.array) when utterance complete
        on_level_callback: Optional, called with (level: float, is_speech: bool) for UI updates
    """

    def __init__(self, on_utterance_callback, on_level_callback=None, device_id=None):
        self.utterance_callback = on_utterance_callback
        self.level_callback = on_level_callback
        self.device_id = device_id
        self.sample_rate = settings.INTERVIEW_SAMPLE_RATE
        self.running = False

        # VAD settings
        self.speech_threshold = 0.5  # Silero confidence threshold
        self.silence_duration_ms = 350  # How long silence = end of utterance
        self.min_speech_duration_ms = 250  # Ignore very short sounds
        self.max_utterance_seconds = 30  # Cap utterance length

        # State
        self.audio_buffer = []
        self.is_speaking = False
        self.silence_samples = 0
        self.speech_samples = 0

        # Load Silero VAD
        custom_print("INFO", "Loading Silero VAD...")
        self.vad_model, self.vad_utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            trust_repo=True
        )
        (self.get_speech_timestamps, _, self.read_audio, _, _) = self.vad_utils
        custom_print("INFO", "Silero VAD loaded")

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice for each audio block."""
        if status:
            custom_print("WARNING", f"Audio status: {status}")

        audio = indata[:, 0].copy()

        # Calculate energy for level meter
        energy = np.sqrt(np.mean(audio ** 2))
        normalized_level = min(1.0, energy * 10)  # Scale for visibility

        # Run VAD on this chunk
        audio_tensor = torch.from_numpy(audio).float()
        speech_prob = self.vad_model(audio_tensor, self.sample_rate).item()

        is_speech = speech_prob > self.speech_threshold
        samples_per_ms = self.sample_rate // 1000

        # Send level update to UI
        if self.level_callback:
            self.level_callback(normalized_level, is_speech)

        if is_speech:
            # Currently speaking
            self.audio_buffer.extend(audio)
            self.speech_samples += len(audio)
            self.silence_samples = 0
            self.is_speaking = True

        elif self.is_speaking:
            # Was speaking, now silence
            self.audio_buffer.extend(audio)
            self.silence_samples += len(audio)

            silence_ms = self.silence_samples / samples_per_ms
            speech_ms = self.speech_samples / samples_per_ms

            # Check if utterance is complete
            if silence_ms >= self.silence_duration_ms and speech_ms >= self.min_speech_duration_ms:
                # Complete utterance detected
                utterance = np.array(self.audio_buffer, dtype=np.float32)
                self._reset_state()

                # Send to callback in background
                threading.Thread(
                    target=self.utterance_callback,
                    args=(utterance,),
                    daemon=True
                ).start()

        # Safety: cap max utterance length
        max_samples = self.max_utterance_seconds * self.sample_rate
        if len(self.audio_buffer) > max_samples:
            utterance = np.array(self.audio_buffer, dtype=np.float32)
            self._reset_state()
            threading.Thread(
                target=self.utterance_callback,
                args=(utterance,),
                daemon=True
            ).start()

    def _reset_state(self):
        self.audio_buffer = []
        self.is_speaking = False
        self.silence_samples = 0
        self.speech_samples = 0

    def start(self):
        """Start capturing audio."""
        self.running = True
        # Silero VAD requires exactly 512 samples at 16kHz (32ms chunks)
        block_size = 512

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            callback=self._audio_callback,
            blocksize=block_size,
            device=self.device_id
        )
        self.stream.start()
        custom_print("INFO", f"Silero VAD started (threshold: {self.speech_threshold})")

    def stop(self):
        """Stop capturing audio."""
        self.running = False
        if hasattr(self, 'stream'):
            self.stream.stop()
            self.stream.close()
        custom_print("INFO", "Audio capture stopped")


def get_audio_capture(on_utterance_callback, on_level_callback=None, device_id=None):
    """Returns Silero VAD audio capture. Requires torch."""
    return AdaptiveAudioCapture(on_utterance_callback, on_level_callback, device_id)

"""
Interview Runner - wires together assistant, display, and audio.
Uses a processing queue so AI thinking doesn't block audio capture.
"""
import time
import threading
import queue

from src.config import settings
from src.services.interview_assistant import InterviewAssistant
from src.services.interview_display import InterviewDisplay
from src.utils.logger import custom_print


def run_manual(job_data: dict | None = None):
    """Manual mode - type what you hear, get AI prompts on screen."""
    print("=" * 50)
    print("INTERVIEW ASSISTANT - MANUAL MODE")
    if job_data:
        print(f"Job: {job_data.get('title', '?')} at {job_data.get('company', '?')}")
    print("Type what interviewer says, press Enter")
    print("Prefix with 'me:' for your responses")
    print("Type 'q' to quit")
    print("=" * 50)

    assistant = InterviewAssistant(job_data)
    display = InterviewDisplay()

    def input_loop():
        time.sleep(0.5)
        while True:
            try:
                text = input("\n> ").strip()
                if text.lower() == 'q':
                    display.stop()
                    break

                is_them = not text.lower().startswith("me:")
                if not is_them:
                    text = text[3:].strip()

                # Log the input
                if is_them:
                    display.log_them(text)
                else:
                    display.log_me(text)

                display.set_speech_state('advisor')

                # Process
                hint = assistant.process_manual(text, is_them=is_them)
                display.log_advisor(hint)
                display.show_hint(hint)
                display.set_speech_state('listening')

            except (EOFError, KeyboardInterrupt):
                display.stop()
                break

    threading.Thread(target=input_loop, daemon=True).start()
    display.start()


def run_audio(job_data: dict | None = None):
    """Audio mode with async processing queue."""
    try:
        from faster_whisper import WhisperModel
        import numpy as np
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install faster-whisper")
        return

    from src.config import settings
    from src.services.interview_audio import get_audio_capture, select_audio_device

    # Load Whisper
    print(f"Loading Whisper ({settings.INTERVIEW_WHISPER_MODEL})...")
    try:
        whisper = WhisperModel(
            settings.INTERVIEW_WHISPER_MODEL,
            device=settings.INTERVIEW_WHISPER_DEVICE,
            compute_type=settings.INTERVIEW_WHISPER_COMPUTE_TYPE
        )
        print("Whisper loaded on GPU!")
    except Exception as e:
        print(f"GPU failed ({e}), trying CPU...")
        whisper = WhisperModel(settings.INTERVIEW_WHISPER_MODEL, device="cpu", compute_type="int8")
        print("Whisper loaded on CPU")

    print(f"\nModels:")
    print(f"  Sentinel: {settings.INTERVIEW_SENTINEL_MODEL}")
    print(f"  Advisor:  {settings.INTERVIEW_ADVISOR_MODEL}")

    assistant = InterviewAssistant(job_data)
    display = InterviewDisplay()

    # Processing queue - audio capture adds, processor thread consumes
    # This way AI thinking doesn't block audio capture
    utterance_queue = queue.Queue()
    processor_running = True

    def processor_thread():
        """Separate thread that processes utterances from queue."""
        while processor_running:
            try:
                audio_chunk = utterance_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            display.set_speech_state('processing')

            # Transcribe with timing
            whisper_start = time.time()
            segments, _ = whisper.transcribe(
                audio_chunk,
                language="en",
                beam_size=1,
                vad_filter=False
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            custom_print("TRANSCRIBE", f"({(time.time() - whisper_start)*1000:.0f}ms) {text[:50]}...")

            # Filter garbage
            if not text or len(text) < 3:
                display.log("(empty/short transcription)", "system")
                display.set_speech_state('listening')
                continue

            text_lower = text.lower()
            garbage = ["thank you", "thanks for watching", "goodbye", "bye", "you"]
            if any(g == text_lower or text_lower.startswith(g + ".") for g in garbage):
                display.log(f"(filtered: {text})", "system")
                display.set_speech_state('listening')
                continue

            # Log the transcription
            display.log(f"TRANSCRIPT: {text}", "system")

            # Sentinel analysis
            display.set_speech_state('sentinel')

            # Track final hint from streaming
            final_hint = {'text': ''}

            def on_hint_chunk(text_so_far):
                final_hint['text'] = text_so_far
                display.show_hint(text_so_far)

            result = assistant.process_chunk_stream(text, on_hint_chunk)

            # Log sentinel result
            custom_print("DEBUG", f"[SENTINEL] Event: {result['event']}")

            if result["action"] == "show_hint":
                display.set_speech_state('advisor')
                if result["event"] == "question":
                    display.log_them(text)
                    custom_print("INFO", f"[THEM] {text}")
                else:
                    display.log_me(text)
                    custom_print("INFO", f"[ME] {text}")
                display.log_advisor(final_hint['text'])
                custom_print("AI_OUTPUT", f"[ADVISOR] {final_hint['text']}")

            display.set_speech_state('listening')

    # Start processor thread
    proc_thread = threading.Thread(target=processor_thread, daemon=True)
    proc_thread.start()

    # Audio level callback
    current_speaking = {'value': False}

    def on_level(level: float, is_speech: bool):
        display.set_audio_level(level)
        if is_speech and not current_speaking['value']:
            current_speaking['value'] = True
            display.set_speech_state('speech')

    def on_utterance(audio_chunk):
        """Called when VAD detects complete utterance - just queue it."""
        current_speaking['value'] = False
        utterance_queue.put(audio_chunk)
        display.log(f"Utterance captured ({len(audio_chunk)/settings.INTERVIEW_SAMPLE_RATE:.1f}s)", "system")

    # Select audio device
    device_id = select_audio_device()

    # Start audio capture
    print("\nStarting audio capture...")
    audio_capture = get_audio_capture(on_utterance, on_level, device_id)
    audio_capture.start()

    display.log("System ready - listening for speech", "system")
    print("\nReady! Watch the conversation log for what's happening.")
    print("Level meter shows audio, log shows transcriptions + AI.\n")

    # Run display (blocks)
    display.start()

    # Cleanup
    processor_running = False
    audio_capture.stop()


def run_interview(job_data: dict | None = None):
    """Entry point."""
    print("\nInterview Assistant")
    if job_data:
        print(f"  Job: {job_data.get('title', '?')} at {job_data.get('company', '?')}")
    print()
    print("1. Audio mode (VAD + Whisper + AI)")
    print("2. Manual mode (type what you hear)")
    choice = input("\nSelect [1/2]: ").strip()

    if choice == "1":
        run_audio(job_data)
    else:
        run_manual(job_data)

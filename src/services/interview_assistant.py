"""
Interview Assistant - Two-tier Gemini architecture for real-time interview help.

Tier 1 (Sentinel): Flash Lite, fires every chunk, tiny prompt, detects questions/answers
Tier 2 (Advisor): Flash, fires on-demand, full CV + job context, generates hints
"""
import asyncio
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from google import genai
from google.genai import types

from src.config import settings
from src.services.cv_data import CV_FULL_TEXT, CV_SUPPLEMENTARY
from src.utils.logger import custom_print


# ---------------------------------------------------------------------------
# Conversation Buffer
# ---------------------------------------------------------------------------

@dataclass
class Utterance:
    """A single piece of speech"""
    text: str
    speaker: Literal["them", "me"]
    timestamp: datetime

    def __str__(self):
        label = "THEM" if self.speaker == "them" else "ME"
        return f"{label}: {self.text}"


class ConversationBuffer:
    """Rolling context of the conversation."""

    def __init__(self, max_utterances: int = 15):
        self.utterances = deque(maxlen=max_utterances)

    def add(self, text: str, speaker: Literal["them", "me"]):
        self.utterances.append(Utterance(
            text=text.strip(),
            speaker=speaker,
            timestamp=datetime.now()
        ))

    def get_context(self) -> str:
        if not self.utterances:
            return "[No conversation yet]"
        return "\n".join(str(u) for u in self.utterances)

    def get_recent(self, n: int = 3) -> str:
        """Get last N utterances as context."""
        recent = list(self.utterances)[-n:]
        if not recent:
            return ""
        return "\n".join(str(u) for u in recent)

    def clear(self):
        self.utterances.clear()

    def __len__(self):
        return len(self.utterances)


# ---------------------------------------------------------------------------
# Tier 1: Sentinel (lightweight, every chunk)
# ---------------------------------------------------------------------------

class Sentinel:
    """
    Lightweight model that watches the transcript stream.
    Detects when a question has been asked or when Simon finishes answering.
    No CV data, minimal prompt, fires on every audio chunk.
    """

    SYSTEM_PROMPT = """Detect interview events from transcript.

Output one of:
QUESTION: [the question]
ANSWER_DONE: [summary]
WAITING

Be conservative."""

    def __init__(self, client: genai.Client):
        self.client = client
        self.recent_text = deque(maxlen=5)  # Last few chunks for context

    async def _async_analyze(self, prompt: str) -> str:
        """Async Sentinel call."""
        response = await self.client.aio.models.generate_content(
            model=settings.INTERVIEW_SENTINEL_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.SYSTEM_PROMPT,
                temperature=0.1,
                max_output_tokens=settings.INTERVIEW_SENTINEL_MAX_TOKENS,
            )
        )
        return response.text.strip() if response.text else "WAITING"

    def analyze(self, new_chunk: str) -> dict:
        """
        Analyze new transcript chunk.
        Returns: {event: "question"|"answer"|"none", text: str}
        """
        start = time.time()
        self.recent_text.append(new_chunk)
        context = " ... ".join(self.recent_text)
        prompt = f"RECENT TRANSCRIPT:\n{context}\n\nLATEST: {new_chunk}"

        try:
            result = asyncio.run(self._async_analyze(prompt))
            elapsed = (time.time() - start) * 1000
            custom_print("SENTINEL", f"({elapsed:.0f}ms) {result}")
            return self._parse_response(result)
        except Exception as e:
            custom_print("ERROR", f"Sentinel error: {e}")
            return {"event": "none", "text": ""}

    def _parse_response(self, response: str) -> dict:
        response = response.strip()
        if response.startswith("QUESTION:"):
            return {"event": "question", "text": response[9:].strip()}
        elif response.startswith("ANSWER_DONE:"):
            return {"event": "answer", "text": response[12:].strip()}
        else:
            return {"event": "none", "text": ""}


# ---------------------------------------------------------------------------
# Tier 2: Advisor (full context, on-demand)
# ---------------------------------------------------------------------------

class Advisor:
    """
    Full-context model that generates actual hints.
    Only called when Sentinel detects a question or completed answer.
    Has access to CV, job description, and conversation history.
    """

    def __init__(self, client: genai.Client, job_data: dict | None = None):
        self.client = client
        self.job_data = job_data or {}
        self.system_prompt = self._build_system_prompt()
        # Log prompt size
        custom_print("ADVISOR", f"System prompt: {len(self.system_prompt)} chars")

    def _build_system_prompt(self) -> str:
        title = self.job_data.get('title', 'Unknown Role')
        company = self.job_data.get('company', 'Unknown Company')
        description = self.job_data.get('description', '')

        job_section = f"Interview for: {title} at {company}"
        if description:
            desc_trimmed = description[:3000]
            job_section += f"\n\nJOB DESCRIPTION:\n{desc_trimmed}"

        return f"""Output ONLY bullet points. No intro, no explanation, no "here's how".

FORMAT:
• point one
• point two
• point three

3-5 bullets max. 5-10 words each. Answer the question asked.

{job_section}

BACKGROUND:
{CV_FULL_TEXT}

{CV_SUPPLEMENTARY}"""

    def get_hint_for_question(self, question: str, conversation: str) -> str:
        """Generate hint for an interviewer's question."""
        prompt = f"""CONVERSATION:
{conversation}

QUESTION: "{question}"

Quick hint for Simon (max 2 lines):"""

        return self._call(prompt)

    def check_answer(self, answer_summary: str, conversation: str) -> str:
        """Check if Simon's answer was complete or needs correction."""
        prompt = f"""CONVERSATION:
{conversation}

SIMON JUST FINISHED ANSWERING: {answer_summary}

Did he miss anything important or make an error?
If his answer was fine, respond with just: Good
If he missed something key, tell him what to add (1 line)."""

        return self._call(prompt)

    def _call(self, prompt: str) -> str:
        """Non-streaming call - returns complete response."""
        try:
            response = self.client.models.generate_content(
                model=settings.INTERVIEW_ADVISOR_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    temperature=settings.GEMINI_TEMPERATURE,
                    max_output_tokens=settings.INTERVIEW_ADVISOR_MAX_TOKENS,
                )
            )
            result = response.text.strip() if response.text else "[empty response]"
            return result
        except Exception as e:
            return f"[Error: {e}]"

    async def _async_generate(self, user_prompt: str) -> str:
        """Async Gemini call with system_instruction."""
        response = await self.client.aio.models.generate_content(
            model=settings.INTERVIEW_ADVISOR_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=settings.GEMINI_TEMPERATURE,
                max_output_tokens=settings.INTERVIEW_ADVISOR_MAX_TOKENS,
            )
        )
        return response.text.strip() if response.text else ""

    def stream_hint(self, question: str, conversation: str, on_chunk):
        """Get hint for a question."""
        start = time.time()
        prompt = f"""QUESTION: "{question}"

CONVERSATION:
{conversation}"""

        try:
            result = asyncio.run(self._async_generate(prompt))
            elapsed = (time.time() - start) * 1000
            custom_print("ADVISOR", f"Response: {elapsed:.0f}ms, {len(result)} chars")
            on_chunk(result)
        except Exception as e:
            custom_print("ERROR", f"Advisor error: {e}")
            on_chunk(f"[Error: {e}]")

    def stream_check(self, answer: str, conversation: str, on_chunk):
        """Check answer."""
        start = time.time()
        prompt = f"""SIMON SAID: {answer}

CONVERSATION:
{conversation}"""

        try:
            result = asyncio.run(self._async_generate(prompt))
            elapsed = (time.time() - start) * 1000
            custom_print("ADVISOR", f"Response: {elapsed:.0f}ms, {len(result)} chars")
            on_chunk(result)
        except Exception as e:
            custom_print("ERROR", f"Advisor error: {e}")
            on_chunk(f"[Error: {e}]")

# ---------------------------------------------------------------------------
# Main Interview Assistant (combines both tiers)
# ---------------------------------------------------------------------------

class InterviewAssistant:
    """
    Two-tier interview assistant.

    Tier 1 (Sentinel): Runs on every transcript chunk, detects events
    Tier 2 (Advisor): Only fires when Sentinel detects question/answer

    Args:
        job_data: Dict from database with title, company, description.
                  If None, runs in generic mode.
    """

    def __init__(self, job_data: dict | None = None, warm_up: bool = True):
        api_key = settings.load_api_key_from_file("gemini_key")
        if not api_key:
            raise RuntimeError("Gemini API key not found in src/keys/gemini_key.txt")

        self.client = genai.Client(api_key=api_key)
        self.job_data = job_data or {}
        self.conversation = ConversationBuffer(max_utterances=15)

        # Two tiers
        self.sentinel = Sentinel(self.client)
        self.advisor = Advisor(self.client, job_data)

        # Track state
        self.last_hint = ""
        self.pending_question = None

        # Warm up connection
        if warm_up:
            self._warm_up()

    def _warm_up(self):
        """Warm up connection with a minimal async call."""
        async def _async_warmup():
            await self.client.aio.models.generate_content(
                model=settings.INTERVIEW_ADVISOR_MODEL,
                contents="1",
                config=types.GenerateContentConfig(max_output_tokens=1)
            )

        start = time.time()
        try:
            asyncio.run(_async_warmup())
            custom_print("INFO", f"Gemini ready: {(time.time() - start)*1000:.0f}ms")
        except Exception as e:
            custom_print("WARNING", f"Warm-up failed: {e}")

    def process_chunk(self, transcript_chunk: str) -> dict:
        """
        Process a new transcript chunk (called every 2-3 seconds from audio).

        Returns: {
            "action": "none" | "show_hint",
            "hint": str,
            "event": "question" | "answer" | "none"
        }
        """
        # Tier 1: Sentinel analyzes the chunk
        analysis = self.sentinel.analyze(transcript_chunk)
        event = analysis["event"]
        event_text = analysis["text"]

        result = {"action": "none", "hint": "", "event": event}

        if event == "question":
            # Interviewer asked a question - get a hint
            self.conversation.add(event_text, speaker="them")
            hint = self.advisor.get_hint_for_question(
                event_text,
                self.conversation.get_context()
            )
            if hint:
                self.last_hint = hint
                result["action"] = "show_hint"
                result["hint"] = hint

        elif event == "answer":
            # Simon finished answering - check if he missed anything
            self.conversation.add(event_text, speaker="me")
            hint = self.advisor.check_answer(
                event_text,
                self.conversation.get_context()
            )
            # Only show if there's actual feedback (not just "Good")
            if hint and hint.lower() not in ("good", "good.", ""):
                self.last_hint = hint
                result["action"] = "show_hint"
                result["hint"] = hint

        return result

    def process_chunk_stream(self, transcript_chunk: str, on_hint_chunk) -> dict:
        """
        Process chunk with streaming Advisor response.
        on_hint_chunk(text_so_far) called as hint generates.
        Returns same dict as process_chunk.
        """
        # Tier 1: Sentinel (not streamed - it's fast)
        analysis = self.sentinel.analyze(transcript_chunk)
        event = analysis["event"]
        event_text = analysis["text"]

        result = {"action": "none", "hint": "", "event": event}

        if event == "question":
            self.conversation.add(event_text, speaker="them")
            result["action"] = "show_hint"
            # Stream the hint
            self.advisor.stream_hint(
                event_text,
                self.conversation.get_context(),
                on_hint_chunk
            )

        elif event == "answer":
            self.conversation.add(event_text, speaker="me")
            result["action"] = "show_hint"
            # Stream the check
            self.advisor.stream_check(
                event_text,
                self.conversation.get_context(),
                on_hint_chunk
            )

        return result

    def process_manual(self, text: str, is_them: bool = True) -> str:
        """
        Manual mode - user types what they hear.
        Bypasses Sentinel, goes straight to Advisor.
        """
        speaker = "them" if is_them else "me"
        self.conversation.add(text, speaker=speaker)

        if is_them:
            hint = self.advisor.get_hint_for_question(
                text,
                self.conversation.get_context()
            )
        else:
            hint = self.advisor.check_answer(
                text,
                self.conversation.get_context()
            )
            if hint.lower() in ("good", "good."):
                hint = "Good"

        self.last_hint = hint
        return hint

    def clear(self):
        """Clear conversation history."""
        self.conversation.clear()
        self.sentinel.recent_text.clear()

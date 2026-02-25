"""
Big Text Display for Interview Assistant
High contrast, large fonts for low vision.
Shows conversation log so you can see what's being processed.
"""
import tkinter as tk
from tkinter import scrolledtext
import threading
import queue
from datetime import datetime

from src.config import settings
from src.utils.logger import custom_print


class InterviewDisplay:
    """High-contrast tkinter display with conversation log."""

    def __init__(self):
        self.message_queue = queue.Queue()
        self.running = False
        self.root = None

    def _create_window(self):
        self.root = tk.Tk()
        self.root.title("Interview Assistant")
        self.root.configure(bg=settings.INTERVIEW_DISPLAY_BG)

        screen_width = self.root.winfo_screenwidth()
        w = settings.INTERVIEW_DISPLAY_WIDTH
        h = settings.INTERVIEW_DISPLAY_HEIGHT + 200  # Taller for log
        x_position = screen_width - w - 20
        self.root.geometry(f"{w}x{h}+{x_position}+20")
        self.root.attributes('-topmost', True)

        main_frame = tk.Frame(self.root, bg=settings.INTERVIEW_DISPLAY_BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # === TOP ROW: Status + Audio level ===
        top_frame = tk.Frame(main_frame, bg=settings.INTERVIEW_DISPLAY_BG)
        top_frame.pack(fill=tk.X, pady=(0, 5))

        self.status_label = tk.Label(
            top_frame,
            text="LISTENING...",
            font=("Arial", 18, "bold"),
            fg="#888888",
            bg=settings.INTERVIEW_DISPLAY_BG,
            anchor="w"
        )
        self.status_label.pack(side=tk.LEFT)

        # Audio level bar
        self.level_canvas = tk.Canvas(
            top_frame, width=200, height=20,
            bg="#222222", highlightthickness=1, highlightbackground="#444444"
        )
        self.level_canvas.pack(side=tk.RIGHT, padx=(10, 0))
        self.level_bar = self.level_canvas.create_rectangle(2, 2, 2, 18, fill="#00FF00", outline="")

        # === CONVERSATION LOG (scrollable) ===
        log_label = tk.Label(
            main_frame, text="CONVERSATION LOG:",
            font=("Arial", 12, "bold"), fg="#666666",
            bg=settings.INTERVIEW_DISPLAY_BG, anchor="w"
        )
        log_label.pack(fill=tk.X, pady=(5, 2))

        self.log_text = scrolledtext.ScrolledText(
            main_frame,
            height=8,
            font=("Consolas", 11),
            bg="#111111",
            fg="#AAAAAA",
            insertbackground="#FFFFFF",
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.X, pady=(0, 10))

        # Configure tags for colored log entries
        self.log_text.tag_config("time", foreground="#666666")
        self.log_text.tag_config("them", foreground="#FF6B6B")
        self.log_text.tag_config("me", foreground="#6BCB77")
        self.log_text.tag_config("sentinel", foreground="#FFAA00")
        self.log_text.tag_config("advisor", foreground="#00FFFF")
        self.log_text.tag_config("system", foreground="#888888")

        # === SEPARATOR ===
        tk.Frame(main_frame, height=2, bg="#444444").pack(fill=tk.X, pady=5)

        # === AI HINT (BIG YELLOW TEXT) ===
        hint_label = tk.Label(
            main_frame, text="AI HINT:",
            font=("Arial", 14, "bold"), fg="#FFFF00",
            bg=settings.INTERVIEW_DISPLAY_BG, anchor="w"
        )
        hint_label.pack(fill=tk.X)

        # Scrollable hint area
        self.response_frame = tk.Frame(main_frame, bg=settings.INTERVIEW_DISPLAY_BG)
        self.response_frame.pack(fill=tk.BOTH, expand=True)

        # Use Text widget for scrolling
        self.response_text = tk.Text(
            self.response_frame,
            font=("Arial", settings.INTERVIEW_DISPLAY_FONT_SIZE, "bold"),
            fg=settings.INTERVIEW_DISPLAY_FG,
            bg=settings.INTERVIEW_DISPLAY_BG,
            wrap=tk.WORD,
            borderwidth=0,
            highlightthickness=0,
            state=tk.DISABLED,
            cursor="arrow"
        )
        self.response_text.pack(fill=tk.BOTH, expand=True)

        # Mouse wheel scrolling
        self.response_text.bind('<MouseWheel>', lambda e: self.response_text.yview_scroll(-1 * (e.delta // 120), 'units'))
        self.response_text.bind('<Button-4>', lambda e: self.response_text.yview_scroll(-1, 'units'))
        self.response_text.bind('<Button-5>', lambda e: self.response_text.yview_scroll(1, 'units'))

        self.root.bind('<Escape>', lambda e: self.stop())
        self.root.bind('<Configure>', self._on_resize)
        self._process_queue()

    def _on_resize(self, event):
        pass  # Handled by _on_hint_resize now

    def _on_hint_resize(self, event):
        """No longer needed - Text widget handles wrapping."""
        pass

    def _append_log(self, text: str, tag: str = "system"):
        """Append text to the conversation log."""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] ", "time")
        self.log_text.insert(tk.END, f"{text}\n", tag)
        self.log_text.see(tk.END)  # Auto-scroll
        self.log_text.config(state=tk.DISABLED)

    def _process_queue(self):
        try:
            while True:
                msg = self.message_queue.get_nowait()
                msg_type = msg.get('type')

                if msg_type == 'log':
                    self._append_log(msg.get('text', ''), msg.get('tag', 'system'))

                elif msg_type == 'response':
                    self.response_text.config(state=tk.NORMAL)
                    self.response_text.delete('1.0', tk.END)
                    self.response_text.insert('1.0', msg.get('text', ''))
                    self.response_text.config(state=tk.DISABLED)

                elif msg_type == 'status':
                    self.status_label.config(
                        text=msg.get('text', ''),
                        fg=msg.get('color', '#888888')
                    )

                elif msg_type == 'audio_level':
                    level = min(1.0, max(0.0, msg.get('level', 0)))
                    bar_width = int(level * 196)
                    color = "#00FF00" if level < 0.3 else "#FFFF00" if level < 0.6 else "#FF6600"
                    self.level_canvas.coords(self.level_bar, 2, 2, 2 + bar_width, 18)
                    self.level_canvas.itemconfig(self.level_bar, fill=color)

                elif msg_type == 'speech_state':
                    state = msg.get('state', 'listening')
                    states = {
                        'listening': ("LISTENING...", "#888888"),
                        'speech': ("SPEECH DETECTED", "#00FF00"),
                        'processing': ("TRANSCRIBING...", "#FFFF00"),
                        'sentinel': ("SENTINEL ANALYZING...", "#FFAA00"),
                        'advisor': ("ADVISOR THINKING...", "#00FFFF"),
                    }
                    text, color = states.get(state, ("...", "#888888"))
                    self.status_label.config(text=text, fg=color)

        except queue.Empty:
            pass

        if self.running:
            self.root.after(30, self._process_queue)

    # === PUBLIC API ===

    def log(self, text: str, tag: str = "system"):
        """Add entry to conversation log. Tags: them, me, sentinel, advisor, system"""
        self.message_queue.put({'type': 'log', 'text': text, 'tag': tag})

    def log_them(self, text: str):
        """Log what interviewer said."""
        self.message_queue.put({'type': 'log', 'text': f"THEM: {text}", 'tag': 'them'})

    def log_me(self, text: str):
        """Log what you said."""
        self.message_queue.put({'type': 'log', 'text': f"ME: {text}", 'tag': 'me'})

    def log_sentinel(self, text: str):
        """Log Sentinel analysis."""
        self.message_queue.put({'type': 'log', 'text': f"[SENTINEL] {text}", 'tag': 'sentinel'})

    def log_advisor(self, text: str):
        """Log Advisor response."""
        self.message_queue.put({'type': 'log', 'text': f"[ADVISOR] {text}", 'tag': 'advisor'})

    def show_hint(self, text: str):
        """Show AI hint in big text."""
        self.message_queue.put({
            'type': 'response',
            'text': text,
            'color': settings.INTERVIEW_DISPLAY_FG
        })

    def show_status(self, text: str, color: str = "#888888"):
        """Update status text."""
        self.message_queue.put({'type': 'status', 'text': text, 'color': color})

    def set_audio_level(self, level: float):
        """Set audio level (0.0 to 1.0)."""
        self.message_queue.put({'type': 'audio_level', 'level': level})

    def set_speech_state(self, state: str):
        """Set state: listening, speech, processing, sentinel, advisor"""
        self.message_queue.put({'type': 'speech_state', 'state': state})

    def start(self):
        """Start display (blocks)."""
        self.running = True
        self._create_window()
        self.root.mainloop()

    def stop(self):
        self.running = False
        if self.root:
            self.root.quit()
            self.root.destroy()

import os
import itertools
import threading
import logfire

class KeyRotator:
    def __init__(self):
        keys_str = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY", "")
        self.keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        if not self.keys:
            raise ValueError("No GROQ_API_KEYS configured.")
        self._cycle = itertools.cycle(self.keys)
        self._lock = threading.Lock()
        self.current_key = next(self._cycle)

    def get_key(self) -> str:
        with self._lock:
            return self.current_key

    def rotate_key(self) -> str:
        with self._lock:
            self.current_key = next(self._cycle)
            logfire.info(f"🔄 Rotated Groq API key to: ...{self.current_key[-6:]}")
            return self.current_key

key_rotator = KeyRotator()
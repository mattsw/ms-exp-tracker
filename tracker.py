import ctypes
import re
import sys
import time
from dataclasses import dataclass, field

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR

EXP_PATTERN = re.compile(r"^([^\[\(\|I]+?)[\[\(\|I]")
TARGET_WINDOW_KEYWORDS = ("maplestory", "ms exp tracker")


def is_target_window_focused() -> bool:
    if sys.platform != "win32":
        return True
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return False
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return False
    buf = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value.lower()
    return any(kw in title for kw in TARGET_WINDOW_KEYWORDS)


@dataclass
class ExpMetrics:
    current_exp: int = 0
    session_exp: int = 0
    session_rate_hr: float = 0.0
    current_hour_exp: int = 0
    current_hour_rate_hr: float = 0.0
    completed_hours: list[int] = field(default_factory=list)
    avg_completed_hour_exp: float = 0.0
    session_elapsed_sec: float = 0.0
    hour_elapsed_sec: float = 0.0
    paused: bool = False


class ExpTracker:
    def __init__(self, region: dict[str, int]) -> None:
        self.region = region
        # Cap ONNX threads to 1 so inference never starves Windows DWM/UI threads
        self.ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)

        now = time.monotonic()
        self.session_start = now
        self.hour_start = now

        self.last_raw_exp: int | None = None
        self.last_frame: np.ndarray | None = None
        self.session_exp = 0
        self.current_hour_exp = 0
        self.completed_hours: list[int] = []

    def _preprocess(self, raw_bgra: np.ndarray) -> np.ndarray:
        bgr = cv2.cvtColor(raw_bgra, cv2.COLOR_BGRA2BGR)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

        green_mask = cv2.inRange(hsv, (30, 80, 100), (90, 255, 255))
        green_cols = np.where(green_mask.sum(axis=0) > 0)[0]
        if len(green_cols) > 0 and green_cols[0] > 10:
            bgr = bgr[:, : green_cols[0]]

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        scaled = cv2.resize(gray, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_LANCZOS4)
        inverted = cv2.bitwise_not(scaled)
        _, clean = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.copyMakeBorder(clean, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)

    def read_exp_value(self, sct: mss.mss) -> int | None:
        raw = np.array(sct.grab(self.region))

        # Skip OCR completely if EXP bar pixels are identical to last tick
        if self.last_frame is not None and np.array_equal(raw, self.last_frame):
            return self.last_raw_exp
        self.last_frame = raw

        processed = self._preprocess(raw)
        result, _ = self.ocr(processed)
        if not result:
            return None

        combined_text = " ".join(line[1] for line in result)
        prefix = combined_text.split("[")[0]
        digits_only = re.sub(r"[^\d]", "", prefix)
        return int(digits_only) if digits_only else None

    def reset_all(self) -> None:
        now = time.monotonic()
        self.session_start = now
        self.hour_start = now
        self.last_raw_exp = None
        self.last_frame = None
        self.session_exp = 0
        self.current_hour_exp = 0
        self.completed_hours.clear()

    def tick(self, sct: mss.mss) -> ExpMetrics:
        now = time.monotonic()

        if now - self.hour_start >= 3600.0:
            self.completed_hours.append(self.current_hour_exp)
            self.current_hour_exp = 0
            self.hour_start = now

        focused = is_target_window_focused()
        if focused:
            reading = self.read_exp_value(sct)
            if reading is not None:
                if self.last_raw_exp is None:
                    self.last_raw_exp = reading
                else:
                    delta = reading - self.last_raw_exp
                    if 0 <= delta <= 100_000:
                        self.session_exp += delta
                        self.current_hour_exp += delta
                    self.last_raw_exp = reading

        session_elapsed = max(1.0, now - self.session_start)
        hour_elapsed = max(1.0, now - self.hour_start)

        session_rate = (self.session_exp / session_elapsed) * 3600.0
        hour_rate = (self.current_hour_exp / hour_elapsed) * 3600.0
        avg_completed = (
            sum(self.completed_hours) / len(self.completed_hours)
            if self.completed_hours
            else hour_rate
        )

        return ExpMetrics(
            current_exp=self.last_raw_exp or 0,
            session_exp=self.session_exp,
            session_rate_hr=session_rate,
            current_hour_exp=self.current_hour_exp,
            current_hour_rate_hr=hour_rate,
            completed_hours=list(self.completed_hours),
            avg_completed_hour_exp=avg_completed,
            session_elapsed_sec=session_elapsed,
            hour_elapsed_sec=hour_elapsed,
            paused=not focused,
        )
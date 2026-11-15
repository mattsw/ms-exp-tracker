import ctypes
import re
import sys
import threading
import time
from dataclasses import dataclass, field

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR

from window_locator import TARGET_KEYWORDS, find_game_window_rect


@dataclass
class ExpMetrics:
    current_exp: int = 0
    current_pct: float | None = None
    paused: bool = False
    session_elapsed_sec: float = 0.0
    session_exp: int = 0
    session_rate_hr: float = 0.0
    hour_elapsed_sec: float = 0.0
    current_hour_exp: int = 0
    current_hour_rate_hr: float = 0.0
    completed_hours: list[int] = field(default_factory=list)
    avg_completed_hour_exp: float = 0.0
    est_level_total_exp: int | None = None
    ttl_seconds: float | None = None


def _is_game_focused() -> bool:
    if sys.platform != "win32":
        return True
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return False
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value.lower()
    return any(kw in title for kw in TARGET_KEYWORDS) and "tracker" not in title


class ExpTracker:
    MAX_SINGLE_TICK_EXP = 100_000
    MAX_SINGLE_TICK_PCT = 2.50
    MIN_PCT_DELTA_FOR_TTL = 0.05

    def __init__(self, exp_region: dict[str, int], pct_region: dict[str, int]) -> None:
        self._lock = threading.Lock()
        self._exp_region = dict(exp_region)
        self._pct_region = dict(pct_region)
        self._ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        self._prev_exp_frame: np.ndarray | None = None
        self._prev_pct_frame: np.ndarray | None = None
        self._reset_unlocked()

    def _reset_unlocked(self) -> None:
        now = time.monotonic()
        self._session_start = now
        self._hour_start = now
        self._paused_session_sec = 0.0
        self._paused_hour_sec = 0.0
        self._pause_started_at: float | None = None

        self._baseline_exp: int | None = None
        self._last_valid_exp: int | None = None
        self._session_exp = 0
        self._current_hour_exp = 0
        self._completed_hours: list[int] = []

        self._level_anchor_exp: int | None = None
        self._level_anchor_pct: float | None = None
        self._last_valid_pct: float | None = None

    def reset_all(self) -> None:
        with self._lock:
            self._prev_exp_frame = None
            self._prev_pct_frame = None
            self._reset_unlocked()

    def _preprocess(self, bgra: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(bgra, cv2.COLOR_BGRA2GRAY)
        upscaled = cv2.resize(gray, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_LANCZOS4)
        inverted = cv2.bitwise_not(upscaled)
        _, thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return cv2.copyMakeBorder(thresh, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)

    def _ocr_text(self, processed: np.ndarray) -> str:
        result, _ = self._ocr(processed)
        if not result:
            return ""
        return "".join(item[1] for item in result)

    def _parse_exp(self, bgra: np.ndarray) -> int | None:
        raw = self._ocr_text(self._preprocess(bgra))
        digits = re.sub(r"\D", "", raw)
        return int(digits) if digits else None

    def _parse_pct(self, bgra: np.ndarray) -> float | None:
        raw = self._ocr_text(self._preprocess(bgra))
        # Strip spaces and enforce exact XX.XX or X.XX decimal match
        cleaned = raw.replace(" ", "")
        match = re.search(r"(\d{1,2}\.\d{2})", cleaned)
        if not match:
            return None
        val = float(match.group(1))
        return val if 0.0 <= val < 100.0 else None

    def _resolve_monitor(self, region: dict[str, int], win_rect: tuple[int, int, int, int] | None) -> dict[str, int] | None:
        if "rel_left" in region:
            if win_rect is None:
                return None
            return {
                "left": win_rect[0] + region["rel_left"],
                "top": win_rect[1] + region["rel_top"],
                "width": region["width"],
                "height": region["height"],
            }
        return dict(region)

    def tick(self, sct: mss.mss) -> ExpMetrics:
        now = time.monotonic()
        focused = _is_game_focused()

        with self._lock:
            if not focused:
                if self._pause_started_at is None:
                    self._pause_started_at = now
                return self._build_metrics_unlocked(now, paused=True)

            if self._pause_started_at is not None:
                paused_dur = now - self._pause_started_at
                self._paused_session_sec += paused_dur
                self._paused_hour_sec += paused_dur
                self._pause_started_at = None

            hour_active = now - self._hour_start - self._paused_hour_sec
            if hour_active >= 3600.0:
                self._completed_hours.append(self._current_hour_exp)
                self._current_hour_exp = 0
                self._hour_start = now
                self._paused_hour_sec = 0.0

            win_rect = find_game_window_rect()
            exp_mon = self._resolve_monitor(self._exp_region, win_rect)
            pct_mon = self._resolve_monitor(self._pct_region, win_rect)
            prev_exp_frame = self._prev_exp_frame
            prev_pct_frame = self._prev_pct_frame

        new_exp: int | None = None
        exp_changed = False
        if exp_mon is not None:
            exp_img = np.array(sct.grab(exp_mon))
            if prev_exp_frame is None or not np.array_equal(exp_img, prev_exp_frame):
                exp_changed = True
                new_exp = self._parse_exp(exp_img)
                with self._lock:
                    self._prev_exp_frame = exp_img

        new_pct: float | None = None
        pct_changed = False
        if pct_mon is not None:
            pct_img = np.array(sct.grab(pct_mon))
            if prev_pct_frame is None or not np.array_equal(pct_img, prev_pct_frame):
                pct_changed = True
                new_pct = self._parse_pct(pct_img)
                with self._lock:
                    self._prev_pct_frame = pct_img

        with self._lock:
            if exp_changed and new_exp is not None:
                if self._baseline_exp is None:
                    self._baseline_exp = new_exp
                    self._last_valid_exp = new_exp
                elif self._last_valid_exp is not None:
                    delta = new_exp - self._last_valid_exp
                    if 0 <= delta <= self.MAX_SINGLE_TICK_EXP:
                        self._session_exp += delta
                        self._current_hour_exp += delta
                        self._last_valid_exp = new_exp

            if pct_changed and new_pct is not None:
                if self._last_valid_pct is None:
                    self._last_valid_pct = new_pct
                    if self._last_valid_exp is not None:
                        self._level_anchor_exp = self._last_valid_exp
                        self._level_anchor_pct = new_pct
                else:
                    pct_delta = new_pct - self._last_valid_pct
                    # Level-up rollover (e.g., 99.92% -> 0.04%)
                    if self._last_valid_pct > 95.0 and new_pct < 5.0:
                        self._last_valid_pct = new_pct
                        if self._last_valid_exp is not None:
                            self._level_anchor_exp = self._last_valid_exp
                            self._level_anchor_pct = new_pct
                    elif 0.0 <= pct_delta <= self.MAX_SINGLE_TICK_PCT:
                        self._last_valid_pct = new_pct
                        if self._level_anchor_exp is None and self._last_valid_exp is not None:
                            self._level_anchor_exp = self._last_valid_exp
                            self._level_anchor_pct = new_pct

            return self._build_metrics_unlocked(time.monotonic(), paused=False)

    def _build_metrics_unlocked(self, now: float, paused: bool) -> ExpMetrics:
        extra_pause = (now - self._pause_started_at) if (paused and self._pause_started_at is not None) else 0.0
        session_elapsed = max(0.001, now - self._session_start - self._paused_session_sec - extra_pause)
        hour_elapsed = max(0.001, now - self._hour_start - self._paused_hour_sec - extra_pause)

        session_rate = (self._session_exp / session_elapsed) * 3600.0
        hour_rate = (self._current_hour_exp / hour_elapsed) * 3600.0
        avg_full = (sum(self._completed_hours) / len(self._completed_hours)) if self._completed_hours else 0.0

        est_level_total: int | None = None
        ttl_sec: float | None = None

        if (
            self._last_valid_exp is not None
            and self._last_valid_pct is not None
            and self._level_anchor_exp is not None
            and self._level_anchor_pct is not None
        ):
            d_exp = self._last_valid_exp - self._level_anchor_exp
            d_pct = self._last_valid_pct - self._level_anchor_pct
            if d_exp > 0 and d_pct >= self.MIN_PCT_DELTA_FOR_TTL:
                est_total = d_exp / (d_pct / 100.0)
                est_level_total = round(est_total)
                remaining_pct = max(0.0, 100.0 - self._last_valid_pct)
                remaining_exp = est_total * (remaining_pct / 100.0)
                if session_rate > 0:
                    ttl_sec = (remaining_exp / session_rate) * 3600.0

        return ExpMetrics(
            current_exp=self._last_valid_exp or 0,
            current_pct=self._last_valid_pct,
            paused=paused,
            session_elapsed_sec=session_elapsed,
            session_exp=self._session_exp,
            session_rate_hr=session_rate,
            hour_elapsed_sec=hour_elapsed,
            current_hour_exp=self._current_hour_exp,
            current_hour_rate_hr=hour_rate,
            completed_hours=list(self._completed_hours),
            avg_completed_hour_exp=avg_full,
            est_level_total_exp=est_level_total,
            ttl_seconds=ttl_sec,
        )
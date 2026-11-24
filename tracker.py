import ctypes
import re
import statistics
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
    MAX_SINGLE_TICK_EXP = 25_000
    MAX_SINGLE_TICK_PCT = 2.00
    MIN_SAMPLE_PCT_STEP = 0.03
    BORDER_PAD = 16

    def __init__(self, exp_region: dict[str, int]) -> None:
        self._lock = threading.Lock()
        self._exp_region = dict(exp_region)
        self._ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        self._prev_frame: np.ndarray | None = None
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
        self._pending_suspect_exp: int | None = None
        self._session_exp = 0
        self._current_hour_exp = 0
        self._completed_hours: list[int] = []

        self._last_valid_pct: float | None = None
        self._sample_anchor_exp: int | None = None
        self._sample_anchor_pct: float | None = None
        self._level_total_samples: list[float] = []

    def reset_all(self) -> None:
        with self._lock:
            self._prev_frame = None
            self._reset_unlocked()

    def _preprocess_line_crnn(self, bgr_crop: np.ndarray, pad_x: int = 16) -> np.ndarray:
        """
        Prepare a single-line crop for direct CRNN recognition (use_det=False).
        Uses the Green channel (high contrast for both white EXP digits and lime-green %)
        to suppress dark gray UI background and 1px black drop-shadows.
        """
        green = bgr_crop[:, :, 1]
        scale = 48.0 / max(1, green.shape[0])
        upscaled = cv2.resize(green, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        # Invert so bright foreground glyphs become dark strokes on a white background
        _, thresh = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return cv2.copyMakeBorder(
            thresh, 8, 8, pad_x, pad_x,
            cv2.BORDER_CONSTANT, value=255
        )

    def _rec_single_line(self, processed: np.ndarray) -> str:
        rec_res, _ = self._ocr(processed, use_det=False, use_cls=False, use_rec=True)
        if not rec_res:
            return ""
        return "".join(item[0] for item in rec_res).replace(" ", "")

    def _ocr_text_fallback(self, processed: np.ndarray) -> str:
        result, _ = self._ocr(processed)
        if not result:
            return ""
        sorted_boxes = sorted(result, key=lambda item: item[0][0][0])
        return "".join(item[1].strip() for item in sorted_boxes).replace(" ", "")

    def _find_bracket_spans(self, green_cols: np.ndarray) -> list[tuple[int, int]]:
        if green_cols.size == 0:
            return []
        spans: list[tuple[int, int]] = []
        start = int(green_cols[0])
        prev = start
        for col in green_cols[1:]:
            c = int(col)
            if c > prev + 3:
                spans.append((start, prev))
                start = c
            prev = c
        spans.append((start, prev))
        return spans

    @staticmethod
    def _extract_valid_exp_int(raw_text: str) -> int | None:
        """
        Extract integer EXP while rejecting truncated comma fragments (e.g. '6,519' from '972,479').
        If commas are present, enforce standard 3-digit grouping on trailing segments.
        """
        # Strip leading non-digit artifacts (e.g. 'EXP.' remnants)
        cleaned = re.sub(r"^[^\d]+", "", raw_text)
        m = re.match(r"^(\d[\d,]*)", cleaned)
        if not m:
            return None
        token = m.group(1).rstrip(",")
        if "," in token:
            parts = token.split(",")
            if not (1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])):
                return None
        digits = token.replace(",", "")
        return int(digits) if digits else None

    def _parse_frame(self, bgra: np.ndarray) -> tuple[int | None, float | None]:
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)

        # Upscale 4x BEFORE HSV bracket detection so 1px anti-aliased '[' and ']' never vanish
        bgr_4x = cv2.resize(bgr, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_CUBIC)
        hsv_4x = cv2.cvtColor(bgr_4x, cv2.COLOR_BGR2HSV)

        # Relaxed S/V bounds handle bilinear sub-pixel blending on stretched game windows
        green_mask = cv2.inRange(hsv_4x, np.array([35, 35, 65]), np.array([95, 255, 255]))
        col_hits = np.count_nonzero(green_mask, axis=0)
        # Require at least 20% vertical height coverage to ignore stray background pixels
        min_col_pixels = max(4, int(bgr_4x.shape[0] * 0.20))
        green_cols = np.where(col_hits >= min_col_pixels)[0]
        spans = self._find_bracket_spans(green_cols)

        if spans:
            left_bracket_start, left_bracket_end = spans[0]
            # Trim 2px inside bracket edge to avoid green bracket bleed into EXP digits
            exp_end = max(4, left_bracket_start - 2)
            exp_crop = bgr_4x[:, :exp_end]

            pct_start = min(bgr_4x.shape[1] - 1, left_bracket_end + 2)
            pct_end = (
                spans[-1][0] - 2
                if len(spans) >= 2 and spans[-1][0] > pct_start + 16
                else bgr_4x.shape[1]
            )
            pct_crop = bgr_4x[:, pct_start:pct_end]

            parsed_exp: int | None = None
            if exp_crop.shape[1] >= 12:
                proc_exp = self._preprocess_line_crnn(exp_crop, pad_x=20)
                exp_text = self._rec_single_line(proc_exp)
                parsed_exp = self._extract_valid_exp_int(exp_text)
                if parsed_exp is None:
                    # Fallback to DBNet+CRNN if single-line recognition had leading badge noise
                    fallback_text = self._ocr_text_fallback(proc_exp)
                    parsed_exp = self._extract_valid_exp_int(fallback_text)

            parsed_pct: float | None = None
            if pct_crop.size > 0 and pct_crop.shape[1] >= 16:
                proc_pct = self._preprocess_line_crnn(pct_crop, pad_x=16)
                pct_text = self._rec_single_line(proc_pct)
                pct_match = re.search(r"(\d{1,2}\.\d{2})", pct_text)
                if pct_match:
                    val = float(pct_match.group(1))
                    if 0.0 <= val < 100.0:
                        parsed_pct = val

            return parsed_exp, parsed_pct

        # Fallback if '[' bracket is completely absent
        proc_full = self._preprocess_line_crnn(bgr_4x, pad_x=20)
        full_text = self._ocr_text_fallback(proc_full)
        pct_match = re.search(r"(\d{1,2}\.\d{2})%", full_text)
        parsed_pct = None
        exp_section = full_text
        if pct_match:
            val = float(pct_match.group(1))
            if 0.0 <= val < 100.0:
                parsed_pct = val
            exp_section = full_text[: pct_match.start()]

        parsed_exp = self._extract_valid_exp_int(exp_section)
        return parsed_exp, parsed_pct

    def _resolve_monitor(self, win_rect: tuple[int, int, int, int] | None) -> dict[str, int] | None:
        if "rel_left" in self._exp_region:
            if win_rect is None:
                return None
            return {
                "left": win_rect[0] + self._exp_region["rel_left"],
                "top": win_rect[1] + self._exp_region["rel_top"],
                "width": self._exp_region["width"],
                "height": self._exp_region["height"],
            }
        return dict(self._exp_region)

    def _estimate_level_total_unlocked(self) -> float | None:
        if not self._level_total_samples:
            return None
        return float(statistics.median(self._level_total_samples))

    def _advance_hour_buckets_unlocked(self, now: float) -> None:
        hour_active = now - self._hour_start - self._paused_hour_sec
        while hour_active >= 3600.0:
            self._completed_hours.append(self._current_hour_exp)
            self._current_hour_exp = 0
            self._hour_start += 3600.0 + self._paused_hour_sec
            self._paused_hour_sec = 0.0
            hour_active = now - self._hour_start

    def _handle_level_up_unlocked(self, new_exp: int | None, new_pct: float | None) -> None:
        est_total = self._estimate_level_total_unlocked()
        if est_total is not None and self._last_valid_exp is not None:
            remainder = max(0, int(round(est_total - self._last_valid_exp)))
            if remainder <= self.MAX_SINGLE_TICK_EXP:
                self._session_exp += remainder
                self._current_hour_exp += remainder

        if new_exp is not None and new_exp <= self.MAX_SINGLE_TICK_EXP:
            self._session_exp += new_exp
            self._current_hour_exp += new_exp
            self._last_valid_exp = new_exp
        else:
            self._last_valid_exp = 0

        self._last_valid_pct = new_pct if (new_pct is not None and new_pct < 5.0) else 0.0
        self._sample_anchor_exp = self._last_valid_exp
        self._sample_anchor_pct = self._last_valid_pct
        self._level_total_samples.clear()
        self._pending_suspect_exp = None

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

            self._advance_hour_buckets_unlocked(now)

            win_rect = find_game_window_rect()
            monitor = self._resolve_monitor(win_rect)
            prev_frame = self._prev_frame

        new_exp: int | None = None
        new_pct: float | None = None
        frame_changed = False

        if monitor is not None:
            img = np.array(sct.grab(monitor))
            if prev_frame is None or not np.array_equal(img, prev_frame):
                frame_changed = True
                new_exp, new_pct = self._parse_frame(img)
                with self._lock:
                    self._prev_frame = img

        with self._lock:
            if not frame_changed:
                return self._build_metrics_unlocked(time.monotonic(), paused=False)

            pct_rolled_over = (
                new_pct is not None
                and self._last_valid_pct is not None
                and self._last_valid_pct > 95.0
                and new_pct < 5.0
            )
            # Require new_pct confirmation (< 5.0%) so a single corrupted EXP read never triggers a false level-up
            exp_rolled_over = (
                new_exp is not None
                and new_pct is not None
                and new_pct < 5.0
                and self._last_valid_exp is not None
                and self._last_valid_pct is not None
                and self._last_valid_pct > 95.0
                and new_exp < self._last_valid_exp
                and new_exp <= self.MAX_SINGLE_TICK_EXP
            )

            if pct_rolled_over or exp_rolled_over:
                self._handle_level_up_unlocked(new_exp, new_pct)
                return self._build_metrics_unlocked(time.monotonic(), paused=False)

            if new_exp is not None:
                if self._baseline_exp is None:
                    # Wait for a frame where both EXP and % parse cleanly so a truncated initial read cannot poison baseline
                    if new_pct is not None:
                        self._baseline_exp = new_exp
                        self._last_valid_exp = new_exp
                        self._sample_anchor_exp = new_exp
                elif self._last_valid_exp is not None:
                    delta = new_exp - self._last_valid_exp
                    if 0 <= delta <= self.MAX_SINGLE_TICK_EXP:
                        self._session_exp += delta
                        self._current_hour_exp += delta
                        self._last_valid_exp = new_exp
                        self._pending_suspect_exp = None
                    elif delta > self.MAX_SINGLE_TICK_EXP:
                        # Reject sudden digit-count jumps (e.g., 6,519 -> 972,479) unless confirmed across two ticks
                        if self._pending_suspect_exp == new_exp:
                            self._last_valid_exp = new_exp
                            self._sample_anchor_exp = new_exp
                            self._sample_anchor_pct = self._last_valid_pct
                            self._pending_suspect_exp = None
                        else:
                            self._pending_suspect_exp = new_exp

            if new_pct is not None:
                if self._last_valid_pct is None:
                    self._last_valid_pct = new_pct
                    self._sample_anchor_pct = new_pct
                    if self._sample_anchor_exp is None and self._last_valid_exp is not None:
                        self._sample_anchor_exp = self._last_valid_exp
                else:
                    pct_delta = new_pct - self._last_valid_pct
                    if 0.0 <= pct_delta <= self.MAX_SINGLE_TICK_PCT:
                        self._last_valid_pct = new_pct
                        if self._sample_anchor_exp is None and self._last_valid_exp is not None:
                            self._sample_anchor_exp = self._last_valid_exp
                            self._sample_anchor_pct = new_pct
                        elif (
                            self._last_valid_exp is not None
                            and self._sample_anchor_exp is not None
                            and self._sample_anchor_pct is not None
                        ):
                            step_exp = self._last_valid_exp - self._sample_anchor_exp
                            step_pct = self._last_valid_pct - self._sample_anchor_pct
                            if step_exp > 0 and step_pct >= self.MIN_SAMPLE_PCT_STEP:
                                implied_total = step_exp / (step_pct / 100.0)
                                self._level_total_samples.append(implied_total)
                                if len(self._level_total_samples) > 40:
                                    self._level_total_samples.pop(0)
                                self._sample_anchor_exp = self._last_valid_exp
                                self._sample_anchor_pct = self._last_valid_pct

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

        est_total = self._estimate_level_total_unlocked()
        if est_total is not None and self._last_valid_pct is not None:
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
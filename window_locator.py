import ctypes
import sys
from ctypes import wintypes

TARGET_KEYWORDS = ("maplestory",)


def find_game_window_rect() -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) in physical screen pixels for the game window."""
    if sys.platform != "win32":
        return None

    user32 = ctypes.windll.user32
    found_rect: tuple[int, int, int, int] | None = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_cb(hwnd: int, _: int) -> bool:
        nonlocal found_rect
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()
        if any(kw in title for kw in TARGET_KEYWORDS) and "tracker" not in title:
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                found_rect = (rect.left, rect.top, rect.right, rect.bottom)
                return False  # Stop enumeration
        return True

    user32.EnumWindows(enum_cb, 0)
    return found_rect
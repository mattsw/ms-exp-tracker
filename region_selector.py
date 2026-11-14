import ctypes
import json
import sys
import tkinter as tk
from pathlib import Path

from window_locator import find_game_window_rect

CONFIG_PATH = Path("config.json")


def enable_dpi_awareness() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()


class RegionSelector:
    def __init__(self) -> None:
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(bg="black")
        self.root.config(cursor="cross")

        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None
        self.region: dict[str, int] = {}

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda _: self.root.destroy())

    def _on_press(self, event: tk.Event) -> None:
        self.start_x, self.start_y = event.x, event.y
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#00FF66", width=2
        )

    def _on_drag(self, event: tk.Event) -> None:
        if self.rect_id is not None:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        left = min(self.start_x, event.x)
        top = min(self.start_y, event.y)
        width = abs(event.x - self.start_x)
        height = abs(event.y - self.start_y)

        if width > 10 and height > 5:
            win_rect = find_game_window_rect()
            if win_rect is not None:
                win_left, win_top, _, _ = win_rect
                self.region = {
                    "rel_left": left - win_left,
                    "rel_top": top - win_top,
                    "width": width,
                    "height": height,
                }
            else:
                self.region = {"left": left, "top": top, "width": width, "height": height}

            CONFIG_PATH.write_text(json.dumps({"exp_region": self.region}, indent=2))
        self.root.destroy()

    def run(self) -> dict[str, int]:
        self.root.mainloop()
        return self.region


if __name__ == "__main__":
    selected = RegionSelector().run()
    print(f"Saved region: {selected}")
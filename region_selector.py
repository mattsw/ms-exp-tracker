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
    STEPS = (
        {
            "key": "exp_region",
            "color": "#00FF66",
            "title": "STEP 1 OF 2: BOX RAW EXP DIGITS",
            "detail": "Drag tightly around the white integer ONLY  (e.g.,  [ 475,898 ]  — exclude '[' bracket)",
            "cursor_tag": "1/2: RAW EXP",
        },
        {
            "key": "pct_region",
            "color": "#58A6FF",
            "title": "STEP 2 OF 2: BOX DECIMAL PERCENTAGE",
            "detail": "Drag tightly around the decimal digits ONLY  (e.g.,  [ 51.74 ]  — exclude '[' and '%]')",
            "cursor_tag": "2/2: EXP %",
        },
    )

    def __init__(self) -> None:
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.30)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")
        self.root.config(cursor="cross")

        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.step_idx = 0
        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None
        self.regions: dict[str, dict[str, int]] = {}

        self.cursor_label_id = self.canvas.create_text(
            0,
            0,
            text=self.STEPS[0]["cursor_tag"],
            fill=self.STEPS[0]["color"],
            font=("Consolas", 11, "bold"),
            anchor="sw",
        )

        self.prompt_win = tk.Toplevel(self.root)
        self.prompt_win.overrideredirect(True)
        self.prompt_win.attributes("-topmost", True)
        self.prompt_win.attributes("-alpha", 0.95)
        self.prompt_win.configure(bg="#161B22", highlightbackground="#00FF66", highlightthickness=2)

        self.title_lbl = tk.Label(
            self.prompt_win,
            text=self.STEPS[0]["title"],
            fg="#00FF66",
            bg="#161B22",
            font=("Consolas", 13, "bold"),
            padx=18,
        )
        self.title_lbl.pack(pady=(10, 2))

        self.detail_lbl = tk.Label(
            self.prompt_win,
            text=self.STEPS[0]["detail"],
            fg="#E6EDF3",
            bg="#161B22",
            font=("Consolas", 10),
            padx=18,
        )
        self.detail_lbl.pack(pady=(0, 4))

        self.hint_lbl = tk.Label(
            self.prompt_win,
            text="Press ESC to cancel",
            fg="#8B949E",
            bg="#161B22",
            font=("Consolas", 9),
            padx=18,
        )
        self.hint_lbl.pack(pady=(0, 8))

        self._center_prompt_card()

        self.canvas.bind("<Motion>", self._on_move)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda _: self._cancel())
        self.prompt_win.bind("<Escape>", lambda _: self._cancel())

    def _center_prompt_card(self) -> None:
        self.prompt_win.update_idletasks()
        card_w = self.prompt_win.winfo_reqwidth()
        screen_w = self.root.winfo_screenwidth()
        x = max(20, (screen_w - card_w) // 2)
        self.prompt_win.geometry(f"+{x}+48")

    def _apply_step_ui(self, step: dict[str, str]) -> None:
        color = step["color"]
        self.prompt_win.configure(highlightbackground=color)
        self.title_lbl.config(text=step["title"], fg=color)
        self.detail_lbl.config(text=step["detail"])
        self.canvas.itemconfig(self.cursor_label_id, text=step["cursor_tag"], fill=color)
        self._center_prompt_card()

    def _cancel(self) -> None:
        self.regions = {}
        try:
            self.prompt_win.destroy()
        except tk.TclError:
            pass
        self.root.quit()
        self.root.destroy()

    def _on_move(self, event: tk.Event) -> None:
        self.canvas.coords(self.cursor_label_id, event.x + 12, event.y - 8)

    def _on_press(self, event: tk.Event) -> None:
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
        color = self.STEPS[self.step_idx]["color"]
        self.rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline=color, width=2
        )

    def _on_drag(self, event: tk.Event) -> None:
        self.canvas.coords(self.cursor_label_id, event.x + 12, event.y - 8)
        if self.rect_id is not None:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        left = min(self.start_x, event.x)
        top = min(self.start_y, event.y)
        width = abs(event.x - self.start_x)
        height = abs(event.y - self.start_y)

        if width <= 8 or height <= 4:
            return

        win_rect = find_game_window_rect()
        if win_rect is not None:
            win_left, win_top, _, _ = win_rect
            box = {
                "rel_left": left - win_left,
                "rel_top": top - win_top,
                "width": width,
                "height": height,
            }
        else:
            box = {"left": left, "top": top, "width": width, "height": height}

        step = self.STEPS[self.step_idx]
        self.regions[step["key"]] = box
        self.step_idx += 1

        if self.step_idx < len(self.STEPS):
            if self.rect_id is not None:
                self.canvas.delete(self.rect_id)
                self.rect_id = None
            self._apply_step_ui(self.STEPS[self.step_idx])
        else:
            CONFIG_PATH.write_text(json.dumps(self.regions, indent=2))
            try:
                self.prompt_win.destroy()
            except tk.TclError:
                pass
            self.root.quit()
            self.root.destroy()

    def run(self) -> dict[str, dict[str, int]]:
        self.root.mainloop()
        return self.regions


if __name__ == "__main__":
    selected = RegionSelector().run()
    print(f"Saved regions: {selected}")
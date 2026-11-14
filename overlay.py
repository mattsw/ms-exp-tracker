import tkinter as tk
from collections.abc import Callable

from region_selector import enable_dpi_awareness
from tracker import ExpMetrics, ExpTracker


class DraggableOverlay:
    def __init__(self, tracker: ExpTracker, on_reselect: Callable[[], None]) -> None:
        enable_dpi_awareness()
        self.tracker = tracker
        self.on_reselect = on_reselect

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.88)
        self.root.configure(bg="#141619")
        self.root.geometry("+20+20")

        self._drag_x = 0
        self._drag_y = 0

        self.header = tk.Frame(self.root, bg="#1F2429", cursor="fleur")
        self.header.pack(fill=tk.X)

        title = tk.Label(
            self.header, text=" MS EXP TRACKER", fg="#8AB4F8", bg="#1F2429",
            font=("Consolas", 9, "bold")
        )
        title.pack(side=tk.LEFT, padx=4, pady=2)

        close_btn = tk.Button(
            self.header, text="×", command=self.root.destroy,
            fg="#E8EAED", bg="#1F2429", bd=0, font=("Consolas", 10, "bold"),
            activebackground="#D93025", activeforeground="white"
        )
        close_btn.pack(side=tk.RIGHT, padx=4)

        for widget in (self.header, title):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)

        self.body = tk.Label(
            self.root, text="Initializing OCR...", justify=tk.LEFT,
            fg="#E8EAED", bg="#141619", font=("Consolas", 10), padx=10, pady=6
        )
        self.body.pack(fill=tk.BOTH)
        self.body.bind("<ButtonPress-1>", self._start_drag)
        self.body.bind("<B1-Motion>", self._do_drag)

        controls = tk.Frame(self.root, bg="#141619")
        controls.pack(fill=tk.X, padx=8, pady=(0, 6))

        tk.Button(
            controls, text="Reset", command=self.tracker.reset_all,
            fg="#E8EAED", bg="#2B3036", bd=0, padx=6, font=("Consolas", 8)
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(
            controls, text="Region", command=self._trigger_reselect,
            fg="#E8EAED", bg="#2B3036", bd=0, padx=6, font=("Consolas", 8)
        ).pack(side=tk.LEFT)

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event: tk.Event) -> None:
        x = self.root.winfo_x() + (event.x - self._drag_x)
        y = self.root.winfo_y() + (event.y - self._drag_y)
        self.root.geometry(f"+{x}+{y}")

    def _trigger_reselect(self) -> None:
        self.root.destroy()
        self.on_reselect()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        mins, secs = divmod(int(seconds), 60)
        hrs, mins = divmod(mins, 60)
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"

    def _format_metrics(self, m: ExpMetrics) -> str:
        hr_idx = len(m.completed_hours) + 1
        return (
            f"Raw EXP     : {m.current_exp:,}\n"
            f"Session ({self._fmt_time(m.session_elapsed_sec)})\n"
            f"  Gained    : {m.session_exp:,}\n"
            f"  Combined  : {m.session_rate_hr:,.0f} /hr\n"
            f"Hour #{hr_idx} ({self._fmt_time(m.hour_elapsed_sec)})\n"
            f"  Bucket    : {m.current_hour_exp:,} ({m.current_hour_rate_hr:,.0f}/hr)\n"
            f"  Avg Full  : {m.avg_completed_hour_exp:,.0f} /hr ({len(m.completed_hours)} done)"
        )

    def _poll(self) -> None:
        metrics = self.tracker.tick()
        self.body.config(text=self._format_metrics(metrics))
        self.root.after(1000, self._poll)

    def run(self) -> None:
        self._poll()
        self.root.mainloop()
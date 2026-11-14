# MS EXP Tracker: Passive OCR Telemetry & Window-Anchored HUD

A read-only, low-overhead Python telemetry overlay demonstrating decoupled ONNX OCR inference, Win32 window-relative coordinate anchoring, and non-blocking `tkinter` UI rendering for *MapleStory Classic World* on Windows.

## 🎯 Project Overview

This utility solves real-time experience-per-hour (`EXP/hr`) telemetry in windowed game clients without reading process memory, injecting DLLs, or sending synthetic inputs.

**Key Architectural Pillars:**
- **Zero Process Intrusion:** Captures screen pixels passively via `mss` and runs local ONNX inference via `RapidOCR`.
- **Window-Relative Coordinate Anchoring:** Resolves the game client's bounding box dynamically via Win32 `GetWindowRect`, persisting EXP offsets relative to the window origin (`rel_left`, `rel_top`) so moving or repositioning the game window never requires recalibration.
- **Multi-Layer CPU/DWM Throttling:** Eliminates system-wide UI stutter via foreground window gating (`GetForegroundWindow`), pixel-diff frame skipping (`np.array_equal`), single-threaded ONNX execution (`intra_op_num_threads=1`), and daemon worker thread offloading.
- **HSV Bracket Isolation:** Crops horizontally at the lime-green `[` delimiter in HSV color space before OCR runs, preventing percentage strings (`[18.08%]`) from concatenating onto the raw EXP integer.

## 🏗️ System Architecture

The application is decoupled into five focused modules:

1. `main.py`: Entry point managing the flat, non-nested `tkinter` lifecycle loop and `SIGINT` (`Ctrl+C`) signal handling.
2. `window_locator.py`: Win32 `EnumWindows` and `GetWindowRect` wrapper resolving physical screen coordinates for the active game window.
3. `region_selector.py`: Per-Monitor DPI-aware (`SetProcessDpiAwareness(2)`) fullscreen crosshair selector that persists window-relative offsets to `config.json`.
4. `tracker.py`: Capture, HSV bracket cropping, Otsu thresholding, pixel-diff caching, outlier filtering (`0 <= delta <= 100,000`), and rolling 60-minute bucketing engine.
5. `overlay.py`: Borderless, always-on-top, draggable `tkinter` HUD polling thread-safe metric snapshots without blocking the main UI thread.

## 🛠️ Technical Specifications

### Capture & OCR Pipeline (`tracker.py`)
- **Screen Capture:** `mss` thread-local GDI capture scoped strictly to the calibrated EXP bounding box.
- **Preprocessing:** HSV green-bracket detection (`H: 30–90, S: 80–255, V: 100–255`) $\rightarrow$ horizontal slice $\rightarrow$ `4x` `INTER_LANCZOS4` upscale $\rightarrow$ bitwise inversion $\rightarrow$ Otsu bimodal thresholding $\rightarrow$ `20px` white border padding.
- **Inference Engine:** `RapidOCR` (`rapidocr-onnxruntime`) capped at `intra_op_num_threads=1` and `inter_op_num_threads=1` to prevent Windows DWM thread starvation.

### Performance & Focus Guardrails
- **Focus Gate:** Queries `user32.GetForegroundWindow()` prior to screen capture; suspends capture and inference (`[PAUSED - UNFOCUSED]`) whenever neither *MapleStory* nor the overlay holds active focus.
- **Frame Diffing:** Compares raw BGRA arrays (`np.array_equal`) against the prior tick, bypassing ONNX inference completely when EXP numerals have not changed.

## 🚀 Getting Started

### Prerequisites
- Windows 10 or Windows 11 (Per-Monitor DPI scaling supported automatically)
- Python 3.11+ added to system `PATH`
- Git for Windows
- *MapleStory Classic World* running in **Windowed** or **Borderless Windowed** mode (`Alt+Enter`)

### Setup & Installation

1. **Clone the repository and enter the directory:**
   `git clone https://github.com/mattsw/ms-exp-tracker.git && cd ms-exp-tracker`

2. **Create a virtual environment:**
   `python -m venv .venv`

3. **Activate the virtual environment in PowerShell:**
   `.\.venv\Scripts\Activate.ps1`
   *(If PowerShell blocks script execution, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once and re-run activation.)*

4. **Install pinned dependencies:**
   `pip install -r requirements.txt`

### Running the Tracker

1. **Start the overlay** (with *MapleStory Classic World* open in Windowed mode):
   `python main.py`
   *(Zero-activation alternative from any shell: `.\.venv\Scripts\python.exe main.py`)*

2. **Calibrate the EXP region (first run only):**
   - Click and drag a tight green rectangle strictly around the white EXP digits and opening green bracket (`142,733 [18.08%]`), excluding the `EXP` label badge on the left and the progress bar border underneath.
   - Offsets save automatically to `config.json` (git-ignored).

3. **HUD Controls:**
   - **Drag HUD:** Click and drag anywhere on the `MS EXP TRACKER` title bar or metric body.
   - **Reset:** Zeroes session EXP, elapsed timers, and completed hourly buckets.
   - **Region:** Re-opens the crosshair selector to recalibrate the capture zone.
   - **× (or `Ctrl+C` in PowerShell):** Cancels scheduled `after` callbacks, stops background worker threads, and exits cleanly.

## 🔧 Troubleshooting

- **`ModuleNotFoundError` (`No module named 'cv2'` or `'mss'`):** Confirm `(.venv)` is active in your terminal (`.\.venv\Scripts\Activate.ps1`) or invoke `.\.venv\Scripts\python.exe main.py` directly.
- **Overlay hidden behind game window:** Press `Alt+Enter` inside *MapleStory* to switch from exclusive fullscreen to **Windowed** or **Borderless Windowed** mode.
- **Incorrect or truncated EXP readings:** Click **Region** on the overlay and draw a tighter box around `<digits> [` without capturing the `EXP` label on the left or bar borders below.
- **System stutter when tabbed out:** Verify `tracker.py` contains `is_target_window_focused()` and `intra_op_num_threads=1`; confirm `Raw EXP` displays `[PAUSED - UNFOCUSED]` when clicking another application.

## 📈 Future Scalability (Roadmap)

- **Persistent Session Logging:** Export completed hourly buckets and session summaries to local SQLite or CSV for historical grind-spot comparison.
- **Target Level ETA:** Parse percentage brackets (`[XX.XX%]`) into a separate secondary pipeline to compute time-to-level (`TTL`) projections.
# MS EXP Tracker: Passive OCR Telemetry & Window-Anchored HUD

A read-only, low-overhead Python telemetry overlay demonstrating independent dual-region ONNX OCR inference, Win32 window-relative coordinate anchoring, dynamic time-to-level (`TTL`) projection, and non-blocking `tkinter` UI rendering for *MapleStory Classic World* on Windows.

## 🎯 Project Overview

This utility solves real-time experience-per-hour (`EXP/hr`) and time-to-level (`TTL`) telemetry in windowed game clients without reading process memory, injecting DLLs, or sending synthetic inputs.

**Key Architectural Pillars:**
- **Zero Process Intrusion:** Captures screen pixels passively via `mss` and runs local ONNX inference via `RapidOCR`.
- **Window-Relative Coordinate Anchoring:** Resolves the game client's bounding box dynamically via Win32 `GetWindowRect`, persisting EXP and percentage offsets relative to the window origin (`rel_left`, `rel_top`) so moving or repositioning the game window never requires recalibration.
- **Multi-Layer CPU/DWM Throttling:** Eliminates system-wide UI stutter via foreground window gating (`GetForegroundWindow`), per-region pixel-diff frame skipping (`np.array_equal`), single-threaded ONNX execution (`intra_op_num_threads=1`), and daemon worker thread offloading.
- **Independent Dual-Region Capture:** Uses a guided two-step crosshair selector (`exp_region` and `pct_region`) to isolate the raw integer EXP and decimal percentage digits independently—excluding `[` and `%]` bracket characters that otherwise introduce OCR misreads—and computes exact level total EXP and remaining `TTL` without hardcoded level tables.

## 🏗️ System Architecture

The application is decoupled into five focused modules:

1. `main.py`: Entry point managing the flat, non-nested `tkinter` lifecycle loop, dual-region config loading (`exp_region` + `pct_region`), and `SIGINT` (`Ctrl+C`) signal handling.
2. `window_locator.py`: Win32 `EnumWindows` and `GetWindowRect` wrapper resolving physical screen coordinates for the active game window.
3. `region_selector.py`: Per-Monitor DPI-aware (`SetProcessDpiAwareness(2)`) two-step fullscreen selector featuring an opaque prompt HUD card and live crosshair field tag (`1/2: RAW EXP` $\rightarrow$ `2/2: EXP %`), persisting both window-relative bounding boxes to `config.json`.
4. `tracker.py`: Independent dual-region screen grabber, Otsu thresholding pipeline, per-box pixel-diff caching, single-tick outlier filtering (`0 <= delta <= 100,000` EXP and `0.00% <= delta <= 2.50%`), rolling 60-minute bucketing, and cumulative $\Delta\text{EXP} / \Delta\text{Pct}$ level-total and `TTL` projection engine.
5. `overlay.py`: Borderless, always-on-top, draggable `tkinter` HUD polling thread-safe `ExpMetrics` snapshots without blocking the main UI thread.

## 🛠️ Technical Specifications

### Capture & Dual-Region OCR Pipeline (`tracker.py`)
- **Screen Capture:** Independent `mss` thread-local GDI grabs scoped strictly to `exp_region` and `pct_region`, skipping OCR execution on whichever box has not changed pixels since the prior tick.
- **Preprocessing:** `4x` `INTER_LANCZOS4` grayscale upscale $\rightarrow$ bitwise inversion $\rightarrow$ Otsu bimodal thresholding $\rightarrow$ `20px` white border padding.
- **Inference Engine:** `RapidOCR` (`rapidocr-onnxruntime`) capped at `intra_op_num_threads=1` and `inter_op_num_threads=1` to prevent Windows DWM thread starvation.

### Dynamic Time-to-Level (`TTL`) Projection (`tracker.py`)
- **Table-Free Level Calibration:** Infers total EXP required for the active level directly from cumulative level-anchor deltas ($\text{TotalLevelEXP} = \Delta\text{EXP} / (\Delta\text{Pct} / 100)$) once $\ge 0.05\%$ EXP is gained, eliminating `0.01%` quantization noise without external lookup tables.
- **Outlier & Level-Up Rollover Guards:** Rejects single-tick percentage jumps $> 2.50\%$ to block transient OCR misreads, and automatically resets level-anchor baselines on level-up rollovers (`> 95.0%` $\rightarrow$ `< 5.0%`) while preserving continuous session `EXP/hr` metrics.

### Performance & Focus Guardrails
- **Focus Gate:** Queries `user32.GetForegroundWindow()` via `_is_game_focused()` prior to screen capture; suspends capture and timer accumulation (`[PAUSED - UNFOCUSED]`) whenever *MapleStory* loses active focus.
- **Frame Diffing:** Compares raw BGRA arrays (`np.array_equal`) independently for both capture regions, bypassing ONNX inference completely when numerals have not changed.

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

2. **Calibrate the two capture regions (first run or when clicking `Region`):**
   - **Step 1 of 2 (`1/2: RAW EXP`):** Drag a tight green box around the white raw EXP integer **only** (e.g., `475,898`), excluding the `EXP` label on the left and the `[` bracket on the right.
   - **Step 2 of 2 (`2/2: EXP %`):** Drag a tight blue box around the decimal percentage digits **only** (e.g., `51.74`), excluding the `[` and `%]` bracket characters.
   - Both window-relative offsets save automatically to `config.json` (git-ignored).
   - Once $\ge 0.05\%$ EXP is gained in the active session, `Next Lvl` transitions automatically from `Calibrating (+0.05% needed)` to `HH:MM:SS (~XXX,XXX lvl)`.

3. **HUD Controls:**
   - **Drag HUD:** Click and drag anywhere on the `MS EXP TRACKER` title bar or metric body.
   - **Reset:** Zeroes session EXP, percentage level anchors, elapsed timers, and completed hourly buckets.
   - **Region:** Launches the guided two-step crosshair selector (`Esc` cancels) to recalibrate `exp_region` and `pct_region`.
   - **× (or `Ctrl+C` in PowerShell):** Cancels scheduled `after` callbacks, stops background worker threads, and exits cleanly.

## 🔧 Troubleshooting

- **`ModuleNotFoundError` (`No module named 'cv2'` or `'mss'`):** Confirm `(.venv)` is active in your terminal (`.\.venv\Scripts\Activate.ps1`) or invoke `.\.venv\Scripts\python.exe main.py` directly.
- **Overlay hidden behind game window:** Press `Alt+Enter` inside *MapleStory* to switch from exclusive fullscreen to **Windowed** or **Borderless Windowed** mode.
- **Skewed percentage readout or `Next Lvl` stuck on `Calibrating`:** Click **Region** on the overlay and redraw both boxes tightly—ensure Step 1 captures **only** raw EXP digits and Step 2 captures **only** `XX.XX` decimal digits with zero `[` or `%]` bracket overlap.
- **System stutter when tabbed out:** Verify `tracker.py` contains `_is_game_focused()` and `intra_op_num_threads=1`; confirm `Raw EXP` displays `[PAUSED - UNFOCUSED]` when clicking another application.

## 📈 Future Scalability (Roadmap)

- **Persistent Session Logging:** Export completed hourly buckets and session summaries to local SQLite or CSV for historical grind-spot comparison.
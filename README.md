# MS EXP Tracker: Passive OCR Telemetry & Window-Anchored HUD

A read-only, low-overhead Python telemetry overlay demonstrating hybrid ONNX OCR inference (`DBNet + CRNN` for integer EXP, direct `CRNN` line recognition for percentage brackets), Win32 window-relative coordinate anchoring, dynamic time-to-level (`TTL`) projection, and non-blocking `tkinter` UI rendering for *MapleStory Classic World* on Windows.

## 🎯 Project Overview

This utility solves real-time experience-per-hour (`EXP/hr`) and time-to-level (`TTL`) telemetry in windowed game clients without reading process memory, injecting DLLs, or sending synthetic inputs.

**Key Architectural Pillars:**
- **Zero Process Intrusion:** Captures screen pixels passively via `mss` and runs local ONNX inference via `RapidOCR`.
- **Window-Relative Coordinate Anchoring:** Resolves the game client's bounding box dynamically via Win32 `GetWindowRect`, persisting EXP offsets relative to the window origin (`rel_left`, `rel_top`) so moving or repositioning the game window never requires recalibration.
- **Multi-Layer CPU/DWM Throttling:** Eliminates system-wide UI stutter via foreground window gating (`GetForegroundWindow`), pixel-diff frame skipping (`np.array_equal`), single-threaded ONNX execution (`intra_op_num_threads=1`), and daemon worker thread offloading.
- **Full-Track HSV Bracket Splitting & Direct CRNN Recognition:** Captures the full static width of the `EXP.` readout in a single box—accommodating horizontal shifts across 1-digit through 7-digit expansion and level-up resets—then isolates `[` and `]` in HSV color space to split raw EXP (`left`) from the percentage readout (`right`, processed via `use_det=False` direct CRNN recognition so narrow leading digits and `1px` decimal points never drop).

## 🏗️ System Architecture

The application is decoupled into five focused modules:

1. `main.py`: Entry point managing the flat, non-nested `tkinter` lifecycle loop, single-region config loading (`exp_region`), and `SIGINT` (`Ctrl+C`) signal handling.
2. `window_locator.py`: Win32 `EnumWindows` and `GetWindowRect` wrapper resolving physical screen coordinates for the active game window.
3. `region_selector.py`: Per-Monitor DPI-aware (`SetProcessDpiAwareness(2)`) fullscreen selector featuring an opaque prompt HUD card and live crosshair tag (`BOX FULL EXP + [XX.XX%]`), persisting the window-relative bounding box to `config.json`.
4. `tracker.py`: HSV green-bracket span detector, dual-path preprocessing (`4x` Lanczos4 for EXP digits; `48px`-normalized cubic upscale with `use_det=False` CRNN recognition for percentages), two-frame jump confirmation (`> 25,000` EXP), exact 3600s hourly bucket advancement, atomic level-up rollover handling, and trimmed-median (`statistics.median`) level-total and `TTL` projection.
5. `overlay.py`: Borderless, always-on-top, draggable `tkinter` HUD polling thread-safe `ExpMetrics` snapshots without blocking the main UI thread.

## 🛠️ Technical Specifications

### Capture & Hybrid OCR Pipeline (`tracker.py`)
- **Screen Capture:** `mss` thread-local GDI capture scoped to the full static `EXP.` track (`exp_region`), bypassing ONNX inference completely when raw BGRA pixels match the prior tick (`np.array_equal`).
- **HSV Bracket Span Isolation:** Detects lime-green `[` and `]` bracket columns (`H: 35–90, S: 80–255, V: 90–255`) to partition the frame into `exp_crop` (`< left_bracket_start`) and `pct_crop` (`left_bracket_end + 1` to `right_bracket_start`).
- **Dual Preprocessing & Inference:**
  - **Raw EXP (`exp_crop`):** Grayscale $\rightarrow$ `4x` `INTER_LANCZOS4` upscale $\rightarrow$ bitwise inversion $\rightarrow$ Otsu thresholding $\rightarrow$ `24px` white padding $\rightarrow$ full `RapidOCR` detection + recognition.
  - **Percentage (`pct_crop`):** Grayscale $\rightarrow$ `48px` target-height `INTER_CUBIC` upscale $\rightarrow$ Otsu thresholding $\rightarrow$ white padding $\rightarrow$ `RapidOCR(..., use_det=False, use_cls=False, use_rec=True)` direct line recognition (preventing DBNet bounding-box pruning on narrow `1.` prefixes).
- **Thread Throttling:** `RapidOCR` capped at `intra_op_num_threads=1` and `inter_op_num_threads=1` to prevent Windows DWM thread starvation.

### Dynamic Time-to-Level (`TTL`) & Rollover Engine (`tracker.py`)
- **Trimmed-Median Level Calibration:** Computes implied level totals ($\text{StepEXP} / (\text{StepPct} / 100)$) across valid kill increments ($\Delta\text{Pct} \ge 0.03\%$) and takes `statistics.median` over a rolling 40-sample window, preventing single-tick quantization jitter from skewing `Next Lvl`.
- **Two-Frame Jump Confirmation & Rollover Guards:** Rejects single-tick EXP spikes `> 25,000` unless confirmed identically across two consecutive frames; detects level-up rollovers (`> 95.0%` $\rightarrow$ `< 5.0%` or EXP reset at `> 95.0%`), credits remaining pre-level EXP, and resets level anchors while preserving continuous `Session` and `Hour` timers.

### Performance & Focus Guardrails
- **Focus Gate:** Queries `user32.GetForegroundWindow()` via `_is_game_focused()` prior to screen capture; suspends capture and timer accumulation (`[PAUSED - UNFOCUSED]`) whenever *MapleStory* loses active focus.

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

2. **Calibrate the full EXP track (first run or when clicking `Region`):**
   - Drag a single green rectangle starting immediately to the right of the yellow `EXP.` label and extending all the way past the closing `]` bracket up to the right edge of the EXP bar container (leaving right-side headroom so 1-digit through 7-digit numbers and `[XX.XX%]` always stay inside the box).
   - Exclude the yellow `EXP.` badge on the left and the progress bar border underneath.
   - Offsets save automatically to `config.json` (git-ignored).
   - Once $\ge 0.03\%$ EXP is gained in the active session, `Next Lvl` transitions automatically from `Calibrating (+0.05% needed)` to `HH:MM:SS (~XXX,XXX lvl)`.

3. **HUD Controls:**
   - **Drag HUD:** Click and drag anywhere on the `MS EXP TRACKER` title bar or metric body.
   - **Reset:** Zeroes session EXP, percentage level anchors, sample buffers, elapsed timers, and completed hourly buckets.
   - **Region:** Re-opens the guided fullscreen crosshair selector (`Esc` cancels) to recalibrate `exp_region`.
   - **× (or `Ctrl+C` in PowerShell):** Cancels scheduled `after` callbacks, stops background worker threads, and exits cleanly.

## 🔧 Troubleshooting

- **`ModuleNotFoundError` (`No module named 'cv2'` or `'mss'`):** Confirm `(.venv)` is active in your terminal (`.\.venv\Scripts\Activate.ps1`) or invoke `.\.venv\Scripts\python.exe main.py` directly.
- **Overlay hidden behind game window:** Press `Alt+Enter` inside *MapleStory* to switch from exclusive fullscreen to **Windowed** or **Borderless Windowed** mode.
- **Missing percentage readout or truncated digits at higher EXP counts:** Click **Region** on the overlay and draw a wider box from right after `EXP.` all the way to the right edge of the EXP container so both `[` and `]` stay inside the capture bounds across 6- and 7-digit numbers.
- **System stutter when tabbed out:** Verify `tracker.py` contains `_is_game_focused()` and `intra_op_num_threads=1`; confirm `Raw EXP` displays `[PAUSED - UNFOCUSED]` when clicking another application.

## 📈 Future Scalability (Roadmap)

- **Persistent Session Logging:** Export completed hourly buckets and session summaries to local SQLite or CSV for historical grind-spot comparison.
# Project VocalEyes

**Select with a long blink — an on-device accessibility tool for people with advanced ALS.**

VocalEyes watches the eyes with a webcam, measures how open they are with the Eye Aspect Ratio (EAR), and turns one deliberate action — closing both eyes and holding them shut — into a **Select**. Ordinary blinks are ignored. No voice, hands, head movement, or gaze target is required.

All processing runs locally on the device. No video, image, or landmark is saved or uploaded.

![Status: beta](https://img.shields.io/badge/status-beta-teal)
![Python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Licence: MIT](https://img.shields.io/badge/licence-MIT-green)

## How it works

1. **MediaPipe Face Mesh** (`refine_landmarks=True`) returns 468 facial landmarks plus 10 iris landmarks per frame.
2. **Eye Aspect Ratio** is computed for each eye from six eyelid landmarks:

   ```
   EAR = (‖p2 − p6‖ + ‖p3 − p5‖) / (2 · ‖p1 − p4‖)
   ```

   EAR is roughly 0.25–0.35 with eyes open and approaches 0 when closed. It is scale-invariant, so distance from the camera does not change the threshold.
3. **BlinkDetector** smooths the combined EAR, applies hysteresis (separate close / reopen thresholds), times closures with a monotonic clock, fires **once** per long blink, then enforces a cooldown.
4. **The overlay** shows exactly what is being tracked — eyelid contours, iris markers, per-eye EAR bars, an EAR history trace, a hold-to-select progress ring — and a large, calm confirmation banner when a selection fires.

## Quick start

```bash
pip install -r requirements.txt
vocaleyes doctor     # check this machine is ready (optional, but fast)
vocaleyes            # start tracking
```

`python -m vocaleyes` and `python vocal_eyes.py` run exactly the same code; the last of these is a thin compatibility shim, so old instructions keep working.

Keep your eyes open and relaxed for the 3-second calibration at startup, then hold both eyes closed for 1 second to select. Press `Q` to quit.

## Project layout

The code lives in the `vocaleyes/` package, one concern per module, so any piece can be read or replaced on its own:

| Module | Owns |
|---|---|
| `geometry`, `landmarks` | Pure maths and the landmark index table |
| `models` | Per-frame eye measurements |
| `detection` | The blink state machine |
| `calibration` | Per-person thresholds, and slow drift compensation |
| `tracking`, `camera` | MediaPipe, the webcam, and the background capture thread |
| `rendering` | Every pixel the user sees |
| `config`, `profiles` | Tunables, and per-person presets |
| `diagnostics`, `stats` | `vocaleyes doctor` and the session report |
| `smoothing` | EMA, medians and per-stage timing budgets |
| `logging_setup` | Text / JSON console logging |
| `cli` | The command line |

`vocal_eyes.py` at the repository root is a compatibility shim only.

## Tuning for one person (recommended)

Eyelid laxity, ptosis, glasses, and lighting all move a person's open-eye EAR, so the defaults are a starting point, not a prescription:

```bash
# Longer, gentler hold + lower threshold
python vocal_eyes.py --long-blink 1.2 --threshold 0.19 --camera 0

# Asymmetric closure (one eyelid closes much less than the other)
python vocal_eyes.py --eye-mode min

# No startup calibration; use a fixed threshold
python vocal_eyes.py --no-calibrate --threshold 0.21
```

| Option | Default | Notes |
|---|---|---|
| `--camera` | `0` | Webcam index; try `1` if no camera is found. |
| `--threshold` | `0.21` | EAR below this starts the hold timer. |
| `--long-blink` | `1.0` | Hold time (seconds) that counts as a Select. |
| `--cooldown` | `1.5` | Quiet period (seconds) after a Select. |
| `--eye-mode` | `average` | `average` (safe default) or `min` (more sensitive). |
| `--calibrate` | `3.0` | Seconds of open-eye calibration at startup. |
| `--show-mesh` | off | Draw the full face mesh (setup / debugging). |
| `--no-mirror` | off | Preview is mirrored by default, like a mirror. |
| `--profile` | — | Apply a saved profile or a shipped preset (see below). |
| `--no-drift` | off | Disable slow threshold drift compensation. |
| `--no-threaded-capture` | off | Capture on the main thread (diagnostics only). |
| `--log-level` | `info` | `quiet`, `info` or `debug`. |
| `--log-format` | `text` | `text`, or `json` for one object per line. |
| `--stats-json` | — | Write the session report to a file. Nothing is written without it. |

## Profiles

People differ, laptops are shared, and retyping flags at 7am is how mistakes happen. A profile stores the handful of settings that genuinely belong to a face:

```bash
vocaleyes profiles                     # list saved profiles and shipped presets
vocaleyes --profile glasses            # run with a preset
vocaleyes --profile mum --threshold 0.19   # a flag always wins over the file
```

Four presets ship with the package — `default`, `ptosis`, `asymmetric`, `glasses` — each with a written rationale for why its numbers are what they are. Saved profiles live in `~/.vocaleyes/profiles/` as plain JSON, so they can be copied, backed up or edited by hand. `VOCALEYES_HOME` moves that directory.

See [`docs/tuning.md`](docs/tuning.md) for what each number means and when to change it.

## Diagnostics

```bash
vocaleyes doctor           # one page: what works, what does not, what to do
vocaleyes doctor --verbose # also show the detail behind passing checks
```

Eight checks — Python, NumPy, OpenCV, MediaPipe, the webcam, the settings, camera permissions and the display — each reported as `ok`, `warn` or `FAIL` with an actionable hint. It needs no camera and no GUI, so it runs over ssh and on a machine where the dependencies are not installed yet. Exit code is `0` when nothing that matters is broken.

## Session report

Every run ends with an honest summary of what actually happened:

```
Session: 4m 12s | 612 frames | 18.4 fps avg (peak 24.1)
Selections: 7 (1.7/min) | short blinks ignored: 41
Tracking losses: 3 | camera frames dropped: 12
Threshold drift: 2 adjustments, 0.210 -> 0.216
```

Pass `--stats-json session.json` to also write that as JSON. Without the flag nothing is ever written to disk.

## Documentation

| Document | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | How the package fits together, and why the boundaries are where they are |
| [`docs/tuning.md`](docs/tuning.md) | Every tunable, what it does, and how to set it for one person |
| [`docs/privacy.md`](docs/privacy.md) | Exactly what leaves the machine (nothing), and where the boundary is |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed, in order |

## Controls

| Key | Action |
|---|---|
| `Q` / `Esc` | Quit |
| `C` | Recalibrate the EAR threshold from open eyes |
| `M` | Toggle the full face mesh |
| `R` | Reset the blink detector |

## What you see

- **Top bar** — `VOCALEYES`, live face status, FPS.
- **Eye overlays** — eyelid contour, iris ring + centre dot, rounded bounding box, and a live EAR pill above each eye. Teal = open, amber = closing/closed.
- **Bottom panel** — per-eye EAR bars with a white threshold tick, combined EAR, EAR history trace, status (`READY` / `HOLDING...` / `SELECTED`), selection count, and controls.
- **Hold ring** — a large progress ring between the eyes fills as the hold builds, with a percentage. No flashing.
- **Selection banner** — a centred `✓ SELECTED` banner, plus a console line:
  ```
  [VocalEyes] Long Blink / Select registered (#1, held 1.04s, EAR at close 0.12)
  ```
- **No face** — a large guidance message appears and tracking pauses. A tracking gap can never become a selection.

## Integrating a real action

`on_long_blink()` in `vocaleyes/hooks.py` is the single integration hook. By default it prints the confirmation above. Replace it — or pass your own callback to `main()` (`vocaleyes/cli.py`) — to drive a mouse click, a scanning keyboard, a switch press, or speech output. Keep downstream work fast and non-blocking: it runs inside the camera loop.

```python
def my_action(event, count):
    # e.g. pyautogui.click(), advance a scanning keyboard, speak, ...
    ...

raise SystemExit(main(action_callback=my_action))
```

## Design notes for advanced ALS

- **Time, not frame count.** Closure is timed with `time.monotonic()`, so slow and fast machines demand the same hold.
- **Hysteresis + smoothing.** The eye must fall below the close threshold to start timing and rise above a higher reopen threshold to end it. One noisy frame cannot start, stop, or fire a selection.
- **Once per closure.** A selection fires once, only after the full hold, and only when the eyes reopen and the cooldown passes can it fire again.
- **Face loss resets state.** If tracking is lost mid-closure, the partial hold is forgotten.
- **Calibration is passive.** The user only needs to look at the screen with eyes open; no button press or gaze target is required. Calibration uses the median open EAR, so a blink during calibration does not skew it.
- **Feedback is large and calm.** Progress and confirmation are big, high-contrast, and static — no flashing, no tiny text, no dependence on sound.

## Troubleshooting

Start with `vocaleyes doctor` — it answers most of these in one page.

| Problem | Check |
|---|---|
| `Could not open webcam` | Camera connected? Another app using it? Camera permission granted? Try `--camera 1`. |
| Webcam stops mid-session | Camera unplugged or taken over by another app; restart the script. |
| Selections fire too easily | *Lower* the threshold, raise `--long-blink`, or press `C` to recalibrate with eyes open. |
| Selections never fire | Raise `--threshold` slightly, lower `--long-blink`, or try `--eye-mode min`; recalibrate with `C`. |
| Jittery EAR / flickering state | Check lighting (avoid strong backlight), clean the lens, sit centred and still — or try `--profile glasses`. |
| The preview lags behind reality | The machine cannot keep up with face-mesh inference. Try `--width 640 --height 480`; the log will say which stage is slow. |

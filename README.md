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

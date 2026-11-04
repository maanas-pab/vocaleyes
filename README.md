# Project VocalEyes

**Select with a long blink — an on-device accessibility tool for people with advanced ALS.**

VocalEyes watches the eyes with a webcam, measures how open they are with the Eye Aspect Ratio (EAR), and turns one deliberate action — closing both eyes and holding them shut — into a **Select**. Ordinary blinks are ignored. No voice, hands, head movement, or gaze target is required.

All processing runs locally on the device. No video, image, or landmark is saved or uploaded.

![Status: core module](https://img.shields.io/badge/status-core%20module-teal)

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
python vocal_eyes.py
```

Keep your eyes open and relaxed for the 3-second calibration at startup, then hold both eyes closed for 1 second to select. Press `Q` to quit.

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

`on_long_blink()` in `vocal_eyes.py` is the single integration hook. By default it prints the confirmation above. Replace it — or pass your own callback to `main()` — to drive a mouse click, a scanning keyboard, a switch press, or speech output. Keep downstream work fast and non-blocking: it runs inside the camera loop.

```python
def my_action(event, count):
    # e.g. pyautogui.click(), advance a scanning keyboard, speak, ...
    ...

raise SystemExit(main(action_callback=my_action))
```


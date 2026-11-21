# Tuning

Every number VocalEyes uses, what it does, how to set it for one person,
and what happens when it is wrong.

Tune **once per person**, during setup, then leave it alone. A threshold
that moves every session is a threshold nobody trusts.

## The two numbers that matter

### `--threshold` (EAR close threshold, default `0.21`)

The Eye Aspect Ratio below which the hold timer starts. This is the whole
sensitivity dial.

| | |
|---|---|
| **Too low** | Selections never fire. The user holds, nothing happens, and they stop trying. |
| **Too high** | Selections fire on ordinary blinks or just sitting with relaxed eyes. For this audience a false selection is the worse failure — it is why the default sits well below the measured open EAR. |
| **How to set it** | Press `C` and have the person sit still with eyes open and relaxed for the 3 seconds. Calibration uses the *median*, so blinking during it does not skew the result. |

The calibrated value is `clamp(median open EAR × 0.70, 0.12, 0.28)`. The
0.70 factor is the gap between "relaxed open" and "starting to close"; the
band stops an odd lighting setup from producing a threshold that fires on
open eyes.

### `--long-blink` (hold time, default `1.0` s)

How long both eyes must stay shut to count as a Select.

| | |
|---|---|
| **Too short** | A real blink (150–300 ms) becomes a selection. |
| **Too long** | Deliberate, accurate users cannot hold that long — eyelid fatigue is real for the people this is for. |
| **How to set it** | Start at 1.0. If the user blinks heavily or has tremor, go to 1.2–1.3. Never go below 0.6. |

Timing uses a monotonic clock, so the same value means the same hold on a
fast laptop and a ten-year-old desktop.

## The supporting cast

| Flag | Default | What it does | Change it when… |
|---|---|---|---|
| `--cooldown` | `1.5` s | Quiet period after a selection, before another can fire. | One long closure is firing twice → raise it. The user is quick and wants rapid consecutive selections → lower it, never below 0.5. |
| `--eye-mode` | `average` | How the two eyes combine: mean, or the smaller of the two. | One eyelid closes far less than the other → `min`, so the stronger closure drives the signal. Note `min` is more sensitive to a wink. |
| `--ear-smoothing` via config | `0.35` | EMA weight on the EAR stream. Higher is smoother but slower. | The EAR trace is hairy and the state flickers → raise it toward `0.5`. The user's holds feel sluggish → lower it. |
| `--calibrate` | `3.0` s | Seconds of open-eye sampling at startup. | The person cannot hold still for 3 seconds → shorten it, or use `--no-calibrate --threshold N`. |
| `--camera` | `0` | Webcam index. | No picture → try `1`, then `2`. |
| `--width` / `--height` | `1280×720` | Requested capture size. | The log warns about the frame budget → drop to `640×480`. Detection barely changes; the cost is in inference on the full frame. |
| `--no-mirror` | off | Un-mirror the preview. | Only if the mirrored preview is disorienting. Mirrored feels natural for setup, like a mirror. |
| `--show-mesh` | off | Draw the full 468-point face mesh. | Setting up, or checking whether the camera actually sees the eyes. Leave it off in use — it is visual noise. |

## Presets


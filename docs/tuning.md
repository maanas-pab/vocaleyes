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


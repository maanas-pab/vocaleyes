#!/usr/bin/env python3
"""Project VocalEyes — long-blink selection for people with advanced ALS.

A single-file, on-device eye-tracking module. A webcam frame is passed
through MediaPipe Face Mesh, the Eye Aspect Ratio (EAR) of each eye is
measured, and a sustained bilateral eye closure is turned into one
deliberate action: a **Long Blink / Select**.

Why this design matters for advanced ALS
----------------------------------------
* **One reliable input, no voice / hands / head movement required.**
  Selection needs only the ability to close both eyes and hold them
  shut. Nothing else on screen has to be looked at, dwelled on, or
  pointed to.
* **Time, not frame count.** Closure is timed with a monotonic clock,
  so a slow laptop and a fast laptop demand the same 1-second hold.
* **Hysteresis + smoothing.** The eye must fall below a close
  threshold to start timing and rise above a slightly higher open
  threshold to end it. A single noisy frame cannot start, stop, or
  fire a selection.
* **Ordinary blinks are ignored.** A normal 0.1–0.4 s blink ends long
  before the hold threshold, so it never selects. Only a deliberate

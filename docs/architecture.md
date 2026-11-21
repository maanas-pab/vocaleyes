# Architecture

VocalEyes is a straight line from webcam to selection, with one deliberate
loop in the middle. This document says what each layer owns, why the
boundaries sit where they do, and what must never cross them.

## The pipeline

```
   CameraStream ──► FramePump ──► FaceMeshTracker ──► extract_eye_readings
   (webcam)        (thread)       (MediaPipe)        (models)
                                                          │
                                                          ▼
                                    EarCalibrator ──► BlinkDetector ──► event
                                    ThresholdDrift        │              │
                                                          ▼              ▼
                                                     Visualizer    on_long_blink
                                                     (overlay)     (your code)
```

One frame enters at the top and either produces a `BlinkEvent` or does not.
Nothing else in the system can produce a selection: not the renderer, not
the calibrator, not a key press.

## Layers

### Pure maths — `geometry`, `landmarks`

Points in, numbers out. No camera, no clock, no globals. `calculate_ear()`
is the whole product in one formula, so it gets its own guards (a
zero-width eye returns `0.0` rather than raising — one bad frame must never
crash the tracker).

`landmarks.py` holds every MediaPipe index VocalEyes depends on, in one
table with the reason each index exists. Changing webcam or MediaPipe
version means re-checking numbers here, never touching detection code.

### Measurement — `models`

`EyeReading` and `FaceReading` are the per-frame facts: six eyelid points
per eye, the EAR, the combined EAR, the bounding box. They carry no
policy — they do not know what a threshold is.

### Policy — `detection`, `calibration`

`BlinkDetector` owns the state machine:


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


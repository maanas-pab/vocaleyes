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

```
        ear < close_threshold            hold >= long_blink
  OPEN ─────────────────────► CLOSED ────────────────────► TRIGGERED
   ▲                            │                               │
   │       ear >= open_thresh   │  ear >= open_threshold        │
   │       (short: ignored)     ▼                               ▼
   └──────────────────────────────────────  COOLDOWN  ◄─────────┘
```

Three rules are non-negotiable and are why the machine looks the way it does:

- **Hysteresis.** Closing needs `ear < close_threshold`; reopening needs
  `ear >= close_threshold + 0.04`. Jitter around one number cannot flutter
  the state.
- **Time, not frames.** Closures are timed with `time.monotonic()`, so a
  slow machine demands exactly the same hold as a fast one.
- **Face loss resets.** A tracking gap is not a closure. `reset()` forgets
  any partial hold, so missing the face for 200 ms can never complete a
  selection that was 800 ms in.

`EarCalibrator` measures open eyes for a few seconds at startup and sets
`threshold = clamp(median × 0.70, 0.12, 0.28)`. `ThresholdDrift` applies
the *same* rule slowly during a session, but only ever moves the threshold
a few thousandths at a time, at most once every 45 seconds, and never while
the eyes are closed. The comment in `calibration.py` that says the two must
not silently diverge is load-bearing: if someone changes one formula they
must change both.

### Acquisition — `tracking`, `camera`

`FaceMeshTracker` is a thin, stateless wrapper over MediaPipe.
`CameraStream` owns the `cv2.VideoCapture` handle and raises `CameraError`
with an actionable message instead of a bare traceback.

`FramePump` runs `read()` on a daemon thread and keeps **one** frame: the
newest. A queue would grow without bound whenever inference is slower than
the camera, so latency would creep up forever; a single slot bounds
end-to-end latency to about one frame period, and the `dropped` counter
makes that trade-off visible rather than silent. The `error` attribute
carries a `CameraError` out of the thread — a worker must never raise into
the void.

### Presentation — `rendering`

Every pixel the user sees, and no logic. The renderer reads detector state
and draws it; it cannot change it. Feedback is deliberately large, calm
and static — no flashing, no tiny text, no dependence on sound.

### Wiring — `config`, `profiles`, `cli`

`Config` is the single source of tunable truth, with validation in
`__post_init__` so a bad value fails at construction, not mid-session.
`profiles` overlays a short list of per-person fields onto a `Config`;
`cli` turns flags into a `Config`, then wires camera → tracker → detector →
renderer, and loops.

`cli` is the only module allowed to talk to `argparse` and `sys.exit`.

### Support — `smoothing`, `logging_setup`, `diagnostics`, `stats`

Neither knows about the others. `smoothing` is signal processing you can
reason about without a webcam; `logging_setup` decides how the console
looks; `diagnostics` answers "will this machine run"; `stats` counts what
happened and renders it at the end.

## Threading

Exactly one thread does work: `FramePump`'s capture thread. Everything else
— inference, state machine, rendering — runs on the main thread in a single
loop. That is on purpose. A selection is a medical-adjacent event; a
race condition that fires one is unacceptable, and the loop is already
I/O-bound on the camera rather than CPU-bound on the state machine.

The hand-off between threads is one `Lock`-guarded slot holding one frame.

## Error handling

Two failure modes are worth naming, and `errors.py` names them: no camera,
and no missing dependency. Both raise a specific exception with an
instruction, because the person running this may be a carer, not a
programmer. Everything else that can fail mid-frame is caught at the frame
boundary — a check in `diagnostics` that crashes becomes a `FAIL` line, not
a traceback.

## Extension points

| Want to… | Touch |
|---|---|
| Drive a mouse, switch, or speech | `hooks.on_long_blink`, or pass `action_callback=` to `main()` |
| Change what a selection looks like | `rendering` |
| Add a per-person tunable | `config.Config`, then `profiles.PROFILE_FIELDS` if it is per-person |
| Support a new camera | `camera.CameraStream` |
| Report a new health signal | `stats.SessionStats` |

The one rule for anything downstream of `on_long_blink`: **it runs inside
the camera loop.** Keep it fast and non-blocking, or hand the work to a
queue and return.

## Import discipline

`vocaleyes/__init__.py` is deliberately cheap. OpenCV and MediaPipe are
only touched when something actually needs them (see `deps.py`), and the
heavy entry points are exposed lazily via PEP 562 `__getattr__`. That is
why `import vocaleyes`, `vocaleyes --help` and `vocaleyes doctor` all work
on a machine where the vision stack has not been installed yet.

Relative imports only; no module imports `cli`, so nothing can form a cycle
with the entry point.

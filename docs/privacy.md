# Privacy

**Nothing leaves this machine.** Not frames, not images, not landmarks,
not EAR values, not logs. VocalEyes has no network code — there is no HTTP
client in the package, and no telemetry, no analytics, no crash reporting.

This matters more here than in most tools. VocalEyes is used by people with
advanced ALS and by the carers around them, in their own homes, in front of
their own webcam. A face is biometric data. Treating it as anything other
than local is a failure, not a feature.

## What VocalEyes reads

| Read | Where it goes |
|---|---|
| Webcam frames | Memory, for the duration of one frame |
| Facial landmarks | Memory, for the duration of one frame |
| Eye Aspect Ratio | Memory, and the on-screen overlay |

Frames are handed from the capture thread to the loop, processed, drawn,
and dropped. The `FramePump` keeps exactly **one** frame at a time, on
purpose — there is no buffer accumulating history behind the scenes.

## What VocalEyes writes

| Write | When |
|---|---|
| Nothing | **Default.** Running `vocaleyes` writes no files at all. |
| Console log lines | Only when you ask (`--log-level`, `--log-format`) |
| Session report JSON | Only when you pass `--stats-json PATH` |
| Profile JSON | Only when you save a profile |

Each of these is an explicit, separate opt-in. There is no default file
path, no "just in case" save, and no periodic flush.

### The session report


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

`--stats-json` writes **numbers only**: frame counts, FPS, how many
selections, how many tracking losses, how much the threshold drifted, and
UTC timestamps for the start and end. It contains no image data, no
landmarks, no EAR trace, and nothing that identifies the person. Schema:
`vocaleyes.session.v1`.

### Profiles

`~/.vocaleyes/profiles/*.json` holds tuning numbers — a threshold, a hold
time, a camera index, an optional free-text note you wrote yourself. No
biometric data. If you put a name in `name`, that is your choice; the
field is yours to blank.

`VOCALEYES_HOME` moves this directory somewhere you control (an encrypted
volume, a USB stick you carry with you).

### Logs

Logs go to the **local console** (stderr) and nowhere else. VocalEyes
never opens a log file, never rotates one, and never attaches a network
handler. `--log-format json` is for a carer's local tooling to parse, not
for shipping anywhere.

## What it does not do

- Record video or audio
- Save screenshots or face crops
- Store landmarks, EAR traces, or blink histories
- Upload anything, ever — including "anonymised" or "aggregated" data
- Phone home for updates, models, or crash reports
- Use cloud APIs of any kind

The MediaPipe face-mesh model runs locally. No inference service is
contacted.

## The boundary, and where it is yours

The guarantee above covers code in this repository. It does **not** cover:

- **Your callback.** `on_long_blink()` is your code. If you make it click
  a button in a web app, whatever that app does is outside this boundary.
  Keep the boundary explicit in whatever you build on top.
- **Your OS.** macOS TCC, Windows camera privacy and your desktop
  environment have their own rules about who may see the camera.
  `vocaleyes doctor` reports where those settings live on your platform.
- **Your environment.** If you run VocalEyes inside a container, a VM or
  over a forwarded display, the video is already somewhere else before it
  reaches us.

## If that ever changes

It should not. If a future version adds any network capability, it must be
off by default, opt-in, documented in the changelog, and reflected in this
file — and the default answer to "does VocalEyes send anything" should
still be no.

## Reporting a concern

Open an issue describing what you observed. Privacy defects here are bugs
like any other, and ones that touch the camera or the network are the
highest priority this project has.

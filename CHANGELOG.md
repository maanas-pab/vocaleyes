# Changelog

All notable changes to Project VocalEyes are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [1.0.0] — 2026-11-19

First packaged release. The behaviour is the same as the original single
file; the difference is that it can now be installed, configured, diagnosed
and extended without reading 1,271 lines first.

### Added

- **The `vocaleyes` package.** The single `vocal_eyes.py` module is split by
  concern into fifteen modules — `geometry`, `landmarks`, `models`,
  `detection`, `calibration`, `tracking`, `camera`, `rendering`, `hooks`,
  `config`, `profiles`, `diagnostics`, `stats`, `smoothing`,
  `logging_setup` and `cli`. `vocal_eyes.py` remains as a compatibility
  shim, so every documented invocation keeps working.
- **Packaging.** `pyproject.toml` with a `vocaleyes` console script, declared
  dependencies, and an MIT `LICENSE`. `pip install .` gives you `vocaleyes`.
- **`vocaleyes doctor`.** Eight checks — Python, NumPy, OpenCV, MediaPipe,
  webcam, settings, camera permissions, display — reported as `ok`, `warn`
  or `FAIL` with an actionable hint each. Runs without a camera and without
  a GUI. Exit code `0` unless something that matters is broken.
- **Profiles and presets.** `--profile NAME` applies a saved profile or a
  shipped preset. Four presets ship with the package — `default`, `ptosis`,
  `asymmetric`, `glasses` — each with a written rationale. Profiles are
  plain JSON in `~/.vocaleyes/profiles` (`VOCALEYES_HOME` overrides), so
  they can be hand-edited and copied between machines.
- **Session report.** Every run ends with frames, average and peak FPS,
  selections per minute, ignored short blinks, tracking losses, dropped
  camera frames and threshold drift. `--stats-json PATH` writes it as JSON;
  without that flag nothing is written to disk.
- **Background capture.** `FramePump` reads the webcam on a daemon thread
  and keeps only the newest frame, so slow face-mesh inference cannot make
  the preview fall seconds behind reality. `--no-threaded-capture` restores
  the old single-threaded read for diagnosis.
- **Threshold drift compensation.** `ThresholdDrift` slowly re-centres the
  threshold on the measured open-eye EAR over a long session — rate-limited,
  capped, and blind to closed eyes. Off by default; `--no-drift` keeps it
  off explicitly.
- **Signal conditioning.** `smoothing.Ema` and `smoothing.MedianFilter`
  for the EAR stream, and `smoothing.StageTimer` for per-stage frame
  accounting (capture / inference / render) against a millisecond budget.

"""Camera handling for Project VocalEyes.

A context-managed webcam that fails with clear, actionable messages,
because a missing or busy camera is the most common first-run failure
for an accessibility tool. Capture also runs on a background pump, so
slow inference never backs up the camera buffer or ages the image on
screen.

"""Lazy, forgiving imports of the two heavy dependencies.

OpenCV and MediaPipe are imported here inside ``try/except`` so that
``import vocaleyes`` — and therefore ``vocal_eyes --help``,
``--version`` and any documentation tooling — still works on a machine
where they have not been installed yet. Nothing else in the package
imports ``cv2`` or ``mediapipe`` directly; they come from this module,
along with :func:`check_dependencies`, which turns a missing wheel into
an instruction instead of a traceback.
"""


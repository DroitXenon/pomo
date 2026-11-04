# Stack choices

`environment.yml` defines the `pomo` Conda environment with Python 3.13 and pip.
The existing application, transitive and test package versions are preserved in
its `pip` section. Conda resolves the Python 3.13 patch version and pip version.

| Selected | Reason | Alternative considered |
| --- | --- | --- |
| Python 3.13 + FastAPI | HTTP, WebSocket, validation and Python perception integration | Flask requires an additional WebSocket integration |
| Uvicorn + websockets | Standard ASGI and WebSocket transport | Hand-written sockets add unnecessary protocol work |
| Plain HTML/CSS/JS | Small interface without a frontend build toolchain | React adds tooling; Gradio is useful for model demos but offers less direct control of this robot UI and transport |
| python-dotenv | Simple local configuration; environment variables override file values | Shell-only configuration is less convenient |
| pytest + HTTPX | Tests actual HTTP and WebSocket routes | State-only tests miss protocol errors |

Official reference: https://fastapi.tiangolo.com/advanced/websockets/

Conda environment format: https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html#creating-an-environment-file-manually

No Node runtime, database or external fonts are required.

Camera foundation uses `opencv-contrib-python==5.0.0.93` and `mediapipe==1.2.0`.
Only one OpenCV distribution is installed; MediaPipe already depends on contrib.
Pillow validates JPEG headers before OpenCV allocates the decoded image. NumPy,
Pillow and the camera-processing Python dependencies are pinned in `environment.yml`.
Linux EGL/GLES native libraries are declared using CEP-24 comment selectors;
recent Conda uses `--format cep-24` (previously verified with Conda 26.9.4). The setup script also supports Conda 25 by removing Linux-only entries from a temporary copy on other platforms, keeping `environment.yml` as the dependency source.

A Windows browser owns getUserMedia capture and the direct video preview. WSL
receives sequential bounded JPEG HTTP uploads; it does not need camera passthrough.
One dedicated worker initializes the model, decodes frames and closes the model.
MediaPipe Face Landmarker emits presence, head-pose and selected blendshape
diagnostics. A separate deterministic policy handles sustained absence. Quality
heuristics gate unusable frames; head direction and expressions do not remind.
The model manifest is in
`models/README.md`; setup verifies its fixed revision and checksum.

UI choices do not commit the firmware to a browser stack.

Face Landmarker uses the Tasks API with VIDEO mode and strictly increasing
worker timestamps, with blendshapes and transformation matrices enabled. Model
confidence options are thresholds rather than fabricated output confidence scores.
Reference: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python


Coarse per-eye direction uses the iris rings and eye contours from the same face
mesh. Eye-local axes normalize position and account for head roll. Blink/geometry
checks and a head-angle limit keep unavailable measurements unknown. Detected closure reports closed per eye.
The UI shows continuous normalized blink scores, independently of eye direction
labels. The API retains raw MediaPipe blendshape coefficients. No additional
model or dependency is required. The UI groups eye directions/blinks and mouth
movement separately. Iris positions are diagnostic observations rather than gaze
coordinates or distraction scores.
Landmark reference: https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/python/solutions/face_mesh_connections.py


Vertical eye direction uses iris displacement relative to the eye-corner line,
normalized by eye width. Lid-relative position remains a diagnostic. Qualified
Face Landmarker eyeLookUp/eyeLookDown coefficients corroborate smaller excursions;
coefficients cannot independently override centered or opposite geometry. Detection
details exposes corner-relative offsets and raw coefficients for webcam evaluation.


The integrated v7 transport uses one `ReminderEngine` for camera and simulated
input. A camera adapter normalizes fresh model observations and applies stable-face
and tracking-loss gates. `backend/behaviour.py` retains the previous standalone
camera policy for historical regression tests; the live application does not run
a second reminder policy. `backend/policy.py` owns all reminder IDs, cooldown,
dismissal, power, mute and display transitions.

While monitoring, backend behavior selects the robot expression. Development
previews are available only while powered on and paused. Raw head/eye/mouth data
remain diagnostics and cannot independently trigger reminders. Protocol v7 replaces
both prior branch contracts; update browser and backend together.

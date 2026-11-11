# CoreS3 display test and future adapter

`pomostack/` is a standalone PlatformIO project for the M5Stack CoreS3. Its
M5Unified sketch draws a static black-and-white face. Open `firmware/pomostack`
as a VS Code folder and use PlatformIO's Build and Upload actions. Uploading
replaces the program currently on the device.

This is a display test. It does not capture camera frames, exchange messages
with the Python backend or implement device controls. Map backend state to the
physical display and physical buttons to commands in a later task; see
../docs/protocol.md. The user confirmed the static face appeared on the CoreS3;
the future USB transport still needs validation. The browser face is a
placeholder, not an LVGL simulation.

`camera-test/` is a separate CoreS3 camera preview, based on the
[M5Stack camera configuration](https://docs.m5stack.com/en/arduino/m5cores3/camera).
Open that folder in VS Code
as a PlatformIO project, build it and upload it to show live camera frames on
the CoreS3 screen. If initialization fails, the sketch shows an error instead
of attempting to use the camera. The preview is not sent to Pomo or saved.
Uploading replaces the current device program; open `pomostack/` and upload it
again to restore the face test.

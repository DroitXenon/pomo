# CoreS3 firmware

## Robot adapter

`robot-adapter/` is the physical Pomo: face, voice and camera. It reads one JSON
line per display change from the backend over USB serial (format in
[../docs/protocol.md](../docs/protocol.md#robot-display-serial)) and draws the five
expressions in black and white with M5Unified: happy, surprised, crying `sad` with
animated tears, bored and idle. Each new reminder is spoken through the CoreS3
speaker unless sound is muted; the browser stays silent while the robot is
connected. With no message for 6 seconds the device shows the bored face and
"No link". When the backend selects the Robot camera input, a background task
streams 320x240 JPEG frames (about 5 per second) back over the same cable; a small
dot in the top-right corner shows the camera is in use. Frames are not stored or
shown on the robot. "No camera" in the top-left corner means the camera failed to
start; reset the robot.

The sketch uses the TinyUSB serial driver (`ARDUINO_USB_MODE=0`) because the
default USB-Serial-JTAG driver in Arduino-ESP32 2.0.x loses bytes at camera data
rates. Two consequences:

- The serial port is named after the board's serial number, for example
  `/dev/cu.usbmodem7C4FADAF80EC1`, and stays the same in any USB socket. Update
  `POMO_SERIAL_PORT` after the first upload.
- Uploads reset the board with a 1200-baud touch, and `tools/after_upload.py`
  restarts it into the new firmware. If an upload cannot find the board, hold the
  reset button for about 3 seconds (green LED) and upload again.

The camera takes over the CoreS3's internal I2C bus, so the sketch starts the
speaker first and does not poll touch or the power button (`M5.update()`).

The spoken sentences are recorded clips in `include/clips.h` (about 3.6 s each,
16 kHz mono, macOS voice "Flo (English (UK))"). They are generated from
`REMINDER_MESSAGES` in `backend/policy.py`, so after changing that text run the
following and upload again (a test fails if the clips are out of date):

```sh
conda run --name pomo python firmware/robot-adapter/tools/make_clips.py
conda run --name pomo python firmware/robot-adapter/tools/make_clips.py --voice "Daniel (English (UK))"   # another voice
```

1. Open `firmware/robot-adapter` in VS Code with PlatformIO, or run `pio run -t upload`
   in that folder, with the CoreS3 connected by USB. Uploading replaces the current
   program.
2. Find the port (`ls /dev/cu.usbmodem*` on macOS) and close any serial monitor.
3. Start the backend with that port, for example
   `POMO_SERIAL_PORT=/dev/cu.usbmodem1101 sh scripts/dev.sh`, then enable monitoring
   in the simulator.

`pio run` builds the sketch without a device.

## Display test

`display-test/` is a standalone PlatformIO project for the M5Stack CoreS3. Its
M5Unified sketch draws a static black-and-white face. Open `firmware/display-test`
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
Uploading replaces the current device program; open `display-test/` and upload it
again to restore the face test.

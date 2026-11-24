# CoreS3 firmware

## Robot adapter

`robot-adapter/` is the physical Pomo face. It reads one JSON line per display
change from the backend over USB serial (format in
[../docs/protocol.md](../docs/protocol.md#robot-display-serial)) and draws the five
expressions in black and white with M5Unified: happy, surprised, crying `sad` with
animated tears, bored and idle. A new reminder ID plays a short chime when sound is
not muted; the laptop browser speaks the words. With no message for 6 seconds the
device shows the bored face and "No link". It sends nothing back.

1. Open `firmware/robot-adapter` in VS Code with PlatformIO, or run `pio run -t upload`
   in that folder, with the CoreS3 connected by USB. Uploading replaces the current
   program.
2. Find the port (`ls /dev/cu.usbmodem*` on macOS) and close any serial monitor.
3. Start the backend with that port, for example
   `POMO_SERIAL_PORT=/dev/cu.usbmodem1101 sh scripts/dev.sh`, then enable monitoring
   in the simulator.

`pio run` builds the sketch without a device. Rendering, the chime and the serial
link have not yet been checked on hardware.

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

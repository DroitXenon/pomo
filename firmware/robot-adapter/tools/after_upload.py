"""PlatformIO post-upload step for the TinyUSB build.

The 1200-baud touch reboots the CoreS3 into its ROM bootloader by setting a
"force download boot" flag that survives the reset esptool performs after
flashing, so the board would stay in the bootloader. Clear that flag
(RTC_CNTL_OPTION1_REG bit 0 on the ESP32-S3) and reset into the new firmware.
"""

Import("env")  # noqa: F821  (provided by PlatformIO)


def clear_force_download(source, target, env):
    port = env.subst("$UPLOAD_PORT")
    esptool = env.PioPlatform().get_package_dir("tool-esptoolpy") + "/esptool.py"
    env.Execute(f'"$PYTHONEXE" "{esptool}" --chip esp32s3 --port "{port}" '
                f"--after hard_reset write_mem 0x6000812C 0 0x1")


env.AddPostAction("upload", clear_force_download)  # noqa: F821

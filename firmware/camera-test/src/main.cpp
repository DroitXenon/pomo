#include <M5Unified.h>
#include <esp_camera.h>
#include <esp_err.h>

namespace {
constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kWhite = 0xFFFF;
bool cameraReady = false;
bool frameError = false;
bool firstFrame = true;
uint32_t lastErrorLog = 0;

void showMessage(const char* title, const char* detail) {
  M5.Display.fillScreen(kBlack);
  M5.Display.setTextColor(kWhite, kBlack);
  M5.Display.setTextSize(2);
  M5.Display.setCursor(8, 20);
  M5.Display.println(title);
  M5.Display.setTextSize(1);
  M5.Display.setCursor(8, 60);
  M5.Display.println(detail);
}

void reportFrameError(const char* reason) {
  const uint32_t now = millis();
  if (!frameError) showMessage("Camera frame unavailable", reason);
  if (!frameError || now - lastErrorLog >= 2000) {
    Serial.printf("Camera frame unavailable: %s\n", reason);
    lastErrorLog = now;
  }
  frameError = true;
}

camera_config_t cameraConfig(bool usePsram) {
  // CoreS3 GC0308 wiring; these are not generic ESP32-CAM pins.
  camera_config_t config{};
  config.pin_pwdn = -1;
  config.pin_reset = -1;
  config.pin_xclk = -1;
  config.pin_sccb_sda = 12;
  config.pin_sccb_scl = 11;
  config.pin_d0 = 39;
  config.pin_d1 = 40;
  config.pin_d2 = 41;
  config.pin_d3 = 42;
  config.pin_d4 = 15;
  config.pin_d5 = 16;
  config.pin_d6 = 48;
  config.pin_d7 = 47;
  config.pin_vsync = 46;
  config.pin_href = 38;
  config.pin_pclk = 45;
  config.xclk_freq_hz = 20000000;
  config.ledc_timer = LEDC_TIMER_0;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.pixel_format = PIXFORMAT_RGB565;
  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 0;  // RGB565 preview does not encode JPEG.
  config.fb_count = usePsram ? 2 : 1;
  config.fb_location = usePsram ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.sccb_i2c_port = -1;
  return config;
}
}  // namespace

void setup() {
  Serial.begin(115200);
  auto config = M5.config();
  M5.begin(config);
  M5.Display.setRotation(0);
  Serial.printf("Display dimensions: %dx%d.\n", M5.Display.width(), M5.Display.height());
  showMessage("Starting CoreS3 camera", "Standalone preview; no images are saved.");

  const bool usePsram = psramFound();
  Serial.printf("CoreS3 camera preview: PSRAM %s, %u frame buffer(s).\n",
                usePsram ? "available" : "unavailable", usePsram ? 2U : 1U);
  if (!usePsram) Serial.println("Trying one DRAM buffer; initialization may fail if memory is insufficient.");

  M5.In_I2C.release();
  camera_config_t camera = cameraConfig(usePsram);
  const esp_err_t result = esp_camera_init(&camera);
  if (result != ESP_OK) {
    Serial.printf("Camera initialization failed: %s (0x%x).\n",
                  esp_err_to_name(result), static_cast<unsigned>(result));
    esp_camera_deinit();
    showMessage("Camera initialization failed", "Check the serial monitor for the error.\nReset the device to retry.");
    return;
  }
  sensor_t* sensor = esp_camera_sensor_get();
  if (sensor == nullptr) {
    esp_camera_deinit();
    Serial.println("Camera initialized without a sensor; preview stopped.");
    showMessage("Camera sensor unavailable", "Preview stopped safely. Reset to retry.");
    return;
  }
  Serial.printf("Camera ready: sensor 0x%x, RGB565 QVGA.\n", static_cast<unsigned>(sensor->id.PID));
  M5.Display.fillScreen(kBlack);
  cameraReady = true;
}

void loop() {
  // Camera SCCB owns the shared internal I2C driver. Do not poll touch or
  // PMIC controls with M5.update() while this standalone preview is active.
  if (!cameraReady) {
    delay(50);
    return;
  }

  camera_fb_t* frame = esp_camera_fb_get();
  if (frame == nullptr) {
    reportFrameError("No frame returned. Reset if the problem persists.");
    delay(20);
    return;
  }
  const bool valid = frame->buf != nullptr && frame->format == PIXFORMAT_RGB565 &&
                     frame->width > 0 && frame->height > 0 &&
                     frame->width <= static_cast<size_t>(M5.Display.width()) &&
                     frame->height <= static_cast<size_t>(M5.Display.height()) &&
                     frame->len >= frame->width * frame->height * sizeof(uint16_t);
  if (!valid) {
    esp_camera_fb_return(frame);
    reportFrameError("Unexpected frame format, size or dimensions.");
    delay(20);
    return;
  }

  if (frameError) M5.Display.fillScreen(kBlack);
  const int x = (M5.Display.width() - static_cast<int>(frame->width)) / 2;
  const int y = (M5.Display.height() - static_cast<int>(frame->height)) / 2;
  M5.Display.pushImage(x, y, frame->width, frame->height,
                       reinterpret_cast<uint16_t*>(frame->buf));
  // Do not let a DMA transfer retain a camera buffer after it is returned.
  M5.Display.waitDMA();
  if (firstFrame) {
    Serial.printf("Preview running: %ux%u, %u bytes per frame.\n",
                  static_cast<unsigned>(frame->width), static_cast<unsigned>(frame->height),
                  static_cast<unsigned>(frame->len));
    firstFrame = false;
  }
  esp_camera_fb_return(frame);
  frameError = false;
  delay(20);
}

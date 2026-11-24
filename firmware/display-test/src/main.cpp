#include <M5Unified.h>

void setup() {
  auto config = M5.config();
  M5.begin(config);

  M5.Display.fillScreen(0x0000);
  int center = M5.Display.width() / 2;

  M5.Display.fillRoundRect(center - 50, 60, 30, 50, 10, 0xFFFF);
  M5.Display.fillRoundRect(center + 20, 60, 30, 50, 10, 0xFFFF);
  M5.Display.drawLine(center - 20, 140, center + 20, 140, 0xFFFF);
}

void loop() {
  M5.update();
  delay(20);
}

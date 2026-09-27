// Optics bench controller for the ESP32.
// Open this folder in the Arduino IDE; the sketch name must match the folder name.
//
// Bench-test firmware: laser on/off plus four TMC2209-driven NEMA 8 steppers
// turning the M1/M2 kinematic mount adjusters. Driven from tools/bench_gui.py
// (or the Serial Monitor) with the protocol in src/comms/protocol.h.

#include "config.h"
#include "src/comms/protocol.h"
#include "src/laser/laser.h"
#include "src/motion/motion.h"

void setup() {
  laser::begin();                  // laser off before anything else
  // A TX buffer keeps Serial.print from blocking the step loop while a reply
  // drains at 115200 baud.
  Serial.setTxBufferSize(1024);
  Serial.begin(SERIAL_BAUD);
  delay(100);
  Serial.println("BOOT optics_bench " FW_VERSION);
  motion::begin();
  protocol::begin();
  Serial.println("READY");
}

void loop() {
  motion::update();
  protocol::poll();
}

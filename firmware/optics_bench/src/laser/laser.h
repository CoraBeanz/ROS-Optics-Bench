#pragma once

// Laser on/off through one GPIO (config.h: LASER_PIN, LASER_ACTIVE_HIGH).
// The laser always boots off.

#include <Arduino.h>
#include "../../config.h"

namespace laser {

inline bool &state() {
  static bool on = false;
  return on;
}

inline void set(bool on) {
  digitalWrite(LASER_PIN, on == LASER_ACTIVE_HIGH ? HIGH : LOW);
  state() = on;
}

inline bool isOn() { return state(); }

inline void begin() {
  pinMode(LASER_PIN, OUTPUT);
  set(false);
}

}  // namespace laser

#pragma once

// Four stepper axes on TMC2209 drivers: driver setup over the shared UART,
// non-blocking ramped motion (AccelStepper, stepped from loop()), soft limits
// and position persistence in flash.
//
// Units: positions and limits in microsteps (USTEPS_PER_REV per adjuster
// turn), speeds in RPM, acceleration in RPM per second.

#include <Arduino.h>
#include "../../config.h"

namespace motion {

enum MoveResult { MOVE_OK, MOVE_CLAMPED, MOVE_NO_DRIVER, MOVE_BAD_AXIS };

void begin();       // pins, UART, driver config, restore positions from flash
void update();      // call every loop(): steps motors, jog timeouts, saving

// Axis lookup: "M1X" / "m1x" / "1".."4" -> 0..3, -1 if unknown.
int  axisIndex(const char *token);
const char *axisName(int i);

MoveResult moveTo(int i, long target);        // absolute, clamped to soft limits
MoveResult moveBy(int i, long delta);         // relative, clamped to soft limits
MoveResult jog(int i, int dir);               // continuous; repeat within JOG_TIMEOUT_MS
void stop(int i);                             // ramp down
void halt(int i);                             // stop on this step, no ramp
bool anyMoving();
bool isMoving(int i);

long position(int i);
long target(int i);
bool setPosition(int i, long pos);            // idle only; ZERO is setPosition(i, 0)
bool setLimits(int i, long lo, long hi);      // saved to flash
long minLimit(int i);
long maxLimit(int i);

void  setSpeed(int i, float rpm);
void  setAccel(int i, float rpmPerS);
float speed(int i);
float accel(int i);
bool  setCurrent(int i, uint16_t mA);         // idle only (UART writes)
uint16_t current(int i);

void enable(int i);
void disable(int i);
bool enabled(int i);

bool driverOk(int i);                         // configured and verified over UART
bool reprobe(int i);                          // idle only: re-run driver config
String driverReport(int i);                   // idle only: DRV_STATUS summary
String slotMapReport();                       // which address answered in which slot

void savePositionsNow();
bool positionsTrusted();                      // false if power was lost mid-move
void markPositionsTrusted();                  // after ZERO ALL: the operator re-referenced every axis

}  // namespace motion

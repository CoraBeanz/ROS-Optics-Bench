#include "motion.h"

#include <AccelStepper.h>
#include <Preferences.h>
#include <TMCStepper.h>

// Driver register set carried over from the bench-proven featherv2 sketch:
// internal current reference, CHOPCONF toff 4 / HSTRT 5 / TBL 1, StealthChop
// at all speeds with PWMCONF OFS 36, GRAD 0, 35 kHz, autoscale + autograd,
// REG 1, LIM 12, microstep interpolation to 256x, IHOLDDELAY 8, TPOWERDOWN 10,
// StallGuard and VACTUAL off (motion comes only from STEP/DIR), 180 ms
// standstill calibration after every enable. Single-wire UART writes are not
// acknowledged, so every config is read back before the axis may move.

namespace motion {

namespace {

TMC2209Stepper drivers[NUM_AXES] = {
  TMC2209Stepper(&TMC_SERIAL, R_SENSE, AXIS_PINS[0].addr),
  TMC2209Stepper(&TMC_SERIAL, R_SENSE, AXIS_PINS[1].addr),
  TMC2209Stepper(&TMC_SERIAL, R_SENSE, AXIS_PINS[2].addr),
  TMC2209Stepper(&TMC_SERIAL, R_SENSE, AXIS_PINS[3].addr),
};

AccelStepper steppers[NUM_AXES] = {
  AccelStepper(AccelStepper::DRIVER, AXIS_PINS[0].step, AXIS_PINS[0].dir),
  AccelStepper(AccelStepper::DRIVER, AXIS_PINS[1].step, AXIS_PINS[1].dir),
  AccelStepper(AccelStepper::DRIVER, AXIS_PINS[2].step, AXIS_PINS[2].dir),
  AccelStepper(AccelStepper::DRIVER, AXIS_PINS[3].step, AXIS_PINS[3].dir),
};

struct Axis {
  const AxisPins *pins;
  TMC2209Stepper *drv;       // may be re-pointed by the slot check
  AccelStepper   *stp;
  long     minPos, maxPos;
  float    rpm, accelRpmS;
  uint16_t currentMa = RUN_CURRENT_MA;
  bool     uartOk = false, cfgOk = false;
  uint8_t  ver = 0;
  bool     energised = false;
  bool     held = false;       // ENABLE: stay energised until DISABLE, no auto-release
  uint32_t stillSince = 0;     // last time the axis was stepping or settling
  bool     settling = false; // enable settle in progress, stepping held off
  uint32_t settleStart = 0;
  bool     jogging = false;
  uint32_t jogDeadline = 0;
  bool     wasRunning = false;
  bool     limited = false;  // the move in progress was clamped to a soft limit
};

Axis axes[NUM_AXES];

enum SlotMap : uint8_t { MAP_UNCHECKED, MAP_OK, MAP_REMAPPED, MAP_INCONCLUSIVE };
SlotMap slotMap = MAP_UNCHECKED;

Preferences prefs;
bool     storedClean = true;     // flash says positions are valid
bool     bootTrusted = true;     // ... and said so at boot
long     savedPos[NUM_AXES];
uint32_t idleSince = 0;

float rpmToUstepsPerS(float rpm) { return rpm / 60.0f * USTEPS_PER_REV; }

bool valid(int i) { return i >= 0 && i < NUM_AXES; }

bool timeReached(uint32_t deadline) { return (int32_t)(millis() - deadline) >= 0; }

bool configDriver(Axis &a) {
  TMC2209Stepper &d = *a.drv;
  d.begin();                      // pdn_disable + mstep_reg_select (UART control)
  a.uartOk = (d.test_connection() == 0);
  a.cfgOk  = false;
  if (!a.uartOk) return false;

  uint8_t ifcntBefore = d.IFCNT();
  d.I_scale_analog(false);        // internal current reference
  d.multistep_filt(true);
  d.toff(4);
  d.hstrt(5);
  d.tbl(1);
  d.rms_current(a.currentMa, HOLD_MULTIPLIER);   // picks VSENSE, IRUN, IHOLD
  d.iholddelay(8);
  d.TPOWERDOWN(10);               // drop to hold current ~0.2 s after the last step
  d.microsteps(MICROSTEPS);
  d.intpol(true);                 // interpolate to 256x for smoothness
  d.en_spreadCycle(false);        // StealthChop at all speeds
  d.pwm_ofs(36);
  d.pwm_grad(0);
  d.pwm_freq(1);                  // 35 kHz
  d.pwm_autoscale(true);
  d.pwm_autograd(true);
  d.pwm_reg(1);
  d.pwm_lim(12);
  d.TPWMTHRS(0);
  d.TCOOLTHRS(0);                 // stall output off
  d.SGTHRS(0);
  d.VACTUAL(0);                   // motion comes from STEP/DIR only
  d.GSTAT(0x07);                  // clear reset / drv_err / uv_cp

  d.CRCerror = false;
  uint8_t  ifcntAfter = d.IFCNT();
  a.ver               = d.version();
  uint32_t gconf      = d.GCONF();
  uint32_t chop       = d.CHOPCONF();
  uint32_t pwm        = d.PWMCONF();
  uint8_t  mres       = (chop >> 24) & 0xF;
  a.cfgOk = !d.CRCerror && ifcntAfter != ifcntBefore && a.ver == TMC_EXPECTED_VER &&
            (gconf & 0x1C0) == 0x1C0 && (gconf & 0x4) == 0 &&   // pdn/mstep_reg/multistep_filt, spreadCycle off
            (chop & 0xF) == 4 && (chop & (1UL << 28)) != 0 &&   // toff 4, intpol
            (256 >> mres) == MICROSTEPS &&
            (pwm & 0xD0000) == 0xD0000;                         // 35 kHz, autoscale, autograd
  return true;
}

// Which chip answers on which UART address? IOIN echoes the chip's own DIR
// pin, so raise one slot's DIR at a time and see which address reports it.
// Straps that don't match AXIS_PINS[].addr would otherwise send one axis's
// current to another motor while every read-back still passes. A consistent
// mix-up is corrected by re-pointing the driver objects.
void checkDriverSlots() {
  for (int i = 0; i < NUM_AXES; i++) {
    if (drivers[i].test_connection() != 0) { slotMap = MAP_UNCHECKED; return; }
  }
  int  found[NUM_AXES];
  bool taken[NUM_AXES] = {false};
  bool conclusive = true;
  for (int slot = 0; slot < NUM_AXES && conclusive; slot++) {
    for (int k = 0; k < NUM_AXES; k++) digitalWrite(AXIS_PINS[k].dir, k == slot ? HIGH : LOW);
    delayMicroseconds(50);
    found[slot] = -1;
    for (int j = 0; j < NUM_AXES && conclusive; j++) {
      drivers[j].CRCerror = false;
      bool high = drivers[j].dir();
      if (drivers[j].CRCerror) conclusive = false;
      else if (high) {
        if (found[slot] != -1 || taken[j]) conclusive = false;
        else found[slot] = j;
      }
    }
    if (found[slot] == -1) conclusive = false;
    else taken[found[slot]] = true;
  }
  for (int k = 0; k < NUM_AXES; k++) digitalWrite(AXIS_PINS[k].dir, LOW);
  if (!conclusive) { slotMap = MAP_INCONCLUSIVE; return; }

  bool identity = true;
  for (int slot = 0; slot < NUM_AXES; slot++) identity &= (found[slot] == slot);
  if (identity) { slotMap = MAP_OK; return; }

  slotMap = MAP_REMAPPED;
  for (int slot = 0; slot < NUM_AXES; slot++) {
    axes[slot].drv = &drivers[found[slot]];
    configDriver(axes[slot]);
  }
  Serial.println("WARN TMC2209 address straps don't match config.h: " + slotMapReport() +
                 " - corrected in software, fix MS1/MS2 or AXIS_PINS addr when convenient");
}

// Motion gate. A driver that never answered runs on pin-strapped defaults
// (unknown microsteps and current), and one that reset since it was
// configured (GSTAT.reset: motor supply dip) is back on them, so both are
// (re)configured first. UART traffic stalls stepping for a few ms, so the
// check only runs while every axis is still.
bool ensureDriver(Axis &a) {
  if (anyMoving()) return a.uartOk;
  if (!a.uartOk) {
    configDriver(a);
    if (a.uartOk && slotMap != MAP_OK && slotMap != MAP_REMAPPED) checkDriverSlots();
  } else {
    a.drv->CRCerror = false;
    uint32_t gstat = a.drv->GSTAT();
    if (!a.drv->CRCerror && (gstat & 0x01)) {
      Serial.println("WARN " + String(a.pins->name) +
                     " driver reset since it was configured (motor supply dip?) - re-configuring");
      configDriver(a);
    }
  }
  return a.uartOk;
}

void energise(Axis &a) {
  if (a.energised) return;
  digitalWrite(a.pins->en, LOW);
  a.energised = true;
  a.settling = true;                         // StealthChop standstill calibration
  a.settleStart = millis();
  a.stillSince = a.settleStart;
}

void release(Axis &a) {
  digitalWrite(a.pins->en, HIGH);
  a.energised = false;
  a.settling = false;
}

MoveResult startMove(int i, long tgt, bool jogMove) {
  if (!valid(i)) return MOVE_BAD_AXIS;
  Axis &a = axes[i];
  if (!ensureDriver(a) && !ALLOW_MOVES_WITHOUT_UART) return MOVE_NO_DRIVER;
  long clamped = constrain(tgt, a.minPos, a.maxPos);
  a.limited = (clamped != tgt) || jogMove;
  a.jogging = jogMove;
  energise(a);
  a.stp->moveTo(clamped);
  return clamped != tgt ? MOVE_CLAMPED : MOVE_OK;
}

void savePositions() {
  for (int i = 0; i < NUM_AXES; i++) {
    long p = axes[i].stp->currentPosition();
    if (p != savedPos[i]) {
      prefs.putLong(("p" + String(i)).c_str(), p);
      savedPos[i] = p;
    }
  }
  if (!storedClean) {
    prefs.putBool("clean", true);
    storedClean = true;
  }
}

void saveLimits(int i) {
  prefs.putLong(("lo" + String(i)).c_str(), axes[i].minPos);
  prefs.putLong(("hi" + String(i)).c_str(), axes[i].maxPos);
}

}  // namespace

// ─────────────────────────────────────────────────────────────────────────────

void begin() {
  long defLo = lroundf(DEFAULT_MIN_TURNS * USTEPS_PER_REV);
  long defHi = lroundf(DEFAULT_MAX_TURNS * USTEPS_PER_REV);

  prefs.begin("bench", false);
  bool fresh = !prefs.isKey("us");
  uint16_t storedUsteps = prefs.getUShort("us", MICROSTEPS);
  storedClean = prefs.getBool("clean", true);
  bootTrusted = storedClean;

  for (int i = 0; i < NUM_AXES; i++) {
    Axis &a = axes[i];
    a.pins = &AXIS_PINS[i];
    a.drv  = &drivers[i];
    a.stp  = &steppers[i];
    a.rpm  = DEFAULT_RPM;
    a.accelRpmS = DEFAULT_ACCEL_RPM_S;

    // Drivers boot disabled; STEP/DIR idle low.
    pinMode(a.pins->en, OUTPUT);
    digitalWrite(a.pins->en, HIGH);
    pinMode(a.pins->step, OUTPUT);
    pinMode(a.pins->dir, OUTPUT);
    digitalWrite(a.pins->dir, LOW);

    long pos = prefs.getLong(("p" + String(i)).c_str(), 0);
    a.minPos = prefs.getLong(("lo" + String(i)).c_str(), defLo);
    a.maxPos = prefs.getLong(("hi" + String(i)).c_str(), defHi);
    if (storedUsteps != MICROSTEPS && storedUsteps != 0) {   // MICROSTEPS changed since last save
      double k = (double)MICROSTEPS / storedUsteps;
      pos = lround(pos * k);
      a.minPos = lround(a.minPos * k);
      a.maxPos = lround(a.maxPos * k);
      saveLimits(i);
    }
    a.stp->setPinsInverted(a.pins->invert, false, false);
    a.stp->setMinPulseWidth(2);
    a.stp->setCurrentPosition(pos);
    a.stp->setMaxSpeed(rpmToUstepsPerS(a.rpm));
    a.stp->setAcceleration(rpmToUstepsPerS(a.accelRpmS));
    savedPos[i] = pos;
  }
  if (fresh || storedUsteps != MICROSTEPS) {
    prefs.putUShort("us", MICROSTEPS);
    for (int i = 0; i < NUM_AXES; i++) {
      prefs.putLong(("p" + String(i)).c_str(), savedPos[i]);
      saveLimits(i);
    }
  }

  TMC_SERIAL.begin(TMC_BAUD, SERIAL_8N1, TMC_RX_PIN, TMC_TX_PIN);
  delay(20);
  for (Axis &a : axes) {
    configDriver(a);
    if (!a.uartOk) {
      Serial.println("WARN " + String(a.pins->name) + " driver offline - no UART reply at address " +
                     String(a.pins->addr) + " (check motor supply, MS1/MS2 straps, 1k TX resistor)");
    } else if (!a.cfgOk) {
      Serial.println("WARN " + String(a.pins->name) + " driver config read-back mismatch (ver=0x" +
                     String(a.ver, HEX) + ") - see DRV " + String(a.pins->name));
    }
  }
  checkDriverSlots();
  if (slotMap == MAP_INCONCLUSIVE) {
    Serial.println("WARN could not verify which driver answers on which UART address (DIR read-back "
                   "inconclusive); check MS1/MS2 straps if one motor ignores CURRENT changes");
  }
  if (!bootTrusted) {
    Serial.println("WARN power was lost during a move: saved positions may be off by that move. "
                   "Re-zero the axes against a known alignment.");
  }
}

void update() {
  bool moving = false;
  for (int i = 0; i < NUM_AXES; i++) {
    Axis &a = axes[i];
    if (a.jogging && timeReached(a.jogDeadline)) {
      a.jogging = false;
      a.stp->stop();                        // host stopped repeating JOG: ramp down
    }
    if (a.settling) {
      if (millis() - a.settleStart < ENABLE_SETTLE_MS) {
        moving |= a.stp->distanceToGo() != 0;   // waiting out the enable settle
        a.stillSince = millis();
        continue;
      }
      a.settling = false;
    }
    bool running = a.stp->run();
    if (running) {
      moving = true;
      a.wasRunning = true;
      a.stillSince = millis();
    } else if (AUTO_RELEASE && a.energised && !a.held && millis() - a.stillSince >= RELEASE_DELAY_MS) {
      release(a);                           // still long enough: coils off until the next move
    }
    if (!running && a.wasRunning) {
      a.wasRunning = false;
      a.jogging = false;
      long p = a.stp->currentPosition();
      bool atLimit = a.limited && (p <= a.minPos || p >= a.maxPos);
      a.limited = false;
      Serial.println("EVT DONE " + String(a.pins->name) + " POS=" + String(p) + (atLimit ? " LIMIT" : ""));
    }
  }

  if (moving) {
    idleSince = millis();
    if (storedClean) {                      // a power cut from here on leaves positions unknown
      prefs.putBool("clean", false);
      storedClean = false;
    }
  } else if (millis() - idleSince >= POS_SAVE_DELAY_MS) {
    bool changed = !storedClean;
    for (int i = 0; i < NUM_AXES && !changed; i++) changed = axes[i].stp->currentPosition() != savedPos[i];
    if (changed) savePositions();
  }
}

int axisIndex(const char *token) {
  if (token == nullptr || *token == 0) return -1;
  if (token[1] == 0 && token[0] >= '1' && token[0] < '1' + NUM_AXES) return token[0] - '1';
  for (int i = 0; i < NUM_AXES; i++) {
    if (strcasecmp(token, AXIS_PINS[i].name) == 0) return i;
  }
  return -1;
}

const char *axisName(int i) { return valid(i) ? AXIS_PINS[i].name : "?"; }

MoveResult moveTo(int i, long tgt) { return startMove(i, tgt, false); }

MoveResult moveBy(int i, long delta) {
  if (!valid(i)) return MOVE_BAD_AXIS;
  // Relative to where the axis is headed, so quick repeated nudges add up.
  return startMove(i, axes[i].stp->targetPosition() + delta, false);
}

MoveResult jog(int i, int dir) {
  if (!valid(i)) return MOVE_BAD_AXIS;
  Axis &a = axes[i];
  if (a.jogging && ((dir > 0) == (a.stp->targetPosition() >= a.stp->currentPosition()))) {
    a.jogDeadline = millis() + JOG_TIMEOUT_MS;  // keep-alive for the jog in progress
    return MOVE_OK;
  }
  MoveResult r = startMove(i, dir > 0 ? a.maxPos : a.minPos, true);
  if (r == MOVE_OK || r == MOVE_CLAMPED) a.jogDeadline = millis() + JOG_TIMEOUT_MS;
  return r;
}

void stop(int i) {
  if (!valid(i)) return;
  axes[i].jogging = false;
  axes[i].stp->stop();
}

void halt(int i) {
  if (!valid(i)) return;
  axes[i].jogging = false;
  axes[i].stp->setCurrentPosition(axes[i].stp->currentPosition());   // target = here, speed 0
}

bool isMoving(int i) { return valid(i) && axes[i].stp->distanceToGo() != 0; }

bool anyMoving() {
  for (int i = 0; i < NUM_AXES; i++) if (isMoving(i)) return true;
  return false;
}

long position(int i) { return valid(i) ? axes[i].stp->currentPosition() : 0; }
long target(int i)   { return valid(i) ? axes[i].stp->targetPosition() : 0; }

bool setPosition(int i, long pos) {
  if (!valid(i) || isMoving(i)) return false;
  axes[i].stp->setCurrentPosition(pos);
  savePositions();
  return true;
}

bool setLimits(int i, long lo, long hi) {
  long absMax = lroundf(ABS_LIMIT_TURNS * USTEPS_PER_REV);
  if (!valid(i) || lo > hi || lo < -absMax || hi > absMax) return false;
  axes[i].minPos = lo;
  axes[i].maxPos = hi;
  saveLimits(i);
  return true;
}

long minLimit(int i) { return valid(i) ? axes[i].minPos : 0; }
long maxLimit(int i) { return valid(i) ? axes[i].maxPos : 0; }

void setSpeed(int i, float rpm) {
  if (!valid(i)) return;
  rpm = constrain(rpm, 0.1f, MAX_RPM);
  axes[i].rpm = rpm;
  axes[i].stp->setMaxSpeed(rpmToUstepsPerS(rpm));
}

void setAccel(int i, float rpmPerS) {
  if (!valid(i)) return;
  rpmPerS = constrain(rpmPerS, 1.0f, 10.0f * MAX_RPM);
  axes[i].accelRpmS = rpmPerS;
  axes[i].stp->setAcceleration(rpmToUstepsPerS(rpmPerS));
}

float speed(int i) { return valid(i) ? axes[i].rpm : 0; }
float accel(int i) { return valid(i) ? axes[i].accelRpmS : 0; }

bool setCurrent(int i, uint16_t mA) {
  if (!valid(i) || anyMoving()) return false;
  mA = constrain(mA, (uint16_t)50, (uint16_t)MAX_CURRENT_MA);
  axes[i].currentMa = mA;
  if (axes[i].uartOk) axes[i].drv->rms_current(mA, HOLD_MULTIPLIER);
  return true;
}

uint16_t current(int i) { return valid(i) ? axes[i].currentMa : 0; }

void enable(int i) {
  if (!valid(i)) return;
  axes[i].held = true;
  energise(axes[i]);
}

void disable(int i) {
  if (!valid(i)) return;
  halt(i);
  axes[i].held = false;
  release(axes[i]);
}

bool enabled(int i) { return valid(i) && axes[i].energised; }

bool driverOk(int i) { return valid(i) && axes[i].uartOk && axes[i].cfgOk; }

bool reprobe(int i) {
  if (!valid(i) || anyMoving()) return false;
  configDriver(axes[i]);
  if (axes[i].uartOk && slotMap != MAP_OK && slotMap != MAP_REMAPPED) checkDriverSlots();
  return axes[i].uartOk;
}

String driverReport(int i) {
  if (!valid(i)) return "";
  Axis &a = axes[i];
  String s = String(a.pins->name) + " addr=" + String(AXIS_PINS[a.drv - drivers].addr);
  if (!a.uartOk) return s + " uart=offline";
  TMC2209Stepper &d = *a.drv;
  d.CRCerror = false;
  uint32_t st    = d.DRV_STATUS();
  uint8_t  gstat = d.GSTAT();
  uint8_t  mres  = d.mres();
  uint16_t irms  = d.rms_current();
  uint8_t  ifcnt = d.IFCNT();
  if (d.CRCerror) return s + " uart=crc_error";
  s += " uart=ok cfg=" + String(a.cfgOk ? "ok" : "FAIL") + " ver=0x" + String(a.ver, HEX);
  s += " usteps=" + String(256 >> mres) + " irms=" + String(irms) + " ifcnt=" + String(ifcnt);
  s += " cs=" + String((st >> 16) & 0x1F) + " stealth=" + String((st >> 30) & 1) + " stst=" + String((st >> 31) & 1);
  s += " otpw=" + String(st & 1) + " ot=" + String((st >> 1) & 1);
  s += " s2g=" + String((st >> 2) & 3) + " s2vs=" + String((st >> 4) & 3) + " ol=" + String((st >> 6) & 3);
  s += " reset=" + String(gstat & 1) + " drv_err=" + String((gstat >> 1) & 1) + " uv_cp=" + String((gstat >> 2) & 1);
  return s;
}

String slotMapReport() {
  if (slotMap == MAP_UNCHECKED)    return "slots=unchecked";
  if (slotMap == MAP_INCONCLUSIVE) return "slots=inconclusive";
  String s = slotMap == MAP_OK ? "slots=ok" : "slots=remapped";
  for (int i = 0; i < NUM_AXES; i++) {
    s += String(i ? "," : " ") + AXIS_PINS[i].name + ":" + String(AXIS_PINS[axes[i].drv - drivers].addr);
  }
  return s;
}

void savePositionsNow() { savePositions(); }

bool positionsTrusted() { return bootTrusted; }

}  // namespace motion

#include "protocol.h"

#include <Arduino.h>
#include "../../config.h"
#include "../laser/laser.h"
#include "../motion/motion.h"
#include "../sensing/sensing.h"

namespace protocol {

namespace {

constexpr size_t MAX_LINE_LEN = 96;
char   line[MAX_LINE_LEN];
size_t lineLen = 0;
bool   overflow = false;

const int ALL = -2;

void ok(const String &s)  { Serial.println("OK " + s); }
void err(const String &s) { Serial.println("ERR " + s); }

bool parseLong(const char *tok, long &out) {
  if (tok == nullptr) return false;
  char *end;
  out = strtol(tok, &end, 10);
  return end != tok && *end == 0;
}

bool parseFloat(const char *tok, float &out) {
  if (tok == nullptr) return false;
  char *end;
  out = strtof(tok, &end);
  return end != tok && *end == 0;
}

// Axis argument: an index, ALL (when allowed), or -1 with an ERR already sent.
int parseAxis(const char *tok, bool allowAll) {
  if (tok == nullptr) { err("missing axis"); return -1; }
  if (allowAll && strcasecmp(tok, "ALL") == 0) return ALL;
  int i = motion::axisIndex(tok);
  if (i < 0) err(String("unknown axis ") + tok);
  return i;
}

template <typename F> void forAxes(int ax, F f) {
  if (ax == ALL) { for (int i = 0; i < NUM_AXES; i++) f(i); }
  else f(ax);
}

template <typename F> String joinAxes(F f) {
  String s;
  for (int i = 0; i < NUM_AXES; i++) { if (i) s += ","; s += f(i); }
  return s;
}

void reportMove(const char *cmd, int i, motion::MoveResult r) {
  switch (r) {
    case motion::MOVE_OK:
      ok(String(cmd) + " " + motion::axisName(i) + " TGT=" + String(motion::target(i)));
      break;
    case motion::MOVE_CLAMPED:
      ok(String(cmd) + " " + motion::axisName(i) + " TGT=" + String(motion::target(i)) + " CLAMPED");
      break;
    case motion::MOVE_NO_DRIVER:
      err(String(motion::axisName(i)) + " driver offline (no UART reply) - check motor supply and wiring, then REPROBE");
      break;
    default:
      err("bad axis");
  }
}

void cmdStatus() {
  Serial.println("STATUS LASER=" + String(laser::isOn() ? 1 : 0) +
                 " POS=" + joinAxes([](int i) { return String(motion::position(i)); }) +
                 " TGT=" + joinAxes([](int i) { return String(motion::target(i)); }) +
                 " MOV=" + joinAxes([](int i) { return String(motion::isMoving(i) ? 1 : 0); }) +
                 " EN="  + joinAxes([](int i) { return String(motion::enabled(i) ? 1 : 0); }) +
                 " DRV=" + joinAxes([](int i) { return String(motion::driverOk(i) ? 1 : 0); }));
}

void cmdInfo() {
  Serial.println(String("INFO FW=") + FW_VERSION +
                 " AXES=" + joinAxes([](int i) { return String(motion::axisName(i)); }) +
                 " USTEPS_PER_REV=" + String(USTEPS_PER_REV) +
                 " MIN=" + joinAxes([](int i) { return String(motion::minLimit(i)); }) +
                 " MAX=" + joinAxes([](int i) { return String(motion::maxLimit(i)); }) +
                 " RPM=" + joinAxes([](int i) { return String(motion::speed(i), 1); }) +
                 " ACCEL=" + joinAxes([](int i) { return String(motion::accel(i), 1); }) +
                 " MA=" + joinAxes([](int i) { return String(motion::current(i)); }) +
                 " MAX_RPM=" + String(MAX_RPM, 1) + " MAX_MA=" + String(MAX_CURRENT_MA) +
                 " ABS_LIMIT=" + String(lroundf(ABS_LIMIT_TURNS * USTEPS_PER_REV)) +
                 " TRUSTED=" + String(motion::positionsTrusted() ? 1 : 0) +
                 " ADC=" + String(sensing::present() ? 1 : 0) +
                 " PD_RF=" + String(PD_REF_TIA_OHMS, 0) + "," + String(PD_OUT_TIA_OHMS, 0) + " PD_RESP=" + String(PD_RESPONSIVITY, 2) +
                 " " + motion::slotMapReport());
}

void cmdPd(const char *a1, const char *a2) {
  if (!sensing::present() && !sensing::probe()) {
    err("ADS1115 not found at 0x" + String(ADS1115_ADDR, HEX) + " - check its I2C wiring and 3V3");
    return;
  }
  if (a1 == nullptr) { Serial.println(sensing::report()); return; }

  if (strcasecmp(a1, "STREAM") == 0) {
    float hz = 0;
    bool off = a2 && strcasecmp(a2, "OFF") == 0;
    if (!off && (!parseFloat(a2, hz) || !sensing::setStream(hz))) {
      err("PD STREAM takes OFF or 0-" + String(PD_MAX_STREAM_HZ) + " Hz");
      return;
    }
    if (off) sensing::setStream(0);
    ok("PD STREAM=" + String(sensing::streamHz(), 1));
    return;
  }

  if (strcasecmp(a1, "DARK") == 0) {
    if (a2 && strcasecmp(a2, "CLEAR") == 0) { sensing::clearDark(); ok("PD DARK CLEARED"); return; }
    if (!sensing::startDark()) err("PD DARK is already running");
    return;   // sensing replies OK PD DARK REF=.. OUT=.. once it has finished
  }

  if (strcasecmp(a1, "RANGE") == 0) {
    float fsr = 0;
    bool autoRange = a2 && strcasecmp(a2, "AUTO") == 0;
    if (!autoRange && (!parseFloat(a2, fsr) || fsr <= 0 || !sensing::setRange(fsr))) {
      err("PD RANGE takes AUTO, 4.096, 2.048, 1.024, 0.512 or 0.256");
      return;
    }
    if (autoRange) sensing::setRange(0);
    ok(sensing::fixedRange() > 0 ? "PD RANGE=" + String(sensing::fixedRange(), 3) : String("PD RANGE=AUTO"));
    return;
  }

  err("PD takes no argument, STREAM, DARK or RANGE");
}

void handle(char *buf) {
  char *cmd = strtok(buf, " \t");
  if (cmd == nullptr) return;
  for (char *p = cmd; *p; p++) *p = toupper(*p);
  char *a1 = strtok(nullptr, " \t");
  char *a2 = strtok(nullptr, " \t");
  char *a3 = strtok(nullptr, " \t");
  String c(cmd);

  if (c == "PING") { ok("PONG"); return; }
  if (c == "STATUS") { cmdStatus(); return; }
  if (c == "INFO") { cmdInfo(); return; }

  if (c == "PD") { cmdPd(a1, a2); return; }

  if (c == "LASER") {
    if (a1 && sensing::darkBusy()) { err("PD DARK is switching the laser, try again"); return; }
    if (a1 && strcasecmp(a1, "ON") == 0) laser::set(true);
    else if (a1 && strcasecmp(a1, "OFF") == 0) laser::set(false);
    else if (a1) { err("LASER takes ON or OFF"); return; }
    ok("LASER=" + String(laser::isOn() ? 1 : 0));
    return;
  }

  if (c == "MOVE" || c == "GOTO") {
    int ax = parseAxis(a1, false);
    if (ax < 0) return;
    long v;
    if (!parseLong(a2, v)) { err(c + " needs a whole number of microsteps"); return; }
    reportMove(cmd, ax, c == "MOVE" ? motion::moveBy(ax, v) : motion::moveTo(ax, v));
    return;
  }

  if (c == "JOG") {
    int ax = parseAxis(a1, false);
    if (ax < 0) return;
    if (!a2 || (strcmp(a2, "+") != 0 && strcmp(a2, "-") != 0)) { err("JOG takes + or -"); return; }
    motion::MoveResult r = motion::jog(ax, a2[0] == '+' ? 1 : -1);
    if (r == motion::MOVE_OK || r == motion::MOVE_CLAMPED) return;   // silent keep-alive
    reportMove(cmd, ax, r);
    return;
  }

  if (c == "STOP" || c == "HALT") {
    int ax = a1 ? parseAxis(a1, true) : ALL;
    if (ax == -1) return;
    forAxes(ax, [&](int i) { if (c == "STOP") motion::stop(i); else motion::halt(i); });
    ok(c);
    return;
  }

  if (c == "ZERO") {
    int ax = parseAxis(a1, true);
    if (ax == -1) return;
    if ((ax == ALL && motion::anyMoving()) || (ax != ALL && motion::isMoving(ax))) { err("stop the motor first"); return; }
    forAxes(ax, [](int i) { motion::setPosition(i, 0); });
    ok("ZERO");
    return;
  }

  if (c == "SETPOS") {
    int ax = parseAxis(a1, false);
    if (ax < 0) return;
    long v;
    if (!parseLong(a2, v)) { err("SETPOS needs a position"); return; }
    if (!motion::setPosition(ax, v)) { err("stop the motor first"); return; }
    ok("SETPOS " + String(motion::axisName(ax)) + " POS=" + String(v));
    return;
  }

  if (c == "LIMITS") {
    int ax = parseAxis(a1, true);
    if (ax == -1) return;
    long lo, hi;
    if (!parseLong(a2, lo) || !parseLong(a3, hi)) { err("LIMITS needs <lo> <hi> in microsteps"); return; }
    bool good = true;
    forAxes(ax, [&](int i) { good &= motion::setLimits(i, lo, hi); });
    if (!good) { err("limits must satisfy lo <= hi and stay within +-" + String(lroundf(ABS_LIMIT_TURNS * USTEPS_PER_REV))); return; }
    ok("LIMITS MIN=" + String(lo) + " MAX=" + String(hi));
    return;
  }

  if (c == "SPEED" || c == "ACCEL") {
    int ax = parseAxis(a1, true);
    if (ax == -1) return;
    float v;
    if (!parseFloat(a2, v) || v <= 0) { err(c + " needs a positive number"); return; }
    forAxes(ax, [&](int i) { if (c == "SPEED") motion::setSpeed(i, v); else motion::setAccel(i, v); });
    int shown = ax == ALL ? 0 : ax;
    ok(c + "=" + String(c == "SPEED" ? motion::speed(shown) : motion::accel(shown), 1));
    return;
  }

  if (c == "CURRENT") {
    int ax = parseAxis(a1, true);
    if (ax == -1) return;
    long v;
    if (!parseLong(a2, v) || v <= 0) { err("CURRENT needs mA"); return; }
    if (motion::anyMoving()) { err("stop the motors first"); return; }
    forAxes(ax, [&](int i) { motion::setCurrent(i, (uint16_t)v); });
    ok("CURRENT=" + String(motion::current(ax == ALL ? 0 : ax)));
    return;
  }

  if (c == "ENABLE" || c == "DISABLE") {
    int ax = parseAxis(a1, true);
    if (ax == -1) return;
    forAxes(ax, [&](int i) { if (c == "ENABLE") motion::enable(i); else motion::disable(i); });
    ok(c);
    return;
  }

  if (c == "DRV") {
    int ax = parseAxis(a1, false);
    if (ax < 0) return;
    if (motion::anyMoving()) { err("stop the motors first (UART reads stall stepping)"); return; }
    ok("DRV " + motion::driverReport(ax));
    return;
  }

  if (c == "REPROBE") {
    int ax = parseAxis(a1, true);
    if (ax == -1) return;
    if (motion::anyMoving()) { err("stop the motors first"); return; }
    forAxes(ax, [](int i) { motion::reprobe(i); });
    ok("REPROBE DRV=" + joinAxes([](int i) { return String(motion::driverOk(i) ? 1 : 0); }) + " " +
       motion::slotMapReport());
    return;
  }

  if (c == "SAVE") { motion::savePositionsNow(); ok("SAVE"); return; }

  err("unknown command " + c);
}

}  // namespace

void begin() {
  lineLen = 0;
  overflow = false;
}

void poll() {
  // At most one line per call, so the step loop never waits on a burst.
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      line[lineLen] = 0;
      bool bad = overflow;
      lineLen = 0;
      overflow = false;
      if (bad) { err("line too long"); return; }
      handle(line);
      return;
    }
    if (lineLen < MAX_LINE_LEN - 1) line[lineLen++] = ch;
    else overflow = true;
  }
}

}  // namespace protocol

#include "sensing.h"

#include <Wire.h>
#include "../laser/laser.h"

namespace sensing {

namespace {

bool found = false;

// The ADS1115 is driven with plain Wire transactions so that every return
// code is checked: a sample whose transfer failed is dropped instead of
// reading as 0 V. Registers per the TI datasheet (SBAS444, 9.6):
// pointer 0 = conversion result, 1 = config. Config bits: OS (15) = 1 starts
// a single-shot conversion; MUX (14:12) = 1xx: AINx against GND; PGA (11:9)
// = 001..101: +-4.096 .. +-0.256 V; MODE (8) = 1: single-shot; DR (7:5) =
// 111: 860 SPS; COMP_MODE, COMP_POL, COMP_LAT (4:2) = 0 and COMP_QUE (1:0) =
// 11: comparator off (ALERT/RDY is not wired).
const uint8_t  REG_CONVERSION  = 0x00;
const uint8_t  REG_CONFIG      = 0x01;
const uint16_t CFG_OS_START    = 0x8000;
const uint16_t CFG_MODE_SINGLE = 0x0100;
const uint16_t CFG_DR_860SPS   = 0x00E0;
const uint16_t CFG_COMP_OFF    = 0x0003;
uint16_t cfgMux(uint8_t ain) { return (uint16_t)((0x4 | ain) << 12); }

// ADS1115 gain ranges, coarse to fine, with their PGA bits. +-6.144 V is
// left out: the inputs can't go above the 3.3 V supply anyway.
struct Range { uint16_t pga; float fsr; };
const Range RANGES[] = {
  { 0x0200, 4.096f }, { 0x0400, 2.048f }, { 0x0600, 1.024f },
  { 0x0800, 0.512f }, { 0x0A00, 0.256f },
};
const int NUM_RANGES = sizeof(RANGES) / sizeof(RANGES[0]);
const uint8_t AIN[NUM_CHANNELS] = { PD_REF_CHANNEL, PD_OUT_CHANNEL };

// 860 SPS is a 1.16 ms conversion; the ADS1115's clock is only good to 10 %.
// Reading the result after a fixed wait saves polling the config register,
// so each sample costs three short I2C transactions: the config write that
// starts it, then a pointer write and a 2-byte read of the result.
const uint32_t CONVERSION_US = 1400;
// The ratio is reported as "-" with the laser off or the reference under
// this: a ratio of two dark offsets would look like good coupling.
const float MIN_REF_V = 0.010f;

int  rangeIdx[NUM_CHANNELS] = { 0, 0 };
int  fixedIdx = -1;                // -1 = auto-range
int  channel = REF;
bool converting = false;
bool retryWait = false;            // the last sample failed: wait a conversion time before the next try
uint32_t convStart = 0;
int  fails = 0;                    // consecutive failed samples

float    latest[NUM_CHANNELS] = { 0, 0 };
double   sum[NUM_CHANNELS] = { 0, 0 };
uint32_t count[NUM_CHANNELS] = { 0, 0 };
float    dark[NUM_CHANNELS] = { 0, 0 };
bool     haveDark = false;

enum DarkPhase { DARK_IDLE, DARK_SETTLE, DARK_SAMPLE, DARK_RESTORE };
DarkPhase darkPhase = DARK_IDLE;
bool     laserWasOn = false;
uint32_t phaseStart = 0;
double   darkSum[NUM_CHANNELS];
uint32_t darkCount[NUM_CHANNELS];

float    streamRate = 0;
uint32_t lastStream = 0;

void resetAverages() {
  for (int c = 0; c < NUM_CHANNELS; c++) { sum[c] = 0; count[c] = 0; }
}

bool writeConfig(uint16_t v) {
  const uint8_t buf[3] = { REG_CONFIG, (uint8_t)(v >> 8), (uint8_t)(v & 0xFF) };
  Wire.beginTransmission(ADS1115_ADDR);
  bool queued = Wire.write(buf, 3) == 3;
  uint8_t e = Wire.endTransmission();          // always, it also releases the bus lock
  return queued && e == 0;
}

bool readRegister(uint8_t reg, uint16_t &out) {
  Wire.beginTransmission(ADS1115_ADDR);
  bool queued = Wire.write(reg) == 1;
  if (Wire.endTransmission() != 0 || !queued) return false;
  if (Wire.requestFrom((uint8_t)ADS1115_ADDR, (size_t)2) != 2) return false;
  int hi = Wire.read(), lo = Wire.read();
  if (hi < 0 || lo < 0) return false;
  out = (uint16_t)((hi << 8) | lo);
  return true;
}

void abortDark();

// A transfer failed: drop the sample and retry the same channel after a
// conversion time. After ADS_MAX_FAILS in a row the ADC counts as gone; PD
// (and so the GUI's live view) probes it again.
void sampleFailed() {
  converting = false;
  retryWait = true;
  convStart = micros();
  if (++fails < ADS_MAX_FAILS) return;
  found = false;
  fails = 0;
  Serial.println("WARN ADS1115 stopped answering - check its I2C wiring and 3V3 (PD retries it)");
  abortDark();
}

void startConversion() {
  uint16_t cfg = CFG_OS_START | cfgMux(AIN[channel]) | RANGES[rangeIdx[channel]].pga |
                 CFG_MODE_SINGLE | CFG_DR_860SPS | CFG_COMP_OFF;
  if (!writeConfig(cfg)) { sampleFailed(); return; }
  retryWait = false;
  convStart = micros();
  converting = true;
}

void accept(int c, float v) {
  if (darkPhase == DARK_SAMPLE) { darkSum[c] += v; darkCount[c]++; return; }
  if (darkPhase != DARK_IDLE) return;   // the laser just switched: let the TIA settle
  latest[c] = v;
  sum[c] += v;
  count[c]++;
}

void finishConversion() {
  converting = false;
  uint16_t reg;
  if (!readRegister(REG_CONVERSION, reg)) { sampleFailed(); return; }
  fails = 0;
  int16_t raw = (int16_t)reg;
  int c = channel;
  int r = rangeIdx[c];
  float v = raw * RANGES[r].fsr / 32768.0f;
  channel = (channel + 1) % NUM_CHANNELS;

  if (fixedIdx >= 0) { accept(c, v); return; }
  // Auto-range for this channel's next conversion: coarser above 90 % of the
  // range, finer once the value would sit under 45 % of the next finer range.
  if (raw > 29491 && r > 0) {
    rangeIdx[c] = r - 1;
    if (raw >= 32767) return;           // clipped: drop it, retake at the coarser range
  } else if (r < NUM_RANGES - 1 && v < 0.45f * RANGES[r + 1].fsr) {
    rangeIdx[c] = r + 1;
  }
  accept(c, v);
}

String volts(float v) { return String(v, 6); }

void finishDark() {
  for (int c = 0; c < NUM_CHANNELS; c++) dark[c] = darkSum[c] / darkCount[c];
  haveDark = true;
  laser::set(laserWasOn);
  Serial.println("OK PD DARK REF=" + volts(dark[REF]) + " OUT=" + volts(dark[OUT]));
}

// The ADC went away during PD DARK: put the laser back and answer the
// pending PD DARK with an ERR instead of leaving it waiting.
void abortDark() {
  if (darkPhase == DARK_IDLE) return;
  bool replyOwed = darkPhase != DARK_RESTORE;     // RESTORE: OK PD DARK was already sent
  darkPhase = DARK_IDLE;
  laser::set(laserWasOn);
  resetAverages();
  if (replyOwed) Serial.println("ERR PD DARK aborted - ADS1115 stopped answering");
}

void updateDark() {
  uint32_t now = millis();
  switch (darkPhase) {
    case DARK_SETTLE:
      if (now - phaseStart >= PD_SETTLE_MS) {
        for (int c = 0; c < NUM_CHANNELS; c++) { darkSum[c] = 0; darkCount[c] = 0; }
        darkPhase = DARK_SAMPLE;
      }
      break;
    case DARK_SAMPLE:
      if (darkCount[REF] >= PD_DARK_SAMPLES && darkCount[OUT] >= PD_DARK_SAMPLES) {
        finishDark();
        phaseStart = now;
        darkPhase = DARK_RESTORE;
      }
      break;
    case DARK_RESTORE:
      if (now - phaseStart >= PD_SETTLE_MS) {
        resetAverages();
        darkPhase = DARK_IDLE;
      }
      break;
    default:
      break;
  }
}

}  // namespace

void begin() {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setTimeOut(I2C_TIMEOUT_MS);   // default 50 ms: a stuck bus would hold up stepping that long per transfer
  probe();
}

bool probe() {
  converting = false;
  retryWait = false;
  fails = 0;
  uint16_t cfg;
  found = readRegister(REG_CONFIG, cfg);   // it acknowledges and its config register reads back
  if (found) Wire.setClock(I2C_CLOCK_HZ);
  return found;
}

bool present() { return found; }

void update() {
  if (!found) return;
  if (converting && micros() - convStart >= CONVERSION_US) finishConversion();
  if (!converting && (!retryWait || micros() - convStart >= CONVERSION_US)) startConversion();
  if (!found) return;                 // it just stopped answering
  updateDark();
  if (streamRate > 0 && darkPhase == DARK_IDLE) {
    uint32_t now = millis();
    if (now - lastStream >= (uint32_t)(1000.0f / streamRate)) {
      lastStream = now;
      Serial.println(report());
    }
  }
}

String report() {
  float v[NUM_CHANNELS];
  uint32_t n[NUM_CHANNELS];
  for (int c = 0; c < NUM_CHANNELS; c++) {
    n[c] = count[c];
    v[c] = n[c] ? (float)(sum[c] / n[c]) : latest[c];
    if (haveDark) v[c] -= dark[c];
  }
  resetAverages();
  String ratio = laser::isOn() && v[REF] > MIN_REF_V ?String(v[OUT] / v[REF], 6) : String("-");
  return "PD REF=" + volts(v[REF]) + " OUT=" + volts(v[OUT]) + " RATIO=" + ratio +
         " FSR=" + String(RANGES[rangeIdx[REF]].fsr, 3) + "," + String(RANGES[rangeIdx[OUT]].fsr, 3) +
         " N=" + String(n[REF]) + "," + String(n[OUT]) +
         " DARK=" + String(haveDark ? 1 : 0) + " LASER=" + String(laser::isOn() ? 1 : 0);
}

bool setStream(float hz) {
  if (hz < 0 || hz > PD_MAX_STREAM_HZ) return false;
  streamRate = hz;
  lastStream = millis();
  resetAverages();
  return true;
}

float streamHz() { return streamRate; }

bool startDark() {
  if (!found || darkPhase != DARK_IDLE) return false;
  laserWasOn = laser::isOn();
  laser::set(false);
  phaseStart = millis();
  darkPhase = DARK_SETTLE;
  return true;
}

void clearDark() {
  haveDark = false;
  dark[REF] = dark[OUT] = 0;
}

bool darkBusy() { return darkPhase != DARK_IDLE; }

bool setRange(float fsr) {
  if (fsr <= 0) { fixedIdx = -1; return true; }
  for (int r = 0; r < NUM_RANGES; r++) {
    if (fabsf(RANGES[r].fsr - fsr) < 0.001f) {
      fixedIdx = r;
      for (int c = 0; c < NUM_CHANNELS; c++) rangeIdx[c] = r;
      resetAverages();
      return true;
    }
  }
  return false;
}

float fixedRange() { return fixedIdx < 0 ? 0 : RANGES[fixedIdx].fsr; }

}  // namespace sensing

#include "sensing.h"

#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include "../laser/laser.h"

namespace sensing {

namespace {

Adafruit_ADS1115 ads;
bool found = false;

// ADS1115 gain ranges, coarse to fine. +-6.144 V is left out: the inputs
// can't go above the 3.3 V supply anyway.
struct Range { adsGain_t gain; float fsr; };
const Range RANGES[] = {
  { GAIN_ONE, 4.096f }, { GAIN_TWO, 2.048f }, { GAIN_FOUR, 1.024f },
  { GAIN_EIGHT, 0.512f }, { GAIN_SIXTEEN, 0.256f },
};
const int NUM_RANGES = sizeof(RANGES) / sizeof(RANGES[0]);
const uint8_t AIN[NUM_CHANNELS] = { PD_REF_CHANNEL, PD_OUT_CHANNEL };

// 860 SPS is a 1.16 ms conversion; the ADS1115's clock is only good to 10 %.
// Reading the result after a fixed wait saves polling the config register,
// so each sample costs two short I2C transactions.
const uint32_t CONVERSION_US = 1400;
// The ratio is reported as "-" with the laser off or the reference under
// this: a ratio of two dark offsets would look like good coupling.
const float MIN_REF_V = 0.010f;

int  rangeIdx[NUM_CHANNELS] = { 0, 0 };
int  fixedIdx = -1;                // -1 = auto-range
int  channel = REF;
bool converting = false;
uint32_t convStart = 0;

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

void startConversion() {
  ads.setGain(RANGES[rangeIdx[channel]].gain);
  ads.startADCReading(MUX_BY_CHANNEL[AIN[channel]], /*continuous=*/false);
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
  int16_t raw = ads.getLastConversionResults();
  converting = false;
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
  probe();
}

bool probe() {
  converting = false;
  found = ads.begin(ADS1115_ADDR, &Wire);
  if (found) {
    Wire.setClock(I2C_CLOCK_HZ);
    ads.setDataRate(RATE_ADS1115_860SPS);
  }
  return found;
}

bool present() { return found; }

void update() {
  if (!found) return;
  if (converting && micros() - convStart >= CONVERSION_US) finishConversion();
  if (!converting) startConversion();
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

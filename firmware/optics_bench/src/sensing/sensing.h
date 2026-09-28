#pragma once

// Photodiode sampling on the ADS1115: the reference and output photodiodes
// are converted in turn, one single-shot conversion at a time, so loop() never
// waits on the ADC. Each channel picks its own gain range (auto-ranging unless
// a fixed range is set) and readings are averaged between reports.
//
// Units: volts at the TIA output, dark offsets subtracted once PD DARK has run.

#include <Arduino.h>
#include "../../config.h"

namespace sensing {

enum Channel { REF = 0, OUT = 1, NUM_CHANNELS = 2 };

void begin();       // I2C + ADS1115 probe; the bench runs without it
void update();      // call every loop(): conversions, dark measurement, streaming

bool present();     // ADS1115 answered at ADS1115_ADDR
bool probe();       // retry begin() (the board may have been plugged in later)

// Mean of the samples since the last report, then starts a new average.
// Falls back to the latest sample if none arrived in between.
String report();    // "PD REF=.. OUT=.. RATIO=.. FSR=.. N=.. DARK=.. LASER=.."

bool setStream(float hz);       // 0 = off
float streamHz();

bool startDark();               // laser off, average, laser back as it was
void clearDark();
bool darkBusy();

// fsr <= 0: auto-range. Otherwise one of 4.096 2.048 1.024 0.512 0.256.
bool setRange(float fsr);
float fixedRange();             // 0 when auto

}  // namespace sensing

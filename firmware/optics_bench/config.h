#pragma once

// Bench-wide settings: pin map, bus addresses, motor defaults and limits.
// Every pin the firmware touches is set here.
//
// Pins marked "from featherv2" are the ones the KineoLabs Feather V2 carrier
// used for its two TMC2209 slots. Pins marked "PLACEHOLDER" were picked from
// the Feather V2's free pads and must be checked against the real wiring.

#include <Arduino.h>

#define FW_VERSION "0.1.0"

// ── Host serial (USB) ────────────────────────────────────────────────────────
#define SERIAL_BAUD 115200

// ── TMC2209 shared single-wire UART ─────────────────────────────────────────
// All four drivers hang on one bus. ESP32 RX goes straight to the shared
// PDN_UART line, ESP32 TX goes to it through a 1 kOhm resistor.
// Each driver gets its own address (0-3) from its MS1/MS2 straps:
//   addr 0: MS1=GND  MS2=GND     addr 1: MS1=3V3  MS2=GND
//   addr 2: MS1=GND  MS2=3V3     addr 3: MS1=3V3  MS2=3V3
#define TMC_SERIAL   Serial1
#define TMC_RX_PIN   7        // from featherv2 (RX pad)
#define TMC_TX_PIN   8        // from featherv2 (TX pad)
#define TMC_BAUD     115200
#define R_SENSE      0.11f    // sense resistor on most TMC2209 modules (BTT, FYSETC)
#define TMC_EXPECTED_VER 0x21 // IOIN version byte of a TMC2209

// A driver that doesn't answer on the UART runs on its pin-strapped defaults
// (MS1/MS2 then pick 8-64x microstepping, current comes from the VREF pot),
// so moves on that axis are refused. Set true only to spin a motor while the
// UART wiring is being debugged; positions will then be wrong by the
// microstep ratio.
#define ALLOW_MOVES_WITHOUT_UART false

// ── Motor axes ──────────────────────────────────────────────────────────────
// Two motors per mirror: X and Y adjusters on M1 and M2. Which adjuster is
// "X" is up to the wiring; rename here if it reads better another way.
// invert: flips the positive direction in software instead of rewiring.
// EN is active low on the TMC2209. GPIO 12 is an ESP32 boot strapping pin:
// it must not be pulled high at reset (no external pull-up on EN).
struct AxisPins {
  const char *name;
  uint8_t step, dir, en;
  uint8_t addr;     // TMC2209 UART address from MS1/MS2
  bool invert;
};

#define NUM_AXES 4
constexpr AxisPins AXIS_PINS[NUM_AXES] = {
  //  name   STEP DIR EN  addr invert
  { "M1X",   4,  13, 12,  0,  false },   // from featherv2 slot M1
  { "M1Y",  27,  33, 15,  1,  false },   // from featherv2 slot M2
  { "M2X",  32,  14, 25,  2,  false },   // PLACEHOLDER (old TFT CS / DC / RST pads)
  { "M2Y",  26,   5, 19,  3,  false },   // PLACEHOLDER (old TFT backlight / SCK / MOSI pads)
};

// ── Laser ───────────────────────────────────────────────────────────────────
// Drives the laser module's TTL/enable input or a MOSFET/transistor that
// switches its supply. A GPIO can't power the module directly.
#define LASER_PIN         21      // PLACEHOLDER (MI pad)
#define LASER_ACTIVE_HIGH true    // false if the enable input is active low

// ── Stepping ────────────────────────────────────────────────────────────────
// NEMA 8, 1.8 deg. The driver interpolates every setting to 256x internally
// (intpol), so 16x is as smooth as it gets while keeping pulse rates low.
// Positions on the serial protocol are in microsteps at this setting.
#define FULL_STEPS_PER_REV 200
#define MICROSTEPS         16
#define USTEPS_PER_REV     (FULL_STEPS_PER_REV * MICROSTEPS)   // 3200

// Motor current. The 8HS15-0604S class is rated 0.6 A per phase; 350 mA RMS
// is about 0.5 A peak. Hold current is a fraction of run current and kicks
// in ~0.2 s after the last step (TPOWERDOWN).
#define RUN_CURRENT_MA   350
#define MAX_CURRENT_MA   420      // ceiling for the CURRENT command
#define HOLD_MULTIPLIER  0.5f

// Speeds in adjuster turns per minute (= motor RPM, direct drive).
// A 100 TPI adjuster moves 0.254 mm per turn.
#define DEFAULT_RPM       30.0f
#define MAX_RPM          120.0f   // 120 RPM x 3200 = 6.4 kHz STEP per axis
#define DEFAULT_ACCEL_RPM_S 120.0f  // RPM gained per second

#define ENABLE_SETTLE_MS 180      // StealthChop standstill calibration after EN low

// ── Soft limits ─────────────────────────────────────────────────────────────
// The CAD check found only ~4 turns of hex engagement one way and ~8 the
// other before the bit bottoms out or pulls out of the adjuster. Limits are
// relative to the zero position (ZERO command) and stored in flash with it.
// ABS_LIMIT_TURNS caps what the LIMITS command will accept.
#define DEFAULT_MIN_TURNS -3.0f
#define DEFAULT_MAX_TURNS  3.0f
#define ABS_LIMIT_TURNS    8.0f

// ── Host safety ─────────────────────────────────────────────────────────────
// A continuous JOG stops unless the host repeats it within this window, so a
// crashed GUI can't leave a motor running to its limit.
#define JOG_TIMEOUT_MS 400

// Positions are written to flash this long after all motion stops.
#define POS_SAVE_DELAY_MS 1000

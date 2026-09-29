#pragma once

// Bench-wide settings: pin map, bus addresses, motor defaults and limits.
// Every pin the firmware touches is set here.
//
// Board: Adafruit ESP32 Feather V2 (product 5400). Drivers: 4x Adafruit
// TMC2209 breakout (product 6121). Laser: Quarton VLM-635-32 LPT.
// Wiring diagram and pin table: electronics/wiring.md.
// M1X/M1Y use the pins of the two TMC2209 slots in the earlier featherv2
// sketch; the rest were picked from the Feather V2's free pads.

#include <Arduino.h>

#define FW_VERSION "0.1.0"

// ── Host serial (USB) ────────────────────────────────────────────────────────
#define SERIAL_BAUD 115200

// ── TMC2209 shared single-wire UART ─────────────────────────────────────────
// All four breakouts' UART pins join on one bus. ESP32 RX goes straight to
// it, ESP32 TX goes to it through a 1 kOhm resistor (the Adafruit breakout
// has no resistor of its own on UART). Each driver gets its own address
// (0-3) from its MS1/MS2 pins, which have no pull resistors on the breakout,
// so tie each one to 3V3 or GND:
//   addr 0: MS1=GND  MS2=GND     addr 1: MS1=3V3  MS2=GND
//   addr 2: MS1=GND  MS2=3V3     addr 3: MS1=3V3  MS2=3V3
#define TMC_SERIAL   Serial1
#define TMC_RX_PIN   7        // Feather V2 RX pad
#define TMC_TX_PIN   8        // Feather V2 TX pad
#define TMC_BAUD     115200
#define R_SENSE      0.05f    // Adafruit 6121 sense resistors (R1/R2). BTT/FYSETC modules use 0.11
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
// EN is active low. The breakout pulls EN low (20k), so a driver is enabled
// until the firmware drives EN high at boot. That pull-down also keeps
// GPIO 12, an ESP32 boot strapping pin, low at reset as it must be.
// GPIO 13 also drives the Feather's red LED, which flickers with M1X DIR.
struct AxisPins {
  const char *name;
  uint8_t step, dir, en;
  uint8_t addr;     // TMC2209 UART address from MS1/MS2
  bool invert;
};

#define NUM_AXES 4
constexpr AxisPins AXIS_PINS[NUM_AXES] = {
  //  name   STEP DIR EN  addr invert
  { "M1X",   4,  13, 12,  0,  false },   // pads A5, 13, 12
  { "M1Y",  27,  33, 15,  1,  false },   // pads 27, 33, 15
  { "M2X",  32,  14, 25,  2,  false },   // pads 32, 14, A1
  { "M2Y",  26,   5, 19,  3,  false },   // pads A0, SCK, MO
};

// On the control board (electronics/pcb) each driver's DIAG output also reaches an
// input-only pin: M1X GPIO 34 (A2), M1Y 39 (A3), M2X 36 (A4), M2Y 37. Not used yet.

// ── Laser ───────────────────────────────────────────────────────────────────
// Quarton VLM-635-32 LPT: 3-6 V supply (< 40 mA, from the Feather's 3V3),
// TTL input high = on, 1-20 mA, so a GPIO drives it directly.
#define LASER_PIN         21      // MI pad
#define LASER_ACTIVE_HIGH true

// ── Photodiodes and ADC ─────────────────────────────────────────────────────
// Two BPW34 photodiodes, each on its own transimpedance amp (MCP6002, one
// half used) run from 3V3, read by an Adafruit ADS1115 (product 1085) on the
// Feather's I2C pads. The Feather V2 powers its STEMMA QT port from GPIO 2,
// which the board package switches on before setup().
//   AIN0: reference photodiode (beamsplitter's reflected port)
//   AIN1: output photodiode (behind the fiber)
// Vout = I_photo x feedback resistor, so 47 kOhm puts the full 3.3 V swing
// at 70 uA, about 175 uW of 635 nm light on a BPW34 (the laser is < 1 mW).
// The ADS1115's own gain ranges (+-4.096 V down to +-0.256 V) cover the dim
// end: 1 LSB at the finest range is 7.8 uV, about 0.4 nW. If a channel sits
// near 3.3 V, fit a smaller resistor on that board and change it here; the
// GUI turns volts into uW with these values.
#define I2C_SDA_PIN     22
#define I2C_SCL_PIN     20
#define I2C_CLOCK_HZ    400000
#define ADS1115_ADDR    0x48      // ADDR pin to GND
#define PD_REF_CHANNEL  0
#define PD_OUT_CHANNEL  1
#define PD_REF_TIA_OHMS 47000.0f  // feedback resistor, reference TIA board
#define PD_OUT_TIA_OHMS 47000.0f  // feedback resistor, output TIA board
#define PD_RESPONSIVITY 0.40f     // BPW34 at 635 nm, A/W (datasheet curve, approximate)
#define PD_DARK_SAMPLES 32        // samples per channel for PD DARK
#define PD_SETTLE_MS    30        // after switching the laser, before sampling
#define PD_MAX_STREAM_HZ 50

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

// Coil release, as in the featherv2 sketch: a motor is energised for a move
// and released (EN high, no coil current) once it has been still for
// RELEASE_DELAY_MS, so the motors don't sit warm between moves. The 100 TPI
// adjuster screws don't back-drive, so the mirror stays put. The delay keeps
// a burst of nudges from paying the enable settle on every one. ENABLE holds
// a motor energised until DISABLE. Set AUTO_RELEASE false to keep motors
// energised (at hold current) after every move instead.
#define AUTO_RELEASE     true
#define RELEASE_DELAY_MS 500

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

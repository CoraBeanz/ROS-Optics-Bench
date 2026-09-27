# ROS-Optics-Bench

A small, mostly 3D-printed optical bench that couples a red laser into an optical fiber by itself. Knock a mirror out of alignment and it steers its way back to maximum coupling without anyone touching a knob.

![Top-view bench layout](docs/images/bench_layout.svg)

## How it works

- **Light path:** a 635 nm laser passes two crossed polarizers (a brightness knob) and a beamsplitter that sends a slice to a reference photodiode. Two kinematic mirrors, M1 and M2, fold the beam in a Z. An 8 mm aspheric lens on a micrometer stage focuses it into a fixed FC fiber connector, and the fiber loops to an output photodiode.
- **Actuation:** each mirror's tip and tilt adjusters are turned by a NEMA 8 stepper through a hex bit, giving four motorized axes. Mirrors 150 mm apart control both the beam's angle and its position at the fiber.
- **Score:** output power divided by reference power, which cancels laser flicker. An optimizer steers the four axes to maximize it.
- **Mechanics:** everything sits on a doweled, printed base so parts can be removed and replaced repeatably.

## Phases

1. **Beam steering.** Motorize the mirrors and use a camera plus two irises to put the beam on a known axis by spot position.
2. **Fiber coupling.** Swap the camera for the lens and fiber, then climb to maximum coupled power. Start with multimode fiber, then move to single-mode.
3. **Demo.** Bump a mirror and watch it recover.

## Electronics

| Part | Role |
| --- | --- |
| Adafruit ESP32 Feather V2 | Real-time side: steppers, soft limits, photodiode sampling |
| 4x Adafruit TMC2209 breakout on one UART bus | Stepper drivers |
| ADS1115 (16-bit ADC) + BPW34 photodiodes with TIA | Reference and output power |
| Jetson (ROS 2) | Camera, optimizer, experiment control |
| Arducam OV9281 (global shutter, UVC) | Beam profiler for phase 1 |

## Repository layout

```
cad/                   Mechanical CAD (Onshape STEP exports)
  assemblies/          Full assemblies, e.g. the motor-mirror assembly
  parts/               Individual printed or machined parts
  print/               STL / 3MF files ready to slice
  vendor/              Purchased-part models (motors, mounts, optics)
docs/                  Notes, drawings, bench layout, test results
electronics/           Wiring diagrams, schematics, pinouts
firmware/optics_bench/ Arduino IDE sketch for the ESP32
  optics_bench.ino     setup() and loop()
  config.h             Pin map, bus addresses, motor limits
  src/motion/          TMC2209 drivers, stepping, homing, soft limits
  src/sensing/         ADS1115 reads, photodiode ratio
  src/comms/           Serial protocol to the host
host/ros2_ws/src/      ROS 2 packages for the Jetson
tools/                 Bench scripts: calibration, hysteresis tests, plotting
```

## Building the firmware

1. In the Arduino IDE, install the ESP32 boards package (Boards Manager, "esp32" by Espressif).
2. Install the libraries below with the Library Manager.
3. Open `firmware/optics_bench/optics_bench.ino`.
4. Select your ESP32 board and port, then Upload. Serial Monitor runs at 115200 baud with newline line endings.

Code in `src/` is compiled with the sketch automatically. Record any library added through the Library Manager here so the build can be reproduced.

| Library | Version | Used for |
| --- | --- | --- |
| TMCStepper (teemuatlut) | 0.7.3 | TMC2209 register setup over UART |
| AccelStepper (Mike McCauley) | 1.64 | Ramped STEP/DIR motion |

Every pin is set in `firmware/optics_bench/config.h`. The wiring diagram and full pin table for the Feather ESP32 V2, the four Adafruit TMC2209 breakouts and the laser are in [electronics/wiring.md](electronics/wiring.md).

## Bench test panel

`tools/bench_gui.py` is a small desktop app for the first bench tests: laser on/off, and jog, nudge and go-to for the four mirror motors.

```
pip install -r tools/requirements.txt
python tools/bench_gui.py          # pick the ESP32's COM port, Connect
python tools/bench_gui.py --sim    # try it without hardware
```

- **Positions** are in microsteps, 3200 per adjuster turn. One turn of a 100 TPI adjuster is 254 um, so a full step is about 1.3 um of screw travel.
- **Zero and soft limits.** "Set 0" calls the current knob position zero. The soft limits (default -3 to +3 turns, adjustable up to +-8) stay relative to zero, because the hex bit only has about 4 turns of engagement one way. Positions and limits are saved to flash and survive a power cycle. If power drops mid-move, the panel warns that positions may be off.
- **Hold-to-jog** (the double arrows) keeps a motor running while the button is held. The firmware stops it by itself if the panel stops refreshing the jog, so a crashed GUI can't run a motor to its limit.
- **Keys:** arrows move M1 (Left/Right = M1X, Down/Up = M1Y), A/D and S/W move M2X and M2Y by the selected step, L toggles the laser, Esc stops everything.
- **Diag** shows the TMC2209 status (current, StealthChop, overtemperature, short and open-load flags). A driver that doesn't answer on the UART shows a red dot and refuses to move.

The serial protocol is plain text and documented in `firmware/optics_bench/src/comms/protocol.h`, so the Serial Monitor or the Jetson can use the same commands.

### First power-up checklist

1. Flash the firmware and connect. A driver whose 12 V supply is off doesn't answer on the UART, so it shows a red dot and a "driver offline" warning.
2. With the 12 V supply on, send `REPROBE ALL` (or just move the axis, which retries). The dots should go green, and the connection bar should say `slots=ok`.
3. Take the hex bits out of the adjusters and nudge each motor by 1/4 turn to check which way positive turns. Flip it with `invert` in `config.h` if needed.
4. Refit the bits, "Set 0" on each axis, and start aligning.

## Status

Bench testing. The firmware drives the laser and the four mirror motors, and `tools/bench_gui.py` is the test panel. Photodiode sensing and the ROS 2 host side have not been started.

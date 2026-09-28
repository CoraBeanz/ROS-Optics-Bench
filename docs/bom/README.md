# Bill of materials

Generated from [`bom.csv`](bom.csv) by `tools/make_bom_md.py`. Edit the CSV, not this file.

This is the NEMA 8 build (the current Motor-Mirror Assembly). Prices are Sept 2026 estimates
in USD, not quotes; blank means already owned or not priced.

Status: **Have** = on the bench, **Print** = 3D printed, **To buy**, **Check** = confirm
whether it is already on hand, **TBD** = part not chosen yet.

## Electronics

| ID | Item | Spec | Qty | Est. unit ($) | Source | Status | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | MCU | Adafruit ESP32 Feather V2 (product 5400) | 1 |  | Adafruit | Have | 1 | Runs the Arduino IDE sketch in firmware/optics_bench |
| E2 | Stepper driver | Adafruit TMC2209 breakout (product 6121) | 4 |  | Adafruit | Have | 1 | R_SENSE is 0.05 ohm. One shared UART bus; strap MS1/MS2 for addresses 0-3 |
| E3 | UART bus resistor | 1 kOhm 1/4 W | 1 |  | Stock | Have | 1 | Feather TX to the driver UART bus |
| E4 | Driver bulk capacitor | 100 uF 25 V electrolytic | 4 |  | Stock | Check | 1 | One across VM/GND at each driver |
| E5 | Driver carrier | Perfboard + female headers | 1 | 8 | Amazon | Check | 1 |  |
| E6 | Motor supply | 12 V 2 A DC | 1 | 8 | Amazon | Check | 1 | Skip if using a bench supply. Drivers only answer UART with 12 V on |
| E7 | Laser | Quarton VLM-635-32 LPT 635 nm module (Amazon B07QCTMMVT) | 1 |  | Amazon | Have | 1 | TTL high = on from GPIO 21. Measured beam about 7 x 3 mm |
| E8 | ADC | Adafruit ADS1115 16-bit I2C breakout (product 1085) | 1 | 15 | Adafruit | Check | 2 | Address 0x48 (ADDR to GND). Plugs into the Feather STEMMA QT port. Adafruit ADS1X15 library |
| E9 | Photodiode | BPW34 Si PIN (5-pack) | 1 | 7 | Amazon / DigiKey | Check | 2 | One on each photodiode board: reference (ADS1115 A0) and fiber output (A1) |
| E10 | TIA op-amp | MCP6002 dual op-amp, DIP-8 | 2 | 0.5 | DigiKey | Check | 2 | One per photodiode board; half B unused, wired as a grounded follower |
| E11 | Hookup | Wire, headers, Dupont/JST connectors | 1 |  | Stock | Have | 1 |  |
| E12 | TIA feedback resistor | 47 kOhm 1% | 2 |  | Stock / DigiKey | Check | 2 | Rf on each board. Keep a few 10 kOhm on hand in case a channel saturates near 3.3 V (then update PD_*_TIA_OHMS in config.h) |
| E13 | TIA feedback capacitor | 1 nF C0G | 2 |  | Stock / DigiKey | Check | 2 | Cf across Rf; 47 us, about 3.4 kHz bandwidth |
| E14 | Op-amp decoupling capacitor | 100 nF ceramic | 2 |  | Stock / DigiKey | Check | 2 | Between MCP6002 pins 8 and 4, at the chip |
| E15 | Photodiode board | Small perfboard + short twisted pair to the ADS1115 | 2 |  | Stock / DigiKey | Check | 2 | Mounted right behind each diode; leads under 10 mm |
| E16 | STEMMA QT cable | JST SH 4-pin, 100 mm | 1 | 1 | Adafruit | Check | 2 | ADS1115 to the Feather STEMMA QT port |

## Motion

| ID | Item | Spec | Qty | Est. unit ($) | Source | Status | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M1 | Stepper motor | NEMA 8, 20 mm frame, 4 mm shaft, 0.6 A, 4-lead (StepperOnline 8HS15-0604S class) | 4 | 22 | Amazon | Have | 1 | Assembly model uses a 30 mm body. Longer body = more torque margin |
| M2 | Shaft adapter | Brass 3-to-4 mm adapter, 2x M3 set screws | 4 |  | Amazon | Have | 1 | Align one set screw with the motor D-flat |
| M3 | Drive rod | 3 mm round rod, 35 mm long, 2 mm hex tip | 4 |  | Hex key / rod stock | Have | 1 | Test-fit the tip in the adjuster socket (2.00 mm vs 5/64 in) |
| M4 | Rod bearing | 3x7x3 mm (683ZZ) | 4 |  | Amazon | Have | 1 | One per rod in the printed Motor Mount |
| M5 | Kinematic mirror mount | Compact 1 in, two 100 TPI hex adjusters (Thorlabs KMS style) | 2 |  | Thorlabs / eBay | Have | 1 | M1 and M2 in the Z-fold |
| M6 | Mirror | 1 in protected silver or aluminium | 2 |  | Thorlabs / eBay | Have | 1 |  |
| M7 | Motor screws | M2 x 4-5 mm | 8 |  | Amazon | Check | 1 | The M2x3 in the CAD model is too short; confirm what is fitted |
| M8 | Fastener kit | M3 screws + M3 heat-set inserts | 1 | 14 | Amazon | To buy | 1 | Brackets and base |
| M9 | Motor Mount | 3D printed (PETG) | 2 |  | Printer | Print | 1 | cad/assemblies Motor-Mirror Assembly |

## Optics

| ID | Item | Spec | Qty | Est. unit ($) | Source | Status | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | Laser aperture | Printed plate, 2 mm hole | 1 |  | Printer | Print | 1 | 10-20 mm after the laser; trims the 7 x 3 mm beam |
| O2 | Polarizer film | Linear polarizer sheet (two pieces) | 1 | 8 | Amazon | To buy | 1 | Variable attenuator. Rotate only the first one |
| O3 | Beamsplitter | Plate or cube beamsplitter | 1 |  | TBD | TBD | 1 | Reflected port feeds the reference PD |
| O4 | Iris plates | Printed, 1.5 mm (also 1, 2, 3 mm) | 2 |  | Printer | Print | 1 | Print undersize and ream |
| O5 | Beam camera | Arducam OV9281 global-shutter UVC (B0332 class) | 1 | 40 | Amazon | Check | 1 | Remove the M12 lens; bare sensor as beam profiler |
| O6 | PD diffuser | Ground glass or frosted tape | 1 |  | Stock | To buy | 2 | 5-10 mm in front of the reference PD |

## Fiber

| ID | Item | Spec | Qty | Est. unit ($) | Source | Status | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | Practice fiber | SMF-28 patch cable, FC/UPC, 1-3 m | 1 | 8 | Amazon / FS.com | To buy | 2 |  |
| F2 | Multimode fiber | 50/125 um patch cable, FC-FC, 1 m | 1 | 8 | Amazon / FS.com | To buy | 2 | First-light target |
| F3 | Single-mode fiber for red | Thorlabs P1-630A-FC-1 (630HP) | 1 | 90 | Thorlabs | To buy | 2 | Price not verified |
| F4 | FC bulkhead adapters | FC/FC square flange (5-pack) | 1 | 8 | Amazon | To buy | 2 | Fixed reference at the fiber and the output PD |
| F5 | Coupling lens | Glass asphere, f 8-11 mm, M9x0.5 cell | 2 | 6 | Amazon / AliExpress | To buy | 2 |  |
| F6 | Focus stage | 40 x 40 mm micrometer linear stage, 10+ mm travel | 1 | 30 | Amazon | To buy | 2 | Moves the lens |
| F7 | Fiber cleaner | One-click FC cleaner | 1 | 10 | Amazon | To buy | 2 | Nice to have |

## Base

| ID | Item | Spec | Qty | Est. unit ($) | Source | Status | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | Bench base | Printed doweled sections, 25 mm insert grid | 1 |  | Printer | Print | 1 | About 420 x 260 mm; matte black near the beam |
| B2 | Dowel pins | Steel dowels for V-grooves | 1 | 8 | Amazon | To buy | 1 | About 50 um repeatability |

## Host

| ID | Item | Spec | Qty | Est. unit ($) | Source | Status | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | Host computer | NVIDIA Jetson | 1 |  |  | Check | 1 | Camera + optimizer (ROS 2) |
| H2 | Bench instrument | Analog Discovery 3 | 1 |  |  | Check | 2 | Bench checks of the TIA and ADC |

**Estimated spend on To buy lines: $196** (excludes Check and TBD lines).

## Alternate: NEMA 11 build

Fall back to this if the knob torque test shows the adjusters need more than about 4 mN-m.
It swaps these lines; everything else stays the same.

| Replaces | With | Qty | Est. unit ($) |
| --- | --- | --- | --- |
| M1 NEMA 8 motor | NEMA 11, 28 mm frame, 45-51 mm body, 5 mm shaft, 10+ N-cm (StepperOnline 11HS20-0674S class) | 4 | 16 |
| M2 3-to-4 mm adapter | 5 mm to 5 mm shaft coupler | 4 | 3 |
| M3 3 mm drive rod | 5 mm steel rod, 100-200 mm, with bonded hex tip | 2 | 4 |
| M7 M2 motor screws | M3 screws (NEMA 11 flange) | 8 | |
| E6 12 V 2 A supply | 12 V 3 A supply | 1 | 10 |

The Motor Mount must be redrawn for the larger frame.

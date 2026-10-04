# Assemblies

| File | What it is |
| --- | --- |
| `ros_laser_bench_main_assembly.step` | The whole bench as built in Onshape: breadboard, optics, both motor-mirror assemblies and the electronics, in place (STEP AP242, about 28 MB) |

![Bench overview](../../docs/images/bench_cad_overview.png)

The file keeps Onshape's assembly tree, so it opens in any CAD tool with every subassembly and part separate and named. Part Studios have no equivalent in STEP, so each part sits under the subassembly it was inserted into. Only parts placed in the assembly are included.

## What's in the main assembly

Listed in beam order, with the Onshape name of each subassembly.

| Subassembly | Count | Role on the bench |
| --- | --- | --- |
| `Laser Assembly` | 1 | 635 nm laser module in its tube, lens holder and mount |
| `2 mm aperture` | 1 | Printed aperture just after the laser, trims the 7 x 3 mm beam |
| `Linear Polarizer Assembly` | 1 | Polarizer film in a holder on a Y mount (attenuator) |
| `Assembly 1` | 1 | Beamsplitter with its mount, clamp and backing; sends a slice of the beam to the reference photodiode |
| `Photodiode Mount Assembly` | 2 | Photodiode on an 18 mm post: one on the beamsplitter's reflected port (reference), one behind the output fiber |
| `Motor-Mirror Assembly` | 2 | M1 and M2: a kinematic mount with a silver mirror, tip and tilt turned by two NEMA 8 motors through 2 mm hex rods |
| `1 mm aperture` | 2 | The two printed irises that define the beam axis |
| `Lens Mount Assembly` | 1 | Asphere in its holder on an 18 mm post (focusing lens; the OV9281 camera takes its place in phase 1) |
| `Fiber Mount Assembly` | 2 | FC bulkhead on a 17 mm post: the input fiber at the lens focus, and the fiber output at the output photodiode |
| `Electronics Assembly` | 1 | Control board with the Feather, four TMC2209 breakouts and the ADS1115, plus one photodiode amp board |
| `Optical Breadboard` | 1 | The printed base: four tiles on the 25 mm hole grid, with the parts that join them |

Each `Motor-Mirror Assembly` contains the motor mount, two NEMA 8 motors, two 3-to-4 mm brass adapters with M3 set screws, two 3x7x3 bearings, two hex rods, eight M2x3 screws, the kinematic mirror mount and the mirror.

Notes on the model:
- The Feather in `Electronics Assembly` is Adafruit's ESP8266 Feather model (2821), standing in for the ESP32 Feather V2 the firmware targets. The two boards share the Feather outline and header positions.
- The control board and photodiode amp models are the KiCad exports in [`cad/parts/pcb`](../parts/pcb/README.md).
- The photodiodes are placeholders (`Dummy PhotoDiode`).

To update, export the main assembly from Onshape as STEP with **Flatten assembly** unticked, replace the file here, and say what changed in the commit message.

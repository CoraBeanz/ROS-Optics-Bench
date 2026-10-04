# CAD

Mechanical design lives in Onshape. This folder holds STEP exports so the repo has a snapshot of the hardware that matches the code.

- `assemblies/`: full assemblies, e.g. `motor-mirror-assembly.step`
- `parts/`: single parts, printed or machined
- `print/`: STL or 3MF files ready to slice
- `vendor/`: models of purchased parts (NEMA 8 motors, mirror mounts, lens tubes)
- `pcb/`: STEP models of the KiCad boards in `electronics/pcb/`, plus a 3D render of each

Re-export and commit a STEP file whenever the Onshape model changes in a way the firmware or bench notes depend on, and say what changed in the commit message.

## PCB models

`pcb/control_board.step` and `pcb/pd_amp.step` are exported from KiCad 10 with board body and component 3D models (no copper or silkscreen, to keep the files small). The board origin is the board centre.

Parts with no model in the STEP files:

- The plug-in modules: Feather ESP32 V2, the four TMC2209 breakouts and the ADS1115. Only their header sockets are modelled.
- F1, the Bourns MF-RHT200 polyfuse (KiCad has no 3D model for it).
- D1 on the photodiode board, the BPW34 (KiCad has no 3D model for the Osram DIL2 package).

To re-export after a board change (KiCad 10, from the repo root):

```
kicad-cli pcb export step -f -o cad/pcb/control_board.step electronics/pcb/control_board/control_board.kicad_pcb
kicad-cli pcb export step -f -o cad/pcb/pd_amp.step electronics/pcb/pd_amp/pd_amp.kicad_pcb
```

# CAD

Mechanical design lives in Onshape. This folder holds STEP exports so the repo has a snapshot of the hardware that matches the code.

- `assemblies/`: full assemblies, e.g. `motor-mirror-assembly.step`
- `parts/`: single parts, printed or machined
- `print/`: STL or 3MF files ready to slice
- `vendor/`: models of purchased parts (NEMA 8 motors, mirror mounts, lens tubes)

Re-export and commit a STEP file whenever the Onshape model changes in a way the firmware or bench notes depend on, and say what changed in the commit message.

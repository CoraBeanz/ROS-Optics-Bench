# CAD

Mechanical design lives in Onshape. This folder holds STEP exports so the repo has a snapshot of the hardware that matches the code.

- `assemblies/`: full assemblies, starting with the whole bench in `ros_laser_bench_main_assembly.step` (see [assemblies/README.md](assemblies/README.md))
- `parts/`: single parts, printed or machined, and the PCB models in `parts/pcb`
- `print/`: STL or 3MF files ready to slice
- `vendor/`: models of purchased parts (NEMA 8 motors, mirror mounts, lens tubes)

Re-export and commit a STEP file whenever the Onshape model changes in a way the firmware or bench notes depend on, and say what changed in the commit message.

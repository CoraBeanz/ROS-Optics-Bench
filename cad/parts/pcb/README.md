# PCB models

STEP exports of the boards in `electronics/pcb`, for importing into Onshape:

| File | Board |
| --- | --- |
| `control_board.step` | Control board rev B, 100 x 100 x 1.6 mm, with the parts and the female sockets fitted |
| `pd_amp.step` | Photodiode amp board, 34.3 x 25.4 x 1.6 mm, with its parts fitted |

These parts have no 3D model:
- The Feather, the TMC2209 breakouts and the ADS1115. Only their sockets are modelled. Adafruit publishes models for the boards themselves.
- F1, the PTC fuse on the control board.
- D1, the BPW34 on the photodiode board.

To regenerate after a board change, run this once for each board:

```
kicad-cli pcb export step -f --subst-models --include-silkscreen -o cad/parts/pcb/control_board.step electronics/pcb/control_board/control_board.kicad_pcb
```

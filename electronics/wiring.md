# Wiring: ESP32, motor drivers and laser

![Wiring diagram](wiring.svg)

Parts:

- [Adafruit ESP32 Feather V2](https://www.adafruit.com/product/5400) (product 5400)
- 4x [Adafruit TMC2209 stepper driver breakout](https://www.adafruit.com/product/6121) (product 6121)
- Quarton VLM-635-32 LPT laser module (635 nm, TTL modulation)

The pins match `firmware/optics_bench/config.h`. If you change a pin there, change it here too, and regenerate the diagram with `python electronics/make_wiring_svg.py electronics/wiring.svg`.

## Feather ESP32 V2 pins

| Feather pad | GPIO | Goes to |
| --- | --- | --- |
| 3V3 | | VDD on all four drivers, MS1/MS2 straps that are tied high, laser +V |
| GND | | GND on all four drivers, laser GND, 12 V supply minus |
| RX | 7 | UART bus (direct) |
| TX | 8 | UART bus through a 1 kOhm resistor |
| A5 | 4 | M1X STEP |
| 13 | 13 | M1X DIR (also the Feather's red LED, so it flickers) |
| 12 | 12 | M1X EN |
| 27 | 27 | M1Y STEP |
| 33 | 33 | M1Y DIR |
| 15 | 15 | M1Y EN |
| 32 | 32 | M2X STEP |
| 14 | 14 | M2X DIR |
| A1 | 25 | M2X EN |
| A0 | 26 | M2Y STEP |
| SCK | 5 | M2Y DIR |
| MO | 19 | M2Y EN |
| MI | 21 | Laser TTL |
| SDA / SCL | 22 / 20 | Free, kept for the ADS1115 |

## TMC2209 breakouts

Header pins in board order. Each driver's MS1/MS2 pins set its UART address.

| Pin | M1X (addr 0) | M1Y (addr 1) | M2X (addr 2) | M2Y (addr 3) |
| --- | --- | --- | --- | --- |
| 1 VDD | 3V3 | 3V3 | 3V3 | 3V3 |
| 2 GND | GND | GND | GND | GND |
| 3 DIR | GPIO 13 | GPIO 33 | GPIO 14 | GPIO 5 (SCK) |
| 4 STEP | GPIO 4 (A5) | GPIO 27 | GPIO 32 | GPIO 26 (A0) |
| 5 MS1 | GND | 3V3 | GND | 3V3 |
| 6 MS2 | GND | GND | 3V3 | 3V3 |
| 7 DIAG | not connected | not connected | not connected | not connected |
| 8 INDEX | not connected | not connected | not connected | not connected |
| 9 UART | UART bus | UART bus | UART bus | UART bus |
| 10 EN | GPIO 12 | GPIO 15 | GPIO 25 (A1) | GPIO 19 (MO) |

Screw terminals on each breakout:

| Terminal | Goes to |
| --- | --- |
| + (VMotor) | 12 V supply plus |
| - (GND) | 12 V supply minus |
| 1A / 1B | One motor coil |
| 2A / 2B | The other motor coil |

## Laser (Quarton VLM-635-32 LPT)

| Laser wire | Goes to |
| --- | --- |
| +V | Feather 3V3 (module runs on 3-6 V and draws under 40 mA) |
| GND | Feather GND |
| TTL | Feather MI (GPIO 21). High turns the laser on. The input takes 1-20 mA, which a GPIO can drive directly. |

Check which wire is which on the module's label. Red is usually +V and black is usually GND.

## Things to know

- **One ground.** The 12 V supply minus, the Feather GND and every breakout GND must all be connected together.
- **UART bus.** The Adafruit breakout connects its UART pin straight to the chip with no resistor. Join all four UART pins into one bus. Connect the Feather RX to the bus directly and the Feather TX through a 1 kOhm resistor.
- **Addresses.** MS1 and MS2 have no pull resistors on the breakout. Tie every one of them to 3V3 or GND as shown above; don't leave them floating.
- **12 V comes first for UART.** The TMC2209 runs its logic from the motor supply, so a driver doesn't answer on UART until 12 V is on. The firmware retries when you move that axis, or you can send `REPROBE ALL`.
- **Sense resistors are 0.05 Ohm** on this breakout, not the 0.11 Ohm used on BTT/FYSETC modules. `config.h` has `R_SENSE 0.05f`. With the wrong value the motors would get almost double the current you set.
- **Current pot and SPREAD jumper.** The firmware sets the motor current and StealthChop over UART, so the pot does nothing. Leave the SPREAD solder jumper open.
- **EN at power-up.** The breakout pulls EN low (a 20 kOhm resistor), so the drivers are enabled until the firmware boots and drives EN high. That pull-down also keeps GPIO 12 low at reset, which the ESP32 needs to boot.
- **Motor coils.** To find a coil pair, measure resistance between the motor's wires. The two wires with a few ohms between them are one coil: put them on 1A/1B and the other pair on 2A/2B. If a motor turns the wrong way, set `invert` for that axis in `config.h` instead of rewiring.
- Never plug or unplug a motor while the 12 V supply is on.

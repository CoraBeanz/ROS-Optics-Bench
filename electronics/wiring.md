# Wiring: ESP32, motor drivers, laser and photodiodes

![Wiring diagram](wiring.svg)

Parts:

- [Adafruit ESP32 Feather V2](https://www.adafruit.com/product/5400) (product 5400)
- 4x [Adafruit TMC2209 stepper driver breakout](https://www.adafruit.com/product/6121) (product 6121)
- Quarton VLM-635-32 LPT laser module (635 nm, TTL modulation)
- [Adafruit ADS1115 16-bit ADC breakout](https://www.adafruit.com/product/1085) (product 1085) and a STEMMA QT cable
- 2x photodiode boards, each with a BPW34 photodiode, an MCP6002 op-amp (DIP-8), a 47 kOhm 1% resistor, a 1 nF C0G capacitor and a 100 nF decoupling capacitor

The pins match `firmware/optics_bench/config.h`. If you change a pin there, change it here too, and regenerate the diagram with `python electronics/make_wiring_svg.py electronics/wiring.svg`.

## Feather ESP32 V2 pins

| Feather pad | GPIO | Goes to |
| --- | --- | --- |
| 3V3 | | VDD on all four drivers, MS1/MS2 straps that are tied high, laser +V, ADS1115 VDD, both photodiode boards |
| GND | | GND on all four drivers, laser GND, 12 V supply minus, ADS1115 GND and ADDR, both photodiode boards |
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
| SDA | 22 | ADS1115 SDA |
| SCL | 20 | ADS1115 SCL |

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

## Photodiodes and ADC

Two BPW34 photodiodes measure the light: the reference diode sits behind the beamsplitter's reflected port and the output diode sits behind the fiber. Each diode has its own transimpedance amplifier (TIA) on a small board right behind it, which turns the photocurrent into a voltage. The ADS1115 reads both voltages and sends them to the Feather over I2C.

### ADS1115 breakout

| ADS1115 pin | Goes to |
| --- | --- |
| VDD | Feather 3V3 |
| GND | Feather GND |
| SCL | Feather SCL (GPIO 20) |
| SDA | Feather SDA (GPIO 22) |
| ADDR | GND, which sets the I2C address to 0x48 |
| ALRT | not connected |
| A0 | Vout of the reference photodiode board |
| A1 | Vout of the output photodiode board |
| A2, A3 | not connected |

A STEMMA QT cable between the ADS1115 and the Feather's STEMMA QT port carries VDD, GND, SDA and SCL in one plug. The Feather V2 powers that port from GPIO 2, which the ESP32 board package switches on at boot. Then only ADDR, A0 and A1 need wires.

### Photodiode board (build two)

| Part | Connection |
| --- | --- |
| BPW34 cathode | MCP6002 pin 2 (input A, minus) |
| BPW34 anode | GND |
| Rf 47 kOhm | Between pin 1 (output A) and pin 2 |
| Cf 1 nF C0G | Across Rf, also between pin 1 and pin 2 |
| MCP6002 pin 3 (input A, plus) | GND |
| MCP6002 pin 8 (VDD) | Feather 3V3 |
| MCP6002 pin 4 (VSS) | GND |
| 100 nF | Between pins 8 and 4, right at the chip |
| MCP6002 pin 5 | GND (half B is unused) |
| MCP6002 pin 6 | Pin 7 (half B as a grounded follower) |
| Pin 1 (Vout) | ADS1115 A0 (reference board) or A1 (output board) |

The diode works at zero bias, so the output sits at 0 V in the dark and rises as `Vout = I_photo x Rf`.

- **Finding the anode.** In room light, a multimeter on DC volts reads about +0.3 V across the diode with the red probe on the anode.
- **Why 47 kOhm.** The laser is under 1 mW. A BPW34 gives about 0.4 A/W at 635 nm, so 47 kOhm reaches the 3.3 V rail at 70 uA, about 175 uW on the diode. The ADS1115's gain ranges cover the dim end, down to about 0.4 nW per count. If a channel sits near 3.3 V, fit a smaller Rf on that board and change `PD_REF_TIA_OHMS` or `PD_OUT_TIA_OHMS` in `config.h`, because the test panel works out microwatts from those values.
- **Bandwidth.** Rf x Cf is 47 us, a 3.4 kHz bandwidth, which is much faster than the ADC samples and keeps the amplifier stable.
- **Leads.** Keep the diode leads under 10 mm, and run Vout and GND to the ADS1115 as a twisted pair.
- **Offset.** The MCP6002's input offset is a few millivolts. On a 3.3 V single supply a negative offset clips at 0 V, so the dark reading may be 0 V or a few millivolts. `PD DARK` in the firmware measures that offset with the laser off and subtracts it.

## Things to know

- **One ground.** The 12 V supply minus, the Feather GND, every breakout GND and both photodiode boards must all be connected together. Run the photodiode grounds back to the Feather rather than to the motor supply, so motor current doesn't flow through them.
- **UART bus.** The Adafruit breakout connects its UART pin straight to the chip with no resistor. Join all four UART pins into one bus. Connect the Feather RX to the bus directly and the Feather TX through a 1 kOhm resistor.
- **Addresses.** MS1 and MS2 have no pull resistors on the breakout. Tie every one of them to 3V3 or GND as shown above; don't leave them floating.
- **12 V comes first for UART.** The TMC2209 runs its logic from the motor supply, so a driver doesn't answer on UART until 12 V is on. The firmware retries when you move that axis, or you can send `REPROBE ALL`.
- **Sense resistors are 0.05 Ohm** on this breakout, not the 0.11 Ohm used on BTT/FYSETC modules. `config.h` has `R_SENSE 0.05f`. With the wrong value the motors would get almost double the current you set.
- **Current pot and SPREAD jumper.** The firmware sets the motor current and StealthChop over UART, so the pot does nothing. Leave the SPREAD solder jumper open.
- **EN at power-up.** The breakout pulls EN low (a 20 kOhm resistor), so the drivers are enabled until the firmware boots and drives EN high. That pull-down also keeps GPIO 12 low at reset, which the ESP32 needs to boot.
- **Motor coils.** To find a coil pair, measure resistance between the motor's wires. The two wires with a few ohms between them are one coil: put them on 1A/1B and the other pair on 2A/2B. If a motor turns the wrong way, set `invert` for that axis in `config.h` instead of rewiring.
- Never plug or unplug a motor while the 12 V supply is on.

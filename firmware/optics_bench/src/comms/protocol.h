#pragma once

// Line-based ASCII protocol on the USB serial port, used by
// tools/test_gui.py and later by the Jetson. One command per line,
// case-insensitive, fields separated by spaces. <ax> is M1X, M1Y, M2X, M2Y
// or 1-4; commands marked [ALL] also take ALL. Positions are in microsteps
// (INFO reports USTEPS_PER_REV; one adjuster turn at 100 TPI = 0.254 mm).
//
//   PING                      -> OK PONG
//   INFO                      -> INFO FW=.. AXES=.. USTEPS_PER_REV=.. MIN=.. MAX=.. RPM=.. ...
//                                ... TRUSTED=0|1 TRUST=a,b,c,d ...: TRUST is per axis, 0 = its
//                                position may be off (a power cut stopped it mid-move, or it
//                                moved and its driver lost power before it was next seen
//                                working), kept in flash until ZERO or SETPOS of that axis;
//                                TRUSTED=0 if any axis is untrusted. A driver that loses power
//                                while its axis sits still leaves TRUST=1
//   STATUS                    -> STATUS LASER=0 POS=a,b,c,d TGT=.. MOV=.. EN=.. DRV=..
//                                (DRV=0: driver offline or config not verified; between moves
//                                the firmware polls one driver every DRV_CHECK_PERIOD_MS)
//   LASER ON|OFF              -> OK LASER=1|0
//   MOVE <ax> <delta>         relative move, clamped to the soft limits (a delta whose
//                             target would overflow clamps too)
//   GOTO <ax> <pos>           absolute move, clamped to the soft limits
//                             MOVE/GOTO reply OK MOVE|GOTO <ax> TGT=<t> [CLAMPED]. EVT DONE
//                             follows when the axis stops if TGT differed from its position
//                             or it was moving; a GOTO to where an idle axis is sends none
//   JOG <ax> +|-              run toward a limit; stops unless repeated within
//                             JOG_TIMEOUT_MS (send it every ~100-200 ms)
//   STOP [<ax>|ALL]           ramp down (no argument = all axes)
//   HALT [<ax>|ALL]           stop on the current step, no ramp
//   ZERO <ax>|ALL             call the current position 0 and save it (limits stay
//                             relative to 0); the axis is trusted again (TRUST=1)
//   SETPOS <ax> <pos>         redefine the current position; the axis is trusted again
//   LIMITS <ax>|ALL <lo> <hi> soft limits in microsteps, saved to flash
//   SPEED <ax>|ALL <rpm>      cruise speed in adjuster turns per minute (finite, > 0)
//   ACCEL <ax>|ALL <rpm/s>    acceleration (finite, > 0)
//   CURRENT <ax>|ALL <mA>     RMS run current, clamped to 50..MAX_MA (motors must be still)
//   ENABLE <ax>|ALL           energise and hold until DISABLE. Without it, a move
//                             energises its motor and releases it RELEASE_DELAY_MS
//                             after it stops (config.h AUTO_RELEASE)
//   DISABLE <ax>|ALL          release the motor (halts it first), ends an ENABLE hold
//   DRV <ax>                  TMC2209 diagnostics (motors must be still)
//   REPROBE <ax>|ALL          re-run the driver config (motors must be still)
//   SAVE                      write the positions of the axes that are still to flash now
//
// Photodiodes (ADS1115). Volts at the TIA outputs, dark offsets subtracted
// once PD DARK has run; RATIO is OUT/REF ("-" with the laser off or REF
// under 10 mV).
//   PD                        -> PD REF=<V> OUT=<V> RATIO=<r> FSR=<ref>,<out> N=<n>,<n> DARK=0|1 LASER=0|1
//                                (mean of the N samples since the last PD line)
//   PD STREAM <hz>|OFF        send a PD line unprompted at <hz> (up to PD_MAX_STREAM_HZ)
//   PD DARK                   laser off, average both channels, laser back as it was;
//                             replies OK PD DARK REF=<V> OUT=<V> when done (~0.1 s), or
//                             ERR PD DARK aborted - ADS1115 stopped answering
//   PD DARK CLEAR             stop subtracting the dark offsets
//   PD RANGE AUTO|<fsr>       ADS1115 gain range: auto, or fixed at 4.096 .. 0.256 V
//   INFO also carries ADC=0|1 PD_RF=<ref ohms>,<out ohms> PD_RESP=<A/W>.
//   A sample whose I2C transfer fails is dropped (N counts only good ones); after
//   ADS_MAX_FAILS in a row the ADC counts as gone (ADC=0, WARN below) until PD finds it.
//
// Replies: "OK <CMD> ..." or "ERR <reason>". Unsolicited lines:
//   EVT DONE <ax> POS=<p> [LIMIT]   a move finished (LIMIT: it stopped at a soft limit),
//                                   also when STOP, HALT or DISABLE cut it short
//   WARN <text>                     something the operator should know, among them:
//     WARN positions untrusted: <ax>[,<ax>..] - ...       at boot, while any axis is untrusted
//     WARN <ax> driver stopped answering on the UART ...  it lost its motor supply; moves on
//                                                         it get ERR <ax> driver offline ..
//     WARN <ax> driver reset since it was configured ...  re-configured
//       both end in "; position untrusted until ZERO or SETPOS (it moved since the driver was
//       last seen working)" or "; position kept (no move since the driver was last seen
//       working), the rotor may settle up to 2 full steps away on the next enable"
//     WARN <ax> driver error flag set (drv_err ...) ...   overtemperature or short
//     WARN ADS1115 stopped answering ...                  ADC=0 until PD finds it again

namespace protocol {

void begin();
void poll();   // non-blocking: reads what has arrived, runs complete lines

}  // namespace protocol

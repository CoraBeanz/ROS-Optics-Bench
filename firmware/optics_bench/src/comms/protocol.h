#pragma once

// Line-based ASCII protocol on the USB serial port, used by
// tools/test_gui.py and later by the Jetson. One command per line,
// case-insensitive, fields separated by spaces. <ax> is M1X, M1Y, M2X, M2Y
// or 1-4; commands marked [ALL] also take ALL. Positions are in microsteps
// (INFO reports USTEPS_PER_REV; one adjuster turn at 100 TPI = 0.254 mm).
//
//   PING                      -> OK PONG
//   INFO                      -> INFO FW=.. AXES=.. USTEPS_PER_REV=.. MIN=.. MAX=.. RPM=.. ...
//   STATUS                    -> STATUS LASER=0 POS=a,b,c,d TGT=.. MOV=.. EN=.. DRV=..
//   LASER ON|OFF              -> OK LASER=1|0
//   MOVE <ax> <delta>         relative move, clamped to the soft limits
//   GOTO <ax> <pos>           absolute move, clamped to the soft limits
//   JOG <ax> +|-              run toward a limit; stops unless repeated within
//                             JOG_TIMEOUT_MS (send it every ~100-200 ms)
//   STOP [<ax>|ALL]           ramp down (no argument = all axes)
//   HALT [<ax>|ALL]           stop on the current step, no ramp
//   ZERO <ax>|ALL             call the current position 0 (limits stay relative to 0)
//   SETPOS <ax> <pos>         redefine the current position
//   LIMITS <ax>|ALL <lo> <hi> soft limits in microsteps, saved to flash
//   SPEED <ax>|ALL <rpm>      cruise speed in adjuster turns per minute
//   ACCEL <ax>|ALL <rpm/s>    acceleration
//   CURRENT <ax>|ALL <mA>     RMS run current (motors must be still)
//   ENABLE <ax>|ALL           energise and hold until DISABLE. Without it, a move
//                             energises its motor and releases it RELEASE_DELAY_MS
//                             after it stops (config.h AUTO_RELEASE)
//   DISABLE <ax>|ALL          release the motor (halts it first), ends an ENABLE hold
//   DRV <ax>                  TMC2209 diagnostics (motors must be still)
//   REPROBE <ax>|ALL          re-run the driver config (motors must be still)
//   SAVE                      write positions to flash now
//
// Photodiodes (ADS1115). Volts at the TIA outputs, dark offsets subtracted
// once PD DARK has run; RATIO is OUT/REF ("-" with the laser off or REF
// under 10 mV).
//   PD                        -> PD REF=<V> OUT=<V> RATIO=<r> FSR=<ref>,<out> N=<n>,<n> DARK=0|1 LASER=0|1
//                                (mean of the N samples since the last PD line)
//   PD STREAM <hz>|OFF        send a PD line unprompted at <hz> (up to PD_MAX_STREAM_HZ)
//   PD DARK                   laser off, average both channels, laser back as it was;
//                             replies OK PD DARK REF=<V> OUT=<V> when done (~0.1 s)
//   PD DARK CLEAR             stop subtracting the dark offsets
//   PD RANGE AUTO|<fsr>       ADS1115 gain range: auto, or fixed at 4.096 .. 0.256 V
//   INFO also carries ADC=0|1 PD_RF=<ref ohms>,<out ohms> PD_RESP=<A/W>.
//
// Replies: "OK <CMD> ..." or "ERR <reason>". Unsolicited lines:
//   EVT DONE <ax> POS=<p> [LIMIT]   a move finished (LIMIT: it stopped at a soft limit)
//   WARN <text>                     something the operator should know

namespace protocol {

void begin();
void poll();   // non-blocking: reads what has arrived, runs complete lines

}  // namespace protocol

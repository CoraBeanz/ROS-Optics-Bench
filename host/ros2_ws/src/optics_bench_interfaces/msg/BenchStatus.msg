# The controller's state, from its STATUS reply. Arrays are per axis, in the
# order of `axes` (M1X, M1Y, M2X, M2Y). Positions are microsteps, 3200 per
# adjuster turn (one turn of a 100 TPI adjuster is 254 um).
std_msgs/Header header
bool connected             # false until the controller answers, or after the link drops
bool aligning              # an Align goal is running
bool laser
string[] axes
int32[] position
int32[] target
bool[] moving
bool[] enabled             # coils powered
bool[] driver_ok           # the TMC2209 answers on the UART

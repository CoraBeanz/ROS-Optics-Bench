# The laser spot on the camera, from intensity moments over the pixels above
# the threshold. Pixels; x to the right, y down, (0, 0) the top-left pixel's centre.
std_msgs/Header header
bool found                 # false when nothing in the image clears the threshold
float64 x
float64 y
float64 sigma_x            # 1-sigma widths along x and y (a Gaussian beam's 1/e^2 radius is 2 sigma)
float64 sigma_y
float64 angle              # orientation of the major axis from +x, radians
float64 peak               # brightest pixel, 0-1 of the sensor's full scale
uint32 pixels              # pixels above the threshold
bool saturated             # some of them are at full scale: turn the exposure or the laser down

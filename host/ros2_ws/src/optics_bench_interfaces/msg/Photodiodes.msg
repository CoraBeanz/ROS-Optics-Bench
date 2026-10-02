# One PD line from the controller: the reference and output photodiode
# amplifier voltages, each the mean of the ADS1115 samples since the last line.
std_msgs/Header header
float64 ref_v
float64 out_v
bool has_ratio             # false with the laser off or the reference under 10 mV
float64 ratio              # out / ref, the coupling score
float64 ref_range_v        # ADS1115 full-scale range used per channel
float64 out_range_v
uint32 ref_samples
uint32 out_samples
bool dark_subtracted
bool laser

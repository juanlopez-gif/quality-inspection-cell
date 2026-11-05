# Supervisor -> Robot.  Topic: /robot/command
# pick_* is the point where the SUCTION CUP touches the top of the piece.
string PREPARE_PICK   = "PREPARE_PICK"    # Piece arrived at the IR sensor: get ready (-> WAITING_TO_PICK)
string PICK_AND_PLACE = "PICK_AND_PLACE"  # Pick at pick_* pose and drop in destination_bin
string GO_HOME        = "GO_HOME"         # Abort / return home
string RESET          = "RESET"           # Clear an ERROR state

std_msgs/Header header
string command
uint32 job_id
float64 pick_x_mm        # ROBOT BASE frame
float64 pick_y_mm
float64 pick_z_mm
float64 pick_yaw_deg
string destination_bin   # Bin id; the robot knows the bin coordinates from its config
string reason

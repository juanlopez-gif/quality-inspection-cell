# Camera -> Supervisor.  Topic: /camera/inspection_result
# Final inspection of the piece stopped in the pick-zone ROI.
string VERDICT_OK     = "OK"
string VERDICT_REJECT = "REJECT"

string DEFECT_NONE        = "NONE"
string DEFECT_MARKED      = "MARKED"
string DEFECT_WRONG_COLOR = "WRONG_COLOR"
string DEFECT_WRONG_SIZE  = "WRONG_SIZE"
string DEFECT_NO_PIECE    = "NO_PIECE"

std_msgs/Header header
uint32 request_id          # Same id as the CameraCommand that asked for it
uint32 track_id
bool success               # false if the camera could not find a piece in the ROI

# --- What was measured ---
string shape               # CIRCLE | SQUARE | UNKNOWN
string color               # RED | GREEN | BLUE | UNKNOWN
float32 measured_size_mm   # Side (square) or diameter (circle)
bool mark_detected
string mark_type           # NONE | CROSS | SMILEY | SCRATCH | DOT | GROOVE | ... (best guess)

# --- Decision ---
string verdict             # OK | REJECT
string defect              # NONE | MARKED | WRONG_COLOR | WRONG_SIZE | NO_PIECE
string destination_bin     # One of the 9 bin ids (see config/cell_params.yaml)

# --- Pick pose (ROBOT BASE frame, millimetres / degrees) from the pose model ---
float64 pick_x_mm
float64 pick_y_mm
float64 pick_z_mm
float64 pick_yaw_deg
float32 pose_confidence

# Robot -> Supervisor.  Topic: /robot/status
# Robot: Universal Robots UR7e with a vacuum suction cup.
string IDLE             = "IDLE"
string WAITING_TO_PICK  = "WAITING_TO_PICK"
string PICKING_CONVEYOR = "PICKING_CONVEYOR" # approach, descend, vacuum ON
string PICKING_DONE     = "PICKING_DONE"
string PLACING          = "PLACING"          # target_bin tells where (e.g. PLACING -> BIN_RED_CIRCLE)
string RETURNING_HOME   = "RETURNING_HOME"
string ERROR            = "ERROR"

std_msgs/Header header
string state
uint32 job_id
string target_bin
bool vacuum_on           # Vacuum suction cup active (piece held when true)
float64 tcp_x_mm         # ROBOT BASE frame
float64 tcp_y_mm
float64 tcp_z_mm
float64 tcp_yaw_deg
string detail

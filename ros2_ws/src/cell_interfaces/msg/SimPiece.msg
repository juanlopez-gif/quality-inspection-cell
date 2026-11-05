# SIMULATION ONLY - ground truth of one piece in the virtual cell.
uint32 id
string shape          # CIRCLE | SQUARE
string color_name     # RED | GREEN | BLUE | YELLOW | ORANGE | PURPLE | ...
uint8 r
uint8 g
uint8 b
float32 size_mm       # Side or diameter
string mark           # NONE | CROSS | SMILEY | SCRATCH | DOT | GROOVE
float32 x_mm          # CELL frame (centre of the piece)
float32 y_mm
float32 z_mm
float32 yaw_deg
string location       # BELT | GRIPPER | BIN
string bin_id         # When location == BIN

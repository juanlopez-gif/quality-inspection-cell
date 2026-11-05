# One piece seen by the camera while it is being transported (preliminary detection).
uint32 track_id       # Tracker id assigned by the camera
string shape          # CIRCLE | SQUARE | UNKNOWN
string color          # RED | GREEN | BLUE | UNKNOWN
float32 x_mm          # Position in the CELL frame (see docs/02_architecture.md)
float32 y_mm
float32 confidence    # 0..1

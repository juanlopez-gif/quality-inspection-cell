# Conveyor -> Supervisor.  Topic: /conveyor/status
string STOPPED = "STOPPED"
string RUNNING = "RUNNING"

std_msgs/Header header
string state          # STOPPED | RUNNING
float32 speed_mm_s    # Current belt speed (0 when stopped)
string last_command   # Last command received (for traceability)

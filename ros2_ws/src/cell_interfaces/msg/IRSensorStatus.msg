# IR sensor -> Supervisor.  Topic: /ir_sensor/status
# The IR sensor is PURELY REACTIVE: it has NO command topic.
# It only reports what it sees at a fixed rate and immediately on every change.
string FREE     = "FREE"
string OCCUPIED = "OCCUPIED"

std_msgs/Header header
string state          # FREE | OCCUPIED
bool changed          # true on the message that reports a transition

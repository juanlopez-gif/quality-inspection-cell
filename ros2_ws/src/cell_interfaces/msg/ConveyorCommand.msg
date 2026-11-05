# Supervisor -> Conveyor.  Topic: /conveyor/command
# The conveyor only moves when the supervisor tells it to.
string RUN  = "RUN"
string STOP = "STOP"

std_msgs/Header header
string command        # RUN | STOP
string reason         # Human readable: which supervisor rule produced this command (e.g. "R1")

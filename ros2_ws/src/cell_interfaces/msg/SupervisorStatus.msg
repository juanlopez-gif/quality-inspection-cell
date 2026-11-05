# Supervisor -> anyone (dashboard, logging).  Topic: /supervisor/status
std_msgs/Header header
string cell_state             # IDLE | TRANSPORTING | INSPECTING | WAITING_ROBOT | ROBOT_HANDLING | ...
string last_rule              # Id of the last rule that fired, e.g. "R1"
string last_rule_text         # Short explanation of that rule
string last_command           # The command that was issued, e.g. "/conveyor/command RUN"
string[] active_rules         # Rules that evaluated TRUE in the last evaluation
uint32 pieces_on_belt
uint32 pieces_processed
uint32 pieces_rejected

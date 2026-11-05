# Supervisor -> Camera.  Topic: /camera/command
# The camera streams detections on its own; the supervisor only asks for the
# final inspection once the piece is stopped in the pick-zone ROI.
string INSPECT = "INSPECT"   # Run the final inspection on the pick-zone ROI
string CANCEL  = "CANCEL"    # Abort a pending inspection

std_msgs/Header header
string command
uint32 request_id     # Echoed back in InspectionResult so the supervisor can match answers
string reason

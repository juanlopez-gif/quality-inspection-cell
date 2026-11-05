# Camera -> Supervisor.  Topic: /camera/detections
# Preliminary detections of pieces that are on the belt OUTSIDE the pick zone.
std_msgs/Header header
DetectedPiece[] pieces         # Pieces in the transport zone
bool pick_zone_occupied        # Camera sees a piece inside the pick-zone ROI
bool belt_motion_detected      # Camera-based estimate of whether the belt is moving
string camera_state            # STREAMING | INSPECTING

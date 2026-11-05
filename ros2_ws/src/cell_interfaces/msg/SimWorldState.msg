# SIMULATION ONLY - full ground truth of the virtual cell.  Topic: /sim/world_state
std_msgs/Header header
SimPiece[] pieces
float32 belt_position_mm   # Accumulated belt travel (useful for animating the belt)

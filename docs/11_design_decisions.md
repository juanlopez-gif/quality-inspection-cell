# 11. Design decisions and assumptions

Decisions taken where the specification left room. All are configurable or easy to change.

| # | Topic | Decision | Where to change |
|---|---|---|---|
| 1 | Several defects at once | Priority **MARKED > WRONG_COLOR > WRONG_SIZE** | `classification.defect_priority` |
| 2 | Size tolerance | 42 ± 2 mm | `pieces.size_tolerance_mm` |
| 3 | Unknown shape (not circle/square) | Goes to `BIN_REJECT_SIZE` (geometric defect) | `classifier.py` |
| 4 | Who decides the bin | The **camera** (it reports verdict + destination, as specified); the supervisor forwards it | exercise 9.9 |
| 5 | Camera command topic | `/camera/command` with `INSPECT`/`CANCEL`; detections stream without being asked | `CameraCommand.msg` |
| 6 | "Pieces in the cell" for running the belt | Pieces in transport (camera) **or** pick zone occupied (camera) | rule R4 |
| 7 | Belt while the robot places | Allowed to run once the piece is lifted (IR FREE) | rule R4/R10 |
| 8 | When to inspect | Only once the conveyor **reports** STOPPED | rule R6 |
| 9 | Robot prepares before the result | `PREPARE_PICK` when IR becomes occupied → `WAITING_TO_PICK` | rule R8 |
| 10 | `PLACING_<bin>` state | Published as state `PLACING` + field `target_bin` (keeps the state list fixed and the bin readable) | `RobotStatus.msg` |
| 11 | Sensor loss | IR silent > 1 s → STOP (fail-safe) | `supervisor.sensor_timeout_s` |
| 12 | Inspection lost | Retry up to 3 times every 3 s, then `FAULT_INSPECTION` | `supervisor.*` |
| 13 | Pick pose frame | Robot base frame (camera applies the calibration transform) | `camera.robot_base_in_cell` |
| 14 | Robot | **Universal Robots UR7e** (850 mm reach), **vacuum suction cup**, driven with `ur_rtde` (simple blocking `moveL`, no MoveIt) | `robot.*`, `ur7e_robot_node.py` |
| 18 | Tool orientation | Fixed (cup pointing down): a round suction cup does not need the piece yaw | `robot.tool_rotvec` |
| 19 | Conveyor + IR I/O | One **Arduino**, line-based serial protocol; one process exposes the `/conveyor` and `/ir_sensor` nodes | `arduino_io_node.py`, `cell_io.ino` |
| 20 | Hardware interlock | Arduino stops the motor itself on the IR edge + watchdog, in addition to rule R2 | `HW_INTERLOCK`, `WATCHDOG_MS` |
| 21 | Lost Arduino | `/ir_sensor` stops publishing (never invents a state) → R1 stops the belt | `stale_s` |
| 23 | Vision | Classical OpenCV (rectified top view in mm, 50 % edge, fill ratio, median colour, Lab mark detection), no deep learning: explainable, no training data needed, runs on a laptop | `vision.py`, docs/14 |
| 24 | Testing vision without camera | The simulator renders camera images; the real pipeline is tested on them (`test_vision.py`) | `sim_renderer.py` |
| 22 | Robot error mid-motion | `stopL`, state `ERROR`, vacuum kept ON (do not drop the piece anywhere) | `ur7e_robot_node.py` |
| 15 | Units | mm, s, degrees everywhere | — |
| 16 | Messages | Custom `cell_interfaces` (typed, self-documented) instead of JSON strings | `cell_interfaces/msg` |
| 17 | Dashboard tech | Python stdlib HTTP server + vanilla JS (no internet, no pip installs) | `dashboard_node.py`, `web/` |

## Open questions for the course staff
* Which UR digital output drives the vacuum, and is there a vacuum sensor (to confirm the grip)?
* Exact IR sensor model (break-beam or reflective, active LOW/HIGH) and how the motor is switched (relay / MOSFET / driver).
* Which camera will be used (USB, resolution, lens) and the lighting → tuning of `camera.vision`.
* Should the operator confirm/clear `FAULT_*` states from the dashboard?

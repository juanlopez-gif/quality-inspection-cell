# 1. System overview

## 1.1 Goal of the cell

The cell receives **pieces placed by hand** at the start of a conveyor, identifies them,
**inspects** them, and a **Universal Robots UR7e** with a **vacuum suction cup** sorts them into **9 bins**.

Pieces (current version):

| Property | Accepted values |
|---|---|
| Shape | circle, square |
| Color | red, green, blue |
| Size | 42 mm (square side or circle diameter), tolerance ±2 mm (configurable) |
| Surface | clean: no mark of any kind |

A piece is **defective** when:

* its **color** is not red, green or blue (e.g. yellow, orange, purple, grey),
* its **size** is outside 42 ± 2 mm (or the shape is not a circle or a square),
* it has **any mark** on the surface: a cross, a smiley face, a scratch, a dot, a groove…

## 1.2 The 9 bins

| Bin id | Contents |
|---|---|
| `BIN_RED_CIRCLE` | good red circles |
| `BIN_GREEN_CIRCLE` | good green circles |
| `BIN_BLUE_CIRCLE` | good blue circles |
| `BIN_RED_SQUARE` | good red squares |
| `BIN_GREEN_SQUARE` | good green squares |
| `BIN_BLUE_SQUARE` | good blue squares |
| `BIN_REJECT_SIZE` | wrong size (or unknown shape) |
| `BIN_REJECT_COLOR` | wrong / unknown color |
| `BIN_REJECT_MARKED` | piece with any mark |

If a piece has **several defects**, the order in `classification.defect_priority` of
`config/cell_config.yaml` decides the bin. Default: **MARKED > WRONG_COLOR > WRONG_SIZE**.

## 1.3 Sequence of operation

1. The operator places a piece at the **LOAD** zone (start of the belt).
2. The **camera** (overhead, sees the whole belt) detects the new piece and reports it
   on `/camera/detections` (preliminary detection: shape + color only).
3. The **supervisor** sees "IR sensor FREE + pieces on the belt" → sends `RUN` to the conveyor (rule R4).
4. The piece travels. The camera keeps reporting the pieces in the *transport zone*.
5. The piece reaches the end and blocks the **IR beam** → the IR sensor reports `OCCUPIED`.
6. The supervisor immediately sends `STOP` (rule R2 — **IR occupied ⇒ belt ALWAYS stopped**)
   and `PREPARE_PICK` to the robot (R8) → robot goes to `WAITING_TO_PICK`.
7. When the conveyor reports `STOPPED`, the supervisor sends `INSPECT` to the camera (R6).
8. The camera inspects the piece inside the **pick ROI**: color, size, marks → verdict,
   destination bin, and the **pick pose** (estimated by the pose model, expressed in the
   robot base frame). It publishes `/camera/inspection_result`.
9. The supervisor sends `PICK_AND_PLACE` (pose + bin) to the robot (R9).
10. Robot: `PICKING_CONVEYOR` (approach, cup on the piece, vacuum ON) → `PICKING_DONE` → `PLACING` (bin) → `RETURNING_HOME` → `IDLE`.
11. As soon as the robot lifts the piece the IR beam is free again → the cycle is closed
    (R10) and, if there are more pieces on the belt, the belt runs again (R4) while the
    robot is still placing.
12. If no piece is left in the cell, the belt stays stopped (R5).

## 1.4 Fundamental principles of the architecture

1. **One brain.** Only the **supervisor** sends commands. Devices never talk to each other.
2. **Command / status pattern.** Each device has a `/<device>/command` topic (input) and a
   `/<device>/status` topic (output).
3. **The IR sensor is reactive.** It has **no command topic**. It only reports.
4. **Event-driven decisions.** Each time a status arrives, the supervisor re-evaluates its
   rules and sends commands only if something has to change. A 10 Hz timer also evaluates
   the rules so time-based rules (timeouts) work.
5. **Safety first.** Rules that stop the conveyor are evaluated first; when the sensor is
   silent the belt is stopped (fail-safe).
6. **Simulation is isolated.** Everything that exists only because we are simulating lives
   in `/sim/*` topics and in `world_sim`. Removing them and plugging real drivers that
   speak the same messages must not change the supervisor.

Continue with [02_architecture.md](02_architecture.md).

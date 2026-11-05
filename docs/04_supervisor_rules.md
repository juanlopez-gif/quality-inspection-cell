# 4. Supervisor rules

Source of truth: `ros2_ws/src/quality_cell/quality_cell/core/supervisor_rules.py`
(ROS wrapper: `quality_cell/nodes/supervisor_node.py`). Unit tests:
`ros2_ws/src/quality_cell/test/test_supervisor_rules.py`.

## 4.1 Decision cycle

```
  any STATUS message ─► update CellView ─► evaluate rules (in order) ─► publish COMMANDS
  10 Hz timer ─────────────────────────────┘
```

* **CellView** = what the supervisor believes: IR state (+ time of last message), conveyor
  state, number of pieces in transport, pick zone occupied, robot state, camera state.
* **Cycle memory** = inspection phase (NONE / REQUESTED / DONE / FAILED / GAVE_UP),
  request id, retries, inspection result, job sent, job id.
* Commands are **idempotent**: the conveyor command is only sent when the desired state
  changes, or re-sent after `command_resend_s` if the device did not reach it.

## 4.2 Rule table

### Conveyor (first matching rule wins — ordered by safety)

| Id | Condition | Action |
|---|---|---|
| **R1** | IR status never received, or older than `sensor_timeout_s` (1 s) | `/conveyor/command STOP` |
| **R2** | IR = OCCUPIED | `/conveyor/command STOP` — **always** |
| **R3** | Robot = PICKING_CONVEYOR (suction cup on the belt) | `/conveyor/command STOP` |
| **R4** | IR = FREE and (pieces in transport > 0 or pick zone occupied) | `/conveyor/command RUN` |
| **R5** | IR = FREE and no pieces in the cell | `/conveyor/command STOP` |

### Camera

| Id | Condition | Action |
|---|---|---|
| **R6** | IR = OCCUPIED and conveyor reports STOPPED and no inspection yet for this piece | `/camera/command INSPECT (request_id = n+1)` |
| **R7** | IR = OCCUPIED and (inspection failed, or no answer after `inspection_timeout_s`) and retries < max | `/camera/command INSPECT` again (new request id). After `inspection_max_retries` → `FAULT_INSPECTION` |

### Robot

| Id | Condition | Action |
|---|---|---|
| **R8** | IR = OCCUPIED and robot IDLE and no job sent for this piece | `/robot/command PREPARE_PICK` (→ WAITING_TO_PICK) |
| **R9** | Inspection DONE and robot WAITING_TO_PICK and no job sent | `/robot/command PICK_AND_PLACE` with the pick pose and destination bin from the camera |

### Cycle

| Id | Condition | Action |
|---|---|---|
| **R10** | A job was sent and IR becomes FREE (the robot lifted the piece) | Close the cycle: count the piece (and the reject), reset the cycle memory |
| **R11** | IR becomes FREE, an inspection was requested/done, but **no** job was sent (the piece was removed by hand or fell) | **Discard** the inspection result, reset the cycle memory |

## 4.3 Why these rules (design notes)

* **R2 before everything except R1**: the specification says that with the sensor occupied
  the belt must *always* be stopped. No other rule can override it because the conveyor
  rules are a first-match chain.
* **R1 (fail-safe)**: if the sensor node dies or the cable is cut we do not know whether a
  piece is at the end → stop.
* **R3**: in normal operation the IR is occupied while the robot picks, so R2 already
  stops the belt. R3 protects against a sensor that sees FREE too early (piece pushed
  aside, reflections…).
* **R6 waits for `STOPPED`**: inspecting a piece that is still sliding gives a wrong pick
  pose.
* **R8 before the result**: the robot gets ready while the camera works (saves time).
* **R9 needs WAITING_TO_PICK**: if the robot is still placing the previous piece the result
  is kept; when the robot returns to IDLE, R8 then R9 fire.
* **The belt may run while the robot places** (R4 after R10): it is safe because the robot
  is no longer over the belt, and it improves throughput.
* **R11 (found while testing)**: without it, if an operator removes the inspected piece
  before the robot takes it, the supervisor keeps that inspection and the NEXT piece is
  picked with the old pose and sent to the OLD piece's bin (a red circle ended in the
  size-reject bin). An inspection result belongs to one physical piece only.
  Regression test: `test_piece_removed_by_hand_discards_old_inspection`.
* **The supervisor does not decide the bin**: the camera does (it owns the inspection
  knowledge, `classifier.py`). The supervisor forwards the decision. Exercise 9.3
  discusses moving this decision into the supervisor.

## 4.4 How to add a rule

1. Write the condition/action in `SupervisorRules.evaluate()` in the right group.
2. Add its text to `RULE_TEXT` (the dashboard reads it automatically).
3. Add the id to `RULE_CAT`/`RULE_CMD` in `web/app.js` (cosmetic).
4. Write a test in `test/test_supervisor_rules.py` and run `./test.sh`.
5. Update this document.

Continue with [05_inspection_and_classification.md](05_inspection_and_classification.md).

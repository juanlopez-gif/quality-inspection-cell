"""Supervisor rule engine - the "brain" of the cell.

NO ROS IMPORTS HERE ON PURPOSE: the ROS node (nodes/supervisor_node.py) only
translates messages into calls to this class and turns the returned
`Command` objects into ROS messages. This makes the rules easy to read, to
unit-test (see test/test_supervisor_rules.py) and to change.

How it works
------------
1. Every time ANY device reports a status, the node updates the `CellView`
   (what the supervisor currently believes about the cell) and calls
   `evaluate(now)`.
2. A timer also calls `evaluate(now)` periodically so time-based rules
   (sensor timeout, inspection timeout, re-sends) work.
3. `evaluate` walks through the rules IN ORDER and returns the list of
   commands to send + which rules fired.

Rule table (keep docs/04_supervisor_rules.md in sync!)
------------------------------------------------------
  CONVEYOR (first matching rule wins - safety first)
   R1  IR sensor silent / unknown           -> conveyor STOP   (safety)
   R2  IR sensor OCCUPIED                   -> conveyor STOP   (safety, ALWAYS)
   R3  Robot is PICKING on the belt         -> conveyor STOP   (safety)
   R4  IR FREE and pieces on the belt       -> conveyor RUN
   R5  IR FREE and no pieces in the cell    -> conveyor STOP
  CAMERA
   R6  IR OCCUPIED and belt STOPPED and no inspection yet -> camera INSPECT
   R7  Inspection unanswered / failed (timeout)           -> camera INSPECT again (retry)
  ROBOT
   R8  IR OCCUPIED and robot IDLE and no job yet          -> robot PREPARE_PICK
   R9  Inspection result ready and robot WAITING_TO_PICK  -> robot PICK_AND_PLACE
  CYCLE
   R10 Job sent and IR becomes FREE (piece lifted)        -> close cycle, reset memory
   R11 IR becomes FREE but NO job was sent (piece removed
       by hand / lost before the robot took it)           -> discard the inspection
       result (it belongs to a piece that is gone)
"""
from dataclasses import dataclass, field
from typing import Optional

RULE_TEXT = {
    'R1': 'SAFETY: IR sensor status unknown / timed out -> STOP conveyor',
    'R2': 'SAFETY: IR sensor OCCUPIED -> STOP conveyor (always)',
    'R3': 'SAFETY: robot is picking on the belt -> STOP conveyor',
    'R4': 'IR FREE and pieces on the belt -> RUN conveyor',
    'R5': 'IR FREE and no pieces in the cell -> STOP conveyor',
    'R6': 'Piece stopped at IR sensor -> camera INSPECT (final inspection)',
    'R7': 'Inspection timed out / failed -> retry camera INSPECT',
    'R8': 'Piece at IR sensor and robot IDLE -> robot PREPARE_PICK',
    'R9': 'Inspection ready and robot WAITING_TO_PICK -> robot PICK_AND_PLACE',
    'R10': 'Piece left the pick zone after the job -> cycle complete',
    'R11': 'Piece left the pick zone WITHOUT a robot job (removed by hand) -> discard its inspection',
}


@dataclass
class Command:
    target: str            # 'conveyor' | 'camera' | 'robot'
    command: str           # e.g. 'RUN', 'STOP', 'INSPECT', 'PICK_AND_PLACE'
    rule: str              # rule id that produced it
    params: dict = field(default_factory=dict)


@dataclass
class CellView:
    """Everything the supervisor knows. Filled from the status topics."""
    ir_state: Optional[str] = None          # 'FREE' | 'OCCUPIED' | None (never heard)
    ir_stamp: float = -1e9                  # time of the last IR message
    conveyor_state: Optional[str] = None    # 'RUNNING' | 'STOPPED'
    transport_pieces: int = 0               # from /camera/detections
    pick_zone_occupied: bool = False        # from /camera/detections
    robot_state: Optional[str] = None
    camera_state: Optional[str] = None


class SupervisorRules:
    def __init__(self, cfg):
        s = cfg['supervisor']
        self.sensor_timeout = s['sensor_timeout_s']
        self.inspection_timeout = s['inspection_timeout_s']
        self.max_retries = s['inspection_max_retries']
        self.resend = s['command_resend_s']

        self.view = CellView()
        # --- memory of the current pick cycle ---
        self.inspection_phase = 'NONE'      # NONE | REQUESTED | DONE | FAILED
        self.request_id = 0
        self.request_time = 0.0
        self.retries = 0
        self.result = None                  # dict with the inspection result
        self.prepare_sent_time = None
        self.job_id = 0
        self.job_sent = False
        # --- memory of commands ---
        self.last_conveyor_cmd = None
        self.last_conveyor_cmd_time = -1e9
        # --- statistics ---
        self.processed = 0
        self.rejected = 0
        self.removed_by_hand = 0
        self.last_rule = ''
        self.active_rules = []

    # ------------------------------------------------------------------ inputs
    def on_ir(self, state, now):
        self.view.ir_state, self.view.ir_stamp = state, now

    def on_conveyor(self, state):
        self.view.conveyor_state = state

    def on_detections(self, n_transport, pick_zone_occupied, camera_state):
        self.view.transport_pieces = n_transport
        self.view.pick_zone_occupied = pick_zone_occupied
        self.view.camera_state = camera_state

    def on_robot(self, state):
        self.view.robot_state = state

    def on_inspection(self, result):
        """result: dict with keys request_id, success, verdict, destination_bin, pick_* ..."""
        if result['request_id'] != self.request_id or self.inspection_phase != 'REQUESTED':
            return False  # stale / unexpected answer -> ignore
        if not result['success']:
            self.inspection_phase = 'FAILED'
            return True
        self.result = result
        self.inspection_phase = 'DONE'
        return True

    # ------------------------------------------------------------- evaluation
    def evaluate(self, now):
        v = self.view
        cmds, fired = [], []
        ir_ok = v.ir_state is not None and (now - v.ir_stamp) <= self.sensor_timeout
        occupied = ir_ok and v.ir_state == 'OCCUPIED'
        free = ir_ok and v.ir_state == 'FREE'
        pieces_on_belt = v.transport_pieces > 0 or v.pick_zone_occupied

        # ---------------- R10: close the cycle (evaluated first, it resets memory)
        if self.job_sent and free:
            fired.append('R10')
            self.processed += 1
            if self.result and self.result.get('verdict') == 'REJECT':
                self.rejected += 1
            self._reset_cycle()
        # ---------------- R11: the piece disappeared before the robot took it.
        # Its inspection result must NOT be used for the next piece.
        elif not self.job_sent and free and self.inspection_phase != 'NONE':
            fired.append('R11')
            self.removed_by_hand += 1
            self._reset_cycle()

        # ---------------- CONVEYOR rules: first match wins (safety first)
        if not ir_ok:
            want, rule = 'STOP', 'R1'
        elif occupied:
            want, rule = 'STOP', 'R2'
        elif v.robot_state == 'PICKING_CONVEYOR':
            want, rule = 'STOP', 'R3'
        elif pieces_on_belt:
            want, rule = 'RUN', 'R4'
        else:
            want, rule = 'STOP', 'R5'
        fired.append(rule)
        expected_state = 'RUNNING' if want == 'RUN' else 'STOPPED'
        if (want != self.last_conveyor_cmd or
                (v.conveyor_state != expected_state and
                 now - self.last_conveyor_cmd_time > self.resend)):
            cmds.append(Command('conveyor', want, rule))
            self.last_conveyor_cmd, self.last_conveyor_cmd_time = want, now

        # ---------------- CAMERA rules
        if occupied and v.conveyor_state == 'STOPPED' and self.inspection_phase == 'NONE':
            fired.append('R6')
            cmds.append(self._request_inspection(now, 'R6'))
        elif occupied and (
                self.inspection_phase == 'FAILED' or
                (self.inspection_phase == 'REQUESTED' and
                 now - self.request_time > self.inspection_timeout)):
            if self.retries < self.max_retries:
                fired.append('R7')
                self.retries += 1
                cmds.append(self._request_inspection(now, 'R7'))
            else:
                self.inspection_phase = 'GAVE_UP'   # needs an operator (see docs)

        # ---------------- ROBOT rules
        if occupied and not self.job_sent and v.robot_state == 'IDLE':
            if self.prepare_sent_time is None or now - self.prepare_sent_time > self.resend:
                fired.append('R8')
                self.prepare_sent_time = now
                cmds.append(Command('robot', 'PREPARE_PICK', 'R8'))
        if (self.inspection_phase == 'DONE' and not self.job_sent and
                v.robot_state == 'WAITING_TO_PICK'):
            fired.append('R9')
            self.job_id += 1
            self.job_sent = True
            r = self.result
            cmds.append(Command('robot', 'PICK_AND_PLACE', 'R9', {
                'job_id': self.job_id,
                'pick_x_mm': r['pick_x_mm'], 'pick_y_mm': r['pick_y_mm'],
                'pick_z_mm': r['pick_z_mm'], 'pick_yaw_deg': r['pick_yaw_deg'],
                'destination_bin': r['destination_bin']}))

        self.active_rules = fired
        if cmds:
            self.last_rule = cmds[-1].rule
        return cmds, fired

    # ----------------------------------------------------------------- helpers
    def _request_inspection(self, now, rule):
        self.request_id += 1
        self.request_time = now
        self.inspection_phase = 'REQUESTED'
        return Command('camera', 'INSPECT', rule, {'request_id': self.request_id})

    def _reset_cycle(self):
        self.inspection_phase = 'NONE'
        self.retries = 0
        self.result = None
        self.prepare_sent_time = None
        self.job_sent = False

    def cell_state(self):
        """High-level label for the dashboard."""
        v = self.view
        if v.ir_state is None:
            return 'WAITING_FOR_SENSORS'
        if self.inspection_phase == 'GAVE_UP':
            return 'FAULT_INSPECTION'
        if v.robot_state == 'ERROR':
            return 'FAULT_ROBOT'
        if v.robot_state in ('PICKING_CONVEYOR', 'PICKING_DONE'):
            return 'ROBOT_PICKING'
        if v.ir_state == 'OCCUPIED':
            if self.inspection_phase in ('NONE', 'REQUESTED', 'FAILED'):
                return 'INSPECTING'
            return 'WAITING_ROBOT'
        if v.conveyor_state == 'RUNNING':
            return 'TRANSPORTING'
        if v.robot_state in ('PLACING', 'RETURNING_HOME'):
            return 'ROBOT_PLACING'
        return 'IDLE'

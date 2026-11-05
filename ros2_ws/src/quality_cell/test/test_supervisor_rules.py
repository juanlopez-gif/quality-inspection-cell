"""Unit tests of the supervisor rules (no ROS needed):  python3 -m pytest test/"""
import os

from quality_cell.core.cell_config import load_config
from quality_cell.core.supervisor_rules import SupervisorRules

CFG = load_config(os.path.join(os.path.dirname(__file__), '..', 'config', 'cell_config.yaml'))


def cmds_for(cmds, target):
    return [c for c in cmds if c.target == target]


def new_sup():
    s = SupervisorRules(CFG)
    s.on_robot('IDLE')
    s.on_conveyor('STOPPED')
    return s


def test_no_sensor_means_stop():
    s = new_sup()
    cmds, fired = s.evaluate(0.0)
    assert 'R1' in fired and cmds_for(cmds, 'conveyor')[0].command == 'STOP'


def test_empty_cell_stays_stopped():
    s = new_sup()
    s.on_ir('FREE', 0.0)
    cmds, fired = s.evaluate(0.0)
    assert 'R5' in fired and cmds_for(cmds, 'conveyor')[0].command == 'STOP'


def test_new_piece_runs_belt():
    s = new_sup()
    s.on_ir('FREE', 0.0)
    s.evaluate(0.0)
    s.on_detections(1, False, 'STREAMING')
    cmds, fired = s.evaluate(0.1)
    assert 'R4' in fired and cmds_for(cmds, 'conveyor')[0].command == 'RUN'


def test_ir_occupied_always_stops_even_with_pieces():
    s = new_sup()
    s.on_ir('FREE', 0.0)
    s.on_detections(3, False, 'STREAMING')
    s.evaluate(0.0)
    s.on_conveyor('RUNNING')
    s.on_ir('OCCUPIED', 0.2)
    cmds, fired = s.evaluate(0.2)
    assert 'R2' in fired and cmds_for(cmds, 'conveyor')[0].command == 'STOP'


def test_sensor_timeout_stops_belt():
    s = new_sup()
    s.on_ir('FREE', 0.0)
    s.on_detections(1, False, 'STREAMING')
    s.evaluate(0.0)
    cmds, fired = s.evaluate(5.0)   # no IR message for 5 s
    assert 'R1' in fired


def test_full_cycle():
    s = new_sup()
    s.on_ir('FREE', 0.0)
    s.on_detections(1, False, 'STREAMING')
    s.evaluate(0.0)
    s.on_conveyor('RUNNING')
    # piece reaches the sensor
    s.on_ir('OCCUPIED', 1.0)
    s.on_detections(0, True, 'STREAMING')
    cmds, fired = s.evaluate(1.0)
    assert cmds_for(cmds, 'conveyor')[0].command == 'STOP'
    assert cmds_for(cmds, 'robot')[0].command == 'PREPARE_PICK'     # R8
    assert not cmds_for(cmds, 'camera')                              # belt not stopped yet
    s.on_conveyor('STOPPED')
    cmds, fired = s.evaluate(1.1)
    cam = cmds_for(cmds, 'camera')
    assert cam and cam[0].command == 'INSPECT' and 'R6' in fired
    rid = cam[0].params['request_id']
    s.on_robot('WAITING_TO_PICK')
    assert s.on_inspection({'request_id': rid, 'success': True, 'verdict': 'OK',
                            'destination_bin': 'BIN_RED_CIRCLE', 'pick_x_mm': 1.0,
                            'pick_y_mm': -250.0, 'pick_z_mm': 6.0, 'pick_yaw_deg': 0.0})
    cmds, fired = s.evaluate(1.8)
    rob = cmds_for(cmds, 'robot')
    assert rob[0].command == 'PICK_AND_PLACE' and 'R9' in fired
    assert rob[0].params['destination_bin'] == 'BIN_RED_CIRCLE'
    # robot picks: belt must stay stopped
    s.on_robot('PICKING_CONVEYOR')
    _, fired = s.evaluate(2.0)
    assert 'R2' in fired
    # piece lifted -> IR free -> cycle closes, belt stays stopped (no more pieces)
    s.on_robot('PICKING_DONE')
    s.on_ir('FREE', 2.5)
    s.on_detections(0, False, 'STREAMING')
    cmds, fired = s.evaluate(2.5)
    assert 'R10' in fired and 'R5' in fired and s.processed == 1


def test_inspection_retry_on_timeout():
    s = new_sup()
    s.on_ir('OCCUPIED', 0.0)
    s.on_conveyor('STOPPED')
    cmds, _ = s.evaluate(0.0)
    assert cmds_for(cmds, 'camera')
    s.on_ir('OCCUPIED', 4.0)
    cmds, fired = s.evaluate(4.0)   # > inspection_timeout_s
    assert 'R7' in fired and cmds_for(cmds, 'camera')[0].params['request_id'] == 2


def test_stale_inspection_is_ignored():
    s = new_sup()
    s.on_ir('OCCUPIED', 0.0)
    s.on_conveyor('STOPPED')
    s.evaluate(0.0)
    assert not s.on_inspection({'request_id': 99, 'success': True})


def test_piece_removed_by_hand_discards_old_inspection():
    """Regression: an inspection result must never be applied to a different piece."""
    s = new_sup()
    s.on_robot('PLACING')                       # robot busy with the previous piece
    s.on_ir('OCCUPIED', 0.0)
    s.on_conveyor('STOPPED')
    cmds, _ = s.evaluate(0.0)
    rid = [c for c in cmds if c.target == 'camera'][0].params['request_id']
    s.on_inspection({'request_id': rid, 'success': True, 'verdict': 'REJECT',
                     'destination_bin': 'BIN_REJECT_SIZE', 'pick_x_mm': 0.0, 'pick_y_mm': -250.0,
                     'pick_z_mm': 6.0, 'pick_yaw_deg': 0.0})
    s.evaluate(0.5)
    # operator removes the piece by hand: IR FREE, no job was sent
    s.on_ir('FREE', 1.0)
    _, fired = s.evaluate(1.0)
    assert 'R11' in fired and s.inspection_phase == 'NONE'
    # next piece arrives: it MUST be inspected again (R6), not picked with the old result
    s.on_robot('IDLE')
    s.on_ir('OCCUPIED', 2.0)
    cmds, fired = s.evaluate(2.0)
    assert 'R6' in fired and not [c for c in cmds if c.command == 'PICK_AND_PLACE']

"""Pick-and-place plan shared by the simulated robot (robot_node.py) and the
real UR7e driver (ur7e_robot_node.py). Same steps, same states -> the
supervisor sees exactly the same behaviour in simulation and on the robot.

A plan is a list of steps:  (robot_state, kind, data, detail)
    kind 'move'   data = (x, y, z) mm, ROBOT BASE frame, linear TCP move
    kind 'vacuum' data = True / False
"""
import math

from quality_cell.core.cell_config import bins_by_id

PICKING_CONVEYOR, PICKING_DONE = 'PICKING_CONVEYOR', 'PICKING_DONE'
PLACING, RETURNING_HOME = 'PLACING', 'RETURNING_HOME'


class PlanError(Exception):
    pass


def home_pose(cfg):
    h = cfg['robot']['home_tcp']
    return (h['x'], h['y'], h['z'])


def build_pick_place_plan(cfg, tf, pick_xyz, destination_bin):
    """pick_xyz: (x, y, z) mm in ROBOT BASE frame where the cup touches the piece top."""
    r = cfg['robot']
    bins = bins_by_id(cfg)
    if destination_bin not in bins:
        raise PlanError('unknown bin %s' % destination_bin)
    b = bins[destination_bin]
    # bins.drop_z_mm is a CELL-frame height (above the belt surface) -> robot frame
    bx, by, bz = tf.cell_to_robot(b['x'], b['y'], cfg['bins']['drop_z_mm'])
    px, py, pz = pick_xyz[0], pick_xyz[1], pick_xyz[2] - r['pick_press_mm']
    for (x, y) in ((px, py), (bx, by)):
        if math.hypot(x, y) > r['max_reach_mm']:
            raise PlanError('target (%.0f, %.0f) mm out of reach (%.0f mm)'
                            % (x, y, r['max_reach_mm']))
    a = r['approach_height_mm']
    return [
        (PICKING_CONVEYOR, 'move', (px, py, pz + a), 'approach above the piece'),
        (PICKING_CONVEYOR, 'move', (px, py, pz), 'descend, cup on the piece'),
        (PICKING_CONVEYOR, 'vacuum', True, 'vacuum ON'),
        (PICKING_DONE, 'move', (px, py, pz + a), 'lifting piece'),
        (PLACING, 'move', (bx, by, bz + a), 'moving to %s' % destination_bin),
        (PLACING, 'move', (bx, by, bz), 'descending into bin'),
        (PLACING, 'vacuum', False, 'vacuum OFF, piece released'),
        (PLACING, 'move', (bx, by, bz + a), 'retreat'),
        (RETURNING_HOME, 'move', home_pose(cfg), 'returning home'),
    ]

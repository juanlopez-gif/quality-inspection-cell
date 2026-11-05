"""ROBOT NODE (simulated Universal Robots UR7e with a vacuum suction cup).

    Subscribes: /robot/command   (PREPARE_PICK | PICK_AND_PLACE | GO_HOME | RESET)
    Publishes : /robot/status    (state machine below + TCP pose + vacuum)

State machine:
    IDLE --PREPARE_PICK--> WAITING_TO_PICK --PICK_AND_PLACE--> PICKING_CONVEYOR
    PICKING_CONVEYOR (approach, descend, vacuum ON) -> PICKING_DONE (lift)
    -> PLACING (move to bin, descend, vacuum OFF, retreat) -> RETURNING_HOME -> IDLE
    PICK_AND_PLACE is also accepted directly from IDLE.  Any unreachable target -> ERROR.

All poses are in the ROBOT BASE frame (mm). The robot knows the bin positions
from the cell config (converted CELL -> ROBOT BASE).
Real cell: ur7e_robot_node.py implements the same contract on the real UR7e
(ur_rtde library: moveL + digital output for the vacuum).
"""
import math

import rclpy

from cell_interfaces.msg import RobotCommand, RobotStatus
from quality_cell.core.cell_config import FrameTransform
from quality_cell.core.robot_plan import PlanError, build_pick_place_plan, home_pose
from quality_cell.nodes.common import CellNode


class RobotNode(CellNode):
    def __init__(self):
        super().__init__('robot')
        r = self.cfg['robot']
        self.speed = r['tcp_speed_mm_s']
        self.vac_on_time = r['vacuum_on_time_s']
        self.vac_off_time = r['vacuum_off_time_s']
        self.dt = 1.0 / r['status_rate_hz']
        self.home = home_pose(self.cfg)
        self.tf = FrameTransform(self.cfg)

        self.tcp = list(self.home)
        self.yaw = 0.0
        self.vacuum_on = False
        self.state = RobotStatus.IDLE
        self.job_id = 0
        self.target_bin = ''
        self.detail = 'at home'
        self.plan = []          # list of segments: (state, kind, data, detail)
        self.seg_t = 0.0

        self.pub = self.create_publisher(RobotStatus, '/robot/status', 10)
        self.create_subscription(RobotCommand, '/robot/command', self.on_command, 10)
        self.create_timer(self.dt, self.step)

    # ------------------------------------------------------------ commands
    def on_command(self, msg):
        self.get_logger().info('Command %s (%s) job=%d bin=%s' % (
            msg.command, msg.reason, msg.job_id, msg.destination_bin))
        if msg.command == RobotCommand.PREPARE_PICK:
            if self.state == RobotStatus.IDLE:
                self.set_state(RobotStatus.WAITING_TO_PICK, 'ready, waiting for pick pose')
        elif msg.command == RobotCommand.PICK_AND_PLACE:
            if self.state not in (RobotStatus.IDLE, RobotStatus.WAITING_TO_PICK):
                self.get_logger().warn('Busy (%s): PICK_AND_PLACE ignored' % self.state)
                return
            self.start_job(msg)
        elif msg.command == RobotCommand.GO_HOME:
            self.plan = [(RobotStatus.RETURNING_HOME, 'move', self.home, 'going home')]
            self.seg_t = 0.0
        elif msg.command == RobotCommand.RESET and self.state == RobotStatus.ERROR:
            self.set_state(RobotStatus.IDLE, 'reset')

    def start_job(self, msg):
        try:
            self.plan = build_pick_place_plan(
                self.cfg, self.tf, (msg.pick_x_mm, msg.pick_y_mm, msg.pick_z_mm),
                msg.destination_bin)
        except PlanError as e:
            return self.fail(str(e))
        self.job_id, self.target_bin = msg.job_id, msg.destination_bin
        self.yaw = msg.pick_yaw_deg
        self.seg_t = 0.0

    def fail(self, why):
        self.get_logger().error(why)
        self.plan = []
        self.set_state(RobotStatus.ERROR, why)

    # ------------------------------------------------------------ motion sim
    def step(self):
        if self.plan:
            state, kind, data, detail = self.plan[0]
            self.set_state(state, detail)
            done = self._run_segment(kind, data)
            if done:
                self.plan.pop(0)
                self.seg_t = 0.0
                if not self.plan:
                    self.target_bin = ''
                    self.set_state(RobotStatus.IDLE, 'at home')
        self.publish()

    def _run_segment(self, kind, data):
        if kind == 'vacuum':
            self.vacuum_on = data
            self.seg_t += self.dt
            return self.seg_t >= (self.vac_on_time if data else self.vac_off_time)
        # linear move at constant TCP speed
        d = [t - c for t, c in zip(data, self.tcp)]
        dist = math.sqrt(sum(v * v for v in d))
        stepd = self.speed * self.dt
        if dist <= stepd:
            self.tcp = list(data)
            return True
        self.tcp = [c + v / dist * stepd for c, v in zip(self.tcp, d)]
        return False

    def set_state(self, state, detail):
        if state != self.state:
            self.get_logger().info('%s -> %s %s' % (self.state, state, self.target_bin))
            self.state = state
            self.publish()          # report transitions immediately
        self.detail = detail

    def publish(self):
        m = self.stamp(RobotStatus())
        m.header.frame_id = 'robot_base'
        m.state, m.job_id, m.target_bin = self.state, self.job_id, self.target_bin
        m.vacuum_on = self.vacuum_on
        m.tcp_x_mm, m.tcp_y_mm, m.tcp_z_mm = self.tcp
        m.tcp_yaw_deg = self.yaw
        m.detail = self.detail
        self.pub.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = RobotNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

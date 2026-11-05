"""UR7e ROBOT NODE (real hardware) - Universal Robots UR7e + vacuum suction cup.

Same contract as the simulated robot_node.py, so the supervisor does not change:

    Subscribes: /robot/command   (PREPARE_PICK | PICK_AND_PLACE | GO_HOME | RESET)
    Publishes : /robot/status    (IDLE, WAITING_TO_PICK, PICKING_CONVEYOR, PICKING_DONE,
                                  PLACING + target_bin, RETURNING_HOME, ERROR)

The motion sequence is the SAME plan as in simulation (core/robot_plan.py).

Communication with the robot: the `ur_rtde` library (RTDE interface of the UR
controller, port 30004 + its own control script):
    rtde_control.moveL(pose, speed, acc)       linear TCP moves (metres, rotation vector)
    rtde_io.setStandardDigitalOut(pin, on)      vacuum valve / ejector
    rtde_receive.getActualTCPPose()             TCP pose for /robot/status

Install:  pip3 install --user --break-system-packages ur_rtde
Robot side (teach pendant):
    * Remote Control enabled and robot in REMOTE mode (e-Series / UR7e).
    * TCP set to the TIP of the suction cup (Installation > General > TCP).
    * Payload set (cup + piece).
    * The poses used here are in the UR "Base" frame (as shown on the pendant).

Parameters:
    dry_run (bool, default false)  no robot: timing-only backend, to test the node
    ur_ip   (string)               overrides robot.ur_ip of cell_config.yaml

SAFETY: the node never moves the robot at start-up. The first motion happens
on the first PICK_AND_PLACE / GO_HOME. Keep the speed low and the e-stop at hand.
"""
import math
import threading
import time

import rclpy
from rclpy.executors import MultiThreadedExecutor

from cell_interfaces.msg import RobotCommand, RobotStatus
from quality_cell.core.cell_config import FrameTransform
from quality_cell.core.robot_plan import PlanError, build_pick_place_plan, home_pose
from quality_cell.nodes.common import CellNode


# ============================================================================ backends
class RtdeBackend:
    """Talks to the real UR7e through ur_rtde. Units here: mm (converted to m)."""

    def __init__(self, ip, cfg, logger):
        import rtde_control
        import rtde_io
        import rtde_receive
        r = cfg['robot']
        self.log = logger
        self.rotvec = list(r['tool_rotvec'])
        self.speed = r['tcp_speed_mm_s'] / 1000.0
        self.acc = r['tcp_acc_mm_s2'] / 1000.0
        self.vac = r['vacuum_output']
        self.vac_high = r.get('vacuum_active_high', True)
        logger.info('Connecting to UR controller %s ...' % ip)
        self.rcv = rtde_receive.RTDEReceiveInterface(ip)
        self.ctl = rtde_control.RTDEControlInterface(ip)
        self.io = rtde_io.RTDEIOInterface(ip)
        logger.info('Connected to UR7e at %s' % ip)

    def move_l(self, xyz_mm):
        pose = [v / 1000.0 for v in xyz_mm] + self.rotvec
        return bool(self.ctl.moveL(pose, self.speed, self.acc))

    def set_vacuum(self, on):
        level = on if self.vac_high else not on
        t, pin = self.vac['type'], int(self.vac['pin'])
        if t == 'tool':
            return bool(self.io.setToolDigitalOut(pin, level))
        if t == 'configurable':
            return bool(self.io.setConfigurableDigitalOut(pin, level))
        return bool(self.io.setStandardDigitalOut(pin, level))

    def tcp_mm(self):
        p = self.rcv.getActualTCPPose()
        return (p[0] * 1000.0, p[1] * 1000.0, p[2] * 1000.0)

    def ok(self):
        return self.ctl.isConnected() and self.rcv.isConnected()

    def stop(self):
        try:
            self.ctl.stopL(1.0)
        except Exception:
            pass


class DryRunBackend:
    """No robot: waits the time a real move would take and reports a fake TCP."""

    def __init__(self, cfg, logger):
        self.speed = cfg['robot']['tcp_speed_mm_s']
        self.tcp = list(home_pose(cfg))
        self.lock = threading.Lock()
        logger.warn('DRY RUN: no robot connected, motions are only timed')

    def move_l(self, xyz_mm):
        start = list(self.tcp)
        dist = math.dist(start, xyz_mm)
        steps = max(1, int(dist / self.speed / 0.02))
        for i in range(1, steps + 1):
            with self.lock:
                self.tcp = [a + (b - a) * i / steps for a, b in zip(start, xyz_mm)]
            time.sleep(0.02)
        return True

    def set_vacuum(self, on):
        return True

    def tcp_mm(self):
        with self.lock:
            return tuple(self.tcp)

    def ok(self):
        return True

    def stop(self):
        pass


# ============================================================================ node
class UR7eRobotNode(CellNode):
    def __init__(self):
        super().__init__('robot')
        r = self.cfg['robot']
        dry = bool(self.declare_parameter('dry_run', False).value)
        ip = self.declare_parameter('ur_ip', r['ur_ip']).value
        self.vac_times = (r['vacuum_on_time_s'], r['vacuum_off_time_s'])
        self.tf = FrameTransform(self.cfg)
        self.backend = DryRunBackend(self.cfg, self.get_logger()) if dry else \
            RtdeBackend(ip, self.cfg, self.get_logger())

        self.lock = threading.Lock()
        self.state = RobotStatus.IDLE
        self.detail = 'connected (not moved yet)'
        self.job_id, self.target_bin = 0, ''
        self.vacuum_on, self.yaw = False, 0.0
        self.worker = None

        self.pub = self.create_publisher(RobotStatus, '/robot/status', 10)
        self.create_subscription(RobotCommand, '/robot/command', self.on_command, 10)
        self.create_timer(1.0 / r['status_rate_hz'], self.publish)

    # ------------------------------------------------------------ commands
    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def on_command(self, msg):
        self.get_logger().info('Command %s (%s) job=%d bin=%s' % (
            msg.command, msg.reason, msg.job_id, msg.destination_bin))
        if msg.command == RobotCommand.PREPARE_PICK:
            if self.state == RobotStatus.IDLE and not self.busy():
                self.set_state(RobotStatus.WAITING_TO_PICK, 'ready, waiting for pick pose')
        elif msg.command == RobotCommand.PICK_AND_PLACE:
            if self.busy() or self.state not in (RobotStatus.IDLE, RobotStatus.WAITING_TO_PICK):
                self.get_logger().warn('Busy (%s): PICK_AND_PLACE ignored' % self.state)
                return
            try:
                plan = build_pick_place_plan(self.cfg, self.tf,
                                             (msg.pick_x_mm, msg.pick_y_mm, msg.pick_z_mm),
                                             msg.destination_bin)
            except PlanError as e:
                return self.set_state(RobotStatus.ERROR, str(e))
            self.job_id, self.target_bin, self.yaw = msg.job_id, msg.destination_bin, msg.pick_yaw_deg
            self.run(plan)
        elif msg.command == RobotCommand.GO_HOME and not self.busy():
            self.run([(RobotStatus.RETURNING_HOME, 'move', home_pose(self.cfg), 'going home')])
        elif msg.command == RobotCommand.RESET and self.state == RobotStatus.ERROR and not self.busy():
            self.set_state(RobotStatus.IDLE, 'reset by supervisor')

    def run(self, plan):
        self.worker = threading.Thread(target=self.execute, args=(plan,), daemon=True)
        self.worker.start()

    # ------------------------------------------------------------ motion (worker thread)
    def execute(self, plan):
        try:
            for state, kind, data, detail in plan:
                self.set_state(state, detail)
                if kind == 'move':
                    if not self.backend.move_l(data):
                        raise RuntimeError('moveL to (%.0f, %.0f, %.0f) failed' % tuple(data))
                elif kind == 'vacuum':
                    if not self.backend.set_vacuum(data):
                        raise RuntimeError('vacuum %s failed' % ('ON' if data else 'OFF'))
                    self.vacuum_on = data
                    time.sleep(self.vac_times[0] if data else self.vac_times[1])
            self.target_bin = ''
            self.set_state(RobotStatus.IDLE, 'at home')
        except Exception as e:     # protective stop, e-stop, lost connection...
            self.backend.stop()
            # The vacuum is NOT switched off: a held piece is not dropped somewhere random.
            self.get_logger().error('Motion aborted: %s' % e)
            self.set_state(RobotStatus.ERROR, str(e))

    # ------------------------------------------------------------ status
    def set_state(self, state, detail):
        with self.lock:
            changed = state != self.state
            self.state, self.detail = state, detail
        if changed:
            self.get_logger().info('-> %s %s (%s)' % (state, self.target_bin, detail))
            self.publish()

    def publish(self):
        m = RobotStatus()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = 'robot_base'
        with self.lock:
            m.state, m.detail = self.state, self.detail
        m.job_id, m.target_bin, m.vacuum_on = self.job_id, self.target_bin, self.vacuum_on
        try:
            m.tcp_x_mm, m.tcp_y_mm, m.tcp_z_mm = self.backend.tcp_mm()
        except Exception:
            pass
        m.tcp_yaw_deg = self.yaw
        if not self.backend.ok() and m.state != RobotStatus.ERROR:
            m.state, m.detail = RobotStatus.ERROR, 'connection to the UR controller lost'
        self.pub.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = UR7eRobotNode()
    ex = MultiThreadedExecutor()
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.backend.stop()
        node.destroy_node()
        rclpy.try_shutdown()

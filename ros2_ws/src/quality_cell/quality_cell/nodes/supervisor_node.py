"""SUPERVISOR NODE - the only node that sends commands.

    Subscribes (status):  /ir_sensor/status, /conveyor/status, /camera/detections,
                          /camera/inspection_result, /robot/status
    Publishes (commands): /conveyor/command, /camera/command, /robot/command
    Publishes (info):     /supervisor/status

Pattern: STATUS arrives -> update view -> evaluate rules -> publish COMMANDS.
All the decision logic lives in quality_cell/core/supervisor_rules.py.
"""
import rclpy

from cell_interfaces.msg import (CameraCommand, CameraDetections, ConveyorCommand,
                                 ConveyorStatus, InspectionResult, IRSensorStatus,
                                 RobotCommand, RobotStatus, SupervisorStatus)
from quality_cell.core.supervisor_rules import RULE_TEXT, SupervisorRules
from quality_cell.nodes.common import CellNode


class SupervisorNode(CellNode):
    def __init__(self):
        super().__init__('supervisor')
        self.rules = SupervisorRules(self.cfg)
        self.last_cmd_text = ''

        # ---- command publishers
        self.pub_conv = self.create_publisher(ConveyorCommand, '/conveyor/command', 10)
        self.pub_cam = self.create_publisher(CameraCommand, '/camera/command', 10)
        self.pub_robot = self.create_publisher(RobotCommand, '/robot/command', 10)
        self.pub_status = self.create_publisher(SupervisorStatus, '/supervisor/status', 10)

        # ---- status subscribers: every callback ends with self.decide()
        self.create_subscription(IRSensorStatus, '/ir_sensor/status', self.on_ir, 10)
        self.create_subscription(ConveyorStatus, '/conveyor/status', self.on_conveyor, 10)
        self.create_subscription(CameraDetections, '/camera/detections', self.on_detections, 10)
        self.create_subscription(InspectionResult, '/camera/inspection_result',
                                 self.on_inspection, 10)
        self.create_subscription(RobotStatus, '/robot/status', self.on_robot, 10)

        rate = self.cfg['supervisor']['eval_rate_hz']
        self.create_timer(1.0 / rate, self.decide)          # time-based rules
        self.create_timer(0.2, self.publish_status)
        self.get_logger().info('Supervisor ready. Rules: %s' % ', '.join(RULE_TEXT))

    # ------------------------------------------------------------ status in
    def on_ir(self, msg):
        if msg.changed:
            self.get_logger().info('IR sensor -> %s' % msg.state)
        self.rules.on_ir(msg.state, self.now_s())
        self.decide()

    def on_conveyor(self, msg):
        self.rules.on_conveyor(msg.state)
        self.decide()

    def on_detections(self, msg):
        self.rules.on_detections(len(msg.pieces), msg.pick_zone_occupied, msg.camera_state)
        self.decide()

    def on_robot(self, msg):
        if msg.state != self.rules.view.robot_state:
            self.get_logger().info('Robot -> %s %s' % (msg.state, msg.target_bin))
        self.rules.on_robot(msg.state)
        self.decide()

    def on_inspection(self, msg):
        accepted = self.rules.on_inspection({
            'request_id': msg.request_id, 'success': msg.success, 'verdict': msg.verdict,
            'defect': msg.defect, 'destination_bin': msg.destination_bin,
            'pick_x_mm': msg.pick_x_mm, 'pick_y_mm': msg.pick_y_mm,
            'pick_z_mm': msg.pick_z_mm, 'pick_yaw_deg': msg.pick_yaw_deg})
        self.get_logger().info('Inspection #%d: %s %s %s -> %s (%s)' % (
            msg.request_id, msg.color, msg.shape, msg.verdict, msg.destination_bin,
            'accepted' if accepted else 'ignored'))
        self.decide()

    # ------------------------------------------------------------ decide
    def decide(self):
        cmds, _ = self.rules.evaluate(self.now_s())
        for c in cmds:
            self.send(c)

    def send(self, c):
        if c.target == 'conveyor':
            m = self.stamp(ConveyorCommand())
            m.command, m.reason = c.command, c.rule
            self.pub_conv.publish(m)
        elif c.target == 'camera':
            m = self.stamp(CameraCommand())
            m.command, m.request_id, m.reason = c.command, c.params['request_id'], c.rule
            self.pub_cam.publish(m)
        elif c.target == 'robot':
            m = self.stamp(RobotCommand())
            m.command, m.reason = c.command, c.rule
            p = c.params
            if p:
                m.job_id = p['job_id']
                m.pick_x_mm, m.pick_y_mm = p['pick_x_mm'], p['pick_y_mm']
                m.pick_z_mm, m.pick_yaw_deg = p['pick_z_mm'], p['pick_yaw_deg']
                m.destination_bin = p['destination_bin']
            self.pub_robot.publish(m)
        self.last_cmd_text = '/%s/command %s' % (c.target, c.command)
        self.get_logger().info('[%s] %s  (%s)' % (c.rule, self.last_cmd_text, RULE_TEXT[c.rule]))

    def publish_status(self):
        r = self.rules
        m = self.stamp(SupervisorStatus())
        m.cell_state = r.cell_state()
        m.last_rule = r.last_rule
        m.last_rule_text = RULE_TEXT.get(r.last_rule, '')
        m.last_command = self.last_cmd_text
        m.active_rules = list(r.active_rules)
        m.pieces_on_belt = r.view.transport_pieces + (1 if r.view.pick_zone_occupied else 0)
        m.pieces_processed = r.processed
        m.pieces_rejected = r.rejected
        self.pub_status.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = SupervisorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

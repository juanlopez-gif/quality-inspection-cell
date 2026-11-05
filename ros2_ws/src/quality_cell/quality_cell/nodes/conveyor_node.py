"""CONVEYOR NODE (simulated driver).

    Subscribes: /conveyor/command   (RUN | STOP)  <- only the supervisor publishes here
    Publishes : /conveyor/status    (RUNNING | STOPPED, speed)

It obeys commands and reports its state. It contains NO cell logic.
Real cell: replace the body of `apply()` with the call to the motor driver
(in this cell: arduino_io_node.py + arduino/cell_io/cell_io.ino).
"""
import rclpy

from cell_interfaces.msg import ConveyorCommand, ConveyorStatus
from quality_cell.nodes.common import CellNode


class ConveyorNode(CellNode):
    def __init__(self):
        super().__init__('conveyor')
        self.speed = float(self.cfg['conveyor']['speed_mm_s'])
        self.state = ConveyorStatus.STOPPED
        self.last_command = ''
        self.pub = self.create_publisher(ConveyorStatus, '/conveyor/status', 10)
        self.create_subscription(ConveyorCommand, '/conveyor/command', self.on_command, 10)
        self.create_timer(1.0 / self.cfg['conveyor']['status_rate_hz'], self.publish_status)

    def on_command(self, msg):
        self.last_command = msg.command
        if msg.command == ConveyorCommand.RUN:
            self.apply(ConveyorStatus.RUNNING)
        elif msg.command == ConveyorCommand.STOP:
            self.apply(ConveyorStatus.STOPPED)
        else:
            self.get_logger().warn('Unknown command %r' % msg.command)

    def apply(self, new_state):
        if new_state != self.state:
            self.get_logger().info('Conveyor %s -> %s' % (self.state, new_state))
            self.state = new_state
        self.publish_status()          # report immediately after a change

    def publish_status(self):
        m = self.stamp(ConveyorStatus())
        m.state = self.state
        m.speed_mm_s = self.speed if self.state == ConveyorStatus.RUNNING else 0.0
        m.last_command = self.last_command
        self.pub.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = ConveyorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

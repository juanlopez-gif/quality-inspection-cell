"""IR SENSOR NODE (simulated) - PURELY REACTIVE.

    Subscribes: /sim/world_state     (SIMULATION ONLY: what is physically on the belt)
    Publishes : /ir_sensor/status    (FREE | OCCUPIED)

There is NO /ir_sensor/command topic: nobody can tell the sensor what to do.
It reports periodically AND immediately whenever the reading changes.
Real cell: replace `on_world` with reading the GPIO / Arduino / controller input.
"""
import rclpy

from cell_interfaces.msg import IRSensorStatus, SimWorldState
from quality_cell.core.geometry import crosses_line_x
from quality_cell.nodes.common import CellNode


class IRSensorNode(CellNode):
    def __init__(self):
        super().__init__('ir_sensor')
        self.x_beam = self.cfg['ir_sensor']['x_mm']
        self.state = IRSensorStatus.FREE
        self.pub = self.create_publisher(IRSensorStatus, '/ir_sensor/status', 10)
        self.create_subscription(SimWorldState, '/sim/world_state', self.on_world, 10)
        self.create_timer(1.0 / self.cfg['ir_sensor']['rate_hz'], lambda: self.publish(False))

    def on_world(self, msg):
        blocked = any(p.location == 'BELT' and
                      crosses_line_x(p.x_mm, p.shape, p.size_mm, p.yaw_deg, self.x_beam)
                      for p in msg.pieces)
        new = IRSensorStatus.OCCUPIED if blocked else IRSensorStatus.FREE
        if new != self.state:
            self.state = new
            self.get_logger().info('IR beam -> %s' % new)
            self.publish(True)   # report the edge immediately

    def publish(self, changed):
        m = self.stamp(IRSensorStatus())
        m.state, m.changed = self.state, changed
        self.pub.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = IRSensorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

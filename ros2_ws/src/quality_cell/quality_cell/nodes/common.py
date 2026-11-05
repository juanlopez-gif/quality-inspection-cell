"""Helpers shared by all nodes."""
from rclpy.node import Node

from quality_cell.core.cell_config import load_config


class CellNode(Node):
    """Base class: declares `cell_config_file` and loads the shared YAML."""

    def __init__(self, name):
        super().__init__(name)
        path = self.declare_parameter('cell_config_file', '').value
        self.cfg = load_config(path or None)
        self.get_logger().info('Loaded cell config: %s' % self.cfg['_path'])

    def now_s(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def stamp(self, msg):
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'cell'
        return msg

"""Load the shared cell configuration and provide frame transforms."""
import math
import os

import yaml


def default_config_path():
    """Installed copy of config/cell_config.yaml (falls back to the source tree)."""
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(get_package_share_directory('quality_cell'),
                            'config', 'cell_config.yaml')
    except Exception:  # pragma: no cover - when running tests without ROS
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.normpath(os.path.join(here, '..', '..', 'config', 'cell_config.yaml'))


def load_config(path=None):
    path = path or default_config_path()
    with open(path, 'r') as f:
        cfg = yaml.safe_load(f)
    cfg['_path'] = path
    return cfg


def bins_by_id(cfg):
    return {b['id']: b for b in cfg['bins']['list']}


class FrameTransform:
    """CELL frame <-> ROBOT BASE frame (planar: translation + yaw)."""

    def __init__(self, cfg):
        rb = cfg['camera']['robot_base_in_cell']
        self.tx, self.ty, self.tz = rb['x'], rb['y'], rb['z']
        self.yaw = math.radians(rb.get('yaw_deg', 0.0))

    def cell_to_robot(self, x, y, z=0.0):
        dx, dy = x - self.tx, y - self.ty
        c, s = math.cos(-self.yaw), math.sin(-self.yaw)
        return (c * dx - s * dy, s * dx + c * dy, z - self.tz)

    def robot_to_cell(self, x, y, z=0.0):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return (c * x - s * y + self.tx, s * x + c * y + self.ty, z + self.tz)

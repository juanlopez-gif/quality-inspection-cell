"""WORLD SIMULATOR NODE - SIMULATION ONLY (does not exist in the real cell).

It plays the role of PHYSICS: it knows where every piece really is.

    Subscribes: /sim/spawn_piece   operator drops a piece at the start of the belt (dashboard)
                /sim/reset         remove every piece
                /conveyor/status   belt RUNNING -> pieces on the belt move along +X
                /robot/status      vacuum ON with the cup on a piece -> piece attached to the TCP;
                                   vacuum OFF -> piece falls into the bin under the TCP
    Publishes : /sim/world_state   ground truth (used by the simulated IR sensor & camera)
                /sim/events        human readable events (spawn rejected, piece binned...)

In the real cell this node disappears: the IR sensor and camera observe the
real world, the real belt moves the real pieces.
"""
import math
import random

import rclpy
from std_msgs.msg import Empty, String

from cell_interfaces.msg import ConveyorStatus, RobotStatus, SimPiece, SimWorldState, SpawnPiece
from quality_cell.core.cell_config import FrameTransform, bins_by_id
from quality_cell.core.geometry import half_extent_x
from quality_cell.nodes.common import CellNode

RATE_HZ = 50.0


class WorldSimNode(CellNode):
    def __init__(self):
        super().__init__('world_sim')
        c = self.cfg['conveyor']
        self.length, self.width = c['length_mm'], c['width_mm']
        self.spawn_x = c['spawn_x_mm']
        self.tf = FrameTransform(self.cfg)
        self.bins = bins_by_id(self.cfg)
        self.pieces = []
        self.next_id = 1
        self.belt_speed = 0.0
        self.belt_pos = 0.0
        self.vacuum_on = False
        self.held = None
        self.rng = random.Random()
        self.jammed = set()

        self.pub_world = self.create_publisher(SimWorldState, '/sim/world_state', 10)
        self.pub_events = self.create_publisher(String, '/sim/events', 10)
        self.create_subscription(SpawnPiece, '/sim/spawn_piece', self.on_spawn, 10)
        self.create_subscription(Empty, '/sim/reset', self.on_reset, 10)
        self.create_subscription(ConveyorStatus, '/conveyor/status', self.on_conveyor, 10)
        self.create_subscription(RobotStatus, '/robot/status', self.on_robot, 10)
        self.create_timer(1.0 / RATE_HZ, self.step)

    def event(self, text):
        self.get_logger().info(text)
        self.pub_events.publish(String(data=text))

    # ------------------------------------------------------------ operator
    def on_spawn(self, msg):
        h = half_extent_x(msg.shape, msg.size_mm, msg.yaw_deg)
        for p in self.pieces:
            if p.location == 'BELT':
                gap = (p.x_mm - half_extent_x(p.shape, p.size_mm, p.yaw_deg)) - (self.spawn_x + h)
                if gap < 10.0:
                    self.event('SPAWN REJECTED: start of the belt is occupied by piece %d' % p.id)
                    return
        p = SimPiece()
        p.id = self.next_id
        self.next_id += 1
        p.shape, p.color_name = msg.shape, msg.color_name
        p.r, p.g, p.b = msg.r, msg.g, msg.b
        p.size_mm, p.mark = msg.size_mm, msg.mark or 'NONE'
        lim = self.width / 2.0 - msg.size_mm / 2.0
        p.x_mm, p.y_mm = self.spawn_x, max(-lim, min(lim, msg.y_offset_mm))
        p.z_mm, p.yaw_deg = 0.0, msg.yaw_deg
        p.location = 'BELT'
        self.pieces.append(p)
        self.event('Piece %d placed: %s %s %.1fmm mark=%s' % (
            p.id, p.color_name, p.shape, p.size_mm, p.mark))

    def on_reset(self, _):
        self.pieces, self.held = [], None
        self.event('World reset: all pieces removed')

    # ------------------------------------------------------------ devices
    def on_conveyor(self, msg):
        self.belt_speed = msg.speed_mm_s if msg.state == ConveyorStatus.RUNNING else 0.0

    def on_robot(self, msg):
        cx, cy, cz = self.tf.robot_to_cell(msg.tcp_x_mm, msg.tcp_y_mm, msg.tcp_z_mm)
        if msg.vacuum_on and not self.vacuum_on:                    # suction starts
            cands = [p for p in self.pieces if p.location == 'BELT']
            if cands:
                p = min(cands, key=lambda q: math.hypot(q.x_mm - cx, q.y_mm - cy))
                dist = math.hypot(p.x_mm - cx, p.y_mm - cy)
                # The cup must be on the piece (centre within 1/3 of its size) and low enough
                if dist < p.size_mm / 3.0 and cz < self.cfg['pieces']['thickness_mm'] + 5.0:
                    p.location, self.held = 'GRIPPER', p
                    self.event('Vacuum ON: robot picked piece %d (cup %.1f mm from centre)' % (p.id, dist))
                else:
                    self.event('Vacuum ON but NO piece under the cup (nearest %.0f mm, z=%.0f)'
                               % (dist, cz))
        if not msg.vacuum_on and self.vacuum_on and self.held:      # suction released
            p, self.held = self.held, None
            b = self.bins.get(msg.target_bin)
            if b and math.hypot(b['x'] - cx, b['y'] - cy) < self.cfg['bins']['size_mm'] / 2:
                p.location, p.bin_id = 'BIN', b['id']
                p.x_mm = b['x'] + self.rng.uniform(-15, 15)
                p.y_mm = b['y'] + self.rng.uniform(-15, 15)
                p.z_mm = 0.0
                self.event('Piece %d dropped in %s' % (p.id, b['id']))
            else:
                p.location = 'FLOOR'
                self.event('Piece %d dropped OUTSIDE any bin!' % p.id)
        self.vacuum_on = msg.vacuum_on
        if self.held:
            self.held.x_mm, self.held.y_mm, self.held.z_mm = cx, cy, cz
            self.held.yaw_deg = msg.tcp_yaw_deg

    # ------------------------------------------------------------ physics
    def step(self):
        dx = self.belt_speed / RATE_HZ
        self.belt_pos += dx
        if dx > 0:
            for p in self.pieces:
                if p.location == 'BELT':
                    end = self.length - half_extent_x(p.shape, p.size_mm, p.yaw_deg)
                    if p.x_mm + dx > end:
                        p.x_mm = end
                        if p.id not in self.jammed:
                            self.jammed.add(p.id)
                            self.event('WARNING: piece %d reached the end of the belt (jam)' % p.id)
                    else:
                        p.x_mm += dx
        m = self.stamp(SimWorldState())
        m.pieces = list(self.pieces)
        m.belt_position_mm = self.belt_pos
        self.pub_world.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = WorldSimNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

"""DASHBOARD NODE - web visualisation + operator panel (http://localhost:8080).

  * Subscribes to EVERY cell topic (read-only monitor) and keeps the latest
    message, message counts and rates.
  * Introspects the live ROS graph (like rqt_graph) every second.
  * Serves the web page in quality_cell/web/ and a small JSON API:
        GET  /api/state      latest messages, stats, supervisor info, config
        GET  /api/graph      live ROS graph (nodes, topics, publishers, subscribers)
        GET  /api/events     event log  (?since=<seq>)
        GET  /api/camera.jpg latest /camera/debug_image (opencv camera backend)
        POST /api/spawn      {shape, color_name, r, g, b, size_mm, mark, y_offset_mm, yaw_deg}
        POST /api/reset      remove every piece from the simulated world
  * The ONLY things it publishes are SIMULATION topics (/sim/spawn_piece,
    /sim/reset): it plays the operator who puts pieces on the belt.
    It NEVER commands the conveyor, camera or robot - that is the supervisor's job.
"""
import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from ament_index_python.packages import get_package_share_directory
from rosidl_runtime_py import message_to_ordereddict
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Empty, String

from cell_interfaces.msg import (CameraCommand, CameraDetections, ConveyorCommand,
                                 ConveyorStatus, InspectionResult, IRSensorStatus,
                                 RobotCommand, RobotStatus, SimWorldState, SpawnPiece,
                                 SupervisorStatus)
from quality_cell.core.supervisor_rules import RULE_TEXT
from quality_cell.nodes.common import CellNode

TOPICS = {
    '/conveyor/command': ConveyorCommand,
    '/conveyor/status': ConveyorStatus,
    '/ir_sensor/status': IRSensorStatus,
    '/camera/command': CameraCommand,
    '/camera/detections': CameraDetections,
    '/camera/inspection_result': InspectionResult,
    '/robot/command': RobotCommand,
    '/robot/status': RobotStatus,
    '/supervisor/status': SupervisorStatus,
    '/sim/world_state': SimWorldState,
    '/sim/spawn_piece': SpawnPiece,
    '/sim/events': String,
}
HIDDEN_TOPICS = ('/rosout', '/parameter_events')


class TopicStats:
    def __init__(self):
        self.count = 0
        self.stamps = deque(maxlen=200)
        self.last = None

    def add(self, d):
        self.count += 1
        self.stamps.append(time.time())
        self.last = d

    def hz(self):
        now = time.time()
        recent = [t for t in self.stamps if now - t < 2.0]
        return len(recent) / 2.0


class DashboardNode(CellNode):
    def __init__(self):
        super().__init__('cell_dashboard')
        self.port = int(self.declare_parameter('port', self.cfg['dashboard']['port']).value)
        self.lock = threading.Lock()
        self.stats = {t: TopicStats() for t in TOPICS}
        self.events = deque(maxlen=500)
        self.seq = 0
        self.graph = {'nodes': [], 'topics': []}
        self.prev = {}          # previous "state" value per topic for change detection
        self.inspections = deque(maxlen=50)

        for topic, typ in TOPICS.items():
            self.create_subscription(typ, topic, self._make_cb(topic), 10)
        self.camera_jpeg, self.camera_stamp = None, 0.0
        self.create_subscription(CompressedImage, '/camera/debug_image', self.on_image, 2)
        self.pub_spawn = self.create_publisher(SpawnPiece, '/sim/spawn_piece', 10)
        self.pub_reset = self.create_publisher(Empty, '/sim/reset', 10)
        self.create_timer(1.0, self.update_graph)

        self.web_dir = os.path.join(get_package_share_directory('quality_cell'), 'web')
        self.start_http()

    # ------------------------------------------------------------ monitoring
    def _make_cb(self, topic):
        def cb(msg):
            d = message_to_ordereddict(msg)
            with self.lock:
                self.stats[topic].add(d)
                self._log_if_interesting(topic, msg)
        return cb

    def on_image(self, msg):
        with self.lock:
            self.camera_jpeg, self.camera_stamp = bytes(msg.data), time.time()

    def _event(self, kind, topic, text):
        self.seq += 1
        self.events.append({'seq': self.seq, 't': time.time(), 'kind': kind,
                            'topic': topic, 'text': text})

    def _log_if_interesting(self, topic, msg):
        """Commands and inspection results are always logged; statuses only on change."""
        if topic.endswith('/command'):
            extra = ''
            if isinstance(msg, RobotCommand) and msg.command == 'PICK_AND_PLACE':
                extra = ' -> %s pick=(%.0f, %.0f, %.0f)' % (
                    msg.destination_bin, msg.pick_x_mm, msg.pick_y_mm, msg.pick_z_mm)
            if isinstance(msg, CameraCommand):
                extra = ' #%d' % msg.request_id
            rule = msg.reason
            self._event('command', topic, '%s%s  [%s: %s]' % (
                msg.command, extra, rule, RULE_TEXT.get(rule, '')))
        elif topic == '/camera/inspection_result':
            self.inspections.appendleft(message_to_ordereddict(msg))
            self._event('result', topic, '#%d %s %s %.1fmm mark=%s -> %s %s (%s)' % (
                msg.request_id, msg.color, msg.shape, msg.measured_size_mm, msg.mark_type,
                msg.verdict, msg.defect, msg.destination_bin))
        elif topic == '/sim/events':
            self._event('sim', topic, msg.data)
        elif topic == '/sim/spawn_piece':
            pass
        elif hasattr(msg, 'state') or hasattr(msg, 'cell_state'):
            key = getattr(msg, 'state', None) or getattr(msg, 'cell_state', '')
            if isinstance(msg, RobotStatus) and msg.target_bin:
                key = '%s -> %s' % (key, msg.target_bin)
            if self.prev.get(topic) != key:
                self.prev[topic] = key
                self._event('status', topic, key)
        elif topic == '/camera/detections':
            key = '%d piece(s) in transport, pick zone %s' % (
                len(msg.pieces), 'OCCUPIED' if msg.pick_zone_occupied else 'empty')
            if self.prev.get(topic) != key:
                self.prev[topic] = key
                self._event('status', topic, key)

    def update_graph(self):
        """Live graph like rqt_graph: who publishes / subscribes each topic."""
        try:
            nodes = sorted({('/' + ns.strip('/') + '/' + n).replace('//', '/')
                            for n, ns in self.get_node_names_and_namespaces()})
            topics = []
            for name, types in self.get_topic_names_and_types():
                if name in HIDDEN_TOPICS:
                    continue
                pubs = sorted({self._fq(i) for i in self.get_publishers_info_by_topic(name)})
                subs = sorted({self._fq(i) for i in self.get_subscriptions_info_by_topic(name)})
                topics.append({'name': name, 'type': types[0] if types else '',
                               'publishers': pubs, 'subscribers': subs})
            with self.lock:
                self.graph = {'nodes': nodes, 'topics': topics, 't': time.time()}
        except Exception as e:  # pragma: no cover
            self.get_logger().warn('graph introspection failed: %s' % e)

    @staticmethod
    def _fq(info):
        ns = info.node_namespace.rstrip('/')
        return '%s/%s' % (ns, info.node_name)

    # ------------------------------------------------------------ API
    def api_state(self):
        with self.lock:
            return {
                'time': time.time(),
                'topics': {t: {'count': s.count, 'hz': round(s.hz(), 1), 'last': s.last}
                           for t, s in self.stats.items()},
                'inspections': list(self.inspections)[:10],
                'last_seq': self.seq,
            }

    def api_events(self, since):
        with self.lock:
            return [e for e in self.events if e['seq'] > since]

    def api_config(self):
        cfg = dict(self.cfg)
        cfg['rules'] = RULE_TEXT
        return cfg

    def spawn(self, d):
        m = SpawnPiece()
        m.shape = str(d.get('shape', 'CIRCLE')).upper()
        m.color_name = str(d.get('color_name', 'RED')).upper()
        m.r, m.g, m.b = [int(max(0, min(255, d.get(k, 0)))) for k in ('r', 'g', 'b')]
        m.size_mm = float(d.get('size_mm', 42.0))
        m.mark = str(d.get('mark', 'NONE')).upper()
        m.y_offset_mm = float(d.get('y_offset_mm', 0.0))
        m.yaw_deg = float(d.get('yaw_deg', 0.0))
        self.pub_spawn.publish(m)

    def start_http(self):
        node = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype='application/json'):
                data = body if isinstance(body, bytes) else body.encode()
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path, _, query = self.path.partition('?')
                if path == '/api/state':
                    return self._send(200, json.dumps(node.api_state()))
                if path == '/api/graph':
                    with node.lock:
                        return self._send(200, json.dumps(node.graph))
                if path == '/api/camera.jpg':
                    with node.lock:
                        jpg, age = node.camera_jpeg, time.time() - node.camera_stamp
                    if jpg is None or age > 3.0:
                        return self._send(404, 'no camera image', 'text/plain')
                    return self._send(200, jpg, 'image/jpeg')
                if path == '/api/config':
                    return self._send(200, json.dumps(node.api_config()))
                if path == '/api/events':
                    since = 0
                    for kv in query.split('&'):
                        if kv.startswith('since='):
                            since = int(kv[6:] or 0)
                    return self._send(200, json.dumps(node.api_events(since)))
                if path == '/':
                    path = '/index.html'
                f = os.path.normpath(os.path.join(node.web_dir, path.lstrip('/')))
                if not f.startswith(node.web_dir) or not os.path.isfile(f):
                    return self._send(404, 'not found', 'text/plain')
                ctype = {'.html': 'text/html', '.js': 'application/javascript',
                         '.css': 'text/css', '.svg': 'image/svg+xml'}.get(
                    os.path.splitext(f)[1], 'application/octet-stream')
                with open(f, 'rb') as fh:
                    return self._send(200, fh.read(), ctype + '; charset=utf-8')

            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0) or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b'{}')
                except ValueError:
                    return self._send(400, '{"error": "bad json"}')
                if self.path == '/api/spawn':
                    node.spawn(body)
                    return self._send(200, '{"ok": true}')
                if self.path == '/api/reset':
                    node.pub_reset.publish(Empty())
                    return self._send(200, '{"ok": true}')
                return self._send(404, '{"error": "unknown endpoint"}')

        self.httpd = ThreadingHTTPServer(('0.0.0.0', self.port), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.get_logger().info('Dashboard running at  http://localhost:%d' % self.port)


def main(args=None):
    rclpy.init(args=args)
    node = DashboardNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.httpd.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()

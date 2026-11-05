"""CAMERA NODE - overhead camera above the conveyor.

    Subscribes: /camera/command            (INSPECT | CANCEL)  <- supervisor
                /sim/world_state           (only in simulation)
    Publishes : /camera/detections         preliminary detections (transport zone), 10 Hz
                /camera/inspection_result  final inspection + pick pose + destination bin
                /camera/debug_image        JPEG with overlays (opencv backend) for the dashboard

Two jobs:
  1) Continuously report the pieces on the belt OUTSIDE the pick zone
     (shape + colour: a first idea of what is coming) and whether the pick zone
     is occupied.
  2) On INSPECT (piece stopped at the IR sensor) inspect the piece inside the
     pick ROI: colour, size, marks -> verdict + bin (classifier.py), and the pick
     pose, reported in the ROBOT BASE frame.

Perception backends (cell_config.yaml -> camera.backend, or parameter `backend`):
  sim     ground truth from the simulator + noise (perception.py). No images.
  opencv  the REAL pipeline (vision.py) on images. Image source (`camera.source`
          or parameter `source`):
            sim_render         images rendered from the simulator (sim_renderer.py)
            0 / /dev/video0 /  a real camera (cv2.VideoCapture), needs the
            rtsp://... / file  calibration file made with tools/calibrate_camera.py
"""
import threading
import time

import cv2
import numpy as np
import rclpy
import yaml
from rcl_interfaces.msg import ParameterDescriptor
from sensor_msgs.msg import CompressedImage

from cell_interfaces.msg import (CameraCommand, CameraDetections, DetectedPiece,
                                 InspectionResult, SimWorldState)
from quality_cell.core.cell_config import FrameTransform
from quality_cell.core.classifier import classify, classify_color
from quality_cell.core.geometry import inside_box
from quality_cell.core.perception import SimulatedPerception
from quality_cell.nodes.common import CellNode


class FrameGrabber:
    """Reads a real camera in a background thread and keeps only the newest frame."""

    def __init__(self, source, cap_cfg, logger):
        self.log = logger
        src = int(source) if str(source).isdigit() else source
        # Linux USB cameras: use V4L2 directly (the default GStreamer backend often fails)
        if isinstance(src, int) or str(src).startswith('/dev/video'):
            self.cap = cv2.VideoCapture(src, cv2.CAP_V4L2)
        else:
            self.cap = cv2.VideoCapture(src)
        if cap_cfg:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cap_cfg.get('width', 1280))
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cap_cfg.get('height', 720))
            self.cap.set(cv2.CAP_PROP_FPS, cap_cfg.get('fps', 30))
        if not self.cap.isOpened():
            raise RuntimeError('Cannot open camera source %r' % (source,))
        self.frame, self.stamp = None, 0.0
        self.lock = threading.Lock()
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            ok, f = self.cap.read()
            if not ok:
                self.log.warn('Camera read failed', throttle_duration_sec=2)
                time.sleep(0.1)
                continue
            with self.lock:
                self.frame, self.stamp = f, time.monotonic()

    def get(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()


class CameraNode(CellNode):
    def __init__(self):
        super().__init__('camera')
        c = self.cfg['camera']
        # Parameters override the config file; empty = use cell_config.yaml
        self.backend = self.declare_parameter('backend', '').value or c.get('backend', 'sim')
        # dynamic typing: `-p source:=0` (int) and `-p source:=/dev/video2` (str) both work
        self.source = str(self.declare_parameter(
            'source', '', ParameterDescriptor(dynamic_typing=True)).value or c.get('source', 'sim_render'))
        self.fov, self.roi = c['fov'], c['pick_roi']
        self.tf = FrameTransform(self.cfg)
        self.world = None
        self.state = 'STREAMING'
        self.pending = None          # inspection in progress: dict
        self.last_dets, self.last_insp = [], None
        self.frame = None

        self.pub_det = self.create_publisher(CameraDetections, '/camera/detections', 10)
        self.pub_res = self.create_publisher(InspectionResult, '/camera/inspection_result', 10)
        self.create_subscription(CameraCommand, '/camera/command', self.on_command, 10)

        if self.backend == 'sim':
            self.perception = SimulatedPerception(self.cfg)
            self.prev_belt_pos = None
            self.create_subscription(SimWorldState, '/sim/world_state', self.on_world, 10)
            self.create_timer(1.0 / c['detection_rate_hz'], self.sim_detections)
        elif self.backend == 'opencv':
            self.setup_opencv(c)
        else:
            raise RuntimeError('camera.backend must be sim or opencv, not %r' % self.backend)
        self.get_logger().info('Camera backend: %s  source: %s' % (
            self.backend, self.source if self.backend == 'opencv' else 'ground truth'))

    # ======================================================================= SIM backend
    def on_world(self, msg):
        self.world = msg

    def belt_pieces(self):
        if self.world is None:
            return []
        return [p for p in self.world.pieces
                if p.location == 'BELT' and inside_box(p.x_mm, p.y_mm, self.fov)]

    def sim_detections(self):
        if self.world is None:
            return
        pos = self.world.belt_position_mm
        moving = self.prev_belt_pos is not None and abs(pos - self.prev_belt_pos) > 0.5
        self.prev_belt_pos = pos
        m = self.stamp(CameraDetections())
        for p in self.belt_pieces():
            if inside_box(p.x_mm, p.y_mm, self.roi):
                m.pick_zone_occupied = True
                continue
            d = self.perception.detect(p)
            m.pieces.append(self.detected_piece(p.id, d['shape'],
                                                classify_color(d['rgb'], self.cfg['classification']),
                                                p.x_mm, p.y_mm, d['confidence']))
        m.belt_motion_detected = moving
        m.camera_state = self.state
        self.pub_det.publish(m)

    def sim_inspect(self, request_id):
        r = self.stamp(InspectionResult())
        r.request_id = request_id
        in_roi = [p for p in self.belt_pieces() if inside_box(p.x_mm, p.y_mm, self.roi)]
        if not in_roi:
            return self.publish_failure(r)
        p = max(in_roi, key=lambda q: q.x_mm)
        f = self.perception.inspect(p)
        x, y, yaw, conf = self.perception.estimate_pose(p)
        self.publish_result(r, p.id, f['shape'], f['rgb'], f['size_mm'], f['mark_detected'],
                            f['mark_type'], x, y, yaw, conf)

    # ======================================================================= OPENCV backend
    def setup_opencv(self, c):
        from quality_cell.core.vision import BeltVision, SimpleTracker
        self.renderer, self.grabber = None, None
        if self.source == 'sim_render':
            from quality_cell.core.sim_renderer import SimCameraRenderer
            self.renderer = SimCameraRenderer(self.cfg)
            H = self.renderer.H_img_to_cell
            self.create_subscription(SimWorldState, '/sim/world_state', self.on_world, 10)
        else:
            path = c.get('calibration_file') or ''
            path = self.declare_parameter('calibration_file', path).value
            if not path:
                raise RuntimeError('A real camera needs camera.calibration_file '
                                   '(run tools/calibrate_camera.py)')
            with open(path) as f:
                cal = yaml.safe_load(f)
            H = np.array(cal['homography_img_to_cell'], dtype=np.float64)
            self.cal_size = tuple(cal.get('image_size', ()))
            self.grabber = FrameGrabber(self.source, c.get('capture'), self.get_logger())
        self.vision = BeltVision(self.cfg, H)
        self.last_insp = {'x': 0.0, 'y': 0.0, 'text': ''}
        self.tracker = SimpleTracker()
        self.pub_img = self.create_publisher(CompressedImage, '/camera/debug_image', 2)
        self.create_timer(1.0 / c['detection_rate_hz'], self.cv_detections)
        self.create_timer(1.0 / c['vision']['debug_image_rate_hz'], self.publish_debug_image)

    def grab(self):
        if self.renderer is not None:
            if self.world is None:
                return None
            return self.renderer.render(self.world.pieces, self.world.belt_position_mm)
        return self.grabber.get()

    def cv_detections(self):
        frame = self.grab()
        if frame is None:
            return
        if self.frame is None and getattr(self, 'cal_size', None) and \
                tuple(frame.shape[1::-1]) != self.cal_size:
            self.get_logger().error(
                'Image size %s differs from the calibration %s: the camera did not accept the '
                'requested resolution, or it changed. Re-calibrate or fix camera.capture.'
                % (frame.shape[1::-1], self.cal_size))
        self.frame = frame
        now = time.monotonic()
        dets = [d for d in self.vision.detect(frame, self.fov) if not d['partial']]
        self.tracker.update(dets, now)
        moving = self.vision.belt_motion(frame, self.fov)
        m = self.stamp(CameraDetections())
        for d in dets:
            d['in_roi'] = inside_box(d['x_mm'], d['y_mm'], self.roi)
            if d['in_roi']:
                m.pick_zone_occupied = True
                continue
            m.pieces.append(self.detected_piece(d['track_id'], d['shape'], d['color'],
                                                d['x_mm'], d['y_mm'], 0.9))
        m.belt_motion_detected = moving
        m.camera_state = self.state
        self.last_dets = dets
        self.pub_det.publish(m)
        if self.pending is not None:
            self.cv_inspect_step(frame)

    def cv_inspect_step(self, frame):
        """Called with every new frame while INSPECTING: accumulate N measurements."""
        found, _ = self.vision.inspect(frame, self.roi)
        found = [f for f in found if not f['partial']]
        if found:
            self.pending['samples'].append(max(found, key=lambda f: f['x_mm']))
        self.pending['frames'] += 1
        need = self.cfg['camera']['vision']['inspect_frames']
        if len(self.pending['samples']) >= need or self.pending['frames'] >= need * 4:
            self.cv_finish()

    def cv_finish(self):
        job, self.pending, self.state = self.pending, None, 'STREAMING'
        r = self.stamp(InspectionResult())
        r.request_id = job['request_id']
        s = job['samples']
        if not s:
            return self.publish_failure(r)
        shapes = [q['shape'] for q in s]
        shape = max(set(shapes), key=shapes.count)
        rgb = tuple(float(np.median([q['rgb'][i] for q in s])) for i in range(3))
        size = float(np.median([q['size_mm'] for q in s]))
        marked = sum(q['mark_detected'] for q in s) * 2 > len(s)     # majority vote
        x = float(np.median([q['x_mm'] for q in s]))
        y = float(np.median([q['y_mm'] for q in s]))
        yaw = float(np.median([q['yaw_deg'] for q in s]))
        tid = next((d['track_id'] for d in self.last_dets if d.get('in_roi')), 0)
        self.last_insp = {'x': x, 'y': y, 'text': ''}
        self.publish_result(r, tid, shape, rgb, size, marked, 'MARK' if marked else 'NONE',
                            x, y, yaw, min(1.0, len(s) / max(1, job['frames'])))

    def publish_debug_image(self):
        if self.frame is None:
            return
        img = self.frame.copy()
        V = self.vision

        def poly(box, color, th):
            pts = V.cell_to_img([(box['x_min'], box['y_min']), (box['x_max'], box['y_min']),
                                 (box['x_max'], box['y_max']), (box['x_min'], box['y_max'])])
            cv2.polylines(img, [np.int32(pts)], True, color, th, cv2.LINE_AA)
            return pts
        fov_pts = poly(self.fov, (66, 197, 245), 1)
        roi_pts = poly(self.roi, (66, 197, 245), 3 if self.state == 'INSPECTING' else 2)
        cv2.putText(img, 'PICK ROI' + (' - INSPECTING' if self.state == 'INSPECTING' else ''),
                    tuple(int(v) for v in roi_pts[3] + (0, -8)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (66, 197, 245), 1, cv2.LINE_AA)
        for d in self.last_dets:
            c = d['contour'].reshape(-1, 2).astype(np.float64) / self.cfg['camera']['vision']['detect_px_per_mm']
            cell = np.c_[self.fov['x_min'] + c[:, 0], self.fov['y_max'] - c[:, 1]]
            pts = np.int32(V.cell_to_img(cell))
            col = (80, 220, 120) if d['color'] != 'UNKNOWN' else (60, 60, 255)
            cv2.polylines(img, [pts], True, col, 2, cv2.LINE_AA)
            cx, cy = V.cell_to_img([(d['x_mm'], d['y_mm'])])[0]
            cv2.drawMarker(img, (int(cx), int(cy)), (255, 255, 255), cv2.MARKER_CROSS, 10, 1)
            label = '#%d %s %s %.1fmm' % (d['track_id'], d['color'], d['shape'], d['size_mm'])
            org = (int(pts[:, 0].min()), int(pts[:, 1].min()) - 6)
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1, cv2.LINE_AA)
        # crop to the belt (+ margin) so the dashboard shows it big
        hh, ww = img.shape[:2]
        x0, y0 = np.maximum(fov_pts.min(axis=0) - 50, 0).astype(int)
        x1, y1 = np.minimum(fov_pts.max(axis=0) + 50, (ww, hh)).astype(int)
        img = np.ascontiguousarray(img[y0:y1, x0:x1])
        if self.last_insp and self.last_insp['text']:
            cv2.putText(img, 'LAST INSPECTION: ' + self.last_insp['text'], (10, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        ok, jpg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            m = CompressedImage()
            m.header.stamp = self.get_clock().now().to_msg()
            m.header.frame_id = 'camera'
            m.format = 'jpeg'
            m.data = jpg.tobytes()
            self.pub_img.publish(m)

    # ======================================================================= common
    @staticmethod
    def detected_piece(tid, shape, color, x, y, conf):
        dp = DetectedPiece()
        dp.track_id, dp.shape, dp.color = int(tid), shape, color
        dp.x_mm, dp.y_mm, dp.confidence = float(x), float(y), float(conf)
        return dp

    def on_command(self, msg):
        if msg.command == CameraCommand.INSPECT:
            self.get_logger().info('INSPECT request #%d (%s)' % (msg.request_id, msg.reason))
            self.state = 'INSPECTING'
            if self.backend == 'sim':
                if self.pending:
                    self.pending.cancel()
                rid = msg.request_id

                def done():
                    self.pending.cancel()
                    self.pending, self.state = None, 'STREAMING'
                    self.sim_inspect(rid)
                self.pending = self.create_timer(self.cfg['camera']['inspection_time_s'], done)
            else:
                self.pending = {'request_id': msg.request_id, 'samples': [], 'frames': 0}
        elif msg.command == CameraCommand.CANCEL and self.pending is not None:
            if self.backend == 'sim':
                self.pending.cancel()
            self.pending, self.state = None, 'STREAMING'

    def publish_failure(self, r):
        r.success, r.verdict = False, InspectionResult.VERDICT_REJECT
        r.defect = InspectionResult.DEFECT_NO_PIECE
        self.get_logger().warn('Inspection #%d: no piece in the ROI' % r.request_id)
        self.pub_res.publish(r)

    def publish_result(self, r, track_id, shape, rgb, size, marked, mark_type, x, y, yaw, conf):
        d = classify(shape, rgb, size, marked, self.cfg)
        r.success, r.track_id = True, int(track_id)
        r.shape, r.color = shape, d['color']
        r.measured_size_mm = float(size)
        r.mark_detected, r.mark_type = bool(marked), mark_type
        r.verdict, r.defect, r.destination_bin = d['verdict'], d['defect'], d['destination_bin']
        rx, ry, rz = self.tf.cell_to_robot(x, y, self.cfg['pieces']['thickness_mm'])
        r.pick_x_mm, r.pick_y_mm, r.pick_z_mm, r.pick_yaw_deg = rx, ry, rz, float(yaw)
        r.pose_confidence = float(conf)
        text = '%s %s %.1fmm mark=%s -> %s' % (r.color, r.shape, size, mark_type, r.destination_bin)
        if self.last_insp is not None:
            self.last_insp['text'] = text
        self.get_logger().info('Inspection #%d piece %d: %s  pick(robot)=(%.1f, %.1f, %.1f)'
                               % (r.request_id, r.track_id, text, rx, ry, rz))
        self.pub_res.publish(r)


def main(args=None):
    rclpy.init(args=args)
    node = CameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if getattr(node, 'grabber', None):
            node.grabber.running = False
        node.destroy_node()
        rclpy.try_shutdown()

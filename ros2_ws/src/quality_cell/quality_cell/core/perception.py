"""Simulated camera perception.

The camera node calls a *perception backend*. Here we provide the simulated
one, which "looks" at the ground truth published by the world simulator and
adds noise. To use the real camera, write another class with the same three
methods (e.g. OpenCV contours + HSV for detection, a trained model such as
YOLO-pose / a keypoint CNN for the pick pose) and select it in camera_node.

    detect(piece)        -> preliminary (shape, rgb, confidence)   [moving belt]
    inspect(piece)       -> final features (shape, rgb, size, mark) [stopped, ROI]
    estimate_pose(piece) -> (x, y, yaw) in CELL frame                [pick pose model]
"""
import random


class SimulatedPerception:
    def __init__(self, cfg, seed=None):
        self.c = cfg['camera']
        self.rng = random.Random(seed)

    def _noisy_rgb(self, p):
        n = self.c['color_noise_std']
        return tuple(max(0, min(255, int(round(v + self.rng.gauss(0, n)))))
                     for v in (p.r, p.g, p.b))

    def detect(self, p):
        """Fast, rough detection while the belt is moving (shape + colour only)."""
        return {'shape': p.shape, 'rgb': self._noisy_rgb(p),
                'confidence': round(self.rng.uniform(0.85, 0.99), 2)}

    def inspect(self, p):
        """Careful inspection of the stopped piece inside the pick ROI."""
        detected = p.mark != 'NONE' and self.rng.random() < self.c['mark_detection_probability']
        return {'shape': p.shape, 'rgb': self._noisy_rgb(p),
                'size_mm': p.size_mm + self.rng.gauss(0, self.c['size_noise_std_mm']),
                'mark_detected': detected,
                'mark_type': p.mark if detected else 'NONE'}

    def estimate_pose(self, p):
        """Simulates the ML pose model: centre + orientation of the piece."""
        n = self.c['position_noise_std_mm']
        yaw = p.yaw_deg + self.rng.gauss(0, self.c['yaw_noise_std_deg'])
        if p.shape == 'SQUARE':          # a square is symmetric every 90 deg
            yaw = ((yaw + 45.0) % 90.0) - 45.0
        else:                             # a circle has no meaningful yaw
            yaw = 0.0
        return (p.x_mm + self.rng.gauss(0, n), p.y_mm + self.rng.gauss(0, n), yaw,
                round(self.rng.uniform(0.9, 0.99), 2))

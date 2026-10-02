import math

import numpy as np

from optics_bench_camera.spot import find_spot, image_to_array


def gaussian(h=200, w=300, x=120.3, y=80.7, sx=6.0, sy=3.0, angle=0.0, peak=200, bg=10, noise=0.0, seed=0):
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    dx, dy = xx - x, yy - y
    c, s = math.cos(angle), math.sin(angle)
    u, v = c * dx + s * dy, -s * dx + c * dy
    img = bg + peak * np.exp(-0.5 * (u / sx) ** 2 - 0.5 * (v / sy) ** 2)
    img += np.random.default_rng(seed).normal(0, noise, img.shape)
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def test_centroid_and_width():
    s = find_spot(gaussian(), threshold=0.05)
    assert s.found and not s.saturated
    assert abs(s.x - 120.3) < 0.05 and abs(s.y - 80.7) < 0.05
    assert abs(s.sigma_x - 6.0) < 0.6 and abs(s.sigma_y - 3.0) < 0.3    # the threshold trims the wings a little


def test_rotated_spot_angle():
    s = find_spot(gaussian(angle=0.5), threshold=0.05)
    assert abs(s.angle - 0.5) < 0.02


def test_noise_and_no_spot():
    s = find_spot(gaussian(noise=3.0), threshold=0.25)
    assert s.found and abs(s.x - 120.3) < 0.3 and abs(s.y - 80.7) < 0.3
    dark = np.random.default_rng(1).normal(12, 2, (200, 300)).clip(0, 255).astype(np.uint8)
    assert not find_spot(dark).found


def test_saturation():
    assert find_spot(gaussian(peak=400)).saturated


class Msg:
    def __init__(self, arr, encoding, step=None):
        self.height, self.width = arr.shape[:2]
        self.encoding = encoding
        self.is_bigendian = False
        raw = arr.tobytes()
        self.step = step or len(raw) // self.height
        self.data = raw


def test_image_encodings():
    g = gaussian()
    a, full = image_to_array(Msg(g, "mono8"))
    assert full == 255 and (a == g).all()
    yuyv = np.zeros((g.shape[0], g.shape[1] * 2), np.uint8)
    yuyv[:, 0::2] = g
    yuyv[:, 1::2] = 128
    a, _ = image_to_array(Msg(yuyv, "yuv422_yuy2"))
    assert (a == g).all()
    a, full = image_to_array(Msg(g.astype("<u2") * 256, "mono16"))
    assert full == 65535 and abs(find_spot(a, full).x - 120.3) < 0.1

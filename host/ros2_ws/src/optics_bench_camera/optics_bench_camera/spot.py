"""Find the laser spot in a camera frame: background-subtracted intensity moments.

Plain numpy, so it can be tried on saved frames without ROS. The bare OV9281
sensor (no lens) sits where the beam will go and sees the spot directly.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np


class Spot(NamedTuple):
    found: bool
    x: float = 0.0          # centroid, pixels (x right, y down)
    y: float = 0.0
    sigma_x: float = 0.0    # 1-sigma widths, pixels
    sigma_y: float = 0.0
    angle: float = 0.0      # major axis from +x, radians
    peak: float = 0.0       # brightest pixel, 0-1 of full scale
    pixels: int = 0
    saturated: bool = False


def find_spot(img, full_scale=None, threshold=0.25, min_peak=0.05, min_pixels=4):
    """img: 2-D array (or H x W x C, averaged to grey). The background is the
    median pixel; pixels above `threshold` of the way from the background to
    the brightest one are weighted by how far above the background they are.
    `min_peak`: no spot unless the brightest pixel is this far (0-1 of full
    scale) above the background."""
    a = np.asarray(img)
    if a.ndim == 3:
        a = a.mean(axis=2)
    if full_scale is None:
        full_scale = float(np.iinfo(a.dtype).max) if np.issubdtype(a.dtype, np.integer) else 1.0
    a = a.astype(np.float64)
    top = float(a.max())
    bg = float(np.median(a[::4, ::4]))     # every 16th pixel is plenty for the background
    if (top - bg) < min_peak * full_scale:
        return Spot(False, peak=top / full_scale)
    w = a - (bg + threshold * (top - bg))
    mask = w > 0
    n = int(mask.sum())
    if n < min_pixels:
        return Spot(False, peak=top / full_scale, pixels=n)
    ys, xs = np.nonzero(mask)
    wt = a[ys, xs] - bg
    s = wt.sum()
    cx, cy = float((wt * xs).sum() / s), float((wt * ys).sum() / s)
    dx, dy = xs - cx, ys - cy
    sxx, syy, sxy = (wt * dx * dx).sum() / s, (wt * dy * dy).sum() / s, (wt * dx * dy).sum() / s
    angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
    saturated = bool((a[mask] >= full_scale * 0.999).any())
    return Spot(True, cx, cy, math.sqrt(sxx), math.sqrt(syy), angle, top / full_scale, n, saturated)


def image_to_array(msg):
    """sensor_msgs/Image -> (2-D numpy array, full scale). Mono and colour
    8-bit, mono16 and YUYV (the luma) are handled; others raise ValueError."""
    enc = msg.encoding.lower()
    h, w, step = msg.height, msg.width, msg.step
    buf = np.frombuffer(bytes(msg.data), dtype=np.uint8)
    if enc in ("mono8", "8uc1"):
        return buf.reshape(h, step)[:, :w], 255.0
    if enc in ("mono16", "16uc1"):
        dt = np.dtype(">u2" if msg.is_bigendian else "<u2")
        return buf.view(dt).reshape(h, step // 2)[:, :w], 65535.0
    if enc in ("rgb8", "bgr8"):
        return buf.reshape(h, step)[:, :w * 3].reshape(h, w, 3).mean(axis=2), 255.0
    if enc in ("yuv422", "yuv422_yuy2", "yuyv"):
        return buf.reshape(h, step)[:, 0:w * 2:2], 255.0
    raise ValueError(f"unsupported image encoding {msg.encoding}")

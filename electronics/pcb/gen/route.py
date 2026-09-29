"""A small two-layer grid router (A* with turn and via costs) for the generated boards.

Copper is kept as exact shapes (pads, tracks, vias). Before each connection the points
that sit too close to other nets' copper are masked out on a grid twice as fine as the
routing grid, and a step is legal only if both its end and its midpoint are free, so every
segment keeps the requested clearance (plus a small margin for the gaps between samples).
Pure numpy; no KiCad imports, so it can be tested on its own.
"""
import heapq
import math

import numpy as np

LAYERS = 2                                     # 0 = F.Cu, 1 = B.Cu
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]


class Shape:
    """Copper on one or both layers. kind: circle (r), rect (hx, hy, angle), seg (a, b, hw)."""

    def __init__(self, kind, net, layers, clearance, **g):
        self.kind, self.net, self.layers, self.clr = kind, net, layers, clearance
        self.g = g
        if kind == "circle":
            cx, cy, r = g["cx"], g["cy"], g["r"]
            self.bbox = (cx - r, cy - r, cx + r, cy + r)
        elif kind == "rect":
            cx, cy, hx, hy = g["cx"], g["cy"], g["hx"], g["hy"]
            rr = math.hypot(hx, hy)
            self.bbox = (cx - rr, cy - rr, cx + rr, cy + rr)
        else:
            (ax, ay), (bx, by), hw = g["a"], g["b"], g["hw"]
            self.bbox = (min(ax, bx) - hw, min(ay, by) - hw, max(ax, bx) + hw, max(ay, by) + hw)

    def dist(self, X, Y):
        g = self.g
        if self.kind == "circle":
            return np.hypot(X - g["cx"], Y - g["cy"]) - g["r"]
        if self.kind == "rect":
            c, s = math.cos(g["angle"]), math.sin(g["angle"])
            u, v = (X - g["cx"]) * c + (Y - g["cy"]) * s, -(X - g["cx"]) * s + (Y - g["cy"]) * c
            dx, dy = np.abs(u) - g["hx"], np.abs(v) - g["hy"]
            return np.hypot(np.maximum(dx, 0), np.maximum(dy, 0)) + np.minimum(np.maximum(dx, dy), 0)
        (ax, ay), (bx, by) = g["a"], g["b"]
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        t = np.clip(((X - ax) * vx + (Y - ay) * vy) / L2, 0, 1) if L2 else 0
        return np.hypot(X - ax - t * vx, Y - ay - t * vy) - g["hw"]


class Router:
    def __init__(self, width, height, pitch=0.635, edge=0.5, margin=0.03,
                 layer_cost=(1.0, 1.5), via_cost=8.0, turn_cost=0.4):
        self.pitch, self.edge, self.margin = pitch, edge, margin
        self.nx, self.ny = int(round(width / pitch)) + 1, int(round(height / pitch)) + 1
        self.xs = np.arange(self.nx) * pitch
        self.ys = np.arange(self.ny) * pitch
        self.fxs = np.arange(2 * self.nx - 1) * pitch / 2       # fine grid: points and midpoints
        self.fys = np.arange(2 * self.ny - 1) * pitch / 2
        self.shapes = []
        self.keepouts = []                              # (shape, applies to vias only)
        self.layer_cost, self.via_cost, self.turn_cost = layer_cost, via_cost, turn_cost
        self.tracks, self.vias = [], []                 # results
        self.w, self.h = width, height

    # ── copper bookkeeping ──
    def add(self, shape):
        self.shapes.append(shape)

    def _window(self, bbox, pad, fine=False):
        x0, y0, x1, y1 = bbox
        p = self.pitch / 2 if fine else self.pitch
        nx, ny = (2 * self.nx - 1, 2 * self.ny - 1) if fine else (self.nx, self.ny)
        i0 = max(int(math.floor((x0 - pad) / p)), 0)
        i1 = min(int(math.ceil((x1 + pad) / p)), nx - 1)
        j0 = max(int(math.floor((y0 - pad) / p)), 0)
        j1 = min(int(math.ceil((y1 + pad) / p)), ny - 1)
        return i0, i1, j0, j1

    def blocked(self, net, hw, clr, via_r=0.4, via_hole=0.2):
        """Fine-grid masks [layer] of points a track of half-width hw on `net` may not touch, and a via mask."""
        X, Y = np.meshgrid(self.fxs, self.fys)
        blk = np.zeros((LAYERS,) + X.shape, bool)
        vblk = np.zeros(X.shape, bool)
        e = hw + self.edge + self.margin
        edge_mask = (X < e) | (Y < e) | (X > self.w - e) | (Y > self.h - e)
        blk |= edge_mask
        ev = via_r + self.edge + self.margin
        vblk |= (X < ev) | (Y < ev) | (X > self.w - ev) | (Y > self.h - ev)
        for s in self.shapes:
            other = s.net != net
            need = hw + max(clr, s.clr) + self.margin
            vneed = via_r + max(clr, s.clr) + self.margin
            pad = max(need, vneed, via_hole + 0.6)
            i0, i1, j0, j1 = self._window(s.bbox, pad, True)
            if i0 > i1 or j0 > j1:
                continue
            d = s.dist(X[j0:j1 + 1, i0:i1 + 1], Y[j0:j1 + 1, i0:i1 + 1])
            if other:
                for l in s.layers:
                    blk[l, j0:j1 + 1, i0:i1 + 1] |= d < need
                vblk[j0:j1 + 1, i0:i1 + 1] |= d < vneed
            elif s.g.get("drill"):                       # own pad: keep via drills off its hole
                vblk[j0:j1 + 1, i0:i1 + 1] |= d < via_r + 0.25
        for s, vias_only in self.keepouts:
            i0, i1, j0, j1 = self._window(s.bbox, hw + 0.6, True)
            d = s.dist(X[j0:j1 + 1, i0:i1 + 1], Y[j0:j1 + 1, i0:i1 + 1])
            if not vias_only:
                blk[:, j0:j1 + 1, i0:i1 + 1] |= d < hw + self.margin
            vblk[j0:j1 + 1, i0:i1 + 1] |= d < via_r + self.margin
        vblk |= blk[0] | blk[1]
        return blk, vblk

    def cells_in(self, shape, layers):
        i0, i1, j0, j1 = self._window(shape.bbox, 0)
        X, Y = np.meshgrid(self.xs[i0:i1 + 1], self.ys[j0:j1 + 1])
        d = shape.dist(X, Y)
        jj, ii = np.nonzero(d <= -0.05)
        return {(l, j0 + j, i0 + i) for l in layers for j, i in zip(jj, ii)}

    # ── search ──
    def astar(self, sources, targets, blk, vblk):
        tx = np.array([t[2] for t in targets])
        ty = np.array([t[1] for t in targets])
        tset = set(targets)
        tbox = (tx.min(), tx.max(), ty.min(), ty.max())

        def h(i, j):
            dx = max(tbox[0] - i, 0, i - tbox[1])
            dy = max(tbox[2] - j, 0, j - tbox[3])
            return (max(dx, dy) + 0.4142 * min(dx, dy))

        openq, best, came = [], {}, {}
        for (l, j, i) in sources:
            if blk[l, 2 * j, 2 * i]:
                continue
            st = (l, j, i, -1)
            best[st] = 0.0
            heapq.heappush(openq, (h(i, j), 0.0, st))
        ny, nx = self.ny, self.nx
        lc, tc, vc = self.layer_cost, self.turn_cost, self.via_cost
        while openq:
            f, g, st = heapq.heappop(openq)
            if best.get(st, 1e18) < g:
                continue
            l, j, i, d = st
            if (l, j, i) in tset:
                path = [(l, j, i)]
                while st in came:
                    st = came[st]
                    path.append(st[:3])
                return path[::-1]
            for nd, (di, dj) in enumerate(DIRS):
                ni, nj = i + di, j + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or blk[l, 2 * nj, 2 * ni] or blk[l, 2 * j + dj, 2 * i + di]:
                    continue
                step = (1.4142 if di and dj else 1.0) * lc[l]
                if d >= 0 and nd != d:
                    diff = min((nd - d) % 8, (d - nd) % 8)
                    step += tc * diff + (2.0 if diff > 2 else 0)
                ng = g + step
                ns = (l, nj, ni, nd)
                if ng < best.get(ns, 1e18):
                    best[ns] = ng
                    came[ns] = st
                    heapq.heappush(openq, (ng + h(ni, nj), ng, ns))
            if not vblk[2 * j, 2 * i]:
                ns = (1 - l, j, i, -1)
                ng = g + vc
                if ng < best.get(ns, 1e18):
                    best[ns] = ng
                    came[ns] = st
                    heapq.heappush(openq, (ng + h(i, j), ng, ns))
        return None

    def commit(self, path, net, hw, clr):
        """Turn a cell path into straight segments and vias, and add them as copper."""
        p = self.pitch
        runs, cur = [], [path[0]]
        for a, b in zip(path, path[1:]):
            if a[0] != b[0]:
                runs.append(cur)
                self.vias.append((net, a[2] * p, a[1] * p))
                self.add(Shape("circle", net, (0, 1), clr, cx=a[2] * p, cy=a[1] * p, r=0.4))
                cur = [b]
            else:
                cur.append(b)
        runs.append(cur)
        for run in runs:
            if len(run) < 2:
                continue
            pts = [run[0]]
            for k in range(1, len(run) - 1):
                a, b, c = pts[-1], run[k], run[k + 1]
                d1 = (b[1] - a[1], b[2] - a[2])
                d2 = (c[1] - b[1], c[2] - b[2])
                if d1[0] * d2[1] != d1[1] * d2[0] or d1[0] * d2[0] + d1[1] * d2[1] < 0:
                    pts.append(b)
            pts.append(run[-1])
            l = run[0][0]
            for a, b in zip(pts, pts[1:]):
                seg = ((a[2] * p, a[1] * p), (b[2] * p, b[1] * p))
                self.tracks.append((net, l, hw * 2, seg))
                self.add(Shape("seg", net, (l,), clr, a=seg[0], b=seg[1], hw=hw))

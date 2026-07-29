#!/usr/bin/env python3
"""
merge_support.py — combine a PrusaSlicer-generated support structure with
an NX-generated non-planar toolpath into one MK4-printable file.

    python merge_support.py support_src.gcode part.gcode out.gcode \
           --dx -24.758 --dy -0.244

What it does
  1. Takes ONLY the deposition motion from the support file. The entire
     PrusaSlicer preamble is discarded, because it contains printer-locked
     checks (M862.3 "MK4S", M862.6 "MMU3") that abort on a plain MK4, plus
     PETG temperatures.
  2. Emits a single start block for whichever material you specify.
  3. Translates the non-planar toolpath onto the support by (dx, dy).
  4. Inserts a retract / lift / travel / prime transition between them.
  5. Emits one end block.
  6. Checks for nozzle-vs-support collisions and reports them.

Extrusion values are never altered -- only X and Y are offset.
"""

import argparse
import math
import re
import sys

NUM = r'(-?\d*\.?\d+)'
AXIS_RE = {k: re.compile(k + NUM) for k in 'XYZEFIJ'}

# Preamble codes that are unsafe or redundant when re-hosted
STRIP = re.compile(r'^\s*(M862|M708|M555|M486|M73|M74|M115|M17|M302|M201|'
                   r'M203|M204|M205|M104|M109|M140|M190|G28|G29|M84|M107|'
                   r'M106|T\d|M83|M82|G90|G91)\b')


def parse_axes(code):
    d = {}
    for k, rx in AXIS_RE.items():
        m = rx.search(code)
        if m:
            d[k] = float(m.group(1))
    return d


def start_block(nozzle, bed):
    return [
        '; ---- start sequence ----',
        'M104 S%d        ; set nozzle temperature' % nozzle,
        'M140 S%d        ; set bed temperature' % bed,
        'M190 S%d        ; wait for bed' % bed,
        'M109 S%d        ; wait for nozzle' % nozzle,
        'G90             ; absolute positioning',
        'M83             ; relative extrusion',
        'G28             ; home all axes',
        'G29             ; mesh bed levelling',
        'G92 E0',
        'M106 S0         ; fan off for first layer',
        '; ---- prime line ----',
        'G1 Z0.2 F1000',
        'G1 X10 Y20 F3000',
        'G1 X10 Y200 E15 F1500',
        'G1 X10.4 Y200 F3000',
        'G1 X10.4 Y20 E15 F1500',
        'G92 E0',
    ]


def end_block():
    return [
        '; ---- end sequence ----',
        'G1 E-2 F2100    ; retract',
        'M104 S0         ; nozzle off',
        'M140 S0         ; bed off',
        'M107            ; fan off',
        'G1 Z100 F1000   ; lift',
        'G1 X10 Y200 F3000 ; park',
        'M84             ; motors off',
    ]


def read_motion(path, start_marker=None, stop_marker=None,
                dx=0.0, dy=0.0, strip_preamble=False, skip_until_type=False):
    """Return (lines, points) keeping only motion, optionally offset."""
    out, pts = [], []
    x = y = z = None
    g = None
    active = start_marker is None
    typed = not skip_until_type
    for raw in open(path, encoding='utf-8-sig', errors='ignore'):
        s = raw.replace('\r', '').rstrip()
        if stop_marker and stop_marker in s:
            break
        if not active:
            if start_marker in s:
                active = True
            continue
        if not typed:
            # Discard PrusaSlicer's intro/purge line (runs at Y=-4, off bed)
            t = s.lstrip()
            if t.startswith(';TYPE:') and 'Custom' not in t:
                typed = True
            continue
        body = s.split(';')[0].strip()
        if not body:
            continue
        if strip_preamble and STRIP.match(body):
            continue
        mg = re.search(r'\bG0*([0123])\b', body)
        if mg:
            g = int(mg.group(1))
        d = parse_axes(body)
        if not d and mg is None:
            continue
        if dx or dy:
            if 'X' in d:
                body = AXIS_RE['X'].sub('X%.4f' % (d['X'] + dx), body, count=1)
            if 'Y' in d:
                body = AXIS_RE['Y'].sub('Y%.4f' % (d['Y'] + dy), body, count=1)
            d = parse_axes(body)
        nx, ny, nz = d.get('X', x), d.get('Y', y), d.get('Z', z)
        if g in (0, 1, 2, 3) and None not in (nx, ny, nz):
            if d.get('E', 0) > 0 and any(k in d for k in 'XYZ'):
                pts.append((nx, ny, nz))
        x, y, z = nx, ny, nz
        out.append(body)
    return out, pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('support')
    ap.add_argument('part')
    ap.add_argument('out')
    ap.add_argument('--dx', type=float, default=-24.758)
    ap.add_argument('--dy', type=float, default=-0.244)
    ap.add_argument('--nozzle', type=int, default=210)
    ap.add_argument('--bed', type=int, default=60)
    ap.add_argument('--safe-z', type=float, default=20.0)
    a = ap.parse_args()

    sup, sup_pts = read_motion(a.support, stop_marker='SUPPORT DONE',
                               strip_preamble=True, skip_until_type=True)
    part, part_pts = read_motion(a.part, start_marker='---- begin part ----',
                                 stop_marker='---- end sequence ----',
                                 dx=a.dx, dy=a.dy)

    if not sup_pts or not part_pts:
        print('ERROR: one of the sections yielded no deposition', file=sys.stderr)
        sys.exit(1)

    first = part_pts[0]
    lines = []
    lines += start_block(a.nozzle, a.bed)
    lines += ['', '; ================= SUPPORT (PrusaSlicer) =================']
    lines += sup
    lines += ['', '; ================= TRANSITION =================',
              'G1 E-0.8 F2100   ; retract',
              'G0 Z%.3f F9000   ; clear the support' % a.safe_z,
              'G0 X%.3f Y%.3f F9000' % (first[0], first[1]),
              'G0 Z%.3f F1200   ; drop to surface' % first[2],
              'G1 E0.8 F2100    ; prime',
              'M106 S128        ; part cooling ~50%',
              '',
              '; ============ NON-PLANAR PART (NX, offset dX=%.3f dY=%.3f) ============'
              % (a.dx, a.dy)]
    lines += part
    lines += ['']
    lines += end_block()

    open(a.out, 'w', newline='\n').write('\n'.join(lines) + '\n')

    # ---------------- reports ----------------
    def ext(p):
        return (min(q[0] for q in p), max(q[0] for q in p),
                min(q[1] for q in p), max(q[1] for q in p),
                min(q[2] for q in p), max(q[2] for q in p))

    print('wrote %s  (%d lines)' % (a.out, len(lines)))
    print('  support deposition : %d points   X %.2f-%.2f Y %.2f-%.2f Z %.2f-%.2f'
          % ((len(sup_pts),) + ext(sup_pts)))
    print('  part deposition    : %d points   X %.2f-%.2f Y %.2f-%.2f Z %.2f-%.2f'
          % ((len(part_pts),) + ext(part_pts)))

    # collision: part commanded below local support top
    cell = 0.5
    grid = {}
    for px, py, pz in sup_pts:
        k = (round(px / cell), round(py / cell))
        grid[k] = max(grid.get(k, 0.0), pz)
    viol = []
    for px, py, pz in part_pts:
        k = (round(px / cell), round(py / cell))
        if k in grid and pz < grid[k] - 0.25:
            viol.append(grid[k] - pz)
    print()
    if viol:
        viol.sort()
        print('  COLLISION RISK: %d part points (%.2f%%) commanded below the local'
              % (len(viol), 100 * len(viol) / len(part_pts)))
        print('  support top -- median %.2f mm, max %.2f mm deep.'
              % (viol[len(viol) // 2], viol[-1]))
        print('  Inspect these in the viewer before printing.')
    else:
        print('  No part point sits below the local support top. Clear.')


if __name__ == '__main__':
    main()

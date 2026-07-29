#!/usr/bin/env python3
"""
verify_extrusion.py — quantitative checks on non-planar FDM G-code.

Produces the numbers reviewer comments 10, 22-25, 28, 35 and 39 ask for.

Usage:
    python verify_extrusion.py file.gcode
    python verify_extrusion.py file.gcode --w 0.42 --h 0.20 --d 1.75 --alpha 1.0
    python verify_extrusion.py file.gcode --split "NON-PLANAR PART"   # hybrid files
    python verify_extrusion.py file.gcode --plot                      # needs matplotlib

Checks performed
  1. Extrusion-model conformance: is E/L constant (no compensation) or does it
     track |K| as Eq. (1) requires?
  2. Implied |K| distribution and inclination range of the specimen.
  3. Travel hygiene: extrusion commanded on non-deposition moves.
  4. Zero-length blocks carrying material (prev_pos initialisation defect).
  5. Retraction accounting.
  6. Global filament total, for comparison against V/A from the CAD model.
"""

import argparse
import math
import re
import statistics
import sys

NUM = r'(-?\d*\.?\d+)'          # NB: matches ".5" as well as "0.5"
AXES = 'XYZEF'


def parse(lines):
    """Return list of move dicts with absolute endpoints and segment length."""
    x = y = z = None
    relative_e = True
    modal_g = None
    moves = []
    for raw in lines:
        raw = raw.replace('\r', '').strip()
        # skip NX Information-listing banner/footer and tape marks
        if (not raw or raw.startswith('%')
                or raw.startswith(('Information', 'Date', 'Current work',
                                   'Node name', 'Tool Path'))):
            continue
        raw = re.sub(r'^N\d+\s*', '', raw)      # strip sequence numbers
        code = raw.split(';')[0].strip()
        if not code:
            continue
        if re.search(r'\bM83\b', code):
            relative_e = True
        elif re.search(r'\bM82\b', code):
            relative_e = False
        # motion word may be absent: G codes are modal in NX output
        m = re.search(r'\bG0*([0123])\b', code)
        if m:
            modal_g = int(m.group(1))
        d = {}
        for k in AXES:
            mm = re.search(k + NUM, code)
            if mm:
                d[k] = float(mm.group(1))
        if modal_g is None or not (set('XYZE') & set(d)):
            continue
        g = modal_g
        nx, ny, nz = d.get('X', x), d.get('Y', y), d.get('Z', z)
        L = (math.dist((x, y, z), (nx, ny, nz))
             if None not in (x, y, z, nx, ny, nz) else None)
        # An E-only block (no X/Y/Z words) is a prime or retract, not a defect.
        eonly = not any(k in d for k in 'XYZ')
        moves.append({'g': g, 'E': d.get('E'), 'F': d.get('F'), 'L': L,
                      'p0': (x, y, z), 'p1': (nx, ny, nz), 'rel': relative_e,
                      'eonly': eonly})
        x, y, z = nx, ny, nz
    return moves


def report(moves, C, label, plot=False):
    print(f'\n{"=" * 62}\n{label}\n{"=" * 62}')

    dep = [m for m in moves if m['g'] == 1 and m['E'] and m['E'] > 0]
    trav = [m for m in moves if m['g'] == 0]
    retr = [m for m in moves if m['E'] and m['E'] < 0]

    if not dep:
        print('  no extruding moves found')
        return

    zs = [m['p1'][2] for m in dep if m['p1'][2] is not None]
    simul = [m for m in dep
             if None not in m['p0'] and abs(m['p1'][2] - m['p0'][2]) > 1e-6
             and (abs(m['p1'][0] - m['p0'][0]) > 1e-6
                  or abs(m['p1'][1] - m['p0'][1]) > 1e-6)]

    print(f'  extruding moves          : {len(dep)}')
    print(f'  simultaneous XYZ moves   : {len(simul)} '
          f'({100 * len(simul) / len(dep):.1f}% -- non-planar fraction)')
    print(f'  extruded Z range         : {min(zs):.3f} - {max(zs):.3f} mm')
    print(f'  total commanded filament : {sum(m["E"] for m in dep):.2f} mm')
    print(f'    -> compare against V/A from the CAD model (comment 24)')

    # ---- 1. extrusion model conformance -------------------------------
    ratios = [(m['E'] / m['L'], m) for m in dep if m['L'] and m['L'] > 1e-6]
    if not ratios:
        return
    vals = sorted(r for r, _ in ratios)
    mean = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    print(f'\n  E/L  min {vals[0]:.6f}  median {vals[len(vals) // 2]:.6f}  '
          f'max {vals[-1]:.6f}')
    print(f'       mean {mean:.6f}   sd {sd:.6f}   '
          f'CV {100 * sd / mean if mean else 0:.3f}%')
    print(f'  Eq.(1) constant 4*alpha*w*h/(pi*d^2) = {C:.6f}')

    if sd / mean < 0.01:
        print('\n  >>> E/L IS CONSTANT. Slope compensation is NOT applied.')
        print(f'      Implied |K| = {mean / C:.4f} on every block.')
        print('      Eq. (1) has degenerated to the planar form.')
    else:
        k = [r / C for r, _ in ratios]
        k.sort()
        th = [math.degrees(math.acos(min(1.0, max(0.0, v)))) for v in k]
        print('\n  >>> E/L VARIES -- compensation is active.')
        print(f'      implied |K| : {k[0]:.3f} - {k[-1]:.3f} '
              f'(median {k[len(k) // 2]:.3f})')
        print(f'      implied theta: {th[0]:.1f} - {th[-1]:.1f} deg')
        print('      quote this inclination range in the abstract (comment 10)')

    # ---- 2. travel hygiene (comment 28) -------------------------------
    bad_travel = [m for m in trav if m['E'] and m['E'] > 0]
    g1_dry = [m for m in moves
              if m['g'] == 1 and not m['E'] and m['L'] and m['L'] > 0.01]
    print(f'\n  travel (G0) moves        : {len(trav)}   '
          f'carrying E: {len(bad_travel)}')
    print(f'  G1 >0.01mm without E     : {len(g1_dry)} '
          f'(travel emitted as G1)')

    # ---- 3. zero-length extrusion (comment 27) ------------------------
    # Exclude E-only blocks: those are primes, which are legitimate.
    primes = [m for m in dep if m['eonly']]
    zero = [m for m in dep
            if not m['eonly'] and m['L'] is not None and m['L'] < 1e-6]
    print(f'  prime moves (E-only)     : {len(primes)}  [expected, not a defect]')
    print(f'  zero-length XYZ with E   : {len(zero)}', end='')
    print('   <-- prev_pos initialisation defect' if zero else '   [clean]')

    # ---- 4. retraction (comment 29) -----------------------------------
    print(f'  retraction moves         : {len(retr)}')

    if plot and sd / mean >= 0.01:
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            kk = [r / C for r, _ in ratios]
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.scatter(kk, [r for r, _ in ratios], s=1, alpha=0.25)
            ax.set_xlabel('implied |K|  (cos theta)')
            ax.set_ylabel('E / L   [mm filament per mm path]')
            ax.set_title('Extrusion compensation vs. surface inclination')
            ax.grid(alpha=0.3)
            fig.tight_layout()
            fig.savefig('extrusion_vs_K.png', dpi=200)
            print('\n  wrote extrusion_vs_K.png  <-- this figure goes in §4.4')
        except ImportError:
            print('\n  (matplotlib unavailable; skipped plot)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('gcode')
    ap.add_argument('--w', type=float, default=0.42, help='bead width [mm]')
    ap.add_argument('--h', type=float, default=0.20, help='layer offset [mm]')
    ap.add_argument('--d', type=float, default=1.75, help='filament dia [mm]')
    ap.add_argument('--alpha', type=float, default=1.0, help='flow modifier')
    ap.add_argument('--split', default=None,
                    help='comment text marking a hybrid section boundary')
    ap.add_argument('--plot', action='store_true')
    a = ap.parse_args()

    C = 4 * a.alpha * a.w * a.h / (math.pi * a.d ** 2)
    lines = open(a.gcode, encoding='utf-8-sig', errors='ignore').read().split('\n')

    if a.split:
        idx = next((i for i, l in enumerate(lines) if a.split in l), None)
        if idx is None:
            print(f'split marker "{a.split}" not found; treating as one section',
                  file=sys.stderr)
        else:
            report(parse(lines[:idx]), C, f'SECTION 1  (before "{a.split}")')
            report(parse(lines[idx:]), C, f'SECTION 2  (after "{a.split}")',
                   a.plot)
            return
    report(parse(lines), C, a.gcode, a.plot)


if __name__ == '__main__':
    main()

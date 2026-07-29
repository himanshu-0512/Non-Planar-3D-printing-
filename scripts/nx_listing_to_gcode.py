#!/usr/bin/env python3
"""
nx_listing_to_gcode.py — convert an NX post/Information listing into a
G-code file that PrusaSlicer's viewer and Marlin firmware will accept.

    python nx_listing_to_gcode.py Prusa_code1.txt part.gcode

Removes, in order:
  * UTF-8 BOM
  * NX banner lines (Information listing / Date / Current work part / Node name)
  * NX footer ("Tool Path Listing has N lines.")
  * '%' tape marks
  * N#### sequence numbers        (Marlin reads N as a line number and
                                   expects a checksum; it will reject these)
  * M02 program end               (not a Marlin code)
Normalises:
  * G00 -> G0, G01 -> G1, G02/G03 -> G2/G3
  * CRLF -> LF
Reports bed-extent and sanity checks at the end.
"""

import argparse
import math
import re
import sys

MK4 = {'X': (0.0, 250.0), 'Y': (0.0, 210.0), 'Z': (0.0, 220.0)}
NUM = r'(-?\d*\.?\d+)'

BANNER = ('Information listing', 'Date\t', 'Date ', 'Current work part',
          'Node name', 'Tool Path Listing')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--keep-comments', action='store_true',
                    help='keep "; ..." trailing comments (default: keep)')
    a = ap.parse_args()

    raw = open(a.src, encoding='utf-8-sig', errors='ignore').read()
    out = []
    dropped = {'banner': 0, 'tape': 0, 'm02': 0, 'blank': 0}
    modal_g = None
    expanded = 0

    for line in raw.split('\n'):
        s = line.replace('\r', '').rstrip()
        if not s.strip():
            dropped['blank'] += 1
            continue
        if s.lstrip().startswith(BANNER):
            dropped['banner'] += 1
            continue
        if s.strip() == '%':
            dropped['tape'] += 1
            continue
        s = re.sub(r'^\s*N\d+\s*', '', s)          # sequence numbers
        if re.match(r'^M0*2\b', s.strip()):
            dropped['m02'] += 1
            continue
        if not s.strip():
            dropped['blank'] += 1
            continue
        s = re.sub(r'\bG0*(\d)\b', r'G\1', s)      # G00 -> G0, G01 -> G1

        body = s.split(';')[0].strip()
        mg = re.search(r'\bG([0123])\b', body)
        if mg:
            modal_g = int(mg.group(1))
        elif body and re.match(r'^[XYZEF]', body) and modal_g is not None:
            # Modal continuation: NX omits the motion word, but neither
            # Marlin nor PrusaSlicer's parser implements modality -- both
            # ignore a line that does not begin with a command letter.
            s = 'G%d %s' % (modal_g, s.lstrip())
            expanded += 1
        out.append(s)

    header = [
        '; converted from NX post listing by nx_listing_to_gcode.py',
        '; source: %s' % a.src.split('/')[-1],
        '; NOTE: extrusion values produced by the NX post-processor;',
        ';       this conversion changes formatting only, never E values.',
    ]
    open(a.dst, 'w', newline='\n').write('\n'.join(header + out) + '\n')

    # ---------------- sanity checks ----------------
    x = y = z = None
    g = None
    lo = {k: 1e9 for k in 'XYZ'}
    hi = {k: -1e9 for k in 'XYZ'}
    retr = prime = 0
    seen_m83 = seen_g28 = False
    first_move_before_home = False
    moved = False
    total_e = 0.0

    for s in out:
        code = s.split(';')[0].strip()
        if not code:
            continue
        if re.search(r'\bM83\b', code):
            seen_m83 = True
        if re.search(r'\bG28\b', code):
            seen_g28 = True
        m = re.search(r'\bG([0123])\b', code)
        if m:
            g = int(m.group(1))
        d = {}
        for k in 'XYZEF':
            mm = re.search(k + NUM, code)
            if mm:
                d[k] = float(mm.group(1))
        if d.get('E', 0) < 0:
            retr += 1
        elif d.get('E', 0) > 0:
            total_e += d['E']
            if not any(k in d for k in 'XYZ'):
                prime += 1
        for k in 'XYZ':
            if k in d:
                lo[k] = min(lo[k], d[k])
                hi[k] = max(hi[k], d[k])
        if g in (0, 1) and any(k in d for k in 'XYZ'):
            if not moved:
                moved = True
                if not seen_g28:
                    first_move_before_home = True
        x, y, z = d.get('X', x), d.get('Y', y), d.get('Z', z)

    print('wrote %s' % a.dst)
    print('  lines out            : %d' % len(out))
    print('  dropped              : banner %d, tape %d, M02 %d, blank %d'
          % (dropped['banner'], dropped['tape'], dropped['m02'],
             dropped['blank']))
    print('  modal lines expanded : %d  (explicit G word injected)' % expanded)
    print()
    print('  M83 relative extrusion : %s' % ('yes' if seen_m83 else 'NO  <-- FATAL'))
    print('  G28 homing present     : %s' % ('yes' if seen_g28 else 'NO  <-- FATAL'))
    print('  motion before homing   : %s'
          % ('YES  <-- check' if first_move_before_home else 'no'))
    print('  retracts / primes      : %d / %d%s'
          % (retr, prime, '' if abs(retr - prime) <= 2 else '   <-- unbalanced'))
    print('  total filament         : %.1f mm' % total_e)
    print()
    ok = True
    for k in 'XYZ':
        mn, mx = MK4[k]
        flag = ''
        if lo[k] < mn - 1e-6 or hi[k] > mx + 1e-6:
            flag = '   <-- OUTSIDE BUILD VOLUME'
            ok = False
        print('  %s extent : %8.2f .. %8.2f   (bed %.0f..%.0f)%s'
              % (k, lo[k], hi[k], mn, mx, flag))
    if not ok:
        print('\n  Part does not fit the MK4 build volume as positioned.')
        sys.exit(1)


if __name__ == '__main__':
    main()

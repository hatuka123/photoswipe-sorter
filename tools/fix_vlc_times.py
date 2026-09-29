"""Give the VLC files in a build the same timestamps as in vendor/vlc.

VLC's plugin index (plugins.dat) is only trusted when every plugin's timestamp matches; the
build copies files with new timestamps, which would make VLC re-scan all plugins (slow start).
Usage: python tools/fix_vlc_times.py dist/PhotoSwipe/_internal/vlc
"""

import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor", "vlc")

dst = sys.argv[1]
n = 0
for root, _, files in os.walk(SRC):
    for name in files:
        s = os.path.join(root, name)
        d = os.path.join(dst, os.path.relpath(s, SRC))
        if os.path.exists(d):
            st = os.stat(s)
            os.utime(d, ns=(st.st_atime_ns, st.st_mtime_ns))
            n += 1
print(f"timestamps fixed on {n} VLC files")

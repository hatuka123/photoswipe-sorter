"""Launch a built .exe on fresh test photos, press real keys, and check the results.

Usage: python tests/verify_exe.py <path to PhotoSwipe.exe> <empty work folder>
"""

import csv
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_test_images import make  # noqa: E402

ctypes.windll.shcore.SetProcessDpiAwareness(2)
u = ctypes.windll.user32
VK = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}


def main(exe_src, work):
    shutil.rmtree(work, ignore_errors=True)
    app_dir = os.path.join(work, "app")
    if os.path.basename(os.path.dirname(exe_src)) == "PhotoSwipe":  # folder version
        shutil.copytree(os.path.dirname(exe_src), app_dir)
    else:
        os.makedirs(app_dir)
        shutil.copy(exe_src, app_dir)
    exe = os.path.join(app_dir, "PhotoSwipe.exe")
    photos = os.path.join(work, "photos")
    make(photos, 220)
    with open(os.path.join(app_dir, "config.json"), "w") as f:
        json.dump({"root_folder": photos, "batch_size": 50}, f)

    t = time.perf_counter()
    proc = subprocess.Popen([exe])
    while not (u.FindWindowW(None, "PhotoSwipe") and u.IsWindowVisible(u.FindWindowW(None, "PhotoSwipe"))):
        time.sleep(0.005)
    print(f"window visible after {(time.perf_counter() - t) * 1000:.0f} ms")
    hwnd = u.FindWindowW(None, "PhotoSwipe")
    time.sleep(1.5)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    def press(k, n):
        for _ in range(n):
            u.keybd_event(VK[k], 0, 0, 0)
            u.keybd_event(VK[k], 0, 2, 0)
            time.sleep(0.35)

    press("left", 5)
    press("right", 5)
    press("up", 5)
    press("down", 3)
    time.sleep(0.5)
    u.PostMessageW(hwnd, 0x10, 0, 0)  # close the window
    proc.wait(10)

    counts = {}
    for name in ("delete-queue", "keep-archive", "starred"):
        counts[name] = sum(len(fs) for _, _, fs in os.walk(os.path.join(photos, "_PhotoSwipe", name)))
    with open(os.path.join(app_dir, "actions_log.csv"), encoding="utf-8-sig") as f:
        actions = [r["action"] for r in csv.DictReader(f)]
    print("folders:", counts)
    print("log:", actions)
    ok = counts == {"delete-queue": 5, "keep-archive": 5, "starred": 2} and \
        actions == ["delete"] * 5 + ["keep"] * 5 + ["star"] * 5 + ["undo-star"] * 3
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))

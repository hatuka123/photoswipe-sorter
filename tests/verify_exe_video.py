"""Real mouse + keyboard check of the built folder .exe on a mix of photos and videos.

Usage: python tests/verify_exe_video.py <dist\\PhotoSwipe folder> <empty work folder>
Screenshots are saved in the work folder.
"""

import csv
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageGrab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_test_videos import make as make_videos  # noqa: E402

ctypes.windll.shcore.SetProcessDpiAwareness(2)
u = ctypes.windll.user32
VK = {"right": 0x27, "space": 0x20}


def main(dist, work):
    shutil.rmtree(work, ignore_errors=True)
    app_dir = os.path.join(work, "app")
    shutil.copytree(dist, app_dir)
    media = os.path.join(work, "media")
    vids = make_videos(os.path.join(work, "gen"), 3, big_hevc=False)
    os.makedirs(media)
    for i, name in enumerate(["01.jpg", "02.mp4", "03.mkv", "04.jpg", "05.mp4"]):
        dst = os.path.join(media, name)
        if name.endswith(".jpg"):
            Image.new("RGB", (1600, 1000), (200, 60 * i, 90)).save(dst)
        else:
            shutil.copy(vids[0] if name.endswith(".mp4") else vids[2], dst)
    with open(os.path.join(app_dir, "config.json"), "w") as f:
        json.dump({"root_folder": media, "media": "both"}, f)

    proc = subprocess.Popen([os.path.join(app_dir, "PhotoSwipe.exe")])
    while not u.FindWindowW(None, "PhotoSwipe"):
        time.sleep(0.05)
    time.sleep(2.5)
    hwnd = u.FindWindowW(None, "PhotoSwipe")
    u.SetForegroundWindow(hwnd)
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))

    def shot(name):
        ImageGrab.grab((r.left, r.top, r.right, r.bottom), all_screens=True).save(os.path.join(work, name))

    def key(k):
        u.keybd_event(VK[k], 0, 0, 0)
        u.keybd_event(VK[k], 0, 2, 0)
        time.sleep(1.2)

    def click(x, y):
        u.SetCursorPos(r.left + x, r.top + y)
        u.mouse_event(2, 0, 0, 0, 0)
        u.mouse_event(4, 0, 0, 0, 0)
        time.sleep(1.2)

    w, h = r.right - r.left, r.bottom - r.top
    shot("1_photo.png")
    key("right")                    # 01.jpg -> keep, 02.mp4 plays
    shot("2_video.png")
    click(w // 2, h // 2)           # click on the video...
    key("right")                    # ...keys must still work: 02 -> keep, 03 plays
    shot("3_after_click.png")
    click(*KEEP_BUTTON)             # mouse on "Keep": 03 -> keep, 04.jpg shows
    key("space")                    # must NOT press the button again
    key("right")                    # 04 -> keep, 05 plays
    key("space")                    # pause
    shot("4_paused.png")
    u.PostMessageW(hwnd, 0x10, 0, 0)
    proc.wait(15)

    kept = sorted(os.listdir(os.path.join(media, "_PhotoSwipe", "keep-archive")))
    with open(os.path.join(app_dir, "actions_log.csv"), encoding="utf-8-sig") as f:
        actions = [r["action"] for r in csv.DictReader(f)]
    print("kept:", kept, "| left:", sorted(n for n in os.listdir(media) if n != "_PhotoSwipe"))
    print("log:", actions)
    ok = kept == ["01.jpg", "02.mp4", "03.mkv", "04.jpg"] and actions == ["keep"] * 4
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


KEEP_BUTTON = (392, 994)  # "Keep (D) ->" in the bottom bar on a 1920x1080 screen

if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))

"""Sorted files land flat in "PhotoSwipe ממוין", old "_PhotoSwipe" folders are migrated.

Usage: python tests/test_folders.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from image_handler import IMAGE_EXTS, Scanner, Sorter, sidecars  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()


tmp = tempfile.mkdtemp()
root = os.path.join(tmp, "album")
cfg = dict(config.DEFAULTS)
targets = config.target_dirs(cfg, root)
check(targets["keep"] == os.path.join(root, "PhotoSwipe ממוין", "keep-archive"), "target is 'PhotoSwipe ממוין'")

print("1. flat target folders")
touch(os.path.join(root, "2019", "summer", "IMG_1.jpg"))
touch(os.path.join(root, "phone", "IMG_1.jpg"))  # same name from another folder
sorter = Sorter(root, targets, os.path.join(tmp, "log.csv"))
sorter.apply("keep", os.path.join(root, "2019", "summer", "IMG_1.jpg"), 0, 1)
sorter.apply("keep", os.path.join(root, "phone", "IMG_1.jpg"), 1, 1)
check(sorted(os.listdir(targets["keep"])) == ["IMG_1 (1).jpg", "IMG_1.jpg"], "both directly in keep-archive")
sorter.undo()
check(os.path.exists(os.path.join(root, "phone", "IMG_1.jpg")), "undo returns it to its own sub-folder")

print("2. motion photo: the video takes the photo's json once the photo is gone")
touch(os.path.join(root, "20240409_104909.MP4"))
touch(os.path.join(root, "20240409_104909.jpg"))
touch(os.path.join(root, "20240409_104909.jpg.json"))
check(sidecars(os.path.join(root, "20240409_104909.MP4")) == [], "not while the photo is still there")
os.remove(os.path.join(root, "20240409_104909.jpg"))
found = sidecars(os.path.join(root, "20240409_104909.MP4"))
check([os.path.basename(p) for p in found] == ["20240409_104909.jpg.json"], f"found once, whatever the case ({found})")
sorter.apply("delete", os.path.join(root, "20240409_104909.MP4"), 2, 1)
check(os.path.exists(os.path.join(targets["delete"], "20240409_104909.jpg.json")), "json moved with the video")

print("3. already sorted folders are never scanned")
touch(os.path.join(root, "sub", "_PhotoSwipe", "keep-archive", "old.jpg"))
touch(os.path.join(root, "sub", "PhotoSwipe ממוין", "starred", "old2.jpg"))
touch(os.path.join(root, "sub", "new.jpg"))
sc = Scanner(root, targets.values(), IMAGE_EXTS, skip_names=config.SKIP_DIRS)
sc.done.wait(5)
names = sorted(os.path.basename(p) for p in sc.paths)
check("old.jpg" not in names and "old2.jpg" not in names and "new.jpg" in names, f"scanned: {names}")

print("4. old _PhotoSwipe folder is renamed and flattened")
old = os.path.join(tmp, "old")
touch(os.path.join(old, "_PhotoSwipe", "keep-archive", "a.jpg"))
touch(os.path.join(old, "_PhotoSwipe", "keep-archive", "2019", "summer", "a.jpg"))
touch(os.path.join(old, "_PhotoSwipe", "delete-queue", "x", "b.jpg"))
moved = config.migrate_legacy(old)
new = os.path.join(old, "PhotoSwipe ממוין")
check(not os.path.exists(os.path.join(old, "_PhotoSwipe")) and os.path.isdir(new), "renamed")
check(sorted(os.listdir(os.path.join(new, "keep-archive"))) == ["a (1).jpg", "a.jpg"], "keep-archive flattened")
check(os.listdir(os.path.join(new, "delete-queue")) == ["b.jpg"], "delete-queue flattened")
check(moved == 2, f"2 files moved up ({moved})")
check(config.migrate_legacy(old) == 0, "second run does nothing")

shutil.rmtree(tmp, ignore_errors=True)
print("\nFAILED:\n  " + "\n  ".join(failures) if failures else "\nALL PASSED")
sys.exit(1 if failures else 0)

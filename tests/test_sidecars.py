"""Google Takeout .json files travel with their photo (and come back on undo).

Usage: python tests/test_sidecars.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from image_handler import Sorter  # noqa: E402

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
long_name = "PXL_20230101_123456789.PORTRAIT.ORIGINAL_long.jpg"  # json name gets cut to 46 chars
files = {
    "a.jpg": ["a.jpg.json"],
    "b(1).jpg": ["b.jpg(1).json"],                            # Takeout's copy-number style
    "c.jpg": ["c.jpg.supplemental-metadata.json"],             # newer Takeout exports
    long_name: [long_name[:46] + ".json"],
    "20210804_184519(0).jpg": ["20210804_184519(0).jpg.json"],
    "no_json.jpg": [],
}
for photo, jsons in files.items():
    touch(os.path.join(root, photo))
    for j in jsons:
        touch(os.path.join(root, j))
touch(os.path.join(root, "20210804_184519.jpg.json"))  # belongs to another photo: must stay
targets = {k: os.path.join(root, "_PhotoSwipe", k) for k in ("delete", "keep", "star")}
sorter = Sorter(root, targets, os.path.join(tmp, "log.csv"))

for i, (photo, jsons) in enumerate(files.items()):
    sorter.apply("keep", os.path.join(root, photo), i, 1)
    moved = all(os.path.exists(os.path.join(targets["keep"], j)) and not os.path.exists(os.path.join(root, j))
                for j in jsons)
    check(moved, f"{photo}: {len(jsons)} json moved along")
check(os.path.exists(os.path.join(root, "20210804_184519.jpg.json")), "another photo's json stays")

# Name clash in the target: the photo becomes "a (1).jpg" and its json "a (1).jpg.json".
touch(os.path.join(root, "a.jpg"))
touch(os.path.join(root, "a.jpg.json"))
sorter.apply("keep", os.path.join(root, "a.jpg"), 9, 1)
check(os.path.exists(os.path.join(targets["keep"], "a (1).jpg.json")), "renamed photo keeps a matching json")

for _ in range(2):
    sorter.undo()
check(os.path.exists(os.path.join(root, "a.jpg.json")), "undo brings the json back")
check(os.path.exists(os.path.join(root, "no_json.jpg")), "undo brings the photo back")

print("\nFAILED:\n  " + "\n  ".join(failures) if failures else "\nALL PASSED")
sys.exit(1 if failures else 0)

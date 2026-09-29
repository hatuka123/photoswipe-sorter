"""Finding images, loading them in the background, moving files, undo and the action log.

Nothing in here touches the GUI, so it can be tested on its own.
"""

import csv
import datetime
import os
import re
import shutil
import threading
import time
from collections import namedtuple

from PIL import Image, ImageOps

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".gif", ".bmp", ".dib",
    ".tif", ".tiff", ".heic", ".heif", ".avif", ".ico", ".tga", ".ppm", ".pcx",
}

UNDO_LIMIT = 20
PREFETCH_AHEAD = 4

Image.MAX_IMAGE_PIXELS = None  # very large panoramas are fine; we only downscale them

# ---------------------------------------------------------------- scanning


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


class Scanner:
    """Walks the folder tree in a background thread; `paths` grows while it runs.

    Only files whose extension is in `exts` are collected (default: images). Folders in
    `exclude_dirs` (full paths) and folders named like one of `skip_names` are left out.
    """

    def __init__(self, root, exclude_dirs=(), exts=IMAGE_EXTS, skip_names=()):
        self.root = root
        self.exts = exts
        self._skip_names = {n.lower() for n in skip_names}
        self.paths = []
        self.done = threading.Event()
        self._stop = False
        self._exclude = {_norm(d) for d in exclude_dirs}
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop = True

    def _run(self):
        try:
            for dirpath, dirnames, filenames in os.walk(self.root):
                if self._stop:
                    return
                dirnames[:] = sorted(
                    d for d in dirnames
                    if not d.startswith("$")
                    and d != "System Volume Information"
                    and d.lower() not in self._skip_names
                    and _norm(os.path.join(dirpath, d)) not in self._exclude
                )
                for name in sorted(filenames, key=str.lower):
                    if os.path.splitext(name)[1].lower() in self.exts:
                        self.paths.append(os.path.join(dirpath, name))
        finally:
            self.done.set()


# ---------------------------------------------------------------- loading

_heif_lock = threading.Lock()
_heif_ready = False


def _ensure_heif():
    """Register HEIC/HEIF support once (done lazily so startup stays fast)."""
    global _heif_ready
    if _heif_ready:
        return
    with _heif_lock:
        if not _heif_ready:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except Exception:
                pass
            _heif_ready = True


def load_image(path, max_size):
    """Decode an image, apply EXIF rotation and shrink it to fit max_size (never enlarge).

    Returns a PIL image, or None if the file can't be read as an image.
    """
    _ensure_heif()
    try:
        with Image.open(path) as im:
            if im.format == "JPEG":
                side = max(max_size)
                im.draft("RGB", (side, side))  # decode huge JPEGs at a reduced scale: much faster
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB")
            im.thumbnail(max_size, Image.Resampling.BICUBIC, reducing_gap=2.0)
            im.load()
            return im
    except Exception:
        return None


Frame = namedtuple("Frame", "image thumb")


def _lower_thread_priority():
    """Background decoding must never slow down the screen (Windows only; ignored elsewhere)."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetThreadPriority(k32.GetCurrentThread(), -1)  # THREAD_PRIORITY_BELOW_NORMAL
    except Exception:
        pass


def load_frame(path, max_size, thumb_size):
    """The photo fitted to the screen plus a small preview, or None if unreadable."""
    im = load_image(path, max_size)
    if im is None:
        return None
    thumb = im.copy()
    thumb.thumbnail(thumb_size, Image.Resampling.BILINEAR, reducing_gap=2.0)
    return Frame(im, thumb)


class Prefetcher:
    """Keeps the current photo and the next few decoded in memory, loaded by worker threads.

    `loader(path)` does the decoding and returns whatever should be cached (None = unreadable).
    """

    def __init__(self, loader, workers=2):
        self.loader = loader
        self._cache = {}  # path -> loader result
        self._want = []
        self._busy = set()
        self._cond = threading.Condition()
        for _ in range(workers):  # Pillow decodes outside the GIL, so two workers ~double throughput
            threading.Thread(target=self._run, daemon=True).start()

    def want(self, paths):
        """Tell the worker which paths are needed soon (most urgent first); drop the rest."""
        with self._cond:
            self._want = list(paths)
            keep = set(self._want)
            for p in list(self._cache):
                if p not in keep:
                    del self._cache[p]
            self._cond.notify_all()

    def peek(self, path):
        """The decoded image if it is ready, else None (never blocks)."""
        with self._cond:
            return self._cache.get(path)

    def get(self, path):
        """The decoded image (None if unreadable); waits for the worker or decodes itself."""
        with self._cond:
            while path in self._busy:
                self._cond.wait()
            if path in self._cache:
                return self._cache[path]
            self._busy.add(path)
        img = self.loader(path)
        with self._cond:
            self._busy.discard(path)
            self._cache[path] = img  # the caller shows it now; the next want() prunes it later
            self._cond.notify_all()
        return img

    def _run(self):
        _lower_thread_priority()
        _ensure_heif()
        while True:
            with self._cond:
                while True:
                    todo = next((p for p in self._want if p not in self._cache and p not in self._busy), None)
                    if todo:
                        break
                    self._cond.wait()
                self._busy.add(todo)
            img = self.loader(todo)
            with self._cond:
                self._busy.discard(todo)
                if todo in self._want:
                    self._cache[todo] = img
                self._cond.notify_all()


# ---------------------------------------------------------------- moving + undo

# sidecars: [(original path, moved-to path)] of the Google Takeout .json files that went along.
Action = namedtuple("Action", "kind src dst pos batch sidecars", defaults=((),))

# Photo extensions (in Takeout's spelling) whose json a motion photo's video may carry.
_MOTION_PHOTO_EXTS = (".jpg", ".JPG", ".jpeg", ".heic", ".HEIC")


def sidecars(path):
    """Google Takeout metadata files belonging to `path` (date, place, people...).

    Takeout names them `photo.jpg.json` (newer exports: `photo.jpg.supplemental-metadata.json`),
    cuts long names to 46 characters before `.json`, and writes the copy number of
    `photo(1).jpg` as `photo.jpg(1).json`. The video half of a motion photo (`IMG.MP4` next to
    `IMG.jpg`) has no json of its own: once the photo is gone, `IMG.jpg.json` goes with the video.
    """
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    bases = [name]
    m = re.fullmatch(r"(.*)(\(\d+\))", stem)
    if m:
        bases.append(m.group(1) + ext + m.group(2))
    if ext.lower() not in IMAGE_EXTS:
        for photo_ext in _MOTION_PHOTO_EXTS:
            if not os.path.exists(os.path.join(folder, stem + photo_ext)):
                bases.append(stem + photo_ext)
    found = []
    for base in bases:
        for extra in ("", ".supplemental-metadata"):
            candidate = os.path.join(folder, (base + extra)[:46] + ".json")
            if os.path.normcase(candidate) not in map(os.path.normcase, found) and os.path.isfile(candidate):
                found.append(candidate)
    return found


def unique_path(path):
    """`path`, or `name (1).ext`, `name (2).ext`... if something is already there."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def move_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for attempt in range(10):
        try:
            shutil.move(src, dst)  # instant rename on the same drive, copy+delete across drives
            return
        except PermissionError:  # a video player may need a moment to let go of the file
            if attempt == 9:
                raise
            time.sleep(0.1)


class Sorter:
    """Moves photos straight into the target folders (no sub-folders) with an undo stack.

    Their Takeout metadata files (see sidecars) go along, renamed to match if the photo was.
    """

    def __init__(self, root, targets, log_file, undo_limit=UNDO_LIMIT):
        self.root = os.path.abspath(root)
        self.targets = targets
        self.log_file = log_file
        self.undo_limit = undo_limit
        self.history = []

    def apply(self, kind, src, pos, batch):
        dst = unique_path(os.path.join(self.targets[kind], os.path.basename(src)))
        move_file(src, dst)
        side = self._sidecars(kind, src, dst, batch)
        action = Action(kind, src, dst, pos, batch, side)
        self.history.append(action)
        del self.history[:-self.undo_limit]
        self._log(kind, src, dst, batch)
        return action

    def undo(self):
        """Put the last moved photo back. Returns (action, restored_path) or None."""
        if not self.history:
            return None
        action = self.history[-1]
        restored = unique_path(action.src)
        move_file(action.dst, restored)
        self.history.pop()
        self._log("undo-" + action.kind, action.dst, restored, action.batch)
        for original, moved in action.sidecars:
            try:
                back = unique_path(original)
                move_file(moved, back)
                self._log("undo-" + action.kind, moved, back, action.batch)
            except OSError:
                pass  # the photo itself is back; a missing .json doesn't block that
        return action, restored

    def _sidecars(self, kind, src, dst, batch):
        """Move the photo's Takeout .json files next to where the photo is going."""
        moved = []
        same_name = os.path.basename(dst) == os.path.basename(src)
        for side in sidecars(src):
            # If the photo had to be renamed ("name (1).jpg"), name the .json after it.
            name = os.path.basename(side) if same_name else os.path.basename(dst) + ".json"
            to = unique_path(os.path.join(os.path.dirname(dst), name))
            try:
                move_file(side, to)
            except OSError:
                continue
            moved.append((side, to))
            self._log(kind + "-json", side, to, batch)
        return tuple(moved)

    def _log(self, kind, src, dst, batch):
        new = not os.path.exists(self.log_file)
        try:
            with open(self.log_file, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["timestamp", "action", "batch", "from", "to"])
                w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), kind, batch, src, dst])
        except OSError:
            pass

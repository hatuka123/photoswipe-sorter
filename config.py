"""Settings stored in a small JSON file (config.json) next to the program."""

import json
import os
import sys

DEFAULTS = {
    "root_folder": "",
    "batch_size": 50,
    # Which files to sort: "both", "photos" or "videos".
    "media": "both",
    # True = go through the files in random order instead of folder by folder.
    "shuffle": False,
    # Empty target folders mean "<root>/_PhotoSwipe/<name>" (same drive = instant moves).
    "delete_dir": "",
    "keep_dir": "",
    "starred_dir": "",
    # Empty log file means "actions_log.csv" next to config.json.
    "log_file": "",
}

TARGET_NAMES = {"delete": "delete-queue", "keep": "keep-archive", "star": "starred"}
CONFIG_KEYS = {"delete": "delete_dir", "keep": "keep_dir", "star": "starred_dir"}
# The folder inside the chosen folder that holds the three target folders ("sorted").
SORTED_DIR = "PhotoSwipe ממוין"
LEGACY_SORTED_DIR = "_PhotoSwipe"  # older versions; renamed to SORTED_DIR on first use
# Folders with these names are never scanned: they hold files that were already sorted.
SKIP_DIRS = {SORTED_DIR, LEGACY_SORTED_DIR}


def app_dir():
    """Folder of the .exe (or of this script), falling back to %APPDATA% if read-only."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    if os.access(base, os.W_OK):
        return base
    fallback = os.path.join(os.environ.get("APPDATA", base), "PhotoSwipe")
    os.makedirs(fallback, exist_ok=True)
    return fallback


CONFIG_PATH = os.path.join(app_dir(), "config.json")


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    try:
        cfg["batch_size"] = max(1, int(cfg["batch_size"]))
    except (TypeError, ValueError):
        cfg["batch_size"] = DEFAULTS["batch_size"]
    if cfg["media"] not in ("both", "photos", "videos"):
        cfg["media"] = DEFAULTS["media"]
    cfg["shuffle"] = bool(cfg["shuffle"])
    return cfg


def save(cfg):
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        pass


def target_dirs(cfg, root):
    """Map of action -> absolute destination folder."""
    dirs = {}
    for action, name in TARGET_NAMES.items():
        custom = cfg.get(CONFIG_KEYS[action], "")
        dirs[action] = os.path.abspath(custom or os.path.join(root, SORTED_DIR, name))
    return dirs


def migrate_legacy(root):
    """Rename an old "<root>/_PhotoSwipe" to SORTED_DIR and flatten its target folders.

    Older versions kept each file's sub-folder path inside the target folders; now every
    sorted file sits directly in its target folder. Returns the number of files moved up.
    """
    from image_handler import move_file, unique_path

    old, new = os.path.join(root, LEGACY_SORTED_DIR), os.path.join(root, SORTED_DIR)
    if not os.path.isdir(old) or os.path.exists(new):
        return 0
    os.rename(old, new)
    moved = 0
    for name in TARGET_NAMES.values():
        top = os.path.join(new, name)
        for dirpath, _, files in os.walk(top, topdown=False):
            if dirpath == top:
                continue
            for f in files:
                move_file(os.path.join(dirpath, f), unique_path(os.path.join(top, f)))
                moved += 1
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    return moved


def log_path(cfg):
    return cfg.get("log_file") or os.path.join(app_dir(), "actions_log.csv")

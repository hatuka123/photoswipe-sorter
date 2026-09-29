"""End-to-end test: opens the real window and presses keys the way a user would.

Usage: python tests/test_app.py
"""

import csv
import faulthandler
import os
import shutil
import statistics
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import FreeSimpleGUI as sg  # noqa: E402

import config  # noqa: E402
import main  # noqa: E402
from make_test_images import make  # noqa: E402

LEFT, UP, RIGHT, DOWN, KEY_A = 37, 38, 39, 40, 65
failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def main_test():
    tmp = tempfile.mkdtemp(prefix="photoswipe_")
    root = os.path.join(tmp, "photos")
    made = make(root, 240)
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    log = os.path.join(tmp, "log.csv")
    config.save(dict(config.DEFAULTS, log_file=log))

    sg.theme("SystemDefaultForReal")
    sg.set_options(dpi_awareness=True)
    t0 = time.perf_counter()
    app = main.App()
    app.window.refresh()
    t1 = time.perf_counter()
    asked = []
    app.ask_next_batch = lambda n: (asked.append(n), "next")[1]
    app.start_session(root)
    app.window.refresh()
    print(f"window shown: {(t1 - t0) * 1000:.0f} ms, first photo (6000x4000): {(time.perf_counter() - t1) * 1000:.0f} ms")
    app.session.scanner.done.wait(10)
    targets = config.target_dirs(app.cfg, root)
    times = []

    def key(code, release=True, think=0.3):
        # A person looks at each photo for a moment; the app pre-loads the next ones meanwhile.
        end = time.perf_counter() + think
        while time.perf_counter() < end:
            app.step(timeout=20)
        start = time.perf_counter()
        app.window.TKroot.event_generate("<KeyPress>", keycode=code, when="tail")
        app.step(timeout=2000)
        app.window.refresh()
        times.append((time.perf_counter() - start) * 1000)
        if release:
            app.window.TKroot.event_generate("<KeyRelease>", keycode=code, when="tail")
            app.step(timeout=2000)

    def count(kind):
        n = 0
        for _, _, files in os.walk(targets[kind]):
            n += len(files)
        return n

    print("1. five presses of each arrow")
    first15 = list(app.session.scanner.paths[:15])
    for code in (LEFT, RIGHT, UP):
        for _ in range(5):
            key(code)
    check(count("delete") == 5 and count("keep") == 5 and count("star") == 5,
          f"5 photos in each folder (delete={count('delete')}, keep={count('keep')}, star={count('star')})")
    check(not any(os.path.exists(p) for p in first15), "moved photos left their original place")

    print("2. undo 10 times with DOWN")
    last10 = [a.src for a in app.session.sorter.history[-10:]]
    for _ in range(10):
        key(DOWN)
    check(all(os.path.exists(p) for p in last10), "all 10 photos are back in place")
    check(app.session.pos == 5, f"cursor stepped back to photo 6 (pos={app.session.pos})")
    with open(log, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    undone = [r["to"] for r in rows if r["action"].startswith("undo")]
    check(undone == list(reversed(last10)), "undo happened in reverse order (checked in log)")

    print("3. undo limit of 20")
    for _ in range(25):
        key(RIGHT)
    before = app.session.pos
    for _ in range(21):
        key(DOWN)
    check(before - app.session.pos == 20, f"exactly 20 undone ({before - app.session.pos})")
    check(main.NOTHING_TO_UNDO in app.window["-MSG-"].get(), "21st undo says nothing to undo")

    print("4. holding a key does not repeat")
    pos = app.session.pos
    key(LEFT, release=False)
    key(LEFT, release=False)
    app.window.TKroot.event_generate("<KeyRelease>", keycode=LEFT, when="tail")
    app.step(timeout=2000)
    check(app.session.pos == pos + 1, "auto-repeat ignored")

    print("5. letter keys work by key position (Hebrew layout safe)")
    key(KEY_A)
    check(app.session.pos == pos + 2, "A = delete")

    print("6. sort everything")
    while app.session.pos < len(app.session.scanner.paths):
        key(RIGHT)
    check(asked[:4] == [1, 2, 3, 4], f"'Next 50?' asked after each batch {asked}")
    check("סיימתם" in app.window["-STATUS-"].get(), "shows all done")
    total = count("delete") + count("keep") + count("star")
    check(total == len(made), f"all {len(made)} photos sorted ({total})")
    check(all(not next(os.walk(targets[k]))[1] for k in targets),
          "photos from all sub-folders sit directly in the target folders (no sub-folders)")
    check(os.path.exists(os.path.join(root, "broken.jpg")), "broken file skipped and left alone")
    check(os.path.exists(os.path.join(root, "notes.txt")), "non-image left alone")

    print("7. config remembered")
    check(config.load()["root_folder"] == os.path.abspath(root), "root folder saved in config.json")

    print("8. speed")
    times.sort()
    print(f"  per key press: median {statistics.median(times):.0f} ms, "
          f"95% {times[int(len(times) * .95)]:.0f} ms, max {times[-1]:.0f} ms ({len(times)} presses)")
    # The slowest presses depend on what else the PC is doing (Tk redraws ~1.6 MP per photo).
    check(statistics.median(times) < 200, "typical photo change under 200 ms")

    if app.video:
        app.video.close()
    app.window.close()
    shutil.rmtree(tmp, ignore_errors=True)


def video_test():
    from make_test_videos import make as make_videos

    tmp = tempfile.mkdtemp(prefix="photoswipe_v_")
    root = os.path.join(tmp, "media")
    videos = make_videos(root, 7, big_hevc=False)
    photos = make(root, 10)
    config.CONFIG_PATH = os.path.join(tmp, "config.json")
    config.save(dict(config.DEFAULTS, log_file=os.path.join(tmp, "log.csv"), media="videos"))
    import video
    real_import = video._import_vlc

    def slow_import():  # like the first start after copying the app, when Windows scans VLC
        time.sleep(3)
        return real_import()

    video._import_vlc = slow_import
    app = main.App()
    app.ask_next_batch = lambda n: "next"
    app._get_video().muted = True  # the test doesn't need to be heard
    t = time.perf_counter()
    app.start_session(root)
    app.window.refresh()
    blocked = (time.perf_counter() - t) * 1000
    video._import_vlc = real_import
    print("9. videos only")
    check(blocked < 1000 and main.STARTING in app.window["-MSG-"].get(),
          f"window keeps working while VLC starts ({blocked:.0f} ms)")
    app.session.scanner.done.wait(10)
    targets = config.target_dirs(app.cfg, root)

    def pump(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            app.step(timeout=20)

    def key(code):
        app.window.TKroot.event_generate("<KeyPress>", keycode=code, when="tail")
        app.step(timeout=2000)
        app.window.TKroot.event_generate("<KeyRelease>", keycode=code, when="tail")
        app.step(timeout=2000)

    def pump_until(cond, limit=10):
        end = time.perf_counter() + limit
        while not cond() and time.perf_counter() < end:
            app.step(timeout=20)
        return cond()

    def wait_playing(limit=5):
        start = time.perf_counter()
        while time.perf_counter() - start < limit:
            app.step(timeout=10)
            if app.video.path and app.video.player.get_time() > 0:
                return (time.perf_counter() - start) * 1000
        return None

    paths = app.session.scanner.paths
    check(len(paths) == len(videos) + 1 and all(main.is_video(p) for p in paths),
          f"only videos listed ({len(paths)} = {len(videos)} + zz_broken.mp4)")
    ms = wait_playing(8)
    vlc = app.video.vlc
    check(ms is not None, f"first video plays (started after {ms and round(ms)} ms)")
    check(app.video.player.audio_get_track_count() > 0, "video has sound")
    check("0:0" in app.window["-STATUS-"].get(), "status shows the video clock")

    key(32)
    pump(0.3)
    check(app.video.player.get_state() == vlc.State.Paused, "SPACE pauses")
    key(32)
    pump(0.3)
    check(app.video.player.get_state() == vlc.State.Playing, "SPACE plays again")

    first = paths[0]
    start = time.perf_counter()
    key(RIGHT)
    ms = wait_playing()
    pump_until(lambda: not app.session.pending)
    check(not os.path.exists(first) and os.path.exists(os.path.join(targets["keep"], os.path.basename(first))),
          "playing video moved to keep-archive")
    check(ms is not None, f"next video plays ({(time.perf_counter() - start) * 1000:.0f} ms from key press)")
    key(DOWN)
    ms = wait_playing()
    check(os.path.exists(first) and app.video.path == first and ms is not None,
          "undo brings the video back and plays it")

    starts = []
    broken_seen = False
    while app.session.pos < len(paths):
        if os.path.basename(paths[app.session.pos]) == "zz_broken.mp4":
            pump(3.5)
            broken_seen = video.UNPLAYABLE in app.window["-STATUS-"].get()
        t = time.perf_counter()
        key(LEFT)
        if app.video.path and os.path.basename(app.video.path) != "zz_broken.mp4":
            wait_playing(3)
            starts.append((time.perf_counter() - t) * 1000)
    check(broken_seen, "broken video says it can't be played")
    pump_until(lambda: not app.session.pending)
    n = sum(len(fs) for _, _, fs in os.walk(targets["delete"]))
    check(n == len(videos) + 1, f"all videos and the broken one could be moved ({n})")
    if starts:
        print(f"  video start after key press: median {statistics.median(starts):.0f} ms, max {max(starts):.0f} ms")

    print("10. mode switch")
    app.set_mode("photos")
    app.session.scanner.done.wait(10)
    check(len(app.session.scanner.paths) == len(photos) and app.video.path is None,
          "photos only: no videos, player stopped")
    for _ in range(3):
        key(RIGHT)
    app.set_mode("both")
    app.session.scanner.done.wait(10)
    check(len(app.session.scanner.paths) == len(photos) - 3, "both: the remaining 7 photos (videos already sorted)")
    check(config.load()["media"] == "both", "mode remembered in config.json")

    app.video.close()
    app.window.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    # If something hangs, print where every thread is stuck and stop.
    faulthandler.dump_traceback_later(int(os.environ.get("TEST_TIMEOUT", "900")), exit=True)
    if "--video" not in sys.argv:
        main_test()
    video_test()
    print("\nFAILED:\n  " + "\n  ".join(failures) if failures else "\nALL PASSED")
    sys.exit(1 if failures else 0)

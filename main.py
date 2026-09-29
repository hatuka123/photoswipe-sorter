"""PhotoSwipe: sort photos and videos with the arrow keys.

LEFT / A  -> delete-queue      RIGHT / D -> keep-archive
UP / W    -> starred           DOWN / Z  -> undo last action
SPACE     -> pause video       M         -> mute video
"""

import os
import sys
import time
import tkinter as tk
from collections import deque

import FreeSimpleGUI as sg
import FreeSimpleGUI.window as _sg_window
from PIL import Image, ImageDraw, ImageFont, ImageTk

import config
from image_handler import IMAGE_EXTS, PREFETCH_AHEAD, Frame, Prefetcher, Scanner, Sorter, load_frame
from video import PANELS, VIDEO_EXTS, VideoPool, is_video

# Windows virtual key codes, so the letters also work with the Hebrew keyboard layout.
KEYS = {37: "delete", 65: "delete", 39: "keep", 68: "keep", 38: "star", 87: "star", 40: "undo", 90: "undo",
        32: "pause", 77: "mute"}
BUTTONS = {"-DEL-": "delete", "-KEEP-": "keep", "-STAR-": "star", "-UNDO-": "undo"}
MODES = {"both": "תמונות + סרטונים", "photos": "רק תמונות", "videos": "רק סרטונים"}
DONE_MSG = {"delete": "הועבר למחיקה", "keep": "נשמר", "star": "סומן בכוכב"}
WHAT = {"both": "תמונות וסרטונים", "photos": "תמונות", "videos": "סרטונים"}

# Colours: a dark frame lets the photos stand out.
BG, PANEL, TEXT, MUTED, ACCENT = "#16171b", "#202228", "#eceef2", "#9aa0ab", "#7c6cff"
FONT = "Segoe UI"
ACTION_STYLE = {  # key: (label, key hint, text colour, button colour, hover colour)
    "-DEL-": ("✕  מחיקה", "←  /  A", "#ffffff", "#d9434b", "#ef5a62"),
    "-STAR-": ("★  כוכב", "↑  /  W", "#1b1400", "#f2b233", "#f7c65a"),
    "-UNDO-": ("↶  ביטול", "↓  /  Z", TEXT, "#3a3d46", "#4a4e59"),
    "-KEEP-": ("✓  שמירה", "→  /  D", "#04210f", "#2fc56b", "#4ad884"),
}
sg.LOOK_AND_FEEL_TABLE["PhotoSwipeDark"] = {
    "BACKGROUND": BG, "TEXT": TEXT, "INPUT": PANEL, "TEXT_INPUT": TEXT, "SCROLL": PANEL,
    "BUTTON": (TEXT, "#3a3d46"), "PROGRESS": (ACCENT, "#2c2e36"), "BORDER": 0,
    "SLIDER_DEPTH": 0, "PROGRESS_DEPTH": 0,
}
# False = photos only (hides the mode switch and never starts VLC).
VIDEOS_ENABLED = True
STARTING = "מפעיל את נגן הווידאו..."
NOTHING_TO_UNDO = "אין מה לבטל"
MODE_EXTS = {"both": IMAGE_EXTS | VIDEO_EXTS, "photos": IMAGE_EXTS, "videos": VIDEO_EXTS}
THUMB = (160, 120)
TIMING = os.environ.get("PHOTOSWIPE_TIMING") == "1"
# Test hook: "keep,keep,delete,undo,..." is performed one action every 1.5 s (used to test the .exe).
SCRIPT = [a for a in os.environ.get("PHOTOSWIPE_SCRIPT", "").split(",") if a]

# FreeSimpleGUI walks the Python call stack on every window.read() for its built-in debugger,
# which costs tens of milliseconds per key press. We never use that debugger.
_sg_window._refresh_debugger = lambda: None


def _asset(name):
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets", name)


ICON = _asset("photoswipe.ico")
LOGO = _asset("photoswipe.png")


def _parts(*parts):
    """Join status parts with " · ". Each part is fenced with left-to-right marks, so Windows
    doesn't mix up the order of Hebrew words, numbers and file paths standing next to each other."""
    return "   ·   ".join(f"‎{p}‎" for p in parts if p)


def _video_thumb():
    """The 'Next:' preview shown when the next file is a video."""
    im = Image.new("RGB", THUMB, (40, 40, 40))
    d = ImageDraw.Draw(im)
    d.polygon([(62, 38), (62, 82), (100, 60)], fill=(230, 230, 230))
    d.text((THUMB[0] // 2, 104), "VIDEO", fill=(230, 230, 230), anchor="mm",
           font=ImageFont.load_default(size=14))
    return im


VIDEO_FRAME = Frame(None, _video_thumb())  # videos need no decoding ahead of time


class Session:
    def __init__(self, root, scanner, sorter):
        self.root = root
        self.scanner = scanner
        self.sorter = sorter
        self.pos = 0  # index into scanner.paths of the file on screen
        self.asked = set()  # batch boundaries where "Next batch?" was already asked
        # Decisions not carried out yet, oldest first: (kind, path, pos, batch). A video is
        # only moved once the player has let go of the file; later moves wait their turn so
        # the undo history stays in order.
        self.pending = deque()


class App:
    def __init__(self):
        self.cfg = config.load()
        if not VIDEOS_ENABLED:
            self.cfg["media"] = "photos"
        self.bs = self.cfg["batch_size"]
        sg.theme("PhotoSwipeDark")
        if os.path.exists(ICON):
            sg.set_options(icon=ICON)  # every window, including the "next batch" question
        sw, sh = sg.Window.get_screen_size()
        self.max_img = (max(320, sw - 40), max(240, sh - 250))
        try:
            self._logo = Image.open(LOGO).convert("RGBA")
        except OSError:
            self._logo = None
        self.window = self._build_window()
        self.prefetch = Prefetcher(
            lambda p: VIDEO_FRAME if is_video(p) else load_frame(p, self.max_img, THUMB))
        label = self.window["-IMG-"].widget
        bg = tuple(c >> 8 for c in label.winfo_rgb(label.cget("background")))
        self._blank = Image.new("RGB", self.max_img, bg)
        # Videos are drawn by VLC into black panels laid over the photo area (see video.py).
        self._video_panels = [tk.Frame(label, bg="black", width=self.max_img[0], height=self.max_img[1])
                              for _ in range(PANELS)]
        self.video = None
        if self.cfg["media"] != "photos":
            self._get_video()  # start VLC in the background so the first video opens fast
        self.session = None
        self.waiting = False  # True while the scanner hasn't reached the next file yet
        self.thumb_pending = False
        self.video_pending = False  # a video is due but VLC is still starting
        self.held = set()
        self._status = ""
        # One screen-sized Tk image that is reused: pasting new pixels into it is much faster
        # than giving the label a new image every time.
        self._photo = None
        self._thumb = None  # keep the Tk image referenced
        self._recent = {}  # original path -> Frame of the last few sorted photos
        self._no_thumb = ImageTk.PhotoImage(Image.new("RGB", THUMB, PANEL))

    def _build_window(self):
        modes = [sg.Radio(label, "mode", key=f"-MODE-{m}", enable_events=True, font=(FONT, 10),
                          background_color=PANEL, default=(m == self.cfg["media"])) for m, label in MODES.items()] if VIDEOS_ENABLED else []
        actions = []
        for key, (label, hint, fg, bg, hover) in ACTION_STYLE.items():
            actions.append(sg.Button(f"{label}\n{hint}", key=key, font=(FONT, 12, "bold"), size=(12, 2),
                                     button_color=(fg, bg), mouseover_colors=(fg, hover), border_width=0,
                                     pad=(6, 4)))
        top = [
            sg.Image(key="-LOGO-", size=(30, 30), background_color=PANEL, pad=((10, 4), 6)),
            sg.Text("PhotoSwipe", font=(FONT, 14, "bold"), background_color=PANEL, pad=(4, 6)),
            sg.Text("", key="-STATUS-", expand_x=True, font=(FONT, 11), text_color=MUTED,
                    background_color=PANEL, pad=(14, 6)),
            *modes,
            sg.Button("📂  בחירת תיקייה", key="-FOLDER-", font=(FONT, 11, "bold"), border_width=0,
                      button_color=("#ffffff", ACCENT), mouseover_colors=("#ffffff", "#8f82ff"), pad=((14, 10), 6)),
        ]
        progress = [
            sg.ProgressBar(self.bs, orientation="h", size=(1, 5), key="-PROG-", expand_x=True, pad=((10, 8), 0)),
            sg.Text("", key="-COUNT-", font=(FONT, 10), text_color=MUTED, background_color=PANEL,
                    pad=((0, 10), (0, 6))),
        ]
        bar = [
            sg.Text("", key="-MSG-", size=(34, 1), font=(FONT, 11), text_color=MUTED, background_color=PANEL,
                    pad=((12, 0), 8)),
            sg.Push(background_color=PANEL),
            *actions,
            sg.Push(background_color=PANEL),
            sg.Text("הבא", font=(FONT, 10), text_color=MUTED, background_color=PANEL),
            sg.Image(key="-NEXT-", size=THUMB, background_color=PANEL, pad=((4, 12), 8)),
        ]
        layout = [
            [sg.Column([top, progress], background_color=PANEL, expand_x=True, pad=0)],
            [sg.Image(key="-IMG-", size=self.max_img, pad=(0, 6))],
            [sg.Column([bar], background_color=PANEL, expand_x=True, pad=0)],
        ]
        # enable_close_attempted_event: on X we stop VLC first, while its parent window still exists.
        w = sg.Window("PhotoSwipe – מיון תמונות וסרטונים", layout, finalize=True, resizable=True,
                      use_default_focus=False, enable_close_attempted_event=True, margins=(0, 0),
                      element_justification="center", return_keyboard_events=False)
        for m in MODES if VIDEOS_ENABLED else ():
            w[f"-MODE-{m}"].widget.configure(selectcolor=BG, activebackground=PANEL, activeforeground=TEXT,
                                             highlightthickness=0)
        if self._logo is not None:
            self._logo_tk = ImageTk.PhotoImage(self._logo.resize((30, 30), Image.LANCZOS))
            w["-LOGO-"].widget.configure(image=self._logo_tk)
        # Buttons must never hold the keyboard focus, or SPACE (pause) would also "click" them.
        for key in [*BUTTONS, "-FOLDER-", *(f"-MODE-{m}" for m in MODES if VIDEOS_ENABLED)]:
            w[key].widget.configure(takefocus=0, cursor="hand2")
        w.bind("<KeyPress>", "-KEY-")
        w.bind("<KeyRelease>", "-KEYUP-")
        w.bind("<FocusOut>", "-BLUR-")
        w.maximize()
        self._focus(w)
        return w

    @staticmethod
    def _focus(window):
        """Give the keyboard back to the main window (after a dialog, or at start)."""
        root = window.TKroot
        root.deiconify()
        root.lift()
        root.focus_force()
        # A closing file dialog can take the focus back a moment later: ask again.
        root.after(150, root.focus_force)

    def _get_video(self):
        if self.video is None:
            self.video = VideoPool(self._video_panels)
        return self.video

    def _stop_video(self):
        if self.video is not None:
            self.video.stop_all()

    # ------------------------------------------------------------ sessions

    def _drain(self, timeout=15):
        """Stop videos and carry out every pending move (before rescanning or exiting)."""
        self._stop_video()
        end = time.monotonic() + timeout
        while self.session and self.session.pending and time.monotonic() < end:
            self.window.TKroot.update()
            self._flush_moves()
            time.sleep(0.02)

    def _flush_moves(self):
        s = self.session
        while s is not None and s.pending:
            kind, src, pos, batch = s.pending[0]
            if self.video is not None and self.video.holds(src):
                return  # the player hasn't let go of this video yet
            s.pending.popleft()
            try:
                s.sorter.apply(kind, src, pos, batch)
            except OSError as e:
                self.window["-MSG-"].update(f"לא ניתן להעביר את {os.path.basename(src)}: {e}")

    def start_session(self, root):
        if self.session:
            self._drain()
            self.session.scanner.stop()
        self._stop_video()
        self._recent.clear()
        root = os.path.abspath(root)
        try:
            config.migrate_legacy(root)  # "_PhotoSwipe" from older versions -> "PhotoSwipe ממוין"
        except OSError as e:
            self.window["-MSG-"].update(f"לא ניתן לשנות את שם התיקייה _PhotoSwipe: {e}")
        targets = config.target_dirs(self.cfg, root)
        scanner = Scanner(root, targets.values(), MODE_EXTS[self.cfg["media"]], skip_names=config.SKIP_DIRS)
        self.session = Session(root, scanner, Sorter(root, targets, config.log_path(self.cfg)))
        self.cfg["root_folder"] = root
        config.save(self.cfg)
        self.show()

    def choose_folder(self):
        self._stop_video()
        folder = sg.popup_get_folder("בחירת התיקייה עם התמונות והסרטונים", no_window=True,
                                     initial_folder=self.cfg.get("root_folder") or None)
        self.held.clear()  # key-release events went to the dialog
        self._focus(self.window)  # so the arrow keys work right away, without clicking the window
        if folder:
            self.start_session(folder)
            return True
        self.show()  # cancelled: carry on where we were
        return False

    def set_mode(self, mode):
        self.window.TKroot.focus_set()  # arrow keys must go to sorting, not to the radio buttons
        if mode == self.cfg["media"]:
            return
        self.cfg["media"] = mode
        config.save(self.cfg)
        if mode != "photos":
            self._get_video()
        if self.session:
            self.start_session(self.session.root)

    # ------------------------------------------------------------ display

    def show(self):
        t0 = time.perf_counter()
        s = self.session
        self.waiting = False
        self.video_pending = False
        what = WHAT[self.cfg["media"]]
        if s is None:
            self._stop_video()
            self._set_photo(self._welcome(), None)
            self._set_progress(None)
            self._set_status("כדי להתחיל, לחצו על \"בחירת תיקייה\" למעלה")
            return
        paths = s.scanner.paths
        while True:
            if s.pos >= len(paths):
                self._stop_video()
                self._set_photo(self._welcome(), None)
                if s.scanner.done.is_set():
                    self._set_progress(None)
                    self._set_status(f"סיימתם! כל ה{what} בתיקייה {os.path.basename(s.root)} מוינו.")
                else:
                    self.waiting = True
                    self._set_status(f"מחפש {what}... (נמצאו {len(paths)})")
                return
            path = paths[s.pos]
            frame = self._recent.pop(path, None) or self.prefetch.get(path)
            if frame is not None:
                break
            del paths[s.pos]  # not a readable image: skip it silently

        nxt = paths[s.pos + 1] if s.pos + 1 < len(paths) else None
        if frame.image is None:  # a video
            self._set_photo(None, nxt)
            pool = self._get_video()
            ok = pool.show(path)
            if ok is None:
                self.video_pending = True  # step() tries again shortly
                self.window["-MSG-"].update(STARTING)
            elif not ok:
                self.window["-MSG-"].update(pool.error or "לא ניתן לנגן את הסרטון (אפשר עדיין למיין אותו)")
            elif self.window["-MSG-"].get() == STARTING:
                self.window["-MSG-"].update("")
            size, kind = "", "סרטון"
        else:
            if self.video is not None:
                self.video.hide()
            self._set_photo(frame, nxt)
            size, kind = f"{frame.image.width}×{frame.image.height}", "תמונה"
        # Only now let the workers start on the next files, so they don't compete with drawing.
        self.prefetch.want(paths[s.pos:s.pos + PREFETCH_AHEAD + 1])
        if nxt is not None and is_video(nxt):
            self._get_video().preload(nxt)  # opened paused and hidden, so it appears instantly
        elif self.video is not None:
            self.video.preload(None)
        found = f"{len(paths)}" + ("" if s.scanner.done.is_set() else "+")
        self._set_progress(s.pos)
        self._set_status(_parts(kind, os.path.relpath(path, s.root), size, f"נמצאו {found} {what}"))
        if TIMING:
            self.window.refresh()
            ms = (time.perf_counter() - t0) * 1000
            with open(os.path.join(config.app_dir(), "timings.txt"), "a") as f:
                f.write(f"show {ms:.1f} ms  {path}\n")

    def _set_status(self, text):
        self._status = text
        self._refresh_status()

    def _refresh_status(self):
        extra = self.video.status() if self.video is not None and self.video.path else ""
        self.window["-STATUS-"].update(_parts(self._status, extra, "רווח = עצירה,  M = השתקה")
                                       if extra else self._status)

    def _set_progress(self, pos):
        """Batch progress bar and "12 / 50 · batch 3"; pos None = nothing being sorted."""
        if pos is None:
            self.window["-PROG-"].update(0)
            self.window["-COUNT-"].update("")
            return
        idx = pos % self.bs + 1
        self.window["-PROG-"].update(idx, max=self.bs)
        self.window["-COUNT-"].update(_parts(f"{idx} / {self.bs}", f"מנה {pos // self.bs + 1}"))

    def _welcome(self):
        """The big logo shown when there is nothing to sort (no folder yet, or all done)."""
        if self._logo is None:
            return None
        if not hasattr(self, "_welcome_frame"):
            side = min(220, self.max_img[1] // 2)
            self._welcome_frame = Frame(self._logo.resize((side, side), Image.LANCZOS), None)
        return self._welcome_frame

    def _set_photo(self, frame, next_path):
        if frame is not None or self._photo is not None:
            canvas = self._blank.copy()
            if frame is not None:
                im = frame.image
                offset = ((canvas.width - im.width) // 2, (canvas.height - im.height) // 2)
                canvas.paste(im, offset, im if im.mode == "RGBA" else None)
            if self._photo is None:
                self._photo = ImageTk.PhotoImage(canvas)
                self.window["-IMG-"].widget.configure(image=self._photo)
            else:
                self._photo.paste(canvas)
        self._next_path = next_path
        self._update_thumb()

    def _update_thumb(self):
        frame = self.prefetch.peek(self._next_path) if self._next_path else None
        self.thumb_pending = self._next_path is not None and frame is None
        if frame is None:  # an empty box of the same size, so the buttons don't shift sideways
            self._thumb = self._no_thumb
        else:
            canvas = Image.new("RGB", THUMB, PANEL)
            canvas.paste(frame.thumb, ((THUMB[0] - frame.thumb.width) // 2, (THUMB[1] - frame.thumb.height) // 2))
            self._thumb = ImageTk.PhotoImage(canvas)
        self.window["-NEXT-"].widget.configure(image=self._thumb)

    # ------------------------------------------------------------ actions

    def act(self, kind):
        s = self.session
        if s is None:
            return
        if kind == "undo":
            return self.undo()
        if kind in ("pause", "mute"):
            if self.video is not None:
                if kind == "pause":
                    self.video.toggle_pause()
                else:
                    self.video.toggle_mute()
                self._refresh_status()
            return
        paths = s.scanner.paths
        if s.pos >= len(paths):
            return
        src = paths[s.pos]
        if self.video is not None and self.video.path == src:
            nxt = paths[s.pos + 1] if s.pos + 1 < len(paths) else None
            if nxt is not None and is_video(nxt) and (s.pos + 1) % self.bs:
                self.video.show(nxt)  # swap to the preloaded next video right away
            self.video.release(src)  # Windows can't move a file that is still open
        s.pending.append((kind, src, s.pos, s.pos // self.bs + 1))
        self._flush_moves()
        frame = self.prefetch.peek(src)
        if frame is not None:  # keep the last few decoded photos so undo shows them instantly
            self._recent[src] = frame
            while len(self._recent) > 3:
                del self._recent[next(iter(self._recent))]
        s.pos += 1
        self.window["-MSG-"].update(f"{DONE_MSG[kind]}: {os.path.basename(src)}")
        if s.pos % self.bs == 0 and s.pos not in s.asked and \
                (s.pos < len(paths) or not s.scanner.done.is_set()):
            s.asked.add(s.pos)
            self._stop_video()
            self._set_photo(self._welcome(), None)
            if self.ask_next_batch(s.pos // self.bs) == "folder" and self.choose_folder():
                return  # the new session already showed its first file
        self.show()

    def undo(self):
        s = self.session
        if s.pending:  # not carried out yet: just forget the decision
            kind, src, pos, batch = s.pending.pop()
            s.pos = pos
            self.window["-MSG-"].update(f"בוטל: {os.path.basename(src)} נשאר במקום")
            self.show()
            return
        if not s.sorter.history:
            self.window["-MSG-"].update(NOTHING_TO_UNDO)
            return
        try:
            res = s.sorter.undo()
        except OSError as e:
            self.window["-MSG-"].update(f"לא ניתן לבטל: {e}")
            self.show()
            return
        action, restored = res
        if restored != action.src and action.src in self._recent:
            self._recent[restored] = self._recent.pop(action.src)
        s.pos = action.pos
        s.scanner.paths[s.pos] = restored
        self.window["-MSG-"].update(f"בוטל: {os.path.basename(restored)} חזר למקומו")
        self.show()

    def ask_next_batch(self, done_batch):
        layout = [[sg.Text(f"✓  סיימתם את מנה {done_batch}", font=(FONT, 16, "bold"), pad=(20, (18, 4)))],
                  [sg.Text("להמשיך למנה הבאה?", font=(FONT, 11), text_color=MUTED, pad=(20, (0, 14)))],
                  [sg.Button(f"המשך ל-{self.bs} הבאים", key="next", bind_return_key=True, font=(FONT, 11, "bold"),
                             button_color=("#04210f", "#2fc56b"), border_width=0, pad=(8, (0, 18))),
                   sg.Button("בחירת תיקייה אחרת", key="folder", font=(FONT, 11), border_width=0,
                             pad=(8, (0, 18)))]]
        w = sg.Window("PhotoSwipe", layout, modal=True, finalize=True, keep_on_top=True,
                      element_justification="center")
        w["next"].set_focus()
        event, _ = w.read()
        w.close()
        self.held.clear()
        self._focus(self.window)
        return event

    # ------------------------------------------------------------ loop

    def run(self):
        root = self.cfg.get("root_folder")
        if root and os.path.isdir(root):
            self.start_session(root)
        else:
            self.show()
            self.choose_folder()
        while self.step():
            pass
        self._drain()
        if self.session:
            self.session.scanner.stop()
        if self.video is not None:
            end = time.monotonic() + 5
            while self.video.busy() and time.monotonic() < end:
                self.window.TKroot.update()
                time.sleep(0.02)
            self.video.close()
        config.save(self.cfg)
        self.window.close()

    def step(self, timeout=None):
        """Wait for one event and handle it. Returns False when the window was closed."""
        playing = self.video is not None and self.video.path is not None
        if SCRIPT and time.monotonic() >= getattr(self, "_script_at", 0):
            self._script_at = time.monotonic() + 1.5
            if hasattr(self, "_script_started"):
                self.act(SCRIPT.pop(0))
            self._script_started = True
        if self.session is not None and self.session.pending:
            self._flush_moves()
        if self.video is not None:
            self.video.poll()
        busy = (self.waiting or self.thumb_pending or self.video_pending or bool(SCRIPT)
                or (self.session is not None and bool(self.session.pending))
                or (self.video is not None and self.video.busy()))
        if timeout is None and (busy or playing):
            timeout = 100 if busy else 250
        event, _ = self.window.read(timeout=timeout)
        if event in (sg.WIN_CLOSED, sg.WINDOW_CLOSE_ATTEMPTED_EVENT):
            return False
        if event == sg.TIMEOUT_EVENT:
            if self.waiting or (self.video_pending and self.video.ready):
                self.show()
            elif self.thumb_pending:
                self._update_thumb()
            if playing:
                self._refresh_status()  # video clock
        elif event == "-KEY-":
            code = self.window.user_bind_event.keycode
            if code in KEYS and code not in self.held:  # ignore auto-repeat while held
                self.held.add(code)
                self.act(KEYS[code])
        elif event == "-KEYUP-":
            self.held.discard(self.window.user_bind_event.keycode)
        elif event == "-BLUR-":
            self.held.clear()
        elif event in BUTTONS:
            self.act(BUTTONS[event])
        elif event == "-FOLDER-":
            self.choose_folder()
        elif isinstance(event, str) and event.startswith("-MODE-"):
            self.set_mode(event[len("-MODE-"):])
        return True


def main():
    dump = os.environ.get("PHOTOSWIPE_HANG_DUMP")  # diagnostics: "<file>" writes all threads every 10 s
    if dump:
        import faulthandler
        faulthandler.dump_traceback_later(10, repeat=True, file=open(dump, "w"))
    try:  # own taskbar entry with our icon, instead of being grouped as "Python"
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhotoSwipe.Sorter")
    except Exception:
        pass
    sg.set_options(dpi_awareness=True)
    app = App()
    try:
        import pyi_splash  # only exists in the single-file build, which shows a "Loading" splash
        pyi_splash.close()
    except ImportError:
        pass
    app.run()


if __name__ == "__main__":
    main()

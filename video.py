"""Video playback with sound, using a trimmed copy of VLC (vendor/vlc) drawn inside our window.

Three players take turns, each drawing into its own panel:
  - "cur":     the video on screen
  - "pre":     the next video, playing silently in a panel parked off-screen until its first
               frame is drawn, then paused back at the start; moving on is just a swap
  - "closing": a video being stopped in the background. Stopping VLC can take a while (the
               first time, Windows Defender scans VLC's plugins as they load), so the window
               never waits for it; the file is only moved once VLC has let go of it.
"""

import os
import sys
import threading
import time

VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".qt", ".mkv", ".avi", ".wmv", ".asf", ".webm", ".3gp", ".3g2",
    ".mts", ".m2ts", ".ts", ".mpg", ".mpeg", ".vob", ".flv", ".ogv", ".divx",
}

ARGS = ["--ignore-config", "--quiet", "--no-video-title-show", "--no-osd", "--no-spu",
        "--no-sub-autodetect-file", "--no-snapshot-preview", "--no-stats", "--no-lua",
        "--no-media-library", "--no-metadata-network-access", "--no-mouse-events",
        "--no-keyboard-events", "--file-caching=100"]  # start sooner (default buffers 300 ms)

PANELS = 3
UNPLAYABLE = "לא ניתן לנגן את הקובץ (אפשר עדיין למיין אותו)"


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def _vlc_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "vlc")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "vlc")


def _import_vlc():
    d = _vlc_dir()
    os.environ["PYTHON_VLC_LIB_PATH"] = os.path.join(d, "libvlc.dll")
    os.environ["PYTHON_VLC_MODULE_PATH"] = os.path.join(d, "plugins")
    os.environ["VLC_PLUGIN_PATH"] = os.path.join(d, "plugins")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(d)
    import vlc
    return vlc


# Plugins every video needs; the virus scanner gets to them first.
_WARM_FIRST = ["codec/libavcodec_plugin.dll", "demux/libmp4_plugin.dll", "demux/libmkv_plugin.dll",
               "demux/libes_plugin.dll", "packetizer/libpacketizer_h264_plugin.dll",
               "packetizer/libpacketizer_hevc_plugin.dll", "video_output/libdirect3d11_plugin.dll",
               "audio_output/libmmdevice_plugin.dll", "codec/libd3d11va_plugin.dll"]


def _warm_up(folder):
    """Let the virus scanner check every VLC plugin now, in the background.

    The first time Windows sees these files (right after the app was copied), Defender scans
    each plugin as it loads, which made the first video take ~10 s to start. Creating an
    "image" file mapping triggers the same scan without loading anything (and without the
    Windows loader lock that VLC itself needs), while the user is still looking at photos.
    """
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.SetThreadPriority(k32.GetCurrentThread(), -2)  # THREAD_PRIORITY_LOWEST
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.CreateFileMappingW.restype = wintypes.HANDLE
        k32.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                           wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
    except Exception:
        return
    invalid = wintypes.HANDLE(-1).value
    plugins = os.path.join(folder, "plugins")
    rest = sorted(os.path.relpath(os.path.join(r, f), plugins).replace("\\", "/")
                  for r, _, fs in os.walk(plugins) for f in fs if f.endswith(".dll"))
    for rel in _WARM_FIRST + [r for r in rest if r not in _WARM_FIRST]:
        # GENERIC_READ | GENERIC_EXECUTE, share read, OPEN_EXISTING
        f = k32.CreateFileW(os.path.join(plugins, rel), 0xA0000000, 1, None, 3, 0, None)
        if f in (None, invalid):
            continue
        m = k32.CreateFileMappingW(f, None, 0x1000000 | 0x20, 0, 0, None)  # SEC_IMAGE, PAGE_EXECUTE_READ
        if m:
            k32.CloseHandle(m)
        k32.CloseHandle(f)


def _fmt(ms):
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


class _Slot:
    """One VLC player and the Tk panel it draws into."""

    def __init__(self, panel):
        self.panel = panel
        self.hwnd = panel.winfo_id()  # must be read on the Tk thread
        self.player = None
        self.path = None  # the file this player has open (also while closing)
        self.role = "free"  # free / cur / pre / closing
        self.primed = False  # "pre" only: first frame drawn, paused back at the start
        self.started = 0.0


class VideoPool:
    def __init__(self, panels):
        """`panels`: equally sized Tk frames inside the area where videos should appear."""
        self.error = None
        self.muted = False
        self._slots = [_Slot(p) for p in panels]
        self._cur = None
        self._want_pre = None
        for s in self._slots:
            self._park(s)
        self._ready = threading.Event()
        threading.Thread(target=self._init, daemon=True).start()

    def _init(self):
        try:
            self.vlc = _import_vlc()
            extra = os.environ.get("PHOTOSWIPE_VLC_ARGS", "").split()  # diagnostics only
            self.instance = self.vlc.Instance(ARGS + extra)
            for s in self._slots:
                s.player = self.instance.media_player_new()
                s.player.set_hwnd(s.hwnd)
                # Key presses and clicks on the video go to our window, not to VLC.
                s.player.video_set_key_input(False)
                s.player.video_set_mouse_input(False)
            threading.Thread(target=_warm_up, args=(_vlc_dir(),), daemon=True).start()
        except Exception as e:  # missing/broken VLC: the app still sorts photos
            self.error = f"נגן הווידאו לא הצליח לעלות: {e}"
        finally:
            self._ready.set()

    @property
    def ready(self):
        return self._ready.is_set()

    @property
    def path(self):
        """The video on screen, or None."""
        return self._cur.path if self._cur else None

    @property
    def player(self):
        """The VLC player on screen (used by the tests)."""
        return self._cur.player if self._cur else None

    def holds(self, path):
        """True while any player (even one still closing) has `path` open."""
        return any(s.path == path for s in self._slots)

    def busy(self):
        """True while something still has to happen in the background (see poll)."""
        return any(s.role == "closing" or (s.role == "pre" and not s.primed) for s in self._slots) or (
            self._want_pre is not None and not self.holds(self._want_pre))

    # ---------------------------------------------------------------- panels

    # place() merges with the previous placement, so every option is given each time.
    @staticmethod
    def _park(slot):  # off-screen: keeps its video output alive but invisible
        slot.panel.place(x=-4 * slot.panel.winfo_reqwidth(), y=0, relx=0, rely=0, anchor="nw")

    @staticmethod
    def _unpark(slot):
        slot.panel.place(x=0, y=0, relx=0.5, rely=0.5, anchor="center")
        slot.panel.lift()

    # ---------------------------------------------------------------- playing

    def _open(self, slot, path, silent):
        media = self.instance.media_new_path(os.path.abspath(path))  # VLC rejects mixed / and \
        if media is None:
            return False
        media.add_option("input-repeat=65535")  # loop until the user decides
        slot.player.set_media(media)
        media.release()
        slot.player.audio_set_mute(self.muted or silent)
        slot.path = path
        slot.primed = False
        slot.started = time.monotonic()
        return slot.player.play() == 0

    def _close(self, slot):
        """Stop `slot` in the background; its file stays open until that has finished."""
        if slot.role in ("free", "closing"):
            return
        if slot is self._cur:
            self._cur = None
        slot.role = "closing"
        slot.player.audio_set_mute(True)
        self._park(slot)

        def stop():
            slot.player.stop()  # returns once VLC has closed the file
            slot.player.set_media(None)
            slot.path = None
            slot.role = "free"

        threading.Thread(target=stop, daemon=True).start()

    def _free(self):
        return next((s for s in self._slots if s.role == "free"), None)

    def show(self, path):
        """Show and play `path` (instantly if it was prepared with preload).

        Returns None if it can't start yet (VLC still starting, or every player still busy):
        call again a little later. The window is never made to wait.
        """
        if not self.ready:
            return None
        if self.error:
            return False
        if self._cur is not None and self._cur.path == path:
            self._unpark(self._cur)
            return True
        old = self._cur
        pre = next((s for s in self._slots if s.role == "pre" and s.path == path), None)
        if pre is not None:  # prepared: swap
            pre.role = "cur"
            self._unpark(pre)
            pre.panel.update_idletasks()
            if not pre.primed:  # still starting up: begin from the start anyway
                pre.player.set_time(0)
            pre.player.audio_set_mute(self.muted)
            pre.player.set_pause(0)
            pre.started = time.monotonic()
            self._cur = pre
        else:
            slot = self._free()
            if slot is None:
                for s in self._slots:  # a different file was prepared: make room
                    if s.role == "pre":
                        self._close(s)
                return None
            if not self._open(slot, path, silent=False):
                return False
            slot.role = "cur"
            self._unpark(slot)
            self._cur = slot
        if old is not None:
            self._close(old)
        if self._want_pre == path:
            self._want_pre = None
        return True

    def preload(self, path):
        """Open `path` paused on its first frame in a hidden player, ready for show().

        preload(None): nothing to prepare (the next file is a photo).
        """
        if self.error:
            return
        self._want_pre = path  # remembered, so poll() prepares it once VLC is ready
        if not self.ready:
            return
        if path is None:
            for s in self._slots:
                if s.role == "pre":
                    self._close(s)
            return
        if any(s.path == path and s.role in ("cur", "pre") for s in self._slots):
            return
        for s in self._slots:
            if s.role == "pre":
                self._close(s)
        slot = self._free()
        if slot is not None:  # otherwise poll() tries again once a player is free
            self._open(slot, path, silent=True)
            slot.role = "pre"

    def poll(self):
        """Call regularly (every ~100 ms while busy()): moves preloading along."""
        if self._want_pre is not None and not self.holds(self._want_pre):
            self.preload(self._want_pre)
        for s in self._slots:
            if s.role == "pre" and not s.primed and s.player.get_time() > 0:
                s.player.set_pause(1)  # its first frame is on the (hidden) panel now
                s.player.set_time(0)
                s.primed = True

    def release(self, path):
        """Start closing `path` in whichever player has it (see holds() for when it's done)."""
        if self._want_pre == path:
            self._want_pre = None
        for s in self._slots:
            if path is not None and s.path == path:
                self._close(s)

    def hide(self):
        """A photo is on screen: stop the current video but keep the prepared one."""
        if self._cur is not None:
            self._close(self._cur)

    def stop_all(self):
        self._want_pre = None
        for s in self._slots:
            self._close(s)

    # ---------------------------------------------------------------- controls & status

    def toggle_pause(self):
        if self._cur is not None:
            self._cur.player.pause()

    def toggle_mute(self):
        self.muted = not self.muted
        if self._cur is not None:
            self._cur.player.audio_set_mute(self.muted)

    def unplayable(self):
        """True if VLC gave up on the file, or nothing has played 3 seconds after starting."""
        s = self._cur
        if s is None:
            return False
        if s.player.get_state() == self.vlc.State.Error:
            return True
        return time.monotonic() - s.started > 3 and s.player.get_length() <= 0 and s.player.get_time() <= 0

    def status(self):
        """'0:12 / 0:45' (+ paused / muted), or '' if nothing is playing."""
        s = self._cur
        if s is None:
            return ""
        if self.unplayable():
            return UNPLAYABLE
        t, total = max(0, s.player.get_time()), max(0, s.player.get_length())
        text = f"{_fmt(t)} / {_fmt(total)}"
        if s.player.get_state() == self.vlc.State.Paused:
            text += "  (עצור)"
        if self.muted:
            text += "  (מושתק)"
        return text

    def close(self):
        """At exit, after stop_all() and once busy() is False (or we gave up waiting)."""
        if self.ready and not self.error:
            for s in self._slots:
                if s.role == "free":
                    s.player.release()

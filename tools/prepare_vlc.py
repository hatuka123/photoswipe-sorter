"""Unpack the official VLC zip into vendor/vlc, keeping only what's needed to play local files.

Usage: python tools/prepare_vlc.py <path to vlc-3.0.24-win64.zip>
(download it from https://download.videolan.org/pub/videolan/vlc/3.0.24/win64/)
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

SHA256 = "fcf30850371ad10c9373cc4f0f4501e7dee49e3e9ae9f20c72fb2661a1ca6323"  # vlc-3.0.24-win64.zip
DEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor", "vlc")

# Plugin folders needed for local playback with sound (no GUI, network, streaming, subtitles).
KEEP_DIRS = ["codec", "demux", "packetizer", "audio_filter", "audio_mixer", "audio_output",
             "video_output", "video_chroma", "video_filter", "stream_filter", "d3d11", "d3d9"]
KEEP_ACCESS = ["libfilesystem_plugin.dll", "libattachment_plugin.dll", "libidummy_plugin.dll"]
# Encoders and subtitle/teletext decoders we never use.
DROP_CODECS = ["libx264_plugin.dll", "libx26410b_plugin.dll", "libx265_plugin.dll", "libaom_plugin.dll",
               "libqsv_plugin.dll", "libzvbi_plugin.dll", "libaribsub_plugin.dll", "libfluidsynth_plugin.dll",
               "liblibass_plugin.dll", "libtheora_plugin.dll", "libschroedinger_plugin.dll"]


def main(zip_path):
    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != SHA256:
        sys.exit("Checksum mismatch - not the official vlc-3.0.24-win64.zip")

    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    src = os.path.join(tmp, "vlc-3.0.24")
    shutil.rmtree(DEST, ignore_errors=True)
    os.makedirs(os.path.join(DEST, "plugins", "access"))
    for name in ("libvlc.dll", "libvlccore.dll", "COPYING.txt"):
        shutil.copy(os.path.join(src, name), DEST)
    for d in KEEP_DIRS:
        shutil.copytree(os.path.join(src, "plugins", d), os.path.join(DEST, "plugins", d))
    for name in KEEP_ACCESS:
        shutil.copy(os.path.join(src, "plugins", "access", name), os.path.join(DEST, "plugins", "access"))
    for name in DROP_CODECS:
        p = os.path.join(DEST, "plugins", "codec", name)
        if os.path.exists(p):
            os.remove(p)
    # Plugin cache (plugins.dat) makes VLC start much faster than scanning every DLL.
    gen = os.path.join(DEST, "vlc-cache-gen.exe")
    shutil.copy(os.path.join(src, "vlc-cache-gen.exe"), gen)
    subprocess.run([gen, os.path.join(DEST, "plugins")], check=True)
    os.remove(gen)
    shutil.rmtree(tmp, ignore_errors=True)
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(DEST) for f in fs)
    print(f"vendor/vlc ready: {size / 1e6:.0f} MB")


if __name__ == "__main__":
    main(sys.argv[1])

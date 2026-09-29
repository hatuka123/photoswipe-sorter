"""Create short test videos with sound in many formats (needs the dev-only imageio-ffmpeg package).

Usage: python tests/make_test_videos.py <folder> [count]
"""

import os
import subprocess
import sys

import imageio_ffmpeg

# (extension, video args, audio args)
FORMATS = [
    ("mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:a", "aac"]),
    ("mov", ["-c:v", "libx265", "-x265-params", "log-level=error", "-tag:v", "hvc1", "-pix_fmt", "yuv420p"], ["-c:a", "aac"]),  # like iPhone
    ("mkv", ["-c:v", "libvpx-vp9", "-deadline", "realtime"], ["-c:a", "libopus"]),
    ("avi", ["-c:v", "mpeg4"], ["-c:a", "libmp3lame"]),
    ("webm", ["-c:v", "libvpx", "-deadline", "realtime"], ["-c:a", "libvorbis"]),
    ("wmv", ["-c:v", "wmv2"], ["-c:a", "wmav2"]),
    ("3gp", ["-c:v", "h263", "-s", "352x288"], ["-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1"]),
]


def make(root, count=14, big_hevc=True):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subdirs = ["", "2019/summer", "phone/WhatsApp Video"]
    made = []
    for i in range(count):
        ext, v, a = FORMATS[i % len(FORMATS)]
        folder = os.path.join(root, subdirs[i % len(subdirs)])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"VID_{i:04d}.{ext}")
        size = "3840x2160" if (big_hevc and i == 1) else "640x360"
        cmd = [ffmpeg, "-y", "-loglevel", "error",
               "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration=3",
               "-f", "lavfi", "-i", f"sine=frequency={300 + 40 * i}:duration=3",
               *v, *a, "-shortest", path]
        subprocess.run(cmd, check=True)
        made.append(path)
    with open(os.path.join(root, "zz_broken.mp4"), "wb") as f:
        f.write(b"not really a video")
    return made


if __name__ == "__main__":
    out = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    print(len(make(out, n)), "videos created in", out)

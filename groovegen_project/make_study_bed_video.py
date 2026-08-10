"""Make an MP4 (title card + audio) for the frozen study bed demo.

Uses the Nexus dark theme. Builds a video-only stream from a single PNG,
then muxes the real WAV with explicit stream mapping so audio is preserved.
"""
import os, subprocess
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
AUD = os.path.join(HERE, "outputs", "audio")
WAV = os.path.join(AUD, "study_bed_frozen.wav")
PNG = os.path.join(AUD, "_study_bed_card.png")
VONLY = os.path.join(AUD, "_study_bed_vonly.mp4")
OUT = os.path.join(AUD, "study_bed_frozen.mp4")

BG = (23, 22, 20)
TEAL = (79, 152, 163)
TEXT = (205, 204, 202)
MUTED = (121, 120, 118)

W, H = 1280, 720


def font(sz, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

def center(text, y, f, fill):
    bb = d.textbbox((0, 0), text, font=f)
    w = bb[2] - bb[0]
    d.text(((W - w) / 2, y), text, font=f, fill=fill)

center("GrooveGen — Frozen Study Bed", 210, font(52, bold=True), TEXT)
center("hero_study  ·  constant verse loop", 300, font(30), TEAL)
center("Same harmony / bass / grand-piano timbre as the hero song,", 380, font(24), MUTED)
center("but a single time-invariant section — no intro/chorus build-up.", 416, font(24), MUTED)
center("This is the experiment bed: only the knob changes across stimuli.", 480, font(24), MUTED)
img.save(PNG)

# video-only stream from the still
subprocess.run([
    "ffmpeg", "-y", "-loop", "1", "-i", PNG,
    "-t", "13.5", "-r", "24", "-pix_fmt", "yuv420p",
    "-c:v", "libx264", "-an", VONLY,
], check=True, capture_output=True)

# mux with explicit mapping
subprocess.run([
    "ffmpeg", "-y", "-i", VONLY, "-i", WAV,
    "-map", "0:v:0", "-map", "1:a:0",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", OUT,
], check=True, capture_output=True)

# verify audio
r = subprocess.run(
    ["ffmpeg", "-i", OUT, "-af", "volumedetect", "-f", "null", "/dev/null"],
    capture_output=True, text=True)
for line in r.stderr.splitlines():
    if "mean_volume" in line or "max_volume" in line or "Duration" in line:
        print(line.strip())
print("OUT:", OUT)

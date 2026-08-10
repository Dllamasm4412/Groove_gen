"""Assemble the melody-timbre candidates into ONE back-to-back MP4 with a
labeled title card for each segment."""
import os, sys, subprocess
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

OUT = config.AUDIO_OUT / "melody_compare"
W, H = 1280, 720
BG = (23, 22, 20); TEAL = (79, 152, 163); TEXT = (205, 204, 202); MUTED = (121, 120, 118)

# (wav filename, index, big label)
SEGMENTS = [
    ("mel_04_electric_piano_current.wav", "1 / 6", "Electric Piano", "the current sound (for reference)"),
    ("mel_00_warm_grand_piano.wav",       "2 / 6", "Warm Grand Piano", "warm keys"),
    ("mel_24_nylon_guitar.wav",           "3 / 6", "Nylon Guitar", "soft, intimate"),
    ("mel_25_steel_acoustic_guitar.wav",  "4 / 6", "Steel Acoustic Guitar", "brighter, strummy"),
    ("mel_26_jazz_electric_guitar.wav",   "5 / 6", "Jazz Electric Guitar", "round, mellow electric"),
    ("mel_27_clean_electric_guitar.wav",  "6 / 6", "Clean Electric Guitar", "bright, poppy electric"),
]


def font(sz, bold=False):
    p = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
         else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return ImageFont.truetype(p, sz) if os.path.exists(p) else ImageFont.load_default()


def center(d, txt, y, f, fill):
    b = d.textbbox((0, 0), txt, font=f); w = b[2] - b[0]
    d.text(((W - w) / 2, y), txt, font=f, fill=fill)


def make_frame(idx, title, sub, path):
    img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img)
    d.rectangle([(W/2 - 60, 150), (W/2 + 60, 154)], fill=TEAL)
    center(d, idx, 185, font(30, True), TEAL)
    center(d, title, 250, font(64, True), TEXT)
    center(d, sub, 360, font(30), MUTED)
    center(d, "Dorian harmony + anthemic bass  ·  same melody, different instrument",
           640, font(24), MUTED)
    img.save(path)


seg_mp4s = []
for wav, idx, title, sub in SEGMENTS:
    base = wav.replace(".wav", "")
    frame = str(OUT / f"frame_{base}.png")
    make_frame(idx, title, sub, frame)
    seg = str(OUT / f"seg_{base}.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", frame, "-i", str(OUT / wav),
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p", "-shortest", seg, "-loglevel", "error",
    ], check=True)
    seg_mp4s.append(seg)
    print("segment:", os.path.basename(seg))

# concat
listfile = str(OUT / "concat.txt")
with open(listfile, "w") as f:
    for s in seg_mp4s:
        f.write(f"file '{s}'\n")
final = str(config.AUDIO_OUT / "melody_timbre_comparison.mp4")
subprocess.run([
    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
    "-c", "copy", final, "-loglevel", "error",
], check=True)
print("FINAL:", final)

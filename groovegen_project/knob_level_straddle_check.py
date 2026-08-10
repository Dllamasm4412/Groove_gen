"""Literature-straddle check: do the implemented knob levels (from the manifest)
straddle the groove curve / sweet-spot ranges recommended in groove_knob_literature.md?

Produces a figure with one panel per core knob, plotting the implemented levels
against the literature's expected groove shape and recommended-range bands.
"""
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches

plt.rcParams.update({
    "figure.dpi": 150,
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.grid": True,
    "grid.alpha": 0.25,
})

BG = "#F7F6F2"
TEXT = "#28251D"
TEAL = "#20808D"
RUST = "#A84B2F"
GOLD = "#FFC553"
MUTED = "#7A7974"
GREEN = "#437A22"

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "outputs", "figures", "knob_level_straddle.png")

# --- IMPLEMENTED levels, read straight from the manifest's achieved/requested cols ---
# syncopation: requested syncopation_level -> ACHIEVED Witek-style index
sync_levels = [0.0, 0.25, 0.5, 1.0]
sync_achieved = [0, 16, 32, 49]       # achieved_syncopation_index (recalibrated)
# density: ACHIEVED onsets/bar
dens_achieved = [5, 9, 15, 25]
# swing: realized swing fraction (%)
swing_frac = [50.0, 55.6, 61.5, 66.7]
# tempo bpm
tempo_bpm = [70, 95, 115, 150]

fig, axes = plt.subplots(2, 2, figsize=(13, 9))
fig.patch.set_facecolor(BG)
for ax in axes.flat:
    ax.set_facecolor(BG)

# ---------------- 1. SYNCOPATION ----------------
ax = axes[0, 0]
# Witek inverted-U on the 0-81 index, apex ~28-32
S = np.linspace(0, 81, 300)
apex = 30
groove = 1 - ((S - apex) / 50) ** 2
ax.plot(S, groove, color=MUTED, lw=2, label="Witek 2014 inverted-U (idealized)")
# literature recommended bands
ax.axvspan(0, 4, color=GOLD, alpha=0.18)
ax.axvspan(12, 18, color=GOLD, alpha=0.18)
ax.axvspan(26, 34, color=GREEN, alpha=0.22)  # sweet spot
ax.axvspan(48, 65, color=RUST, alpha=0.15)
ax.text(30, 0.10, "lit sweet\nspot S≈26–34", ha="center", va="bottom",
        fontsize=8.5, color=GREEN, fontweight="bold")
# recalibrated achieved values -- now span the full inverted-U
label_dx = [10, 10, 10, 10]
label_dy = [-22, 14, 14, 14]
for i, s in enumerate(sync_achieved):
    g = 1 - ((s - apex) / 50) ** 2
    ax.scatter(s, g, color=TEAL, s=90, zorder=5, edgecolor="white")
    ax.annotate(f"L{i} (S={s})", (s, g), textcoords="offset points",
                xytext=(label_dx[i], label_dy[i]), fontsize=9, color=TEAL,
                fontweight="bold")
ax.set_title("Syncopation — RECALIBRATED: levels now span the curve", color=GREEN)
ax.set_xlabel("Witek syncopation index S (0–81)")
ax.set_ylabel("relative groove (idealized)")
ax.set_xlim(-3, 81)
ax.set_ylim(-0.05, 1.12)

# ---------------- 2. EVENT DENSITY ----------------
ax = axes[0, 1]
d = np.linspace(2, 26, 200)
groove_d = (d - 2) / (26 - 2)  # monotonic positive (no ceiling established)
ax.plot(d, groove_d, color=MUTED, lw=2, label="monotonic + (Madison/Senn)")
bands = [(4, 6), (8, 10), (14, 16), (20, 24)]
for b in bands:
    ax.axvspan(b[0], b[1], color=GREEN, alpha=0.15)
for i, dv in enumerate(dens_achieved):
    g = (dv - 2) / (26 - 2)
    ax.scatter(dv, g, color=TEAL, s=90, zorder=5, edgecolor="white")
    ax.annotate(f"L{i}\n{dv}/bar", (dv, g), textcoords="offset points",
                xytext=(6, -4), fontsize=9, color=TEAL, fontweight="bold")
ax.set_title("Event density — levels land squarely in lit bands", color=GREEN)
ax.set_xlabel("onsets per bar")
ax.set_ylabel("relative groove (monotonic)")
ax.set_xlim(2, 26)
ax.set_ylim(-0.05, 1.05)

# ---------------- 3. SWING ----------------
ax = axes[1, 0]
sw = np.linspace(50, 75, 200)
# sweet zone 60-67%, mild inverted-U peaking ~63
groove_s = 1 - ((sw - 63) / 18) ** 2
ax.plot(sw, groove_s, color=MUTED, lw=2, label="sweet zone 60–67% (Friberg)")
ax.axvspan(50, 51, color=GOLD, alpha=0.18)
ax.axvspan(55, 57, color=GOLD, alpha=0.18)
ax.axvspan(60, 63, color=GREEN, alpha=0.22)
ax.axvspan(66, 68, color=RUST, alpha=0.15)
ax.text(61.5, 0.46, "lit sweet\nspot 60–63%", ha="center", va="bottom",
        fontsize=8.5, color=GREEN, fontweight="bold")
swing_dy = [10, 10, 12, 10]
swing_dx = [8, 8, -4, 8]
for i, sv in enumerate(swing_frac):
    g = 1 - ((sv - 63) / 18) ** 2
    ax.scatter(sv, g, color=TEAL, s=90, zorder=5, edgecolor="white")
    ha = "right" if i == 2 else "left"
    ax.annotate(f"L{i} {sv:.0f}%", (sv, g), textcoords="offset points",
                xytext=(swing_dx[i], swing_dy[i]), fontsize=9, color=TEAL,
                fontweight="bold", ha=ha)
ax.set_title("Swing — levels straddle the sweet zone well", color=GREEN)
ax.set_xlabel("swing fraction (%)")
ax.set_ylabel("relative groove (idealized)")
ax.set_xlim(49, 75)
ax.set_ylim(0.4, 1.08)

# ---------------- 4. TEMPO ----------------
ax = axes[1, 1]
t = np.linspace(60, 200, 200)
groove_t = 1 - ((t - 113) / 70) ** 2  # peak ~107-126, use 113
ax.plot(t, groove_t, color=MUTED, lw=2, label="inverted-U peak ~107–126 (Etani)")
ax.axvspan(100, 126, color=GREEN, alpha=0.18)
ax.text(143, 0.55, "lit peak\n107–126 BPM", ha="center", va="center",
        fontsize=8.5, color=GREEN, fontweight="bold")
tempo_dy = [-30, 14, -30, 14]
for i, tv in enumerate(tempo_bpm):
    g = 1 - ((tv - 113) / 70) ** 2
    ax.scatter(tv, g, color=TEAL, s=90, zorder=5, edgecolor="white")
    ax.annotate(f"L{i} ({tv})", (tv, g), textcoords="offset points",
                xytext=(8, tempo_dy[i]), fontsize=9, color=TEAL,
                fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=TEAL, lw=0.8))
ax.set_title("Tempo — straddles peak (if used as a knob)", color=GREEN)
ax.set_xlabel("tempo (BPM)")
ax.set_ylabel("relative groove (idealized)")
ax.set_xlim(60, 200)
ax.set_ylim(0.0, 1.08)

fig.suptitle("Implemented knob levels vs. literature groove curves  (teal = your rendered levels)",
             fontsize=15, fontweight="bold", color=TEXT, y=0.99)
fig.tight_layout(rect=[0, 0.03, 1, 0.96])
fig.text(0.5, 0.005,
         "Idealized curves illustrate literature-reported SHAPE only (not your data). "
         "Bands = recommended ranges from groove_knob_literature.md.",
         ha="center", fontsize=8, color=MUTED)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
fig.savefig(OUT, bbox_inches="tight", facecolor=BG)
print("saved", OUT)

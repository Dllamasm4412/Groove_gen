"""
GrooveGen — interactive web UI (Gradio)
=======================================

A browser UI to drive the GrooveGen engine: pick a genre, set tempo + the groove
knob, and render a full song you can play inline.

Runs three places with the SAME code:
  • Your laptop  ->  python app.py            (opens http://127.0.0.1:7860)
  • Google Colab ->  see the bottom of this file / notebooks/08_ui.ipynb
  • Raspberry Pi ->  python app.py --host 0.0.0.0   (open from any device on the LAN)

Two render engines:
  • "Engine (fast, runs anywhere)"  — pure-Python genre seed + FluidSynth. Default.
                                      This is exactly what produced the demo songs.
  • "AMT transformer (needs GPU)"   — Anticipatory Music Transformer embellishes the
                                      seed. Only enabled when a GPU + model are present
                                      (e.g. Colab T4). Falls back to the engine otherwise.

Requires: pip install gradio   (plus the normal GrooveGen deps + FluidSynth system lib)
"""
from __future__ import annotations

import argparse
import os
import tempfile
import traceback

import gradio as gr

import groovegen as gg
from groovegen import dlbed, genre_styles as gs

# ----------------------------------------------------------------------------- #
# Setup
# ----------------------------------------------------------------------------- #
GENRES = list(gs.GENRE_STYLES.keys())  # 6 genres
DEFAULT_GENRE = "pop" if "pop" in GENRES else GENRES[0]
OUT_DIR = os.path.join(tempfile.gettempdir(), "groovegen_ui")

# Info-panel figures live alongside this file in assets/.
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
FIG_CURVES = os.path.join(ASSETS, "groove_param_curves.png")
FIG_DANCE = os.path.join(ASSETS, "danceability_by_genre.png")
os.makedirs(OUT_DIR, exist_ok=True)

# Resolve a soundfont once; tell the user if none is found.
try:
    SF2 = gg.default_sf2()
    SF2_OK = bool(SF2) and os.path.exists(SF2)
except Exception:
    SF2, SF2_OK = None, False


def _gpu_available() -> bool:
    """True only if torch + CUDA are both present (Colab T4, a CUDA laptop, etc.)."""
    try:
        import torch  # noqa: WPS433 (optional dep)
        return bool(torch.cuda.is_available())
    except Exception:
        return False


GPU = _gpu_available()


# ----------------------------------------------------------------------------- #
# AMT (deep-learning) embellishment — optional, GPU-gated
# ----------------------------------------------------------------------------- #
def _amt_embellish(src_midi: str, genre: str, tempo: int) -> tuple[str, str]:
    """
    Run the Anticipatory Music Transformer over the genre seed to produce an
    embellished MIDI bed. Returns (midi_path, note). On any failure, returns the
    original seed and an explanatory note so the UI never hard-crashes.
    """
    try:
        import torch
        from transformers import AutoModelForCausalLM
        from anticipation import ops  # noqa: F401  (sanity import)
        from anticipation.sample import generate as amt_generate  # type: ignore
        from anticipation.convert import events_to_midi, midi_to_events  # type: ignore

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_id = "stanford-crfm/music-medium-800k" if device == "cuda" else "stanford-crfm/music-small-800k"
        model = AutoModelForCausalLM.from_pretrained(model_id).to(device).eval()

        events = midi_to_events(src_midi)
        # Continue/embellish from the seed for a couple of bars worth of tokens.
        out_events = amt_generate(model, start_time=0, end_time=8, inputs=events, top_p=0.95)
        out_midi = os.path.join(OUT_DIR, f"amt_{genre.replace('/', '_')}.mid")
        events_to_midi(out_events).write(out_midi)
        return out_midi, f"AMT bed generated with {model_id} on {device.upper()}."
    except Exception as exc:  # noqa: BLE001 — we want a graceful fallback in a UI
        return src_midi, (
            "AMT step skipped (fell back to the engine seed): "
            f"{type(exc).__name__}: {exc}. "
            "The transformer needs a GPU + `transformers`, `torch`, and `anticipation` installed."
        )


# ----------------------------------------------------------------------------- #
# Main render callback
# ----------------------------------------------------------------------------- #
def render(genre, tempo, knob, density, bars, seconds, seed, use_amt):
    """Build a full song and return (audio_path, status_markdown)."""
    if not SF2_OK:
        return None, (
            "**No soundfont found.** Install one so the engine can render audio:\n\n"
            "- Linux: `sudo apt-get install -y fluidsynth fluid-soundfont-gm`\n"
            "- macOS: `brew install fluid-synth`, then drop `FluidR3_GM.sf2` into `soundfonts/`"
        )

    tempo = int(tempo)
    safe = genre.replace("/", "_")
    notes = []

    try:
        # 1) Genre style seed MIDI (pure python, no GPU).
        seed_pm = gs.build_style_seed(genre, bars=int(bars), seed=int(seed))
        src_midi = os.path.join(OUT_DIR, f"seed_{safe}.mid")
        seed_pm.write(src_midi)

        # 2) Optionally embellish with the AMT transformer (GPU only).
        if use_amt:
            src_midi, amt_note = _amt_embellish(src_midi, genre, tempo)
            notes.append(amt_note)
        else:
            notes.append("Engine render (no transformer).")

        # 3) Arrange the seed into a full song and register it as a bed profile.
        prof = dlbed.register_genre_song(src_midi, genre, tempo, n_bars=int(bars),
                                         name=f"ui_{safe}")

        # 4) Render the full track with the knob-controlled drums on top.
        params = gg.GrooveParams(
            tempo_bpm=float(tempo),
            bed_profile=prof,
            with_bed=True,
            target_seconds=float(seconds),
            event_density=int(density),
            syncopation_level=float(knob),
            seed=int(seed),
            drum_style=genre,   # genre-idiomatic kit/groove (knob still modulates on top)
        )
        pm = gg.PatternBuilder(params).build_looped()
        out_wav = os.path.join(OUT_DIR, f"song_{safe}.wav")
        meta = gg.render_wav(pm, out_wav, sf2_path=SF2)

        loud = meta.get("measured_lufs_pre_norm")
        peak_lin = meta.get("peak_post_norm")
        dur = meta.get("duration_s", seconds)
        detail = []
        if loud is not None:
            detail.append(f"loudness {loud:.1f} LUFS")
        if peak_lin is not None:
            detail.append(f"peak {peak_lin:.2f}")
        notes.append(
            f"Rendered **{genre}** at **{tempo} BPM**, groove knob **{knob}**, "
            f"{dur:.0f}s" + (f" ({', '.join(detail)})." if detail else ".")
        )
        return out_wav, "\n\n".join(notes)

    except Exception as exc:  # noqa: BLE001
        return None, f"**Render failed:** {type(exc).__name__}: {exc}\n\n```\n{traceback.format_exc()}\n```"


# ----------------------------------------------------------------------------- #
# Reference content for the "About the parameters" tab
# ----------------------------------------------------------------------------- #
RECS_MD = """
## Recommended groove parameter values

These come from a quantitative review of the groove-perception literature (full citations
below). "Wanting to move" (WTM) and pleasure are the standard groove outcomes. The study
sweep uses **4 levels (L0–L3)** per knob.

| Parameter | Shape | Sweet spot | 4-level sweep | Evidence |
|---|---|---|---|---|
| **Syncopation** (the groove knob) | Inverted-U | **L2 — medium** (Witek index ≈ 26–34) | L0 none (S≈0–4) · L1 light (12–18) · **L2 sweet spot (26–34)** · L3 heavy (48–65) | Strong — Witek 2014 (R²=.35–.43); Sioros 2014 |
| **Tempo** | Inverted-U | **~100–126 BPM** (use 115–120) | 70 · 95 · **115** · 150 BPM | Strong — Etani 2018 (ηp²=.39) |
| **Event density** | Monotonic-positive (small) | **14–16 onsets/bar** | 4–6 · 8–10 · **14–16** · 20–24 | Moderate — Madison 2011; Senn 2018 (R²=.011) |
| **Microtiming** | Quantized ≈ natural ≫ exaggerated | **0–8 ms** (keep tight) | 0 · 5–8 · 12–18 · 30–40 ms | Strong that large MT hurts — Frühauf 2013; Davies 2013; Senn 2016 |
| **Swing (16th)** | Sweet spot | **60–63%** (1.5:1–1.7:1) | 50% · 55–57% · **60–63%** · 67% | Moderate — Friberg & Sundström 2002; Ziereis 2019 |

**Bottom line for maximizing groove:** medium syncopation (**knob = L2**), tempo **~115–120 BPM**,
density **14–16 hits/bar**, timing **tight (quantized)**, light-to-moderate swing (**~60%**).
The UI defaults (knob 2, 120 BPM) sit right in these sweet spots.
"""

DANCE_MD = """
## Which genres are most danceable in Sophia's dataset

Grouping the **704 unique stimulus tracks** by artist-genre tag and averaging Spotify
danceability (0–100):

| Rank | Genre | Mean danceability | n tracks |
|---|---|---|---|
| 1 | **Latin** | 72.9 | 9 |
| 2 | **Hip-hop / rap** | 67.2 | 90 |
| 3 | **R&B / soul** | 65.2 | 59 |
| 4 | Pop | 59.8 | 159 |
| 5 | Country | 57.7 | 45 |
| 6 | Rock | 55.3 | 163 |

**Latin, hip-hop/rap and R&B/soul lead.** The top individual tracks by danceability are
*Billie Jean* (93), *Break My Stride* (92) and *All I Ever Asked* (91) — which is why the
reworked **pop** style was modeled on that funky, syncopated, ~115–120 BPM dance-pop profile
rather than a buzzy synth lead.

*Note: genre tags are broad (the "pop" bucket sweeps k-pop, pop-rock, hyperpop, etc.), and
Latin's mean rests on a small n=9, so treat the exact ordering as indicative.*
"""

BED_MD = """
## Where the drum-beat bed comes from

The constant harmonic **bed** under the drums isn't arbitrary — it's parameterized to match the
feature profile of the songs participants picked for **sensory-motor (groove) appreciation**
that **also** scored in the top danceability tercile in Sophia's data (**n = 83 tracks**):

- **Tempo 120 BPM** (median of the subset), **4/4**, metronomic pulse.
- **Bass-forward** (median low-band energy ratio 0.70) — a prominent fingered-bass root pulse.
- **Prominent sustained harmony** (median harmonic ratio 0.70) — a real chord bed, not a thin pad.
- **Slight positive/major lean** (median valence 60) → a bright-but-cool **Dorian vamp** (Am7–D/A).
- **Low event rate** (onset density ~4.5) so the bed never competes with the drum manipulation.

> *"The constant harmonic bed was parameterized to match the central tendencies of tracks
> participants selected for sensory-motor appreciation and that scored in the top tercile of
> Spotify danceability (n = 83): a 4/4, 120-BPM, bass-forward Dorian vamp with prominent
> sustained harmony."* No commercial recordings were reproduced — only aggregate feature targets.
"""

REFS_MD = """
## References

**Groove parameters**
- Witek, Clarke, Wallentin, Kringelbach & Vuust (2014). Syncopation, body-movement and pleasure in groove music. *PLOS ONE* 9(4), e94446. https://doi.org/10.1371/journal.pone.0094446
- Sioros, Miron, Davies, Gouyon & Madison (2014). Syncopation creates the sensation of groove in synthesized music. *Frontiers in Psychology* 5, 1036. https://doi.org/10.3389/fpsyg.2014.01036
- Senn, Kilchenmann, Bechtold & Hoesl (2018). Groove in drum patterns as a function of rhythmic properties and listeners' attitudes. *PLOS ONE* 13(6), e0199604. https://doi.org/10.1371/journal.pone.0199604
- Etani, Marui, Kawase & Keller (2018). Optimal tempo for groove. *Frontiers in Psychology* 9, 462. https://doi.org/10.3389/fpsyg.2018.00462
- Janata, Tomic & Haberman (2012). Sensorimotor coupling in music and the psychology of the groove. *J. Exp. Psychol. General* 141(1), 54–75. https://doi.org/10.1037/a0024208
- Madison, Gouyon, Ullén & Hörnström (2011). Modeling the tendency for music to induce movement. *J. Exp. Psychol. HPP* 37(5), 1578–1594. https://doi.org/10.1037/a0024323
- Frühauf, Kopiez & Platz (2013). Music on the timing grid. *Musicae Scientiae* 17(2), 246–260. https://doi.org/10.1177/1029864913486793
- Davies, Madison, Silva & Gouyon (2013). The effect of microtiming deviations on the perception of groove. *Music Perception* 30(5), 497–510. https://doi.org/10.1525/MP.2013.30.5.497
- Senn, Kilchenmann, von Georgi & Bullerjahn (2016). The effect of expert performance microtiming on groove. *Frontiers in Psychology* 7, 1487. https://doi.org/10.3389/fpsyg.2016.01487
- Friberg & Sundström (2002). Swing ratios and ensemble timing in jazz performance. *Music Perception* 19(3), 333–349. https://doi.org/10.1525/MP.2002.19.3.333
- Ziereis, Datseris, Geisel, Albrecht, Priesemann & Hagmayer (2019). Microtiming deviations and swing feel in jazz. *Scientific Reports* 9, 19812. https://doi.org/10.1038/s41598-019-55981-3

**Bed / danceability source**
- Sophia dataset (CU Boulder Brain Music Lab), survey + Spotify audio features, N=122 participants / 704 unique tracks. Bed profile derived from the sensory-motor, top-danceability-tercile subset (n=83). See `sophia/BED_FEATURE_PROFILE.md` and `groove_knob_literature.md` in the project for the full review.
"""


# ----------------------------------------------------------------------------- #
# UI layout
# ----------------------------------------------------------------------------- #
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="GrooveGen", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            "# GrooveGen\n"
            "Generate groove-inducing songs across six genres. Pick a genre, set the "
            "tempo and the **groove knob** (syncopation), then render and play."
        )

        gpu_txt = "✅ GPU detected — AMT transformer available." if GPU else \
                  "ℹ️ No GPU — running engine-only (AMT toggle will fall back)."
        sf2_txt = f"Soundfont: `{os.path.basename(SF2)}`" if SF2_OK else \
                  "⚠️ No soundfont found — install FluidSynth + a GM soundfont to render."
        gr.Markdown(f"{gpu_txt}  \n{sf2_txt}")

        with gr.Tabs():
            with gr.Tab("Generate"):
                with gr.Row():
                    with gr.Column(scale=1):
                        genre = gr.Dropdown(GENRES, value=DEFAULT_GENRE, label="Genre")
                        tempo = gr.Slider(60, 200, value=120, step=1, label="Tempo (BPM)")
                        knob = gr.Slider(0, 4, value=2, step=1,
                                         label="Groove knob (syncopation level)")
                        density = gr.Slider(2, 16, value=8, step=1,
                                            label="Event density (onsets per bar)")
                        with gr.Accordion("Advanced", open=False):
                            bars = gr.Slider(1, 4, value=2, step=1, label="Seed bars")
                            seconds = gr.Slider(8, 60, value=16, step=1, label="Length (seconds)")
                            seed = gr.Number(value=7, precision=0, label="Random seed")
                            use_amt = gr.Checkbox(
                                value=False,
                                label="Use AMT transformer (needs GPU; falls back to engine)",
                            )
                        go = gr.Button("Generate", variant="primary")

                    with gr.Column(scale=1):
                        audio = gr.Audio(label="Result", type="filepath", interactive=False)
                        status = gr.Markdown()

                go.click(
                    render,
                    inputs=[genre, tempo, knob, density, bars, seconds, seed, use_amt],
                    outputs=[audio, status],
                )

                gr.Markdown(
                    "**Tip:** the *groove knob* drives syncopation — turn it up for a more "
                    "off-beat, danceable feel. *Genre* sets the instruments, chords and comp "
                    "style (e.g. pop = funky clavinet, classic-rock = palm-muted power chords)."
                )

            with gr.Tab("About the parameters"):
                gr.Markdown(RECS_MD)
                gr.Image(str(FIG_CURVES), label="Groove vs. parameter level",
                         show_label=False, interactive=False)
                gr.Markdown(DANCE_MD)
                gr.Image(str(FIG_DANCE), label="Danceability by genre",
                         show_label=False, interactive=False)
                gr.Markdown(BED_MD)
                gr.Markdown(REFS_MD)
    return demo


def main():
    parser = argparse.ArgumentParser(description="GrooveGen web UI")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address. Use 0.0.0.0 to reach it from other devices (e.g. on a Pi).")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true",
                        help="Create a temporary public Gradio link (handy on Colab).")
    args = parser.parse_args()

    demo = build_ui()
    demo.launch(server_name=args.host, server_port=args.port, share=args.share)


if __name__ == "__main__":
    main()

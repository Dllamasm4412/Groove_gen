"""
GrooveGen — Closed-Loop Experiment / Simulation UI (Gradio)
===========================================================

Drive the GrooveGen CascadeController from a heart-rate signal and watch the
three-tier cascade (GENRE -> TEMPO -> DENSITY) respond, bar by bar.

TODAY:  type a heart rate value -> step the controller -> see genre/tempo/density.
LATER:  flip the source to ESP32 + DigiRobot PPG over serial. The UI does NOT
        change — see groovegen/hr_source.py (SerialHRSource). Same interface.

Run:
    python app_experiment.py                 # http://127.0.0.1:7861
    python app_experiment.py --host 0.0.0.0  # open from LAN / another device
    (Colab: launch=... share=True is set automatically when no display)

Concept:
    * You set a TARGET (setpoint) — the arousal you want to steer the listener
      toward, expressed as a target heart rate (e.g. "calm them to 70 BPM").
    * You feed the CURRENT measured heart rate (typed now, PPG later).
    * Both are mapped BPM -> arousal (0..1) with a per-subject resting/max range.
    * The controller steps one bar and reports which tier acted and the new
      genre / tempo / density. The trace + plot accumulate across the session.

Honest scope: this is the CONTROL loop + a simulator. It is NOT an efficacy
claim. Heart rate here is an input signal the controller TRACKS; the plant
(how music would move real HR) is not modeled in this UI.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import gradio as gr

# --- import the real controller + HR source (never reimplement the controller) ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groovegen.pd_controller import CascadeController  # noqa: E402
from groovegen.hr_source import (  # noqa: E402
    TextInputHRSource, HRArousalMapper,
)

# genre-from-tempo band derivation (matches nb15 exactly)
def genre_from_tempo(bpm: float) -> str:
    if bpm >= 112:
        return "latin"
    if bpm >= 98:
        return "pop"
    if bpm >= 84:
        return "r&b"
    return "calm (sparse low-tempo R&B/soul)"


# --- dark theme to match the project's plots ---
BG, FG, MUT = "#171614", "#CDCCCA", "#797876"
ACCENT, TEAL, GREEN = "#4F98A3", "#20808D", "#6DAA45"
WARN, GOLD, RESTLINE = "#BB653B", "#FFC553", "#BCE2E7"
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": FG, "axes.labelcolor": FG, "xtick.color": MUT,
    "ytick.color": MUT, "axes.edgecolor": MUT, "font.family": "DejaVu Sans",
})

TIER_COLOR = {"none": MUT, "density": GREEN, "tempo": GOLD, "genre": WARN}


class ExperimentSession:
    """Holds one live controller + HR mapper + the accumulating trace."""

    def __init__(self):
        self.source = TextInputHRSource(initial_bpm=70.0)
        self.mapper = HRArousalMapper(resting_hr=60.0, max_hr=120.0)
        self.controller = None
        self.trace = []  # list of dict rows
        self.reset(resting_hr=60.0, max_hr=120.0)

    def reset(self, resting_hr, max_hr, start_genre_idx=0, start_tempo=125.0):
        self.mapper.set_range(resting_hr, max_hr)
        self.controller = CascadeController(
            band=0.06, max_step_bpm=15.0, tempo_min=70.0, tempo_max=140.0,
            density_min=3, density_max=8,  # nb15 tuning: cap 8, floor 3
        )
        # nb15 tuning: deadband + big deliberate jumps live in the controller;
        # commit interval is enforced by the saturation gates.
        self.controller.reset(initial_genre_idx=start_genre_idx,
                              initial_tempo=start_tempo)
        # prime committed tempo so the first bar has a value
        self.controller._committed_next_tempo = start_tempo
        self.trace = []
        return self._empty_outputs()

    def _empty_outputs(self):
        return ("—", "—", "—", "—", pd.DataFrame(
            columns=["bar", "target_hr", "measured_hr", "setpoint", "measurement",
                     "tier_acted", "genre", "tempo_bpm", "density"]), self._plot())

    def step(self, target_hr, measured_hr):
        """One bar: map both HRs to arousal, step controller, log."""
        self.source.push(measured_hr)
        setpoint = self.mapper.to_arousal(target_hr)      # where we want them
        measurement = self.mapper.to_arousal(measured_hr)  # where they are
        out = self.controller.step(setpoint=setpoint, measurement=measurement)
        # genre shown is the tempo-band derivation (matches nb15 hero artifact)
        disp_genre = genre_from_tempo(out["tempo_bpm"])
        row = {
            "bar": len(self.trace) + 1,
            "target_hr": round(float(target_hr), 1),
            "measured_hr": round(float(measured_hr), 1),
            "setpoint": round(setpoint, 3),
            "measurement": round(measurement, 3),
            "tier_acted": out["tier_that_acted"],
            "genre": disp_genre,
            "tempo_bpm": round(float(out["tempo_bpm"]), 1),
            "density": int(out["density"]),
        }
        self.trace.append(row)
        df = pd.DataFrame(self.trace)
        return (
            disp_genre,
            f'{row["tempo_bpm"]:.0f} BPM',
            str(row["density"]),
            row["tier_acted"],
            df,
            self._plot(),
        )

    def _plot(self):
        plt.close("all")  # avoid figure accumulation across steps
        fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
        fig.patch.set_facecolor(BG)
        if not self.trace:
            for ax in axes:
                ax.text(0.5, 0.5, "no data yet — step the controller",
                        ha="center", va="center", color=MUT, transform=ax.transAxes)
                ax.set_facecolor(BG)
            fig.tight_layout()
            return fig
        df = pd.DataFrame(self.trace)
        bars = df["bar"]
        # panel 1: heart rate (measured vs target)
        ax = axes[0]
        ax.plot(bars, df["measured_hr"], color=ACCENT, lw=2, marker="o", ms=3,
                label="measured HR")
        ax.plot(bars, df["target_hr"], color=RESTLINE, lw=1.5, ls="--",
                label="target HR (setpoint)")
        ax.set_ylabel("HR (BPM)")
        ax.legend(loc="upper right", facecolor=BG, edgecolor=MUT, labelcolor=FG,
                  fontsize=8)
        ax.set_title("Closed-loop experiment trace", color=FG, loc="left",
                     fontweight="bold")
        # panel 2: tempo, colored by tier that acted
        ax = axes[1]
        ax.plot(bars, df["tempo_bpm"], color=GOLD, lw=2, marker="o", ms=3)
        for _, r in df.iterrows():
            ax.scatter(r["bar"], r["tempo_bpm"],
                       color=TIER_COLOR.get(r["tier_acted"], MUT), s=28, zorder=3)
        ax.set_ylabel("tempo (BPM)")
        # panel 3: density
        ax = axes[2]
        ax.step(bars, df["density"], color=GREEN, lw=2, where="mid")
        ax.set_ylabel("density")
        ax.set_xlabel("bar")
        for ax in axes:
            ax.grid(True, alpha=0.15)
        fig.tight_layout()
        return fig

    def export_csv(self):
        if not self.trace:
            return None
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "experiment_trace.csv")
        pd.DataFrame(self.trace).to_csv(path, index=False)
        return path

    def render_audio(self, library_dir="library"):
        """Render the CURRENT session trace to a WAV using the curated library
        beds (pick_nearest_bed -> retime -> per-bar drum overlay -> splice),
        reusing nb15's exact render machinery via groovegen.session_render.

        Returns (audio_path_or_None, status_markdown). Not real-time: this is a
        batch render of the arc the operator just drove. Honest scope: it is the
        audio the control loop produced, NOT an efficacy claim.
        """
        if not self.trace:
            return None, "**No trace yet.** Step the controller a few bars first, then render."
        # session_render pulls in soundfile/librosa/pretty_midi/fluidsynth; import
        # lazily so the UI still launches even if audio deps are missing, and the
        # user sees a clear message instead of a launch-time crash.
        try:
            from groovegen.session_render import render_session
        except Exception as e:  # pragma: no cover
            return None, (f"**Audio deps unavailable:** `{type(e).__name__}: {e}`. "
                          "Run the setup cell (0.2) so fluidsynth + soundfile are installed.")
        out_wav = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "experiment_session_render.wav")
        logs = []
        try:
            result = render_session(list(self.trace), out_wav,
                                    library_dir=library_dir, log=logs.append)
        except Exception as e:
            log_tail = "\n".join(logs[-8:])
            return None, (f"**Render failed:** `{type(e).__name__}: {e}`\n\n"
                          f"```\n{log_tail}\n```")
        status = "```\n" + "\n".join(logs) + "\n```"
        if result is None:
            return None, ("**Nothing rendered.** " + status +
                          "\n\n_Most likely the bed library isn't present in this "
                          "runtime. Restore it (0.1b) or build it (LIB_build_beds)._")
        return result, status


def build_ui():
    session = ExperimentSession()

    with gr.Blocks(title="GrooveGen — Closed-Loop Experiment",
                   theme=gr.themes.Base()) as demo:
        gr.Markdown(
            "# GrooveGen — Closed-Loop Experiment / Simulation\n"
            "Type a **target heart rate** (where you want to steer the listener) "
            "and the **measured heart rate** (typed now; ESP32 + PPG later). "
            "Each **Step** runs one bar of the GENRE→TEMPO→DENSITY cascade."
        )

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### Subject calibration")
                resting = gr.Number(value=60, label="Resting HR (arousal 0)")
                maxhr = gr.Number(value=120, label="Max / target-ceiling HR (arousal 1)")
                start_tempo = gr.Slider(70, 140, value=125, step=1,
                                        label="Start tempo (BPM)")
                reset_btn = gr.Button("Reset session", variant="secondary")

                gr.Markdown("### Live input")
                target_hr = gr.Slider(40, 180, value=70, step=1,
                                      label="Target HR (setpoint)")
                measured_hr = gr.Slider(40, 180, value=125, step=1,
                                        label="Measured HR (now: manual)")
                step_btn = gr.Button("▶ Step one bar", variant="primary")

                gr.Markdown(
                    "_Source: **manual (text input)**. To use ESP32 + PPG later, "
                    "swap in `SerialHRSource` — the UI is unchanged._"
                )
                export_btn = gr.Button("Export trace CSV", variant="secondary")
                csv_file = gr.File(label="trace.csv")

            with gr.Column(scale=2):
                with gr.Row():
                    genre_box = gr.Textbox(label="Genre (tempo-band)", value="—",
                                           interactive=False)
                    tempo_box = gr.Textbox(label="Tempo", value="—",
                                           interactive=False)
                    density_box = gr.Textbox(label="Density", value="—",
                                             interactive=False)
                    tier_box = gr.Textbox(label="Tier that acted", value="—",
                                          interactive=False)
                plot = gr.Plot(label="Trace")
                table = gr.Dataframe(label="Bar-by-bar trace", wrap=True,
                                     interactive=False)

                gr.Markdown(
                    "### Hear it\n"
                    "Render the arc you just drove to audio (curated library "
                    "beds, retimed + per-bar drums, spliced on downbeats). "
                    "**Not real-time** — it batch-renders the recorded trace "
                    "(~15-30s). This is the audio the control loop produced, "
                    "not an efficacy claim."
                )
                render_btn = gr.Button("Render current session to audio",
                                       variant="primary")
                auto_render = gr.Checkbox(
                    value=False,
                    label="Auto-render after every step",
                    info="Re-renders the whole trace each time you step a bar "
                         "(~15-30s per step). Convenient, but every step waits "
                         "on a full render — uncheck for fast stepping.",
                )
                audio_out = gr.Audio(label="Session render", type="filepath",
                                     interactive=False, autoplay=False)
                render_status = gr.Markdown("")

        # --- wiring ---
        def do_reset(r, m, st):
            return session.reset(r, m, start_tempo=st)

        reset_btn.click(do_reset, [resting, maxhr, start_tempo],
                        [genre_box, tempo_box, density_box, tier_box, table, plot])

        def do_step(t, m):
            return session.step(t, m)

        step_evt = step_btn.click(
            do_step, [target_hr, measured_hr],
            [genre_box, tempo_box, density_box, tier_box, table, plot])

        export_btn.click(lambda: session.export_csv(), None, csv_file)

        def do_render():
            path, status = session.render_audio()
            return path, status

        render_btn.click(do_render, None, [audio_out, render_status])

        # Auto-render: after a step completes, if the toggle is on, render the
        # growing trace. Chained via .then() so it runs AFTER do_step updates
        # the trace. When the toggle is off we return gr.update() (no-op) so the
        # existing audio/status are left untouched and stepping stays fast.
        def maybe_auto_render(auto_on):
            if not auto_on:
                return gr.update(), gr.update()
            path, status = session.render_audio()
            return path, status

        step_evt.then(maybe_auto_render, [auto_render], [audio_out, render_status])

        # When the user turns the toggle ON, render immediately so they don't
        # have to take an extra step to hear where they already are.
        def on_toggle(auto_on):
            if not auto_on:
                return gr.update(), gr.update()
            path, status = session.render_audio()
            return path, status

        auto_render.change(on_toggle, [auto_render], [audio_out, render_status])

    return demo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--share", action="store_true",
                    help="public share link (auto-on in Colab)")
    args = ap.parse_args()
    in_colab = "google.colab" in sys.modules or os.environ.get("COLAB_GPU")
    demo = build_ui()
    demo.launch(server_name=args.host, server_port=args.port,
                share=args.share or bool(in_colab))


if __name__ == "__main__":
    main()

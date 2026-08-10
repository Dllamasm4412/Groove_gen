"""Builder for the Part A notebook: Setup (Part 0) + Experiment UI (Part A)."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []

def md(t): cells.append(nbf.v4.new_markdown_cell(t))
def code(t): cells.append(nbf.v4.new_code_cell(t))

md("""# GrooveGen — Part A: Setup + Experiment UI

This one notebook does **Part 0 (setup)** and **Part A (the experiment UI)** together, so you
can calibrate a subject, type a target/measured heart rate, and step the closed-loop
cascade controller bar-by-bar — all inside Colab.

**Requires:** GPU runtime is *not* needed for this notebook (UI + controller are CPU-only).
A CPU runtime is fine and faster to start. (You only need the GPU for Part B bed generation.)

Run the cells top to bottom.""")

md("""## Part 0 — Setup

### 0.1 Get the code into Colab
Just run this cell. If it can't find `groovegen_code_only.zip`, it opens an **upload
widget right here** -- pick the zip from your computer and it unzips automatically. No
need to use Colab's side file panel.""")

code("""import os, sys, glob, zipfile

def _already_setup():
    return os.path.isdir("groovegen") or (
        os.path.isdir("groovegen_project")
        and os.path.isdir(os.path.join("groovegen_project", "groovegen")))

def _find_zip():
    cands = []
    for d in (".", "/content", os.path.expanduser("~")):
        cands += glob.glob(os.path.join(d, "groovegen_code_only*.zip"))
        cands += glob.glob(os.path.join(d, "groovegen_project*.zip"))
    cands = [c for c in dict.fromkeys(cands) if os.path.exists(c)]
    cands.sort(key=os.path.getmtime, reverse=True)
    return cands[0] if cands else None

if not _already_setup():
    zip_path = _find_zip()
    if zip_path is None:
        try:
            from google.colab import files
            print("Select groovegen_code_only.zip from your computer ...")
            up = files.upload()   # opens a Choose Files button in the output
            zip_path = next((k for k in up if k.lower().endswith(".zip")), None)
            assert zip_path, "No .zip was chosen. Re-run this cell and pick the zip."
        except ImportError:
            raise FileNotFoundError(
                "groovegen_code_only.zip not found and not in Colab. "
                "Put the zip next to this notebook and re-run.")
    print("unzipping:", zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(".")

if os.path.isdir("groovegen_project") and not os.path.isdir("groovegen"):
    os.chdir("groovegen_project")

sys.path.insert(0, os.getcwd())
print("cwd:", os.getcwd())
print("has groovegen pkg:", os.path.isdir("groovegen"))
print("has app_experiment.py:", os.path.exists("app_experiment.py"))
assert os.path.isdir("groovegen"), \\
    "Still no groovegen/ package -- the wrong zip may have been uploaded."
print("setup OK")""")

md("""### 0.2 Install dependencies

The UI needs only a light subset (gradio + the controller's numpy/pandas/matplotlib).
The heavy audio/ML stack (madmom, transformers, fluidsynth) is **only** needed for
Part B/C, so we skip it here to keep this notebook fast to start.

If you plan to run Part B/C in this *same* runtime later, run the full install from
`COLAB_RUNBOOK.md` Cell 0.2 instead.""")

code("""import sys, os
os.system(f"{sys.executable} -m pip install -q gradio pandas numpy matplotlib")
print("UI deps installed")""")

md("""## Part A — Experiment UI

This imports the **real** UI (`app_experiment.build_ui()`) — the same one you'd get from
`python app_experiment.py`, but rendered **inline** in the notebook. Nothing is
reimplemented; `build_ui()` returns the Gradio app and we just launch it here.

**How to use it once it appears:**
1. **Subject calibration** — enter resting HR and max HR (maps BPM → arousal 0..1).
2. **Target HR** (setpoint you want to steer toward) and **Measured HR** (what the sensor reads; typed for now).
3. **Step one bar** — the cascade controller acts and reports genre / tempo / density and which tier moved.
4. The **trace table + plot** accumulate across the session; **Export CSV** saves the run.

Heart rate here is an input the controller **tracks** — this is the control loop + simulator,
not an efficacy claim.""")

code('''from app_experiment import build_ui

demo = build_ui()

# inline=True renders the UI inside this cell's output.
# share=True also gives a public gradio.live link (handy if inline is cramped).
demo.launch(inline=True, share=True, quiet=True)''')

md("""### Stopping / restarting the UI
The launch cell keeps running while the UI is live. To stop it, interrupt the cell
(the ■ stop button). To restart, just re-run the launch cell above.

### Later: real sensor instead of typed HR
When the ESP32 + DigiRobot PPG is ready, the UI does **not** change — only the HR
*source* does. In `groovegen/hr_source.py`, `SerialHRSource(port="/dev/ttyUSB0", baudrate=115200)`
reads one BPM float per line (`Serial.println(bpm);` in firmware) and exposes the same
interface as the manual `TextInputHRSource`.

### What's next
- **Part B** (generate personalized beds from your 12 songs) needs a **GPU** runtime — see
  `COLAB_RUNBOOK.md` Part B, or run it in a separate GPU notebook.
- **Part C** is `notebooks/15_closed_loop_hr_audio.ipynb`, which consumes the cached beds.""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
out = "notebooks/A_setup_and_experiment_ui.ipynb"
with open(out, "w") as f:
    nbf.write(nb, f)
print("wrote", out, "with", len(cells), "cells")

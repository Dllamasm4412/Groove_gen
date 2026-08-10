"""Assemble GrooveGen handoff zips.

Two archives:
  1. groovegen_full_handoff.zip  — EVERYTHING needed to continue the project:
        - groovegen_pilot/  (active closed-loop code + the 4 handoff docs)
        - groovegen_project/ (v1 pipeline, controller, notebooks, data, sophia)
        - root .py modules + all decision/finding/spec/research .md docs
        - all council_*.md responses + briefs
        - requirements + README + how-to-run
     EXCLUDES only regenerable bulk (grid stimulus wavs, large session wavs) and caches.
  2. groovegen_pilot_and_docs.zip — the lean "start here" archive:
        groovegen_pilot/ (code + docs) + the controller it depends on + requirements.
"""
import os, zipfile, fnmatch

ROOT = "/Users/daniel/Desktop/PhD/groove_gen_project"

# Patterns to always skip (regenerable bulk / caches / os cruft)
SKIP_GLOBS = [
    "*/__pycache__/*", "*.pyc", "*/.ipynb_checkpoints/*", "*/.DS_Store",
    # regenerable bulk audio (stimulus grid + large intermediate session renders)
    "*/outputs/audio/grid/*.wav",
    "*/groovegen_pilot/sessions/*.wav",
    "*/groovegen_pilot/renderer_selfcheck.wav",
    "*/groovegen_pilot/phase1_renderer_demo.wav",   # keep the .mp4, drop the raw wav
]

def skip(path):
    rel = path
    return any(fnmatch.fnmatch(rel, g) for g in SKIP_GLOBS)

def add_tree(zf, abs_dir, arc_prefix):
    for dirpath, dirnames, filenames in os.walk(abs_dir):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".ipynb_checkpoints")]
        for fn in filenames:
            ap = os.path.join(dirpath, fn)
            if skip(ap):
                continue
            rel = os.path.relpath(ap, ROOT)
            zf.write(ap, os.path.join(arc_prefix, rel))

def add_file(zf, abs_path, arc_prefix):
    if os.path.exists(abs_path) and not skip(abs_path):
        rel = os.path.relpath(abs_path, ROOT)
        zf.write(abs_path, os.path.join(arc_prefix, rel))

# ---- root-level files to include in the FULL zip ----
root_py = [f for f in os.listdir(ROOT) if f.endswith(".py")]
root_md = [f for f in os.listdir(ROOT) if f.endswith(".md")]
root_misc = ["README.md", "HOW_TO_RUN.md"]  # already .md, harmless dup-guard

# ================= FULL HANDOFF ZIP =================
full = os.path.join(ROOT, "groovegen_full_handoff.zip")
with zipfile.ZipFile(full, "w", zipfile.ZIP_DEFLATED) as zf:
    add_tree(zf, os.path.join(ROOT, "groovegen_pilot"), "GrooveGen")
    add_tree(zf, os.path.join(ROOT, "groovegen_project"), "GrooveGen")
    for f in sorted(set(root_py + root_md)):
        add_file(zf, os.path.join(ROOT, f), "GrooveGen")

# ================= LEAN PILOT + DOCS ZIP =================
lean = os.path.join(ROOT, "groovegen_pilot_and_docs.zip")
with zipfile.ZipFile(lean, "w", zipfile.ZIP_DEFLATED) as zf:
    add_tree(zf, os.path.join(ROOT, "groovegen_pilot"), "GrooveGen_pilot")
    # the controller + its module deps the pilot imports from groovegen_project
    for dep in [
        "groovegen_project/groovegen/pd_controller.py",
        "groovegen_project/groovegen/hr_source.py",
        "groovegen_project/groovegen/__init__.py",
        "groovegen_project/requirements.txt",
    ]:
        add_file(zf, os.path.join(ROOT, dep), "GrooveGen_pilot")
    # the root modules the pilot imports directly
    for dep in [
        "symbolic_bed_proto.py", "symbolic_from_profile.py", "symbolic_tiers_demo.py",
    ]:
        add_file(zf, os.path.join(ROOT, dep), "GrooveGen_pilot")

for p in (full, lean):
    print(f"{p}  {os.path.getsize(p)/1e6:.1f} MB")

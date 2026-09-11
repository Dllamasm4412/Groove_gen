from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import datetime
from itertools import combinations
from pathlib import Path

import streamlit as st
from scoring import compute_all

FAMILIES = ["calm", "lofi", "latin", "rock", "hiphop", "pop", "rnb"]
RENDERS_DIR = Path(__file__).parent.parent / "renders" / "frozen_v2"
PROFILES_DIR = Path(__file__).parent.parent / "profiles"
CHECKPOINTS_DIR = Path(__file__).parent.parent / "profiles" / "checkpoints"
GATE_VERSION = "2.0.0"


def iso_now() -> str:
    """Return timezone-aware ISO-8601 timestamp for profile logging."""
    return datetime.now().astimezone().isoformat()


def valid_participant_id(value: str) -> bool:
    """Validate participant IDs: 2-32 chars, alnum + underscore + hyphen."""
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{2,32}", value))


def load_render_paths() -> dict[str, Path]:
    """Build expected frozen tier-3 render paths per family."""
    return {family: RENDERS_DIR / f"{family}_t3.wav" for family in FAMILIES}


def fail_if_assets_missing(paths: dict[str, Path]) -> None:
    """Stop app with a clear error if any required render files are missing."""
    missing = [path for path in paths.values() if not path.exists()]
    if not missing:
        return

    lines = [str(path) for path in missing]
    st.error(
        "Missing frozen renders required for the personalization gate.\n\n"
        + "Expected files:\n"
        + "\n".join(lines)
        + "\n\nRun `python freeze_library.py --out renders/frozen` before starting this widget."
    )
    st.stop()


def find_checkpoint(participant_id: str) -> Path | None:
    """Return the most recent checkpoint file for this participant, or None."""
    if not CHECKPOINTS_DIR.exists():
        return None
    candidates = sorted(CHECKPOINTS_DIR.glob(f"{participant_id}_*_checkpoint.json"))
    return candidates[-1] if candidates else None


def load_checkpoint(path: Path) -> dict:
    """Load checkpoint JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def restore_from_checkpoint(cp: dict) -> None:
    """Restore session_state from a checkpoint dict."""
    st.session_state.session_start = cp["session_start"]
    st.session_state.vetoes = cp["vetoes"]
    st.session_state.comparisons = cp["comparisons"]
    st.session_state.pair_order = cp["pair_order"]
    st.session_state.current_pair_idx = cp["current_pair_idx"]
    st.session_state.stage = cp["stage"]


def save_checkpoint() -> None:
    """Persist current pairwise/veto/session state to disk for resume."""
    if "participant_id" not in st.session_state:
        return
    participant_id = st.session_state.participant_id
    session_start = st.session_state.session_start
    ts_slug = (
        session_start.replace(":", "").replace(".", "").replace("-", "").replace("+", "_")[:15]
    )
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    cp_path = CHECKPOINTS_DIR / f"{participant_id}_{ts_slug}_checkpoint.json"
    cp = {
        "participant_id": participant_id,
        "session_start": session_start,
        "gate_version": GATE_VERSION,
        "stage": st.session_state.stage,
        "vetoes": list(st.session_state.get("vetoes", [])),
        "pair_order": list(st.session_state.get("pair_order", [])),
        "current_pair_idx": st.session_state.get("current_pair_idx", 0),
        "comparisons": list(st.session_state.get("comparisons", [])),
    }
    cp_path.write_text(json.dumps(cp, indent=2), encoding="utf-8")


def delete_checkpoint() -> None:
    """Remove checkpoint file for current participant (called on save/redo)."""
    if "participant_id" not in st.session_state:
        return
    if not CHECKPOINTS_DIR.exists():
        return
    for cp in CHECKPOINTS_DIR.glob(f"{st.session_state.participant_id}_*_checkpoint.json"):
        cp.unlink(missing_ok=True)


def ensure_pairwise_initialized() -> None:
    """Create reproducible pair ordering among non-vetoed families."""
    if "pair_order" in st.session_state:
        return

    participant_id = st.session_state.get("participant_id", "")
    seed = int(hashlib.sha256(participant_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    vetoes = set(st.session_state.get("vetoes", []))
    surviving = [f for f in FAMILIES if f not in vetoes]
    pairs = list(combinations(surviving, 2))
    rng.shuffle(pairs)

    pair_order: list[dict] = []
    for idx, (left, right) in enumerate(pairs):
        if rng.random() < 0.5:
            fam_a, fam_b = left, right
        else:
            fam_a, fam_b = right, left
        pair_order.append({"index": idx, "family_a": fam_a, "family_b": fam_b})

    st.session_state.pair_order = pair_order
    st.session_state.comparisons = []
    st.session_state.current_pair_idx = 0


def reset_for_redo() -> None:
    """Reset pairwise/veto/result state while preserving participant/session header."""
    delete_checkpoint()
    for key in [
        "pair_order",
        "comparisons",
        "current_pair_idx",
        "vetoes",
        "latest_result",
        "profile_path",
        "profile_json",
        "resume_checkpoint_path",
        "resume_checkpoint_data",
    ]:
        if key in st.session_state:
            del st.session_state[key]

    for family in FAMILIES:
        cb_key = f"veto_{family}"
        if cb_key in st.session_state:
            del st.session_state[cb_key]

    st.session_state.stage = "veto"


def save_profile(result: dict) -> tuple[Path, dict]:
    """Write participant gate profile JSON and return file path + object."""
    participant_id = st.session_state.participant_id
    session_start = st.session_state.session_start
    session_end = iso_now()

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = PROFILES_DIR / f"{participant_id}_{timestamp}.json"

    vetoes = list(st.session_state.get("vetoes", []))
    comparisons = list(st.session_state.get("comparisons", []))
    pair_order = list(st.session_state.get("pair_order", []))

    profile = {
        "participant_id": participant_id,
        "session_start": session_start,
        "session_end": session_end,
        "gate_version": GATE_VERSION,
        "families": list(FAMILIES),
        "raw_comparisons": comparisons,
        "vetoes": vetoes,
        "bt_scores": result["bt_scores"],
        "rank_order": result["rank_order"],
        "admissible_families": result["admissible_families"],
        "primary_family_block_a": result["primary_family_block_a"],
        "primary_family_block_b": result["primary_family_block_b"],
        "confidence": result["confidence"],
        "warning": result["warning"],
        "n_families_available": len(FAMILIES),
        "n_families_vetoed": len(vetoes),
        "n_families_surviving": len(FAMILIES) - len(vetoes),
        "n_pairs_compared": len(comparisons),
        "pair_order": pair_order,
    }

    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    delete_checkpoint()
    return profile_path, profile


def confidence_label(confidence: float) -> str:
    """Map confidence scalar to plain-English interpretation."""
    if confidence > 0.7:
        return "decisive"
    if confidence >= 0.4:
        return "clear"
    return "weak"


def main() -> None:
    """Run the Streamlit gate UI."""
    st.set_page_config(page_title="GrooveGen pre-session gate", layout="wide")

    render_paths = load_render_paths()
    fail_if_assets_missing(render_paths)

    if "stage" not in st.session_state:
        st.session_state.stage = "consent"

    stage = st.session_state.stage

    if stage == "consent":
        st.title("GrooveGen — pre-session music preference")
        pid_value_raw = st.text_input(
            "Participant ID", value=st.session_state.get("participant_id", "")
        )
        if st.button("Begin"):
            pid_value = pid_value_raw.strip() if isinstance(pid_value_raw, str) else ""
            if not valid_participant_id(pid_value):
                st.error("Participant ID must be 2-32 chars and use only A-Z, a-z, 0-9, _ or -.")
            else:
                st.session_state.participant_id = pid_value
                st.session_state.session_start = iso_now()
                st.session_state.stage = "resume_check"
                st.rerun()
        return

    if stage == "resume_check":
        participant_id = st.session_state.get("participant_id", "")
        cp_path = find_checkpoint(participant_id)
        if cp_path is None:
            st.session_state.stage = "instructions"
            st.rerun()

        cp = load_checkpoint(cp_path)
        st.session_state.resume_checkpoint_path = str(cp_path)
        st.session_state.resume_checkpoint_data = cp

        veto_count = len(cp.get("vetoes", []))
        pair_order = cp.get("pair_order", [])
        done_pairs = int(cp.get("current_pair_idx", 0))
        total_pairs = len(pair_order)

        st.title("Resume prior gate session")
        st.write(f"Resume in-progress session from {cp.get('session_start', '(unknown)')}?")
        st.write(f"{veto_count} vetoes recorded, {done_pairs} of {total_pairs} pairs completed.")

        resume_col, restart_col = st.columns(2)
        with resume_col:
            if st.button("Resume"):
                restore_from_checkpoint(cp)
                st.rerun()
        with restart_col:
            if st.button("Start over"):
                Path(cp_path).unlink(missing_ok=True)
                for key in [
                    "pair_order",
                    "comparisons",
                    "current_pair_idx",
                    "vetoes",
                    "latest_result",
                    "profile_path",
                    "profile_json",
                    "resume_checkpoint_path",
                    "resume_checkpoint_data",
                ]:
                    if key in st.session_state:
                        del st.session_state[key]
                for family in FAMILIES:
                    cb_key = f"veto_{family}"
                    if cb_key in st.session_state:
                        del st.session_state[cb_key]
                st.session_state.stage = "instructions"
                st.rerun()
        return

    if stage == "instructions":
        st.title("GrooveGen — pre-session music preference")
        st.write(
            "You will hear pairs of ~15-second music clips across 7 style families: "
            "calm, lofi, latin, rock, hiphop, pop, rnb."
        )
        st.write(
            "First, you'll preview each style and mark any you do NOT want to hear "
            "during your session. Then you'll hear pairs from the remaining styles "
            "and choose which you'd prefer."
        )
        st.write(
            "Total time depends on how many styles you veto:\n"
            "- Veto none: 21 pairs, ~15 min\n"
            "- Veto 2: 10 pairs, ~8 min\n"
            "- Veto 4: 3 pairs, ~2 min\n\n"
            "Your progress is saved after every answer — you can quit and resume."
        )
        if st.button("I understand — begin listening"):
            st.session_state.stage = "veto"
            st.rerun()
        return

    if stage == "veto":
        st.header("Any styles you do not want at all?")
        st.write(
            "Check any style you do NOT want played during your session. It's OK to check none."
        )

        for family in FAMILIES:
            st.subheader(family)
            st.audio(str(render_paths[family]), format="audio/wav", start_time=0, end_time=10)
            st.checkbox(
                "Do not play this style during my session",
                key=f"veto_{family}",
            )

        n_surviving = len([f for f in FAMILIES if not st.session_state.get(f"veto_{f}", False)])
        n_pairs = n_surviving * (n_surviving - 1) // 2
        minutes_est = max(1, round(n_pairs * 0.75))
        st.write(
            f"With current vetoes: {n_surviving} families remain, {n_pairs} pairs, ~{minutes_est} min."
        )

        if n_surviving < 2:
            st.error("You must leave at least 2 families un-vetoed to complete the gate.")

        if st.button("Continue", disabled=n_surviving < 2):
            st.session_state.vetoes = [
                family for family in FAMILIES if st.session_state.get(f"veto_{family}", False)
            ]
            for key in ["pair_order", "comparisons", "current_pair_idx"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.session_state.stage = "pairwise"
            save_checkpoint()
            st.rerun()
        return

    if stage == "pairwise":
        ensure_pairwise_initialized()

        pair_order = st.session_state.pair_order
        current_idx = st.session_state.current_pair_idx

        if len(pair_order) == 0:
            st.error("At least two non-vetoed families are required. Returning to veto selection.")
            st.session_state.stage = "veto"
            st.rerun()

        if current_idx >= len(pair_order):
            st.session_state.stage = "confirm"
            st.rerun()

        current = pair_order[current_idx]
        fam_a = current["family_a"]
        fam_b = current["family_b"]
        pair_index = current["index"]

        st.header(f"Pair {current_idx + 1} of {len(pair_order)}")
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Clip A")
            st.audio(str(render_paths[fam_a]), format="audio/wav")
        with col_b:
            st.subheader("Clip B")
            st.audio(str(render_paths[fam_b]), format="audio/wav")

        btn_a_col, btn_b_col = st.columns(2)
        with btn_a_col:
            prefer_a = st.button("I prefer Clip A", key=f"prefer_a_{current_idx}")
        with btn_b_col:
            prefer_b = st.button("I prefer Clip B", key=f"prefer_b_{current_idx}")

        if prefer_a or prefer_b:
            chosen = "a" if prefer_a else "b"
            st.session_state.comparisons.append(
                {
                    "pair_index": pair_index,
                    "family_a": fam_a,
                    "family_b": fam_b,
                    "chosen": chosen,
                    "timestamp": iso_now(),
                }
            )
            st.session_state.current_pair_idx = current_idx + 1
            if st.session_state.current_pair_idx >= len(pair_order):
                st.session_state.stage = "confirm"
            save_checkpoint()
            st.rerun()
        return

    if stage == "confirm":
        comparisons = st.session_state.get("comparisons", [])
        vetoes = st.session_state.get("vetoes", [])
        surviving = [fam for fam in FAMILIES if fam not in set(vetoes)]
        if len(surviving) < 2:
            st.error(
                "You cannot continue with fewer than 2 non-vetoed families. Returning to veto selection."
            )
            st.session_state.stage = "veto"
            st.rerun()

        result = compute_all(comparisons, FAMILIES, vetoes)
        st.session_state.latest_result = result

        st.header("Review preference profile")
        st.write(f"Compared {len(comparisons)} pairs across {len(surviving)} families.")
        st.write("Vetoed: " + (", ".join(vetoes) if vetoes else "none") + ".")

        ordered_rows = [
            {"family": fam, "bt_score": f"{result['bt_scores'][fam]:.4f}"}
            for fam in result["rank_order"]
        ]
        st.table(ordered_rows)

        if vetoes:
            st.subheader("Vetoed styles")
            st.markdown("\n".join([f"- ~~{fam}~~ (excluded)" for fam in vetoes]))

        conf = result["confidence"]
        st.write(f"Confidence: {conf:.3f} ({confidence_label(conf)})")

        if result["warning"] is not None:
            st.warning("Fewer than 2 admissible families remain after vetoes.")

        save_col, redo_col = st.columns(2)
        with save_col:
            if st.button("Confirm and save profile"):
                profile_path, profile_json = save_profile(result)
                st.session_state.profile_path = str(profile_path)
                st.session_state.profile_json = profile_json
                st.session_state.stage = "saved"
                st.rerun()
        with redo_col:
            if st.button("Redo listening test"):
                reset_for_redo()
                st.rerun()
        return

    if stage == "saved":
        st.header("Profile saved")
        profile_path = st.session_state.get("profile_path", "(unknown)")
        st.write(f"Profile saved to {profile_path}. You may close this window.")
        profile_json = st.session_state.get("profile_json", {})
        st.code(json.dumps(profile_json, indent=2), language="json")
        return

    st.error("Unknown stage state. Resetting to consent.")
    st.session_state.stage = "consent"
    st.rerun()


if __name__ == "__main__":
    main()

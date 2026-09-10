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

FAMILIES = ["calm", "lofi", "latin", "rock", "hiphop"]
RENDERS_DIR = Path(__file__).parent.parent / "renders" / "frozen"
PROFILES_DIR = Path(__file__).parent.parent / "profiles"
GATE_VERSION = "1.0.0"


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


def ensure_pairwise_initialized() -> None:
    """Create reproducible pair ordering and A/B assignments for this participant."""
    if "pair_order" in st.session_state:
        return

    participant_id = st.session_state.get("participant_id", "")
    seed = int(hashlib.sha256(participant_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    pairs = list(combinations(FAMILIES, 2))
    rng.shuffle(pairs)

    pair_order: list[dict] = []
    for idx, (left, right) in enumerate(pairs):
        if rng.random() < 0.5:
            fam_a, fam_b = left, right
        else:
            fam_a, fam_b = right, left
        pair_order.append(
            {
                "index": idx,
                "family_a": fam_a,
                "family_b": fam_b,
            }
        )

    st.session_state.pair_order = pair_order
    st.session_state.comparisons = []
    st.session_state.current_pair_idx = 0


def reset_for_redo() -> None:
    """Reset pairwise/veto/result state while preserving participant/session header."""
    for key in [
        "pair_order",
        "comparisons",
        "current_pair_idx",
        "vetoes",
        "latest_result",
        "profile_path",
        "profile_json",
    ]:
        if key in st.session_state:
            del st.session_state[key]

    for family in FAMILIES:
        cb_key = f"veto_{family}"
        if cb_key in st.session_state:
            del st.session_state[cb_key]

    st.session_state.stage = "pairwise"


def save_profile(result: dict) -> tuple[Path, dict]:
    """Write participant gate profile JSON and return file path + object."""
    participant_id = st.session_state.participant_id
    session_start = st.session_state.session_start
    session_end = iso_now()

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = PROFILES_DIR / f"{participant_id}_{timestamp}.json"

    profile = {
        "participant_id": participant_id,
        "session_start": session_start,
        "session_end": session_end,
        "gate_version": GATE_VERSION,
        "families": list(FAMILIES),
        "raw_comparisons": list(st.session_state.get("comparisons", [])),
        "vetoes": list(st.session_state.get("vetoes", [])),
        "bt_scores": result["bt_scores"],
        "rank_order": result["rank_order"],
        "admissible_families": result["admissible_families"],
        "primary_family_block_a": result["primary_family_block_a"],
        "primary_family_block_b": result["primary_family_block_b"],
        "confidence": result["confidence"],
        "warning": result["warning"],
    }

    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
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
                st.session_state.stage = "instructions"
                st.rerun()
        return

    if stage == "instructions":
        st.title("GrooveGen — pre-session music preference")
        st.write(
            "You will hear pairs of ~30-second music clips. For each pair, choose which one "
            "you would prefer to listen to during a longer session. There are no right or "
            "wrong answers — pick the one you'd rather hear. There are 10 pairs total, about 10 minutes."
        )
        if st.button("I understand — begin listening"):
            st.session_state.stage = "pairwise"
            st.rerun()
        return

    if stage == "pairwise":
        ensure_pairwise_initialized()

        pair_order = st.session_state.pair_order
        current_idx = st.session_state.current_pair_idx

        if current_idx >= len(pair_order):
            st.session_state.stage = "veto"
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
            st.audio(str(render_paths[family]), format="audio/wav")
            st.checkbox(
                "Do not play this style during my session",
                key=f"veto_{family}",
            )

        if st.button("Continue"):
            st.session_state.vetoes = [
                family for family in FAMILIES if st.session_state.get(f"veto_{family}", False)
            ]
            st.session_state.stage = "confirm"
            st.rerun()
        return

    if stage == "confirm":
        comparisons = st.session_state.get("comparisons", [])
        vetoes = st.session_state.get("vetoes", [])
        result = compute_all(comparisons, FAMILIES, vetoes)
        st.session_state.latest_result = result

        st.header("Review preference profile")

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

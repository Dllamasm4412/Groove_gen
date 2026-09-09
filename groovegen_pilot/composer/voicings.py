"""
voicings.py -- Shared chord-voicing library for GrooveGen.

Purpose
-------
This module holds the hand-designed CHORD VOICING functions that the per-family
composer cells (calm, lofi, hiphop, rnb, pop, rock, latin) call to turn a
Roman-numeral chord into a concrete stack of simultaneous MIDI pitches. It is a
DELIBERATE, RULE-BASED library. There is no ML model here; every musical
decision is a line of code you can point at.

A "voicing" here always returns a list of MIDI pitch integers to be played
SIMULTANEOUSLY (typically at the start of a chord, sustained for its duration).
Rhythmic patterns -- arpeggios, ostinatos, bass grooves -- live in
`patterns.py` and return time-stamped events instead. See that file for the
rhythmic side of the composer library.

Design conventions (used by every function in this module)
----------------------------------------------------------
1. Every voicing accepts EITHER a `(key_root_midi, roman)` pair OR an explicit
   `chord_tones: list[int]`. When both are given, `chord_tones` wins. When
   `chord_tones` is None, we resolve the Roman numeral internally against
   `_ROMAN_TABLE` (imported from `calm_cell.py`, single source of truth).
2. Every voicing accepts an optional `prev_voicing: list[int] | None` argument.
   Most voicings ignore it, but `smooth_voice_lead` uses it to minimize
   voice-leading motion; higher-level composers can chain it across chords.
3. Every voicing accepts optional `register_low` and `register_high` bounds
   as MIDI pitch integers, and clamps the returned pitches into that window
   by octave-shifting (never by transposing a whole chord). Sensible per-family
   defaults are documented in each function's docstring.
4. Returned pitch lists are ALWAYS sorted ascending and deduplicated.
5. All voicings are DETERMINISTIC -- no random state, no time-dependent
   behavior. Randomness (velocity jitter, ornamentation choices) is the
   composer cell's job, not the voicing library's.

Functions
---------
    rootless_A_B        Jazz rootless voicing, A form or B form (3-7-9-5 / 7-3-5-9)
    quartal_voicing     Stacked-4ths voicing (McCoy Tyner / neo-soul)
    drop_2              Drop-2 close voicing (jazz standard practice)
    shell_voicing       Root + 3rd + 7th only (bebop comping)
    smooth_voice_lead   Reorder next-chord tones to minimize motion from previous
    sus_add9            Sus2/sus4 with added 9 (pop / worship)
    power_chord         Root + 5th (+ optional octave), rock
    open_position_triad Folk/rock open triads with wide spacing

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

from typing import Sequence

# Import from the calm_cell module so Roman-numeral resolution has ONE source
# of truth. If future work wants to break this dependency, replace with an
# explicit `_ROMAN_TABLE` and `_build_chord_tones` inlined here -- the calm cell
# would then import from this module instead.
from composer.calm_cell import _ROMAN_TABLE, _build_chord_tones


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_chord_tones(
    chord_tones: Sequence[int] | None,
    key_root_midi: int | None,
    roman: str | None,
) -> list[int]:
    """Return the underlying chord tones for a voicing call.

    Precedence: explicit `chord_tones` > (key_root_midi, roman) resolution.
    """
    if chord_tones is not None:
        return list(chord_tones)
    if key_root_midi is None or roman is None:
        raise ValueError(
            "Voicing needs either chord_tones or (key_root_midi + roman)."
        )
    return _build_chord_tones(key_root_midi, roman)


def _clamp_to_window(pitches: Sequence[int], low: int, high: int) -> list[int]:
    """Octave-shift each pitch to sit inside [low, high]. Preserves pitch class."""
    if low >= high:
        raise ValueError(f"Invalid register window: [{low}, {high}]")
    out: list[int] = []
    for p in pitches:
        q = p
        # Bring up if too low.
        while q < low:
            q += 12
        # Bring down if too high.
        while q > high:
            q -= 12
        # If still out of window (very narrow window vs. tone), just clip.
        q = max(low, min(high, q))
        out.append(q)
    return sorted(set(out))


def _third_seventh_ninth_fifth(chord_tones: Sequence[int]) -> tuple[int, int, int, int]:
    """Return (3rd, 7th, 9th, 5th) MIDI pitches for a 4-note chord.

    Requires len(chord_tones) >= 4 (root, 3rd, 5th, 7th at minimum). The 9th
    is derived as root+14 semitones. Used by rootless voicings.
    """
    if len(chord_tones) < 4:
        raise ValueError(
            f"Rootless voicings need a 4-note chord (got {len(chord_tones)}). "
            "Try shell_voicing for triads."
        )
    root = chord_tones[0]
    third = chord_tones[1]
    fifth = chord_tones[2]
    seventh = chord_tones[3]
    ninth = root + 14
    return third, seventh, ninth, fifth


# ---------------------------------------------------------------------------
# Voicing functions
# ---------------------------------------------------------------------------

def rootless_A_B(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    form: str = "A",
    register_low: int = 55,   # G3
    register_high: int = 76,  # E5
    prev_voicing: Sequence[int] | None = None,
) -> list[int]:
    """Jazz rootless voicing, Bill-Evans style.

    Form A: 3rd - 5th - 7th - 9th, ascending. Bright, open.
    Form B: 7th - 9th - 3rd - 5th, ascending. Darker, more intervallic.

    NOTE: Both forms return the SAME PITCH SET {3, 5, 7, 9} because the
    library always returns sorted ascending pitch lists. The A/B distinction
    is a voice-leading convention about which prior-chord voice each new
    voice replaces, not about pitch content -- callers that care about the
    A/B ordering should either pair with `smooth_voice_lead` to control
    voice motion or track the ordering themselves.

    Recommended families: R&B, jazz-influenced pop, neo-soul comping.
    Not appropriate for: rock, folk, calm (calm uses broken chords).

    Requires a 4-note chord (maj7/min7/dom7). Raises ValueError on triads --
    use `shell_voicing` instead for those.

    `prev_voicing` is accepted for uniform interface but ignored.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    third, seventh, ninth, fifth = _third_seventh_ninth_fifth(tones)

    if form == "A":
        raw = [third, fifth, seventh, ninth]
    elif form == "B":
        raw = [seventh, ninth, third, fifth]
    else:
        raise ValueError(f"rootless_A_B form must be 'A' or 'B', got {form!r}")

    return _clamp_to_window(raw, register_low, register_high)


def quartal_voicing(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    n_stacked_fourths: int = 3,
    register_low: int = 55,   # G3
    register_high: int = 79,  # G5
    prev_voicing: Sequence[int] | None = None,
) -> list[int]:
    """Stacked-4ths voicing (McCoy Tyner, neo-soul / modal jazz).

    Builds a stack of perfect 4ths starting from the chord's 3rd or 5th
    (whichever gives more diatonic hits inside the chord). Ambiguous mode --
    good for modal and neo-soul textures.

    Recommended families: R&B (neo-soul), lofi, ambient.
    Not appropriate for: rock (too diffuse), calm (see calm_cell design notes),
    Latin (clashes with montuno).

    `prev_voicing` accepted but ignored.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if len(tones) < 3:
        raise ValueError("quartal_voicing needs at least a triad.")

    # Start from the 5th (index 2) if we have one; else from the 3rd.
    start = tones[2] if len(tones) >= 3 else tones[1]
    raw = [start + 5 * i for i in range(n_stacked_fourths)]
    return _clamp_to_window(raw, register_low, register_high)


def drop_2(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    register_low: int = 48,   # C3
    register_high: int = 74,  # D5
    prev_voicing: Sequence[int] | None = None,
) -> list[int]:
    """Drop-2 voicing: take a close-position 4-note chord and drop the 2nd-from-top
    voice down an octave. Standard jazz-guitar and jazz-piano practice; also very
    common in R&B and pop ballad piano.

    Example on Cmaj7 (close: C E G B) -> drop-2: G, C, E, B (G lowered an octave).

    Recommended families: R&B, pop ballad, jazz-influenced textures.
    Not appropriate for: rock, calm (uses broken chords), Latin.

    `prev_voicing` accepted but ignored.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if len(tones) < 4:
        raise ValueError(
            f"drop_2 needs a 4-note chord (got {len(tones)}). "
            "Use shell_voicing for triads."
        )
    # Close position, ascending: root, 3rd, 5th, 7th.
    close = sorted(tones[:4])
    # The 2nd-from-top voice is close[2]; drop it an octave.
    dropped = [close[0], close[1], close[3], close[2] - 12]
    return _clamp_to_window(dropped, register_low, register_high)


def shell_voicing(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    include_root: bool = True,
    register_low: int = 48,   # C3
    register_high: int = 72,  # C5
    prev_voicing: Sequence[int] | None = None,
) -> list[int]:
    """Shell voicing: root + 3rd + 7th (or 3rd + 7th if include_root=False).

    Bebop comping staple. Omits the 5th because it's harmonically weakest.
    Works on triads by substituting the 5th for the 7th (i.e. becomes just root
    + 3rd + 5th, which is a plain triad -- fine).

    Recommended families: hip-hop (sampled-piano feel), R&B, jazz.
    Not appropriate for: rock (too jazzy), calm (uses broken chords).

    `prev_voicing` accepted but ignored.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if len(tones) < 3:
        raise ValueError("shell_voicing needs at least a triad.")

    root = tones[0]
    third = tones[1]
    # Prefer 7th if available (4-note chord), else use 5th.
    upper = tones[3] if len(tones) >= 4 else tones[2]

    raw = [root, third, upper] if include_root else [third, upper]
    return _clamp_to_window(raw, register_low, register_high)


def smooth_voice_lead(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    prev_voicing: Sequence[int] | None = None,
    register_low: int = 55,   # G3
    register_high: int = 76,  # E5
) -> list[int]:
    """Return a voicing of the target chord that minimizes total voice motion
    from `prev_voicing` (sum of absolute semitone moves).

    Algorithm:
      1. Resolve the target chord's pitch classes (mod 12).
      2. For each of those pitch classes, find the octave placement (within the
         register window) that is closest to the corresponding prev_voicing note
         under a min-sum-assignment matching.
      3. Return the resulting voicing.

    If prev_voicing is None or empty, we fall back to a close-position voicing
    inside the register window (essentially a default cluster).

    Voice-leading is the ONE stateful concern in this library. Composer cells
    that care about smooth chord-to-chord motion (calm, R&B, pop ballad) can
    chain smooth_voice_lead across their progression by threading each call's
    output into the next call's `prev_voicing`.

    Uses greedy nearest-neighbor matching (O(n^2)); correct for n <= 5 voicings.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if not tones:
        return []

    # Default fallback: close-position voicing centered in the window.
    if not prev_voicing:
        center = (register_low + register_high) // 2
        # Place the root nearest center, then stack the rest tightly above.
        root = tones[0]
        shifted = root
        while shifted < center - 6:
            shifted += 12
        while shifted > center + 6:
            shifted -= 12
        offset = shifted - root
        raw = [t + offset for t in tones]
        return _clamp_to_window(raw, register_low, register_high)

    # For each new pitch class, find the placement closest to any prev voice.
    prev_list = sorted(prev_voicing)
    new_voicing: list[int] = []
    used_prev = [False] * len(prev_list)

    # Generate all octave placements of each target tone within the window.
    def _candidates(t: int) -> list[int]:
        c: list[int] = []
        low = t
        while low - 12 >= register_low:
            low -= 12
        p = low
        while p <= register_high:
            if p >= register_low:
                c.append(p)
            p += 12
        return c

    # Greedy nearest-neighbor pairing: for each target tone (in the order the
    # chord was built -- root, 3rd, 5th, 7th), pick the candidate placement
    # whose distance to the nearest unused prev voice is smallest.
    for t in tones:
        cands = _candidates(t)
        if not cands:
            continue
        best_cand = cands[0]
        best_cost = 10**9
        for c in cands:
            # Find nearest still-unused prev voice.
            local_best = 10**9
            for j, pv in enumerate(prev_list):
                if used_prev[j]:
                    continue
                d = abs(c - pv)
                if d < local_best:
                    local_best = d
            if local_best < best_cost:
                best_cost = local_best
                best_cand = c
        # Mark the closest unused prev voice as used.
        best_j = -1
        best_j_dist = 10**9
        for j, pv in enumerate(prev_list):
            if used_prev[j]:
                continue
            d = abs(best_cand - pv)
            if d < best_j_dist:
                best_j_dist = d
                best_j = j
        if best_j >= 0:
            used_prev[best_j] = True
        new_voicing.append(best_cand)

    return _clamp_to_window(new_voicing, register_low, register_high)


def sus_add9(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    which: str = "sus2",
    register_low: int = 55,   # G3
    register_high: int = 76,  # E5
    prev_voicing: Sequence[int] | None = None,
) -> list[int]:
    """Sus voicing with an added 9th. Very common in modern worship, pop ballad,
    lofi, and ambient contexts.

    which='sus2': root, 2nd, 5th, 9th (bright, open)
    which='sus4': root, 4th, 5th, 9th (suspended, unresolved)

    Note: when the RESOLVED chord tones already encode sus2add9 (see
    _ROMAN_TABLE 'Isus2add9' / 'IVadd9'), we return those directly and ignore
    the `which` flag. Otherwise we build the sus from the chord's root.

    Recommended families: lofi, calm variants, pop ballad.
    Not appropriate for: rock (too airy), Latin (rhythm-based, not sus-based).

    `prev_voicing` accepted but ignored.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if not tones:
        raise ValueError("sus_add9 needs at least a root tone.")

    # If the resolved chord already has the sus2add9 shape (4 tones spanning >12
    # semitones, containing the 9th), return it directly.
    if len(tones) == 4 and (tones[3] - tones[0]) >= 12:
        return _clamp_to_window(tones, register_low, register_high)

    root = tones[0]
    if which == "sus2":
        raw = [root, root + 2, root + 7, root + 14]  # 1, 2, 5, 9
    elif which == "sus4":
        raw = [root, root + 5, root + 7, root + 14]  # 1, 4, 5, 9
    else:
        raise ValueError(f"sus_add9 which must be 'sus2' or 'sus4', got {which!r}")

    return _clamp_to_window(raw, register_low, register_high)


def power_chord(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    include_octave: bool = True,
    register_low: int = 40,   # E2 (electric-guitar low E)
    register_high: int = 60,  # C4
    prev_voicing: Sequence[int] | None = None,
) -> list[int]:
    """Rock power chord: root + 5th (+ optional root-up-an-octave).

    Deliberately ambiguous major/minor -- the 3rd is omitted. This is the
    defining rock guitar voicing.

    include_octave=True gives the classic 3-note power chord (1-5-8), False
    gives just the 2-note interval (1-5) for a more open sound.

    Recommended families: rock (default).
    Not appropriate for: calm, R&B, jazz, Latin. Do not call for those.

    `prev_voicing` accepted but ignored.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if not tones:
        raise ValueError("power_chord needs at least a root tone.")

    root = tones[0]
    fifth = root + 7
    raw = [root, fifth]
    if include_octave:
        raw.append(root + 12)
    return _clamp_to_window(raw, register_low, register_high)


def open_position_triad(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    register_low: int = 40,   # E2
    register_high: int = 72,  # C5
    prev_voicing: Sequence[int] | None = None,
) -> list[int]:
    """Folk / acoustic-rock open-position triad with wide spacing.

    Spreads a triad across ~2 octaves in the "root - 5th (up an octave) - 3rd
    (up another octave)" shape, matching guitar open-position C / G / D voicings.

    Example on C major: C2, G3, E4.

    Recommended families: rock (softer subtype), folk-adjacent lofi.
    Not appropriate for: R&B, hip-hop, Latin.

    `prev_voicing` accepted but ignored.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if len(tones) < 3:
        raise ValueError("open_position_triad needs at least a triad.")

    root = tones[0]
    third = tones[1]
    fifth = tones[2]

    # Guitar-open shape: root low, 5th up an octave from root, 3rd up another octave.
    raw = [root, fifth + 12, third + 24]
    # Clamp preserves pitch class via octave shift.
    return _clamp_to_window(raw, register_low, register_high)


# ---------------------------------------------------------------------------
# Self-test: exercise every voicing on a Cmaj7 to catch obvious breakage.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    C_MIDI = 48  # C3
    print("Voicing library self-test (chord: Cmaj7, key: C)", file=sys.stderr)
    print("-" * 60, file=sys.stderr)

    # Cmaj7 = C, E, G, B => MIDI [48, 52, 55, 59] for tests that need a 4-note chord.
    CMAJ7 = [48, 52, 55, 59]

    tests = [
        ("rootless_A_B (form A, Cmaj7)", lambda: rootless_A_B(chord_tones=CMAJ7, form="A")),
        ("rootless_A_B (form B, Cmaj7)", lambda: rootless_A_B(chord_tones=CMAJ7, form="B")),
        ("quartal_voicing (C triad)",   lambda: quartal_voicing(C_MIDI, "I")),
        ("drop_2 (Cmaj7)",              lambda: drop_2(chord_tones=CMAJ7)),
        ("shell_voicing (C triad)",     lambda: shell_voicing(C_MIDI, "I")),
        ("smooth_voice_lead (no prev)", lambda: smooth_voice_lead(C_MIDI, "I")),
        ("smooth_voice_lead (with prev)",
            lambda: smooth_voice_lead(C_MIDI, "IV",
                                       prev_voicing=smooth_voice_lead(C_MIDI, "I"))),
        ("sus_add9 (sus2, C)",          lambda: sus_add9(C_MIDI, "I", which="sus2")),
        ("sus_add9 (sus4, C)",          lambda: sus_add9(C_MIDI, "I", which="sus4")),
        ("power_chord (C)",             lambda: power_chord(C_MIDI, "I")),
        ("open_position_triad (C)",     lambda: open_position_triad(C_MIDI, "I")),
    ]

    def _midi_to_name(m: int) -> str:
        names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        return f"{names[m % 12]}{m // 12 - 1}"

    for label, fn in tests:
        try:
            v = fn()
            named = [_midi_to_name(p) for p in v]
            print(f"  {label:35s} -> {v}  {named}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  {label:35s} FAILED: {e}", file=sys.stderr)

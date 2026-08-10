# Where to submit this fall — AI-council recommendation

**Question posed:** Given the SYSTEM/METHOD framing (no efficacy claim, bidirectional closed-loop
physiological music control), a solo time-constrained fall 2026 window, and TEI ruled out, what is
the best venue to target — and the best backup?

**Method:** a 3-model advisory council (Claude Opus, GPT-5, Gemini) each reasoned independently
over the same brief (`council_venue_brief.md`) containing verified, current (Aug 2026) deadlines.
Full responses: `council_venue_opus.md`, `council_venue_gpt.md`, `council_venue_gemini.md`.

---

## Unanimous recommendation

> ### PRIMARY: **NIME 2027** — full paper + demo (deadline ~Feb 2027)
> ### BACKUP: **CHI 2027 Late-Breaking Work** (6pp; CFP opens ~Dec 2026–Feb 2027)
> ### ARCHIVAL EXTENSION (2027): **TISMIR** journal (or IMWUT/UbiComp)

All three models converged on this independently. All three also agreed on the single most
important negative finding:

> **CHI 2027 full paper (Sep 10, 2026) is a trap — do NOT chase it.** Five weeks, no draft, no
> human data, hardware not yet ordered, and a reviewer culture that will reject a
> simulation-plus-n≈6 system paper for "insufficient empirical / human contribution" — which is
> exactly the study you have (correctly) chosen not to run. It would burn the whole fall to trade
> a likely accept at the best-fit venue for a likely reject at a mismatched one.

## Why NIME (the reasoning all three share)

- **It is the only venue where every element of the locked framing reads as a strength, not a
  liability.** The cascade controller and reference governor read as *instrument design*; the
  ~15× real-time margin and p95≈330 ms with zero deadline misses read as the *engineering
  justification* for a symbolic bed; the audible up/down-regulation demos read as the
  *evaluation*; and the absence of an efficacy claim reads as *appropriate scoping* rather than a
  missing study.
- **The "we falsified per-bar morphing by ear" story is treated as honest design knowledge at
  NIME and as sloppiness at CHI.**
- **The timeline is achievable.** ~5 months (not 5 weeks) converts the fall from a panic sprint
  into a real runway: order the Polar H10 in week 1, run a small honest pilot (n≈5–8) in October,
  write carefully, and iterate the demo video.

## Why NOT the alternatives

| Venue | Verdict | Reason |
|---|---|---|
| **CHI 2027 full (Sep 10)** | ❌ trap | 5 weeks solo, no draft/data/hardware; reviewer bias toward human evaluation kills a no-efficacy system paper |
| **CHI 2027 LBW** | ✅ backup only | Great fit (6pp, system+pilot+video, low bar) but non-archival and opens ~winter, so not a "fall" deliverable and not a home for the two-timescale result |
| **TISMIR (Sep 1 / Dec 1)** | ✅ later archival | Right *shape* (journal, no page pressure, no forced study) but Sep 1 impossible, Dec 1 collides with coursework, review is slow, and its center of mass is MIR not real-time control. Best as the 2027 archival extension of the NIME paper |
| **ISMIR / ICMI / SMC / ACII / AVI 2026** | ❌ closed | All 2026 deadlines already passed (spring); next cycles are 2027 |
| **ACM MM Asia 2026 demo (Sep 1)** | ⚪ optional insurance | Low prestige, but a demo submission is ~work you need anyway and a useful *forcing function* (Opus). Weak alignment (GPT/Gemini) |

## Caveat on dates

**Verified (Aug 2026):** CHI 2027 full paper = Sep 10, 2026; TISMIR windows = Sep 1 / Dec 1, 2026;
ACM MM Asia demo = Sep 1, 2026. **NIME 2027 (~Feb 2027) is inferred from the NIME 2026 pattern**
(abstracts early Feb, full paper mid-Feb) — the exact date must be confirmed against the official
NIME 2027 CFP when it posts. Additional venues Opus raised (IMWUT/UbiComp rolling, AudioMostly,
ICMC, MOCO, IUI, JNMR) were flagged unverified and should be checked before relying on them.

## The plan the council converged on (5-week sprint that feeds NIME, not CHI)

Use the *old CHI sprint window* (Aug 5 – ~Sep 10) as an internal milestone to get the technical
paper draft-ready, then let October's pilot fill in the evidence.

- **Week 1 (Aug 5–11):** Order the Polar H10 **today** (longest-lead dependency). Lock the claim
  list to exactly four claims (architecture; two-timescale rendering result; reference governor as
  a *reportable* 6 BPM/min reference; falsified per-bar assumption). Stand up an offline RR-replay
  path so code is ready when hardware lands. Start IRB/exempt determination if human RR data will
  be reported.
- **Week 2 (Aug 12–18):** **Feature freeze — no new features after this week.** Regenerate all
  figures at publication quality (latency histogram + deadline misses; transition audit;
  deadband/dwell ablation; genre-ladder timeline; HR→arousal calibration fit). Machine-check
  within-segment plan invariance and save the log as a reproducibility artifact.
- **Week 3 (Aug 19–25):** Write the paper skeleton end to end (related work grounded in the
  iso-principle + prior biofeedback-music instruments; architecture; systems results). Complete
  the Sophia secondary analysis write-up. Write fast; a complete artifact beats polished prose.
- **Week 4 (Aug 26–Sep 1):** Produce the demo video (~90 s: one up-reg + one down-reg run, on-screen
  HR/arousal/tempo overlay, no vocals). Optionally submit a 2–4pp **ACM MM Asia demo by Sep 1** as
  a cheap external forcing function.
- **Week 5 (Sep 2–8):** First live H10 runs on yourself + 1–2 lab mates; confirm end-to-end
  closed-loop with real RR intervals. Write the October pilot protocol (n≈5–8, per-subject
  calibration, **no group inferential test**). Send the draft to two readers (one HCI, one
  music-tech).

Then: **October** = pilot collection · **November** = rewrite around real data · **December** =
polish + optional CHI workshop position paper · **January** = NIME submission ready two weeks early.

## Candid risks the council flagged (all three independently)

1. **Scope creep is the #1 risk, not venue choice.** The system is built; the solo-student failure
   mode is re-engineering instead of writing. The Week-2 feature freeze is the highest-value line
   in the plan.
2. **"Efficacy creep" in the writing.** Never write "the system calmed users." Always
   "the system tracked the arousal reference." Police this in the abstract, intro, and limitations.
3. **Hardware / Colab-BLE integration.** Live Bluetooth-LE HR into a cloud Colab instance is
   finicky; a bad bridge breaks the "closed-loop" claim. Test it immediately; build a logged
   **offline replay mode** now so the paper survives a hardware delay.
4. **NIME is demo-driven.** A clunky or jarring-sounding demo sinks a strong architecture. The
   audio must clearly show smooth bidirectional control. Include failure cases and justify
   segment-rate control.
5. **NIME rejection risk ≈ 40–50 %** (accept rates hover near half). Preempt the predictable
   criticisms — linear HR→arousal is crude (limitations paragraph), a scripted reference sidesteps
   whether the listener follows (frame as a control abstraction), "we've seen biofeedback music
   before" (make the demo excellent).
6. **Cost of this plan:** no *submitted archival full paper* in fall 2026 — only (optionally) an MM
   Asia demo. If your program/advisor requires a fall submission line item, the honest mitigation
   is the MM Asia demo + a CHI workshop position paper — **not** a Sep 10 CHI full-paper Hail Mary.

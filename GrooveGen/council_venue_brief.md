# Council brief — Fall 2026 paper venue for GrooveGen

Current date context: early August 2026. "This fall semester" = Aug–Dec 2026.
TEI is OFF the table (author's call — time constraints; TEI cycle timing doesn't work).

## What the paper IS (locked framing)
- **Contribution type: SYSTEM / METHOD**, not efficacy. We are NOT claiming the music
  measurably changes physiology in humans. We claim a *working closed-loop system* that
  regulates a generated musical bed from a physiological signal.
- One-line: "A closed-loop system that controls a symbolic music generator from a listener's
  heart rate, tracking a scripted arousal reference in real time — bidirectional
  (up- and down-regulation)."
- **Core novelty = the control architecture + the two-timescale rendering result:**
  - Cascade controller: fast event-density loop (per segment) → tempo loop on saturation →
    genre-energy ladder (calm→r&b→pop→latin) as a gated coarse actuator.
  - HR→arousal per-subject linear calibration; controller tracks arousal∈[0,1].
  - Reference governor: rate-limited linear ramp (reportable "6 BPM/min reference", NOT a
    physiological promise) + terminal taper + progress gate + lead clamp.
  - **Empirical systems result:** whole-segment symbolic render = ~2 s vs 30 s budget
    (~15× real-time margin); per-bar p50≈221 ms / p95≈330 ms, ZERO deadline misses. This
    latency/jitter characterization is the justification for a symbolic (not neural-audio) bed.
  - Honest reframing we can publish: "per-bar morphing was an unvalidated assumption we
    falsified by ear; segment-rate control is the corrected design."
- NO VOCALS anywhere. Grounded in iso-principle (music-therapy) literature.

## Evidence we will HAVE by a fall deadline
- Full working system (Colab T4, symbolic pipeline, FluidSynth).
- Simulation validation: within-segment plan invariance (machine-checked), ~3–5 genre
  changes / 15 min, latency figure, transition-audit figure, deadband/dwell ablation.
- Audible bidirectional transition demos (MP4).
- Possibly an n≈5–8 pilot with a Polar H10 (RR intervals) — SMALL, no group inferential
  test claimed. Efficacy is explicitly NOT the contribution.
- Secondary dataset analysis (Sophia, n=122 / 643 tracks) grounding bed feature profile.

## Author / logistics constraints
- Solo-ish PhD student (Daniel Llamas), CU Boulder (Cognitive Science / ATLAS / HCI).
- Runs on Google Colab, one session at a time. Hardware (Polar H10) not yet ordered.
- Time-constrained THIS fall. Wants something realistically hittable, not aspirational.
- Prior internal doc: `tei_publishability_audit.md` already argued the system-contribution framing.

## Candidate venues with REAL current deadlines (verified Aug 2026)
- **CHI 2027** — full paper due **Sep 10, 2026** (AoE); no separate abstract deadline;
  notif Dec 2026; conf May 2027 Pittsburgh. A* HCI. archival, ~10–12 pp.
- **CHI 2027 Late-Breaking Work (LBW)** — typically opens ~Dec 2026–Feb 2027 (poster/6pp,
  non-archival-ish extended abstract). Lower bar, good for a system+pilot.
- **ISMIR 2026** — main paper deadline already PASSED (spring). Not an option for a new full paper.
- **TISMIR (journal, Trans. ISMIR)** — rolling; call lists submission windows **1 Sep 2026**
  and **1 Dec 2026**. Journal = no fixed conf deadline pressure; slower review.
- **NIME 2027** — based on NIME 2026 pattern (abstracts early Feb, full mid-Feb). So NIME 2027
  deadline likely **~Feb 2027** (just after fall). Music/interface venue, very on-topic, but
  slightly past "this fall."
- **AVI 2027** — AVI 2026 paper deadline was Jan 25, 2026; AVI 2027 likely **~Jan 2027**.
- **ACII 2026** — deadline PASSED (Apr 2026). ACII is efficacy-heavy anyway (weaker fit for a
  system paper with no efficacy claim). ACII 2027 would be ~spring 2027.
- **ICMI 2026** — deadline PASSED (Apr 2026).
- **SMC 2026 (Sound & Music Computing)** — deadline PASSED (Mar 2026). SMC 2027 ~spring 2027.
- **ACM Multimedia Asia 2026** — regular papers due Aug 3, 2026 (essentially now/passed);
  demo/industry Sep 1, 2026. Possible but MM-Asia is a weaker prestige fit.

## QUESTION for each council member
Given the SYSTEM/METHOD framing, the solo time-constrained fall window, and the real deadlines
above: **What is the single best primary venue to target this fall, and the best backup?**
Address explicitly:
1. Is **CHI 2027 full paper (Sep 10)** realistic for a solo student in ~5 weeks given the
   system is built but the paper is not written? Or is that a trap (rejection risk, time)?
2. Is a **CHI 2027 LBW** (later, lighter) the smarter "this fall/early winter" play?
3. Where does **TISMIR (journal, Sep/Dec windows)** fit — is a journal a better home for a
   system+latency-characterization paper with a tiny pilot?
4. Is it worth WAITING ~4–6 weeks for **NIME 2027 (~Feb 2027)** given NIME is arguably the most
   ON-TOPIC venue (music interfaces, embodied/physiological instruments) and welcomes
   system+demo papers? Trade "this fall" literalness vs. best-fit venue.
5. Any venue we're missing that fits "closed-loop physiological music control, system
   contribution, small/no pilot" better?
Give a concrete recommendation with a one-paragraph justification and a rough 5-week action plan
for the recommended primary.

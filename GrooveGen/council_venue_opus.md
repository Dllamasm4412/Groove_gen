# Council member (Opus): venue recommendation for GrooveGen, Fall 2026

## Answers to the five questions

**1. CHI 2027 full paper (Sep 10) — realistic in ~5 weeks solo? No. It's a trap.**
Not because the work is weak, but because CHI is the single worst-matched venue for *this* paper in *this* state. You have five weeks to produce a 10–12pp archival CHI paper with (a) no draft, (b) no related-work synthesis written, (c) no human data at all, and (d) hardware not yet ordered — Polar H10 shipping plus RR-interval plumbing plus IRB-adjacent logistics alone eats 2 of the 5 weeks if anything slips. Worse, CHI's modal reviewer response to a system paper whose evaluation is simulation + latency traces + n≈6 pilot is "insufficient empirical contribution / unclear what we learn about people," and the framing you have correctly locked (explicitly *no* efficacy claim) removes the one thing that would have satisfied them. Expected outcome: ~10–15% accept for a rushed solo submission versus CHI's ~25% baseline, at the cost of your entire fall. The one real upside — reviews arriving Dec 2026 in time to rewrite for NIME — is obtainable far more cheaply.

**2. CHI 2027 LBW — smarter, but as a backup, not the plan.** LBW is genuinely well-suited: 6pp, system + pilot + video, poster audience, low bar, and it puts "CHI" on the CV. But it is non-archival-ish, it is *not* a home for your two-timescale rendering result (the actual novelty gets compressed to a paragraph), and its deadline opens Dec 2026–Feb 2027 — i.e. it isn't a fall deliverable either. Keep it as the guaranteed-landing option and as a cheap derivative of a better paper.

**3. TISMIR — right *shape* of venue, wrong *timing* and slightly wrong audience.** A journal genuinely suits a system + latency-characterization paper with a tiny pilot: no page pressure, room for the control architecture, ablations, and the honest "we falsified per-bar morphing" narrative, and no reviewer demanding a study you refuse to claim. But Sep 1 is impossible, Dec 1 means writing a journal-quality paper while coursework runs, and TISMIR review is slow (first decision months out, R&R cycles beyond that) — you get zero line items this academic year. Also, TISMIR's center of mass is MIR (retrieval, corpora, models); real-time control loops and deadline-miss statistics are peripheral there. **Keep TISMIR as the eventual archival extension** of the NIME paper (that is a very normal and respected path), targeting the 2027 windows once the pilot has grown.

**4. Waiting ~4–6 weeks for NIME 2027 (~Feb 2027) — yes. Do this.** NIME is the venue whose reviewers already believe your contribution *is* a contribution: new musical interfaces, physiological/embodied instruments, real-time control, and an explicit tradition of system + demo papers judged on design reasoning, architecture, and craft rather than on inferential statistics. Your falsified per-bar-morphing story would be treated as intellectually honest design knowledge at NIME and as sloppiness at CHI. The cost of waiting is trivial: NIME's deadline is ~5 months out, not 5 weeks, which converts your fall from a panic sprint into a proper runway — order the H10 in week 1, run n≈6–8 in October, and submit a paper with real RR-interval traces instead of simulation only. "This fall literalness" is a self-imposed constraint with no academic payoff; a February submission is still a fall's worth of work, and it is the difference between a likely accept and a likely reject.

**5. Venues you may be missing** (dates unverified — confirm before relying on any):
- **ACM IMWUT/UbiComp** — rolling quarterly deadlines (~Feb/May/Aug/Nov), journal-track, loves closed-loop physiological sensing systems with rigorous latency/jitter characterization. Strongest "serious archival" alternative to TISMIR, but reviewers will push for in-the-wild deployment.
- **AudioMostly** (ACM, audio/interaction, system-and-demo friendly) and **ICMC** — both plausible, similar spirit to NIME, useful as parallel shots.
- **MOCO** (Movement & Computing) — sympathetic to physiological/embodied control loops.
- **CHI 2027 workshops** (CFPs land Dec–Feb) — a 4pp position paper on "reference governors for physiological music control" is a ~4-day cost with real networking return.
- **ACM MM Asia 2026 demo (Sep 1)** — low prestige, but a *demo* submission is ~5 pages of work you need anyway, and an audible bidirectional demo is exactly what it rewards. Cheap optional insurance.
- **JNMR** (rolling) — a fallback journal if TISMIR reviewers balk at the non-MIR framing.

---

## Recommendation

**PRIMARY: NIME 2027 full paper + demo (deadline ~Feb 2027).**
This is the only venue where every element of your locked framing is an asset rather than a liability: the cascade controller and reference governor are read as instrument design, the ~15× real-time margin and p95≈330 ms with zero deadline misses are read as the engineering justification for symbolic rendering, the audible up/down-regulation demos are read as the evaluation, and the absence of an efficacy claim is read as appropriate scoping rather than a missing study. Critically, the timeline is *achievable*: five months lets a solo student on Colab order hardware, collect a small honest pilot, write carefully, and iterate the demo video — which is precisely the profile of an accepted NIME paper. Chasing CHI Sep 10 instead trades a likely accept at the best-fit venue for a likely reject at a mismatched one, and burns the same fall doing it.

**BACKUP: CHI 2027 Late-Breaking Work (opens ~Dec 2026–Feb 2027).**
It is a near-free derivative: compress the NIME draft to 6pp, foreground the pilot and video. If NIME rejects, LBW lands you a CHI-badged artifact in the same cycle, and the full paper then goes to TISMIR or IMWUT in 2027 with a larger pilot.

## 5-week action plan (Aug 5 – Sep 8, 2026) — the NIME critical path

- **Week 1 (Aug 5–11):** Order the Polar H10 *today*; it is the longest-lead item and everything human depends on it. Stand up the RR-interval ingest path against a recorded/synthetic stream so the code is ready when hardware lands. Lock the paper's claim list to exactly four claims (architecture, two-timescale rendering result, reference governor as a *reportable* 6 BPM/min reference, falsified per-bar assumption). Start IRB/exempt-determination paperwork if human RR data will be reported.
- **Week 2 (Aug 12–18):** Freeze the system. No new features after this week. Regenerate all five figures at publication quality: latency histogram (p50/p95, deadline misses), transition audit, deadband/dwell ablation, genre-ladder timeline, HR→arousal calibration fit. Machine-check within-segment plan invariance and save the log as a reproducibility artifact.
- **Week 3 (Aug 19–25):** Write the NIME-shaped skeleton end to end — 6–8 pages, related work grounded in the iso-principle and prior biofeedback-music instruments, architecture section, systems-results section. Write badly and fast; the point is a complete artifact, not prose.
- **Week 4 (Aug 26–Sep 1):** Produce the demo video: 90 seconds, one up-regulation and one down-regulation run, on-screen HR/arousal/tempo overlay, no vocals. **Submit a 2–4pp version as an ACM MM Asia demo by Sep 1** — an external forcing function that converts your draft into a shipped artifact and costs almost nothing.
- **Week 5 (Sep 2–8):** First live H10 runs on yourself plus 1–2 lab mates; confirm end-to-end closed-loop behavior with real RR intervals. Write the pilot protocol for October (n≈6–8, per-subject calibration, no group inferential test). Send the draft to two readers — one HCI, one music-tech — and put NIME's abstract/full-paper dates in the calendar with a two-week buffer.

Fall then runs: October = pilot collection, November = rewrite around real data, December = polish + optional CHI workshop position paper, January = NIME submission ready two weeks early.

## Candid risk assessment

- **Biggest risk is not venue choice, it's scope creep.** The system is built; the failure mode for solo students is re-engineering instead of writing. The Week-2 feature freeze is the single highest-value line in this plan; if you break it, the February deadline slips too.
- **Hardware risk.** H10 not yet ordered is the one hard dependency. If it slips past mid-September, the October pilot slides into November and the NIME paper reverts to simulation-only — survivable at NIME (many accepted papers have no user study), fatal at CHI or IMWUT. Order it now.
- **NIME rejection risk: moderate, roughly 40–50%.** NIME accept rates hover near half, and the plausible criticisms are real: reviewers may say HR→arousal linear calibration is too crude a proxy, that a *scripted* arousal reference sidesteps the hard problem (there's no evidence the listener follows it), or that they've seen biofeedback-music systems before and want to know what the *musical* result sounds like. Preempt all three explicitly: cite the calibration's limits in a limitations paragraph, frame the reference governor as a control abstraction rather than a physiological promise, and make the audio demo excellent — at NIME, a weak-sounding demo sinks a strong architecture.
- **Framing risk.** "No efficacy claim" is correct and defensible, but some reviewer will still ask "so does it work on people?" Your answer must be one crisp sentence in the abstract ("we characterize the controller, not the listener response") repeated in the intro and limitations. Do not let it be inferred.
- **Cost of my recommendation.** You end fall 2026 with no submitted archival full paper — only an MM Asia demo. If your program or advisor requires a fall submission line item, that's the pressure point; the MM Asia demo plus a CHI workshop paper is the honest mitigation. Do not solve it by submitting to CHI on Sep 10.

---

*Sources: reasoning based solely on the deadlines and evidence stated in `/home/user/workspace/council_venue_brief.md`; no external retrieval was performed, per instructions. Venue dates flagged "unverified" in Q5 must be confirmed against official CFPs.*

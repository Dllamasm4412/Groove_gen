# Council recommendation: GrooveGen venue strategy

## Direct answers to the five questions

**1. Is CHI 2027 full paper realistic?**  No—not as the rational primary plan. Five weeks, a solo author, unpurchased hardware, and an unwritten paper make the schedule a bad bet. CHI will ask whether the design knowledge generalizes, why the mappings are warranted, and what people can actually experience; latency alone does not supply that HCI contribution. A thin systems paper is a high-variance submission that could trade away a much stronger NIME paper.

**2. Is CHI LBW smarter?**  Yes, substantially. LBW is a sensible dissemination route for a polished system, short pilot, transition demos, and an explicit “design correction” story: per-bar morphing was rejected after auditory inspection, leading to segment-rate control. It gives visibility and feedback without forcing a premature efficacy narrative. It is not an archival replacement for a full paper, so use it as a presentation artifact and feedback mechanism.

**3. Where does TISMIR fit?**  TISMIR is a credible *technical fallback*, particularly for a December submission after the system and analyses are mature. The symbolic representation, feature-profile analysis, reproducible control logic, and latency/jitter characterization are journal-friendly. However, it is not the natural first home: the central contribution is an interactive physiological music-control instrument, not a music-information-retrieval method. A tiny pilot is acceptable only if clearly framed as feasibility/usability observation rather than evidence of regulation. Its rolling timeline lowers deadline pressure but brings slower, more demanding revisions and little timely community feedback.

**4. Should the author wait for NIME 2027?**  Yes. This is the best decision, even though it is not a literal fall submission. NIME is where the paper’s actual intellectual object—an embodied, physiological, generative-music interface—will be legible without pretending to be a clinical study or generic HCI deployment. The added months allow the H10 and feasibility pilot, better transitions, and reproducibility beyond a fragile single Colab session. The work can then be an instrument/system paper rather than a rushed CHI submission shaped for a different evaluation culture.

**5. Missing venues?**  No missing *fall 2026* venue is clearly better. ACM Multimedia Asia’s demo route is weakly aligned. Beyond fall, SMC 2027 is the best additional archival alternative; AVI only fits after a visualization/interaction pivot. Avoid ACII and ICMI without substantive affective-computing evaluation.

## Primary recommendation: NIME 2027

Target **NIME 2027 full paper** as the primary venue, accepting that the decisive submission is likely around February rather than in the fall. It is the highest-fit venue for a closed-loop physiological music system whose contribution is a controllable instrument architecture and its real-time rendering behavior. The paper can foreground the cascade controller, reference governor, calibration, and two-timescale rendering result, supported by audio demonstrations, transition auditing, simulation invariants, and a limited feasibility pilot. NIME reviewers are more likely than CHI reviewers to value the audible artifact and design of the musical interaction itself. Waiting is not procrastination here; it is a controlled investment in a submission that matches both the paper and the author’s evidence.

## Backup: CHI 2027 Late-Breaking Work

Submit a **CHI 2027 LBW** if it opens on the expected winter schedule. Present the compact system and pilot while retaining NIME as the archival target. Do not submit a rushed CHI full paper merely to meet the September date.

## Five-week action plan for NIME primary

**Week 1:** Freeze the contribution statement and system boundaries. Order the H10 immediately. Create a reproducible experiment manifest: hardware/software versions, scripted reference trajectories, seeds, timing logs, and a definition of every controller state.

**Week 2:** Produce the systems evaluation package: latency/jitter figure, deadline-miss table, plan-invariance test, and deadband/dwell ablation. Record clean up- and down-regulation demo clips with annotated controller states.

**Week 3:** Run transition auditing with a preregistered-style rubric and complete the Sophia secondary analysis. Write methods and results first; these should stand without any human-efficacy claim.

**Week 4:** If the chest strap is working, conduct only a narrow feasibility pilot (n≈5–8): signal quality, calibration completion, controller stability, and participant-reported transition acceptability. Do not chase significance or add protocol complexity.

**Week 5:** Draft the full paper skeleton, figures, and companion demo. Get two targeted internal reviews—one NIME/music-computing reader and one HCI methods reader—then make a gap list for the remaining runway to February.

## Candid risk assessment

The biggest risk is not lack of novelty; it is overclaiming. “Tracking a scripted arousal reference” can be misread as proving physiological regulation. Keep “reference” explicitly a controller target, report HR behavior descriptively, and never imply therapeutic efficacy. Second, the genre-energy ladder may appear ad hoc or culturally simplistic unless its gating, mapping rationale, and failure modes are transparent. Third, Colab-only execution and unpurchased hardware threaten reproducibility and pilot completion; build a logged offline replay mode now so the paper survives a hardware delay. Reviewers may find transition quality more persuasive than latency: include failures and justify segment-rate control. Rejection remains plausible if the interaction feels like a technical demo rather than an instrument, but February makes it an honest, manageable risk—not a rushed CHI trap.

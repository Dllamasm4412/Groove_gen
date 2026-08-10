# Advisory Council Response: Venue Recommendation for GrooveGen

As an expert in HCI and music computing, I have reviewed the brief for the GrooveGen paper. The core strength of your work is the **system architecture and latency/jitter characterization**, not human efficacy. Pushing this to the wrong venue or rushing a deadline will lead to frustrating reviews asking for a 30-person user study you never intended to run. Here is my candid advice.

## Answers to the 5 Core Questions

**1. Is CHI 2027 full paper (Sep 10) realistic or a trap?**
It is an absolute trap. For a solo student with an unwritten paper, hardware (Polar H10) not yet ordered, and a pilot yet to be run, a 5-week sprint to CHI is a recipe for burnout and a near-certain rejection. Furthermore, despite the existence of a "systems" subcommittee, CHI reviewers consistently harbor a strong bias toward comprehensive human evaluation. Submitting a rushed system paper with a tiny n=5 pilot to CHI will almost certainly result in reviews complaining about the lack of an efficacy study, completely missing your intended contribution. 

**2. Is a CHI 2027 LBW a smarter "this fall" play?**
Yes, a CHI LBW (due ~Dec 2026/Jan 2027) is a much safer bet for a system plus a small pilot. It reduces the writing burden (6 pages) and the reviewer expectations for evaluation are significantly lower. However, keep in mind that an LBW is an extended abstract/poster, not a full archival paper. If your ultimate goal is a full archival paper, this should only be a backup or a parallel side-quest, not your main target.

**3. Where does TISMIR (Dec 1 window) fit?**
TISMIR is an excellent philosophical fit. As a journal, it welcomes deep technical validation (latency characterization, simulation validation, architecture design) without demanding the large-scale user studies typical of HCI conferences. The December 1 window gives you a realistic ~4-month runway to order the hardware, run the pilot, and polish the manuscript. The downside is that journal review cycles can be slow, depriving you of the immediate feedback and networking of a conference.

**4. Is it worth waiting for NIME 2027 (~Feb 2027)?**
Absolutely. NIME is arguably the most on-topic venue in the world for an embodied, closed-loop physiological music interface. NIME reviewers uniquely appreciate the value of a working, novel system and a compelling demo, and they will understand the iso-principle grounding without demanding clinical efficacy proof. Trading the literal "this fall" constraint for a February deadline is the smartest strategic move you can make for the paper's reception and your own sanity.

**5. Any missing venues?**
You might consider ACM IUI (Intelligent User Interfaces, usually October), but it leans heavily toward AI/ML interaction paradigms and might not appreciate the music-centric latency characterization as much as NIME. Audio Mostly is another good fit, but its deadline is usually late spring/early summer. Stick to NIME or TISMIR.

---

## 1. Recommended Primary Venue: NIME 2027 (~Feb 2027)

**Justification:**
You should firmly target **NIME 2027** as your primary venue and abandon the September CHI deadline. NIME is the perfect home for a paper explicitly framed as a system/method contribution involving musical interfaces and physiological signals. The NIME community thrives on novel control architectures, interactive systems, and high-quality demos, meaning your latency characterization and bidirectional MP4 demos will be deeply appreciated rather than viewed as "insufficient evaluation." By shifting your target to February, you transform a panicked, impossible 5-week CHI sprint into a highly structured, reasonable 6-month timeline. This allows you to order the Polar H10 immediately, run a rigorous albeit small n=5-8 pilot, perform your simulation validations without cutting corners, and write a polished, compelling manuscript.

## 2. Recommended Backup Venue

**TISMIR (December 1, 2026 Window)**. If by late November the system is completely locked, the pilot data is pristine, and you have a dense technical validation (latency, jitter, architecture) that feels slightly too heavy or long for a typical NIME conference paper, pivot to the TISMIR December 1 deadline. Alternatively, **CHI 2027 LBW** serves as a great fallback if the pilot hits snags and you need to publish a work-in-progress to secure a quick win.

## 3. Realistic 5-Week Action Plan (Aug - early Sept)

Even though NIME is in February, you must use the next 5 weeks (the old CHI sprint window) to lock down the system validation and draft the core technical sections, treating mid-September as an internal milestone.

*   **Week 1:** **Order the hardware and lock the architecture.** Order the Polar H10 today. Finalize the Python/Colab architecture. Draft the Introduction and Related Work sections, clearly planting your flag as a "system contribution" grounded in the iso-principle.
*   **Week 2:** **Simulation & Latency Characterization.** Run the simulation validations (within-segment plan invariance, latency figures, transition-audit figures). Generate the deadband/dwell ablation charts. Draft the "System Design" and "Technical Evaluation" sections based on this data.
*   **Week 3:** **Secondary Dataset & Demo Polish.** Complete the Sophia dataset analysis (n=122/643 tracks) to justify the bed feature profile. Draft the "Musical Mapping" section. Record your bidirectional transition MP4 demos.
*   **Week 4:** **Pilot Setup.** By now, the Polar H10 should have arrived. Write the protocol for your n=5-8 pilot. Test the hardware integration with your Colab pipeline on yourself. Ensure there are no Bluetooth/streaming latency bottlenecks.
*   **Week 5:** **Draft Review & Internal Deadline (Sep 10).** Run 1-2 pilot participants to debug the flow. Assemble the drafted sections into a cohesive "v1" manuscript. Take a breath. You now have a complete technical draft and a working pilot setup 5 months ahead of the NIME deadline. 

## 4. Candid Risk Assessment

*   **The "Efficacy" Creep Risk:** Your biggest risk is inadvertently making efficacy claims in your writing. If you write "the system successfully calmed users," reviewers will demand proof. You must rigorously police your language to say "the system successfully tracked the arousal reference," maintaining the strict system/method framing.
*   **Hardware Integration Failure:** You haven't ordered the Polar H10 yet. Connecting a live Bluetooth LE heart rate monitor to a cloud-based Google Colab instance in real-time is notoriously finicky. If this bridge fails or introduces massive latency, your "closed-loop" claim falls apart. You need to test this connection immediately.
*   **Rejection Risk at NIME:** While NIME is a great fit, it is heavily demo-driven. If your MP4 demos sound robotic, clunky, or the transitions are jarring, NIME reviewers will reject it regardless of the elegant cascade controller logic. The audio output must clearly demonstrate the bidirectional mapping working smoothly.

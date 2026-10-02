# ADR 0012 — Fairness of the stop-and-wait baseline is non-negotiable

**Status:** Accepted · **Date:** 2026-10-02

## Context

The project's reported objective is a ≥20 % reduction in total task-completion time
against **stop-and-wait on overlapping routes**. Any competent team can produce a large
improvement against a badly implemented baseline. Such a number is not a result about
the coordination policy; it is a result about how much the baseline was handicapped.

The evaluator is also specified to be built **before** tuning, so that the comparison
is not shaped by the outcome it is meant to measure.

## Decision

1. **The baseline is a reasonable, correct implementation of stop-and-wait.** It is
   never weakened to manufacture a headline number.
2. The baseline uses the **same** actuator model — so its stops and starts cost the
   same acceleration time — the same safety gate, the same sensing including noise and
   latency, the same footprint and stopping-distance budget, the same planner and
   velocity profile, and a genuine wait rather than a sleep.
3. The **evaluator is defined and versioned before tuning.** Metric definitions,
   eligibility rules and seed sets are fixed first.
4. A result is reported **with the failing cases visible.** Excluded pairs, failure
   rates and reasons travel beside every aggregate.
5. If the measured improvement is negative or small, that is reported as the finding,
   with the bottleneck and the next experiment.

## Consequences

This is the decision most likely to make the headline number less impressive, which is
precisely why it is recorded as an ADR: it is a commitment made *before* knowing the
answer, and it is the commitment that makes the answer meaningful.

Two concrete disciplines follow:

- **The baseline pays real stopping costs.** A robot that stops at a stop line must
  ramp down and back up under the same acceleration limits. Removing that would give
  the baseline a different vehicle, not a different policy.
- **Failures are not deletable.** A baseline timeout is not an outlier to be trimmed.
  It is a data point about what stop-and-wait does under contention — often the most
  interesting thing in the dataset.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| **Weakened baseline** | Measures the handicap, not the policy |
| **Best-case baseline runs** | Cherry-picks the comparison in the baseline's favour |
| **Dropping failed seeds** | A timeout is exactly what stop-and-wait does badly; dropping it hides the effect under study |
| **Tuning on the held-out set** | Invalidates the held-out estimate silently |
| **Changing metric definitions after seeing results** | Selecting the definition that flatters the result |
| **Single unpaired run per policy** | Interleaving variance is indistinguishable from a policy effect |
| **Reporting only the mean** | One failed-but-fast run can dominate a mean; the median and the paired distribution carry the signal |
| **Post-hoc confidence interval** | A bootstrap from one observation looks rigorous and is not |

## Revisiting condition

Revisit only if the baseline is shown to be **unrepresentative** rather than
unfavourable — for example if measurement shows stop-and-wait implementations in the
published literature do not pay the stopping cost, meaning our baseline is not the
comparison the target refers to. That is an empirical claim requiring external
evidence, recorded in `docs/RESEARCH.md`.

If the baseline genuinely over-states the improvement, that must be **stated in the
report**, not corrected by quietly improving the candidate.

Changing the evaluator itself requires a **new evaluation version**. Re-tuning on a
final holdout without documenting that is forbidden.

## Verification

- `tests/integration/test_baseline_fairness.py` — both arms share actuator model,
  safety gate, sensor model and stopping budget
- `tests/integration/test_eligibility.py` — excluded pairs and failure rates are
  reported beside aggregates
- `docs/BENCHMARKS.md` — the measured result is recorded as **unmeasured** until a
  paired suite is executed, in either direction
- `docs/KNOWN_LIMITATIONS.md` §1 — the 20 % target is explicitly not claimed
- `docs/evidence/CLAIM_EVIDENCE.md` rows 3.7–3.9 — per-claim status
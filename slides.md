# Project Slides

---

## Slide 1: Title

**Correctness-Aware Caching for Agentic LLM Tool Calls**

Archit Kumar, Maaz Hussain, Divya Pothavajhyula, Rohan Tolani

---

## Slide 2: Motivation

**What is the problem?**

LLM agents solve tasks by making sequences of tool calls — fetching a stock price, checking the weather, looking up a trend — and using those results to reason toward a final answer. Because these tool calls are expensive (slow, paid APIs), caching their results is an obvious optimization. But caching introduces staleness: you might return an old value instead of the current one.

The problem is that in agentic systems, staleness is much more dangerous than in traditional systems. In a web cache, a stale result just means one response is slightly wrong. In an agentic workflow, a stale result at step 1 can corrupt the agent's reasoning across steps 2, 3, and 4, producing a completely wrong final answer. And the further upstream the stale call is, the more downstream reasoning it contaminates.

Existing caching approaches don't account for this. They optimize for hit rate, latency, or staleness age — none of which tell you whether the agent actually got the right answer. A cache can have a 90% hit rate and still produce wrong answers most of the time.

**Why does this matter?**

As agentic systems handle more real-world tasks — trading decisions, travel planning, medical triage — correctness is not optional. A caching layer that looks efficient by traditional metrics but silently degrades agent answer quality is worse than no caching at all, because it hides the problem.

---

## Slide 3: Approach

**How are we addressing it?**

We build a system that lets us directly measure whether caching hurts agent correctness, and then design a policy that minimizes that harm.

**Step 1 — Build a multi-step agent harness.**
We define structured agent tasks where the correct answer is known (ground truth). Example: "Should I buy, sell, or hold AAPL?" The agent fetches the current price (step 1), fetches the 30-day trend (step 2), and decides based on both (step 3). Ground truth is computed with fully fresh data. Correctness is whether the cached-data run agrees.

**Step 2 — Show the disconnect between hit rate and correctness.**
We run the same tasks under a fixed-TTL cache and show that high hit rates do not imply high correctness. This is the core empirical claim: existing metrics are misleading.

**Step 3 — Exploit workflow structure to do better.**
Not all tool calls are equally sensitive. Two signals drive this:
- **Downstream dependent count** — a call that feeds three downstream steps has a larger blast radius when stale than a leaf-node call. In a portfolio workflow, `get_price(AAPL)` might feed both a risk metric and a tax liability calculation, while `get_price(GOOG)` only feeds the risk metric. Both have the same change rate, but a stale AAPL corrupts more intermediate steps.
- **Workflow position** — upstream calls that gate branching decisions are especially damaging when stale because they don't just corrupt a value, they send the agent down the wrong branch entirely, suppressing downstream tool calls that should have happened.

We annotate each tool call with its position and number of downstream dependents, and use this to assign tighter TTLs to high-impact calls. Low-impact calls get looser TTLs to preserve hit rate where it's safe.

**What we are NOT doing:**
We are not doing semantic matching of tool calls, thundering herd mitigation, or bursty traffic optimization. Those are real problems but orthogonal to the correctness claim. We stay focused.

---

## Slide 4: Current Status

**Where are we now?**

The API Simulator is complete. It is a FastAPI server that mimics dynamic external APIs (stock prices and weather). Values change continuously over time at configurable rates — prices change fast, weather changes slowly. Every response includes version metadata (version number and last-changed timestamp) so we can measure staleness precisely against ground truth. This component is tested and running.

The Cache Gateway architecture is designed but not yet fully implemented. The interface is defined — agents send tool call requests with workflow context (step number, number of downstream dependents), and the gateway returns cached or fresh results based on the active policy. Pluggable policy logic is scaffolded.

The Agent Runner and correctness evaluation harness have not been started yet. This is the critical path for the rest of the project.

The load generator (k6 scripts) from the previous design is being retired. Simulating raw HTTP traffic was not agentic — it did not capture workflow structure or measure correctness.

---

## Slide 5: End Goal

**What do we expect to accomplish before the end of semester?**

By the end of the semester we will have:

1. **A working multi-step agent harness** with at least two task types (trading decision, travel advisory), each defined as a workflow with sequential tool dependencies. The harness runs each task with and without the cache, records the answers, and computes correctness.

2. **Three implemented cache policies:** no cache (always correct, high cost), fixed TTL (standard baseline), and workflow-aware TTL (our contribution). Each policy is configurable and outputs metrics.

3. **A correctness vs. cost Pareto frontier** across the three policies, showing that workflow-aware TTL achieves better correctness than fixed TTL at the same API cost — or equivalently, the same correctness at lower cost.

4. **Evidence that hit rate is a poor proxy for correctness** in agentic settings. Specifically: fixed TTL will have comparable or higher hit rates than workflow-aware TTL but lower correctness, because it treats all tool calls the same regardless of workflow position.

The goal is a clean, focused result: one concrete new metric (correctness), one concrete new policy (workflow-aware TTL), and one concrete empirical finding (hit rate misleads, workflow structure matters).

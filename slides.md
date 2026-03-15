# Project Slides

---

## Slide 1: Title

**Correctness-Aware Caching for Agentic LLM Tool Calls**

Archit Kumar, Maaz Hussain, Divya Pothavajhyula, Rohan Tolani

---

## Slide 2: Motivation

**What is the problem and why is it important?**

LLM agents solve tasks by making sequences of tool calls — fetching a stock price, checking the weather, looking up a trend — and using those results to reason toward a final answer. Because these tool calls are expensive (slow, paid APIs), caching their results is an obvious optimization. But caching introduces staleness: you might return an old value instead of the current one.

In agentic systems, staleness is much more dangerous than in traditional systems. In a web cache, a stale result just means one response is slightly wrong. In an agentic workflow, a stale result at step 1 can corrupt the agent's reasoning across steps 2, 3, and 4, producing a completely wrong final answer. The further upstream the stale call is, the more downstream reasoning it contaminates.

Existing caching approaches don't account for this. They optimize for hit rate, latency, or staleness age — none of which tell you whether the agent actually got the right answer. A cache can have a 90% hit rate and still produce wrong answers most of the time.

As agentic systems handle more real-world tasks — trading decisions, travel planning, medical triage — correctness is not optional. A caching layer that looks efficient by traditional metrics but silently degrades agent answer quality is worse than no caching at all, because it hides the problem.

---

## Slide 3: Approach

**How are we going to address it?**

We build a system that directly measures whether caching hurts agent correctness, and then design a policy that minimizes that harm.

**Step 1 — Build a multi-step agent harness using LangGraph.**
We define agent tasks as LangGraph DAGs. Each node is a tool call; edges define data dependencies. LangGraph's graph structure gives us workflow context automatically: downstream dependent count from graph edges, workflow step from topological depth. No manual annotation needed. Each task runs once through the cache gateway (potentially stale); ground truth is a direct fresh call to the API simulator. No-cache is correct by definition — it is our cost baseline, not a comparison run.

**Step 2 — Show the disconnect between hit rate and correctness.**
We run tasks under a fixed-TTL cache and show that high hit rates do not imply high correctness. This is the core empirical claim: existing metrics are misleading.

**Step 3 — Exploit workflow structure to do better.**
Not all tool calls are equally sensitive. Two signals drive the workflow-aware TTL policy:
- **Downstream dependent count** — a call feeding three downstream steps has a larger blast radius when stale than a leaf-node call. Same change rate, different impact.
- **Workflow position** — upstream calls that gate branching decisions are especially damaging when stale: they don't just corrupt a value, they send the agent down the wrong branch entirely, suppressing downstream calls that should have happened.

The cache gateway reads DAG structure at runtime and assigns tighter TTLs to high-impact calls, looser TTLs where it's safe. We are not doing semantic matching, thundering herd mitigation, or bursty traffic optimization — those are orthogonal to the correctness claim.

---

## Slide 4: Current Status

**Where are we now?**

The **API Simulator** is complete. It is a FastAPI server with four endpoints: price, trend, news_sentiment, and weather. Each key's value changes continuously via a background Poisson update loop at a configurable rate — prices change every ~20s, sentiment every ~50s, weather every ~3 min, trend every ~15 min. Every response includes a version number and last-changed timestamp so staleness can be measured precisely against ground truth.

The **Cache Gateway** is partially complete. The infrastructure is built: a FastAPI gateway that accepts tool call requests with workflow context (step depth, downstream dependent count), an in-memory cache store, and a pluggable policy interface. Two policies are implemented: `none` (always calls upstream — correctness baseline) and `fixed_ttl` (one TTL per tool type — the standard Redis-equivalent baseline). The workflow-aware TTL policy — our actual contribution — is not yet implemented.

The **LangGraph agent** and correctness evaluation harness have not been started. This is the critical path for the rest of the project. We have chosen LangGraph because its native DAG representation directly provides the workflow structure the cache gateway needs — downstream dependent count from graph edges, workflow step from topological depth — without any manual annotation.

---

## Slide 5: End Goal

**What do we expect to accomplish before the end of semester?**

By the end of the semester we will have:

1. **A LangGraph-based agent harness** with two stock-based task types (investment decision, portfolio rebalancing), each defined as a LangGraph DAG. Each task runs once through the gateway under the policy under test; correctness is measured against a direct fresh call to the simulator. No-cache is correct by definition and serves as the cost baseline. A weather-based workflow is a stretch goal.

2. **Three implemented cache policies:** no cache (always correct, high cost), fixed TTL (standard baseline), and workflow-aware TTL (our contribution). Each policy is configurable and outputs metrics.

3. **A correctness vs. cost Pareto frontier** across the three policies, showing that workflow-aware TTL achieves better correctness than fixed TTL at the same API cost — or equivalently, the same correctness at lower cost.

4. **Evidence that hit rate is a poor proxy for correctness** in agentic settings. Specifically: fixed TTL will have comparable or higher hit rates than workflow-aware TTL but lower correctness, because it treats all tool calls the same regardless of workflow position.

The goal is a clean, focused result: one concrete new metric (correctness), one concrete new policy (workflow-aware TTL), and one concrete empirical finding (hit rate misleads, workflow structure matters).

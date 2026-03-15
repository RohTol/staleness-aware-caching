# Cache Behavior Examples

Concrete walkthroughs of what happens with and without the cache for two key workflow shapes.

---

## How the cache works

The cache is shared across all agents and all workflows. The key is `(tool, args)` — e.g. `(price, {ticker: "AAPL"})`. Any agent asking for the same tool + args gets the same cached result, as long as the TTL hasn't expired. TTL is the only thing controlling freshness.

Workflows are defined as LangGraph DAGs. The cache gateway receives workflow context (step depth, downstream dependent count) derived automatically from the graph structure on each tool call.

---

## Example 1: Investment Decision (branching chain)

**Workflow:**
```
get_price(AAPL)                              ← fast, ~1 change per 20s
    ↓
IF price dropped > 2% vs baseline:
    get_news_sentiment(AAPL)                 ← medium, ~1 change per 50s
        ↓
    IF sentiment < -0.3: SELL
    ELSE: HOLD
ELSE:
    get_trend(AAPL)                          ← slow, ~1 change per 15 min
        ↓
    IF price > trend * 1.05: SELL (overbought)
    ELSE: BUY or HOLD
```

**Downstream dependents (from LangGraph graph edges):**
- `get_price(AAPL)` → 3 dependents (branch selection, sentiment/trend call, final decision)
- `get_news_sentiment(AAPL)` → 1 dependent (final decision)
- `get_trend(AAPL)` → 1 dependent (final decision)

---

### Without cache (cost baseline)

No-cache always hits the API fresh, so it is always correct by definition. It is the cost ceiling — not a separate comparison run. Ground truth for the other policies is a direct fresh API call, not a no-cache policy run.

```
Agent A at T=0:
  get_price(AAPL)        → API call → $182, dropped 3%   ✓
  price dropped → get_news_sentiment(AAPL) → API call → -0.6 (negative) ✓
  sentiment < -0.3 → decision: SELL ✓

Agent B at T=10s (same query):
  get_price(AAPL)        → API call → $182  ✓
  ... same result, full API cost again
```

Every agent pays full API cost. Always correct — but at maximum cost.

---

### With fixed TTL = 60s

```
Agent A at T=0:
  get_price(AAPL)        → MISS → $182, dropped 3%    [cached, TTL=60s]
  get_news_sentiment     → MISS → -0.6 (negative)     [cached, TTL=60s]
  decision: SELL ✓

-- price recovers at T=30s: AAPL back to $187, only down 0.5% --
-- news sentiment flips at T=40s: +0.4 (positive, recovery story) --

Agent B at T=50s:
  get_price(AAPL)        → HIT → $182, "dropped 3%"  ✗ STALE (actual: only down 0.5%)
  stale price triggers wrong branch → get_news_sentiment → HIT → -0.6 ✗ STALE (actual: +0.4)
  decision: SELL ✗  (should have been: BUY or HOLD)
```

Both stale hits compound: wrong branch taken, wrong sentiment used, wrong decision. 4 out of 4 calls were hits, 0 out of 4 were correct.

---

### With workflow-aware TTL

`get_price` has 3 downstream dependents and the fastest change rate → tight TTL (15s).
`get_news_sentiment` has 1 downstream dependent and medium change rate → moderate TTL (30s).
`get_trend` has 1 downstream dependent and the slowest change rate → loose TTL (10 min).

```
Agent A at T=0:
  get_price(AAPL)        → MISS → $182, dropped 3%    [cached, TTL=15s]
  get_news_sentiment     → MISS → -0.6                [cached, TTL=30s]
  decision: SELL ✓

-- price recovers at T=30s, sentiment flips at T=40s --

Agent B at T=50s:
  get_price(AAPL)        → EXPIRED → fresh call → $187, down 0.5%  ✓
  0.5% drop, not > 2% → takes other branch → get_trend(AAPL)
  get_trend(AAPL)        → MISS → $183 avg            [cached, TTL=10min] ✓
  price slightly above trend → decision: HOLD ✓
```

Agent B gets the right answer. The tight TTL on `get_price` forced a fresh lookup that corrected the branch, saving Agent B from two stale downstream calls.

---

## Example 2: Portfolio Rebalancing (fan-in, downstream dependent count)

**Workflow:**
```
get_price(AAPL)  ──┬──→  get_risk_metric(portfolio)  →  decide: rebalance or hold
                   └──→  get_tax_liability(AAPL)      →  decide: sell timing
get_price(GOOG)  ──┤
                   └──→  get_risk_metric(portfolio)
get_price(MSFT)  ──┘
```

**Downstream dependents:**
- `get_price(AAPL)` → 3 dependents (risk metric, tax liability, final decision)
- `get_price(GOOG)` → 2 dependents (risk metric, final decision)
- `get_price(MSFT)` → 2 dependents (risk metric, final decision)
- `get_risk_metric` → 1 dependent (final decision)
- `get_tax_liability` → 1 dependent (final decision)

All price calls have the same change rate (~every 20s). But `get_price(AAPL)` has a larger blast radius — it feeds two intermediate calculations instead of one.

---

### With fixed TTL = 30s — Agent B runs at T=25s, AAPL has changed

```
get_price(AAPL)         → HIT → $182  ✗ stale (actual: $178, dropped on bad earnings)
get_price(GOOG)         → HIT → $155  ✓
get_price(MSFT)         → HIT → $412  ✓

get_risk_metric         → computed from stale AAPL → wrong
get_tax_liability(AAPL) → computed from stale AAPL → wrong

decide: HOLD            ✗  (should have been: SELL AAPL)
```

Two intermediate steps corrupted by one stale call. The extra downstream dependent made the damage worse.

---

### With workflow-aware TTL

`get_price(AAPL)` has 3 downstream dependents → tighter TTL (15s).
`get_price(GOOG)` and `get_price(MSFT)` have 2 → standard TTL (30s).

```
Agent B at T=25s:
  get_price(AAPL)         → EXPIRED → fresh API call → $178  ✓
  get_price(GOOG)         → HIT → $155  ✓
  get_price(MSFT)         → HIT → $412  ✓

  get_risk_metric         → correct
  get_tax_liability(AAPL) → correct

  decide: SELL AAPL       ✓
```

One extra API call (AAPL), everything else cached. Both intermediate steps correct. Right final decision.

---

## The core point

Downstream dependent count is a proxy for **blast radius** — how many things go wrong if this call is stale. Workflow-aware TTL uses this to allocate freshness selectively:

- Tighten TTL where upstream position and high fan-out make staleness most damaging
- Relax TTL where calls are downstream, isolated, or slow-changing

A generic cache like Redis cannot do this on its own — it has no knowledge of the workflow DAG. That's what makes this contribution agentic-specific.

**The result this sets up:** workflow-aware TTL may have a lower overall hit rate than fixed TTL, but higher correctness — because the misses are happening on the right calls.

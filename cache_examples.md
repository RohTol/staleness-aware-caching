# Cache Behavior Examples

Concrete walkthroughs of what happens with and without the cache for two key workflow shapes.

---

## How the cache works

The cache is shared across all agents and all workflows. The key is `(tool, args)` — e.g. `(weather, {city: "NYC", day: "Friday"})`. Any agent asking for the same tool + args gets the same cached result, as long as the TTL hasn't expired. TTL is the only thing controlling freshness.

---

## Example 1: Trip Planning (branching chain)

**Workflow:**
```
get_weather(NYC, Friday)
get_weather(NYC, Saturday)
    ↓
IF both good:
    get_flight_price(NYC→LA)
        ↓
    IF price < budget:
        get_hotel(LA)
            ↓
        decide: BOOK
ELSE:
    decide: DON'T BOOK
```

**Downstream dependents:**
- `get_weather(NYC, Friday)` → 3 dependents (Saturday check, flight, hotel, decision)
- `get_weather(NYC, Saturday)` → 3 dependents
- `get_flight_price` → 2 dependents (hotel, decision)
- `get_hotel` → 1 dependent (decision)

---

### Without cache

```
Agent A at T=0:
  get_weather(NYC, Friday)   → API call → 72°F, sunny   ✓
  get_weather(NYC, Saturday) → API call → 68°F, cloudy  ✓
  both good → get_flight_price(NYC→LA) → API call → $320 ✓
  price < budget → get_hotel(LA) → API call → available  ✓
  decision: BOOK ✓

Agent B at T=10s (same query):
  get_weather(NYC, Friday)   → API call → 72°F, sunny   ✓
  ... same result, same cost
```

Every agent pays full API cost. Always correct.

---

### With fixed TTL = 5 min

```
Agent A at T=0:
  get_weather(NYC, Friday)   → MISS → API call → 72°F, sunny   [cached, TTL=5min]
  get_weather(NYC, Saturday) → MISS → API call → 68°F, cloudy  [cached, TTL=5min]
  both good → get_flight_price → MISS → $320                   [cached, TTL=5min]
  get_hotel → MISS → available                                  [cached, TTL=5min]
  decision: BOOK ✓

-- real weather changes at T=2min: NYC Friday → 40°F, thunderstorm --

Agent B at T=3min:
  get_weather(NYC, Friday)   → HIT → 72°F, sunny   ✗ STALE (actual: thunderstorm)
  get_weather(NYC, Saturday) → HIT → 68°F, cloudy  ✓
  both "good" → get_flight_price → HIT → $320
  get_hotel → HIT → available
  decision: BOOK ✗  (should have been: DON'T BOOK)
```

High hit rate, wrong answer. Agent B booked a trip into a thunderstorm.

Note also: because step 1 was stale, the agent never even reconsidered the branch. It didn't just get a wrong number — it took the entirely wrong path through the workflow.

---

### With workflow-aware TTL

`get_weather` is at step 1 with high downstream dependents and a high change rate → tight TTL (1 min).
`get_flight_price` is at step 3 with fewer dependents and changes slowly → loose TTL (10 min).

```
Agent A at T=0:
  get_weather(NYC, Friday)   → MISS → API call → 72°F, sunny   [cached, TTL=1min]
  get_weather(NYC, Saturday) → MISS → API call → 68°F, cloudy  [cached, TTL=1min]
  get_flight_price           → MISS → $320                     [cached, TTL=10min]
  get_hotel                  → MISS → available                 [cached, TTL=5min]
  decision: BOOK ✓

-- real weather changes at T=2min --

Agent B at T=3min:
  get_weather(NYC, Friday)   → EXPIRED → API call → 40°F, thunderstorm ✓
  weather not good → decision: DON'T BOOK ✓
  (flight + hotel calls never happen → upstream correction saved downstream cost)
```

Agent B pays for one weather call and gets the right answer. Flight and hotel calls are avoided entirely because the upstream decision is correct. Lower correctness cost than fixed TTL, and still cheaper than no-cache on average because stable downstream calls remain cached.

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

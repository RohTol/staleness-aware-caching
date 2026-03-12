# Agentic Workflow Examples

These are the workflows we use for evaluation. All tool calls map to simulator endpoints backed by two real data sources:
- **yfinance** — minute-by-minute stock prices and historical data → `/price`, `/trend`
- **meteostat** — hourly weather data → `/weather`
- **simulated** — news sentiment (no clean real-time source) → `/news_sentiment`

A good workflow for our purposes has:
- Genuine branching: later tool calls are chosen *based on* earlier results, not just chained
- A final answer that requires synthesizing several pieces of information
- Tool calls with clearly different change rates, so workflow-aware TTL has something to exploit

---

## Change Rate Reference

| Endpoint | Rate | Roughly |
|---|---|---|
| `/trend?ticker=` | very slow | ~1 change per 15 min |
| `/weather?city=` | slow | ~1 change per 3 min |
| `/news_sentiment?ticker=` | medium | ~1 change per 50s |
| `/price?ticker=` | fast | ~1 change per 20s |

---

## Workflow 1: Investment Decision (stock, branching chain)

**Question the agent answers:** "Should I buy, sell, or hold AAPL?"

**Shape:** linear chain with conditional branch

```
get_price(AAPL)                          ← fast, changes every ~20s
    ↓
IF price dropped > 2% vs trend:
    get_news_sentiment(AAPL)             ← medium, only called conditionally
        ↓
    IF sentiment < -0.3: SELL
    IF sentiment >= -0.3: HOLD
ELSE:
    get_trend(AAPL)                      ← slow, only called if price looks stable
        ↓
    IF price > trend * 1.05: SELL (overbought)
    ELSE: BUY or HOLD
```

**Why it's interesting:**
- `get_price` gates the branch. A stale price doesn't just return a wrong number — it determines which branch the agent takes. The agent might skip the sentiment check entirely, or check it when it shouldn't.
- `get_news_sentiment` and `get_trend` are only called conditionally, so staleness upstream suppresses downstream tool calls entirely.
- Three different change rates in one workflow: the TTL needed for each call is completely different.

**Downstream dependents:**
- `get_price(AAPL)` → 3 dependents (branch selection, sentiment/trend call, final decision)
- `get_news_sentiment(AAPL)` → 1 dependent (final decision)
- `get_trend(AAPL)` → 1 dependent (final decision)

---

## Workflow 2: Portfolio Rebalancing (stock, parallel fan-in)

**Question the agent answers:** "Which of my holdings should I rebalance?"

**Shape:** parallel price lookups → risk computation → decision

```
get_price(AAPL)  ──┬──→  compute_risk_metric(portfolio)  →  decide: rebalance or hold
                   └──→  compute_tax_liability(AAPL)      →  decide: sell timing
get_price(GOOG)  ──┤
                   └──→  compute_risk_metric(portfolio)
get_price(MSFT)  ──┘
                   └──→  compute_risk_metric(portfolio)
```

`compute_risk_metric` and `compute_tax_liability` are computed by the agent from the prices — they are not external calls.

**Why it's interesting:**
- All three price calls have the same change rate, but `get_price(AAPL)` feeds two downstream computations (risk + tax) while GOOG and MSFT each feed only one (risk). So AAPL has a larger blast radius even though the change rates are identical.
- This is the clearest demonstration that downstream dependent count matters independently of change rate. A policy based only on change rate (like fixed TTL per tool type) gets this wrong.

**Downstream dependents:**
- `get_price(AAPL)` → 3 dependents (risk metric, tax liability, final decision)
- `get_price(GOOG)` → 2 dependents (risk metric, final decision)
- `get_price(MSFT)` → 2 dependents (risk metric, final decision)

---

## Workflow 3: Weather-Based Event Decision (weather, branching chain)

**Question the agent answers:** "Should I schedule the outdoor event this weekend?"

**Shape:** sequential weather checks with conditional branch

```
get_weather(city, Saturday)              ← slow, changes hourly
    ↓
IF Saturday looks good:
    get_weather(city, Sunday)            ← only checked if Saturday is viable
        ↓
    IF both good: SCHEDULE
    ELSE: MOVE INDOORS
ELSE:
    CANCEL
```

**Why it's interesting:**
- Stale weather on Saturday can cause the agent to check Sunday when it shouldn't (or skip checking Sunday when it should). The second tool call is suppressed or triggered incorrectly based on the first.
- Simple structure that cleanly isolates the branch suppression effect — no arithmetic, just a threshold decision.
- Easiest workflow to build ground truth for: correct answer is determined entirely by the two weather values.

**Downstream dependents:**
- `get_weather(city, Saturday)` → 2 dependents (Sunday check, final decision)
- `get_weather(city, Sunday)` → 1 dependent (final decision)

---

## Summary

| Workflow | Endpoints used | Key structural feature |
|---|---|---|
| Investment Decision | price + news_sentiment + trend | Branching suppresses downstream calls; 3 different change rates |
| Portfolio Rebalancing | price × 3 | Same change rate, different blast radius from downstream dependent count |
| Weather Event | weather × 2 | Cleanest branch suppression example; easy ground truth |

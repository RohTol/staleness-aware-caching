# Agentic Workflow Examples

These are candidate workflows for the project. A good workflow for our purposes has:
- Multiple tool calls where later calls are chosen *based on* earlier results (branching, not just chaining)
- A final answer that requires synthesizing several pieces of information
- Tool calls with clearly different change rates, so workflow-aware TTL has something to exploit

---

## Finance / Stock

### Portfolio Rebalancing Agent
**Shape:** parallel fan-in → aggregation → decision

```
get_price(AAPL)  ──┐
get_price(GOOG)  ──┼──→  get_risk_metric(portfolio)  →  decide: rebalance or hold
get_price(MSFT)  ──┘
                         (also uses: get_sector_trend(tech))
```

**Why it's interesting:** Staleness in any one price call corrupts the risk metric, which corrupts the final rebalancing decision. Multiple levels of dependency. The sector trend changes slowly (loose TTL is fine); the individual prices change fast (tight TTL needed).

---

### Earnings Reaction Agent
**Shape:** linear chain with conditional branch

```
get_price(AAPL)
    ↓
get_earnings_surprise(AAPL)
    ↓
IF beat:  get_peer_prices([GOOG, MSFT, AMZN])  →  decide: rotate into peers
IF miss:  decide: sell AAPL
```

**Why it's interesting:** A stale `get_earnings_surprise` doesn't just return a wrong number — it causes the agent to take the wrong branch entirely, skipping the peer lookup. The downstream damage is structural, not just numerical. This is one of the strongest arguments that agentic staleness is categorically different from web cache staleness.

---

### Sentiment-Adjusted Position Agent
**Shape:** parallel calls with different change rates → decision

```
get_price(ticker)           ← changes every ~20s
get_news_sentiment(ticker)  ← changes with news cycles, fast
get_analyst_rating(ticker)  ← changes rarely (weekly/monthly)
    ↓
decide: sentiment-adjusted buy/sell/hold
```

**Why it's interesting:** Two tools with very different change rates feeding the same decision. Makes the workflow-aware TTL argument clean and concrete — news sentiment needs a tight TTL, analyst rating can safely have a loose one. Same API call structure, very different caching behavior.

---

## Weather / Travel

### Trip Planning Agent
**Shape:** linear chain with conditional branches

```
get_weather(destination, Friday)
get_weather(destination, Saturday)
    ↓
IF both good:
    get_flight_price(origin, destination)
        ↓
    IF price < budget:
        get_hotel_availability(destination)
            ↓
        decide: book trip
ELSE:
    decide: don't book
```

**Why it's interesting:** Stale weather at step 1 can cause the agent to skip the flight lookup entirely — the cache miss doesn't just corrupt a value, it suppresses entire downstream tool calls. The further upstream the stale call, the more work gets skipped or misdirected.

---

### Event Planning Agent
**Shape:** parallel calls, one dependent on another's output

```
get_weather(city)
get_venue_availability(city, date)
    ↓
get_expected_attendance(event_type, weather=<step1 result>)
    ↓
decide: indoor vs outdoor venue, capacity to book
```

**Why it's interesting:** `get_expected_attendance` takes the weather result as an input argument, so staleness in step 1 propagates directly into a wrong tool call argument in step 3 — not just wrong reasoning, but a wrong API call.

---

## Recommended picks for the paper

Use two workflows that cover different dependency shapes:

| Workflow | Shape | Why |
|---|---|---|
| Portfolio Rebalancing | Parallel fan-in | Multiple stale inputs degrade a shared aggregation step |
| Trip Planning / Earnings Reaction | Branching chain | Staleness suppresses entire branches, not just values |

These two shapes cover the interesting cases and give you distinct stories for how workflow position matters. A third workflow (e.g. Sentiment-Adjusted Position) can be included to show the change-rate contrast that motivates workflow-aware TTL.

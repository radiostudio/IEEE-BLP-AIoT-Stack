# System Workflows: Edge Loop First, Agentic Cloud Loop as Extension

**Context:** the workshop runs with each student's laptop as the gateway. Not
every student has an LLM subscription, so the course completes the entire
edge loop with zero LLM dependency; the agentic cloud loop is then an
extension that adds a model to an already-working system. This ordering is
also pedagogically right: students first play the agent's role by hand, so
when the model takes over that role they know exactly what it is doing.

---

## 1. SIM software workflow (firmware, runs identically in both loops)

```
BOOT
 |- power_init        sensor rail ON, battery sense armed
 |- seq_store_init    per-sensor counters restored from NVS (resume ahead: no phantom loss)
 |- adv_init          BLE up, 100 ms advertisement repeat
 |- fault_init        serial console armed (instructor channel)
 |- selftest          each enabled module: init() x3 retries -> present / ABSENT
 |                    (an absent sensor still advertises, flagged not-ok)
 v
LOOP (every 10 ms)
 |- fault_poll_serial       instructor commands: fault N stuck|offset|drop|none, cal12 dry/wet
 |- for each module at its period (staggered so multi-sensor SIMs rotate):
 |    sample()              driver reads hardware; NEVER fabricates on failure
 |    status = ok? | low_batt?                    every failure is a bit, not a guess
 |    fault_apply()         stuck/offset transform payload + set fault_injected; drop skips frame
 |    seq_next()            one seq per reading (radio repeats reuse it)
 |    adv_publish()         11-byte contract header + card-defined payload
 v
(no sleep: continuous advertising is the power-bank keep-alive)
```

The SIM has no concept of edge versus cloud loop. It measures, stamps, and
broadcasts. Everything above it decides what the data means.

## 2. Gateway software workflow (student laptop, both loops)

```
python -m gateway run          (or `simulate` when no hardware is present)
 |
 BLE advertisement arrives (any SIM in range; broadcast, so every laptop hears every SIM)
 |- filter: company ID (and kit_id if configured)
 |- parse: 11-byte header + payload          (core.py, the contract)
 |- dedupe: same (kit,type,seq) seen?        radio repeats collapse to one reading
 |- decode: card registry resolves (type_id, schema) -> fields in engineering units
 |- reconcile: seq gap -> delivery ratio; tick_ms vs arrival -> jitter-free timestamp
 |- store: SQLite WAL (readings, sensors, annotations, experiments)
 |- rules: engine evaluates approved rules against latest values  <- THE EDGE LOOP LIVES HERE
 |- dashboard: http://127.0.0.1:8931/ live table (thin, for the bench)
```

Interfaces on top of the store, by loop:

| Surface | Needs LLM? | Used in |
|---|---|---|
| Dashboard (browser) | No | Phase A |
| `python -m gateway tool <name> ...` (CLI tools) | No | Phase A |
| Rule files + `approve-rule` | No | Phase A |
| `python -m gateway recipe <name>` offline evidence packs | No | Phase A/bridge |
| MCP server (`python -m gateway mcp`) + Claude | Yes | Phase B |

## 3. Phase A: the edge loop, zero LLM (the complete base course)

**The trick that makes this work pedagogically: in Phase A, the student IS
the agent.** Every step below is exactly what the model will do in Phase B,
performed by hand through the same tool functions. The CLI calls the same
code the MCP server exposes, so nothing is a toy substitute.

### A1. Bring-up (perception)

```
python -m gateway run                      # laptop becomes the gateway
python -m gateway tool list_sensors        # discover: what can I sense? (= agent's list_sensors)
python -m gateway tool describe_sensor 6   # read the contract: ranges, accuracy, failure modes
python -m gateway tool read_latest 1:6     # perceive: current CO2
```

Checkpoint: every sensor online, delivery ratio near 1.0. Walk the SIM away
and watch the ratio fall: the QoS lesson, no AI involved.

### A2. Validate (doubt)

```
python -m gateway tool validate_reading 1:1 temperature_c        # verdict on the live value
python -m gateway tool validate_reading 1:1 temperature_c 1000   # what would the system say to 1000 C?
```

Instructor injects `fault 1 stuck` on the SIM console. Students must catch it
from data alone (hint: validate's rate-of-change reasoning, and the card's
failure modes). This is the adversarial validation lab, human edition.

### A3. Context (the journal)

```
python -m gateway tool annotate "window opened for cleaning" 1:6
```

Students learn WHY context needs a channel: the CO2 dip they just recorded is
unexplainable a week later without this note. In Phase B the agent asks for
this context; in Phase A they discipline themselves to record it.

### A4. Act: the rule lifecycle (the heart of the edge loop)

```
1. AUTHOR   copy rules/rules.d/corridor_lighting.json to my_rule.json.pending
            edit conditions against the card: sensors, fields, thresholds, for_s
2. DEPLOY   the .pending suffix = staged, not running
3. APPROVE  python -m gateway approve-rule my_rule      (the human gate, kept even when
                                                         the author is human: the habit matters)
4. OBSERVE  rule fires appear on the console and in the journal
5. MEASURE  python -m gateway tool query_timeseries 1:11 load_current_rms_a 120 mean
            did the rule change the measured energy? (predict first, then look)
```

Rules are deterministic JSON: conditions (`sensor`, `field`, `op`, `value`,
`for_s`/`within_s`), `on_fault: skip` (bad data never drives action), an
action, a cooldown. Everything a student needs to author one is on the sensor
card. No model in the loop, by design: this is the loop that must work when
the cloud is gone, and Phase A proves the whole course runs on it.

### A5. Fusion without a model

`python -m gateway recipe occupancy` builds an offline evidence pack (JSON):
aligned series from PIR + SPL + CO2 + reed, each with its validation verdict
and delivery ratio, plus the journal. In Phase A, students reason over the
pack themselves and defend an occupancy verdict in class. The pack is
deliberately the same artifact the model receives in Phase B, so Phase B
becomes: "the thing you did last week, delegated."

## 4. Phase B: the agentic cloud loop (the extension)

### The role handover

| Agentic step | Phase A (student) | Phase B (agent) |
|---|---|---|
| Discover | `tool list_sensors` | model calls `list_sensors` |
| Read contract | `tool describe_sensor` | model reads the card, plans around accuracy bands |
| Perceive | `tool read_latest` / dashboard | model queries series, chooses windows itself |
| Doubt | `tool validate_reading` | model validates before trusting, cites verdicts |
| Contextualize | remember to annotate | model ASKS the user, then annotates |
| Fuse | reason over the evidence pack | model builds and reasons over the pack |
| Act | hand-author rule, human approves | model authors the rule; SAME human approval gate |
| Audit | query kWh, compare by hand | model closes the loop on its own recommendation |

Nothing new appears in the system in Phase B except the reasoner. Every tool,
every gate, every artifact is the one Phase A already exercised. That is the
course's central design: the agentic extension changes WHO reasons, never
what is possible or what is governed.

### B1. Connect a model

```
python -m gateway mcp        # stdio MCP server; register in the MCP client's config
```

Access options where subscriptions are scarce, in preference order:
1. **Shared instructor account** driving one MCP-connected client, projected;
   students take turns phrasing the questions (works for a whole class).
2. **Free-tier Claude Desktop** where available to students (MCP works on
   local stdio servers; usage limits apply, fine for exercises).
3. **Bring-your-own-key or local model** through any MCP-capable client;
   `recipe` online mode also accepts an API key via ANTHROPIC_API_KEY.
4. **No access at all:** the student still runs Phase B logic through the
   offline evidence packs and peer-reviews a subscribed teammate's agent
   transcript; the assessment (below) is designed so this is not a lesser role.

### B2. The cloud-loop session shape

```
Student: "Is this room healthy, and is the AC earning its bill?"   (capstone C1)
 Agent: list_sensors -> describe_sensor (cards) -> asks where sensors are mounted
        -> annotate answers -> capture_experiment over a class day
        -> query_timeseries (aligned on reconciled time)
        -> validate_reading on every stream it is about to trust
        -> verdict with evidence, caveats, and the ONE thing to check physically
        -> proposes a rule spec -> deploy_rule (lands PENDING)
Student: reviews the JSON against the cards      <- the student now audits the agent,
python -m gateway approve-rule ...                  which they can do BECAUSE of Phase A
 Agent (next week): queries measured kWh, compares to its own prediction, reports honestly
```

### B3. Watchdogs (agentic, scheduled)

`python -m gateway liveness` (cron/Task Scheduler): flags silent sensors into
the journal ("Is Silence Good News?"). `recipe` runs on schedule build packs;
with a key the model reviews them, without one they queue for class review.

## 5. Assessment aligned to the two phases

- **Phase A passes when:** every sensor validated with the card in hand; one
  injected fault caught from data with the reasoning written down; one rule
  authored, approved, and its effect MEASURED (predict-then-measure); one
  evidence pack argued to a verdict in class.
- **Phase B passes when:** the student can audit an agent, not merely prompt
  it: catch one agent conclusion that the evidence does not support (the
  instructor seeds one via fault injection), approve or reject the agent's
  rule with reasons referenced to the cards, and explain where the agent is
  and is not allowed to act, and why.

## 6. One-page cheat sheet (print for the workshop)

```
GATEWAY        python -m gateway run | simulate | dashboard | smoke
SEE            http://127.0.0.1:8931/
TOOLS (no LLM) python -m gateway tool list_sensors
               python -m gateway tool describe_sensor <type>
               python -m gateway tool read_latest <kit:type>
               python -m gateway tool validate_reading <kit:type> <field> [value]
               python -m gateway tool query_timeseries <kit:type> <field> [minutes] [mean|min|max]
               python -m gateway tool annotate "<note>" [kit:type]
RULES          edit gateway/rules/rules.d/<name>.json.pending
               python -m gateway approve-rule <name>
FUSION         python -m gateway recipe occupancy | cold_chain
WATCHDOG       python -m gateway liveness
AGENT (LLM)    python -m gateway mcp   (register in the MCP client config)
SIM CONSOLE    fault <type> stuck|offset|drop|none, status, cal12 dry|wet  (115200 baud)
```

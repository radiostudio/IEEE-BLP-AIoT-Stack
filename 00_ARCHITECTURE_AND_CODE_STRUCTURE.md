# AIoT and Climate Change: AI-First Course Architecture and Code Structure

**Supersedes:** the architecture sections of `RS_IEEE - Sensor Interface Manual_REV5.pptx`
**Incorporates:** `AIoT_Climate_Change_Kit_AI-First_Review.md` (sensor cards, MCP gateway, two loops) and `additional_sensors_1.md` (nine new sensors)
**Date:** 5 August 2026

---

## 1. What Changed From Rev5

| Aspect | Rev5 | This course |
|---|---|---|
| Sensor count | 7 | 14 |
| SIM assignment | Mixed (PIR shared SENSIM-001 with DS18B20) | 5 SIMs, one per electrical interface |
| Gateway | Raspberry Pi 4, fixed | Edge device contract: Raspberry Pi or Arduino Uno Q, laptop as tier-0 fallback |
| AI role | Cloud dashboard, analytics bolted on | MCP server is the product surface; agents orchestrate sensing, inference, and action |
| Curriculum spine | Sensor-by-sensor chapters | Sensors as functional building blocks; capstone questions force fusion, validation, action |
| Data contract | Human-readable manual | Machine-readable sensor cards resolved from the BLE payload |

## 2. The Sensor Set and SIM Mapping

All five SIMs are built around the ESP32. They differ only in the front-end interface circuitry and the sensor driver compiled into the firmware. Every SIM powers its sensor, runs from a USB power bank for field deployment, and broadcasts BLE advertisement packets. BLE advertisements give tens of metres of range indoors, so the edge device does not need to sit next to the sensor.

| # | Sensor | Measurand | SIM | Interface |
|---|--------|-----------|-----|-----------|
| 1 | DS18B20 | Temperature | SIM1 | One-Wire |
| 2 | BME688 | Gas / IAQ, T, RH, P | SIM2 | I2C |
| 3 | PIR | Motion | SIM3 | GPIO |
| 4 | Industrial transmitters (4-20 mA) | Wind speed, level, pressure, etc. | SIM4 | Analog |
| 5 | Industrial digital sensors | Soil probe, energy meter, etc. | SIM5 | RS485 / Modbus RTU |
| 6 | SCD41 | CO2 | SIM2 | I2C |
| 7 | VEML7700 | Illuminance (lux) | SIM2 | I2C |
| 8 | SPL (MEMS mic + envelope) | Sound pressure level | SIM4 | Analog |
| 9 | JSN-SR04T | Distance / level | SIM4 | Pulse-width (see note) |
| 10 | Reed switch | Open/closed state | SIM3 | GPIO |
| 11 | SCT-013 | AC current | SIM4 | Analog |
| 12 | SEN0193 (DFRobot) | Soil moisture | SIM4 | Analog |
| 13 | Water level (RadioStudio bare-trace PCB) | Water presence/level | SIM4 | Analog (resistive) |
| 14 | AT42QT1010 | Proximity / touch | SIM3 | GPIO |

🔴 **Interface note on the JSN-SR04T (high confidence):** the JSN-SR04T does not output an analog voltage. Its native interface is trigger/echo pulse-width (or UART on some variants). Assigning it to SIM4 works only because the ESP32 on SIM4 has spare GPIO: the echo pulse is timed by GPIO interrupt capture, exactly the mechanism SIM3 uses for PIR edges. The slides list it under SIM4 as directed, but the firmware path is `pulse_capture`, not `adc`. If SIM4's connector does not expose two GPIO lines (trigger out, echo in), this sensor must move to SIM3.

## 3. System Architecture

```
[Packaged Sensor] --keyed harness--> [SIM (ESP32)] --BLE adv--> [Edge Device] --MQTT/HTTPS--> [Cloud + MCP Server] <--> [Agents / Claude]
                                          |                          |
                                    powers sensor,            BLE scan, decode via
                                    interface driver,         sensor cards, SQLite
                                    payload builder           timeseries, local MCP,
                                                              edge rule engine
```

Two loops, honestly separated (from the AI-first review):

- **Edge loop (cloud unavailable):** the LLM is a design-time tool. The student states intent in natural language; the model emits a small deterministic rule (threshold, state machine, schedule); the rule is deployed to the edge device and runs with no model in the path.
- **Cloud loop:** the LLM operates at runtime through MCP tools: cross-sensor queries, longer horizons, natural-language interrogation, agent orchestration.

## 4. BLE Advertisement Payload Specification

Legacy advertisement, 31-byte AD budget, Manufacturer Specific Data:

```
Offset  Size  Field
0       2     Company ID (0xFFFF development / RadioStudio assigned)
2       2     kit_id            (which kit; multi-kit campuses)
4       1     sensor_type_id    (resolves the sensor card)
5       1     schema_version    (payload layout version)
6       2     seq               (monotonic sequence counter, wraps at 65535)
8       4     tick_ms           (monotonic milliseconds since SIM boot)
12      1     status            (bit0 sensor_ok, bit1 low_batt, bit2 fault_injected, ...)
13      n     payload           (per sensor card, fixed-point fields, <= 12 bytes)
```

Non-negotiable fields, and why:

- **`seq`:** advertisements are unacknowledged broadcast. Without a counter, packet loss is silent. With it, students compute delivery ratio and learn QoS from their own data.
- **`tick_ms`:** every multi-sensor experiment is a time-alignment problem. The gateway reconciles `tick_ms` against arrival time to remove BLE scan-window jitter before correlating streams.
- **`sensor_type_id` + `schema_version`:** this pair is what lets the gateway auto-resolve the sensor card. It is the difference between "the LLM parsed a number" and "the LLM parsed a number it can reason about."

Multi-sensor SIM2 note: BME688, SCD41, and VEML7700 can share one I2C bus. Each sensor gets its own `sensor_type_id` and the SIM rotates advertisement sets (one adv per sensor per interval) rather than packing all readings into one frame. This keeps every frame under 31 bytes and keeps the card model one-card-one-measurand-set.

## 5. Sensor Cards: The Machine-Readable Contract

One JSON file per packaged sensor, stored in the gateway `cards/` directory and served as an MCP resource. The card is what the model reads instead of guessing.

```json
{
  "card_version": "1.0",
  "sensor_type_id": 6,
  "schema_version": 1,
  "part": "SCD41",
  "packaged_part": "PSENS-010",
  "sim": "SIM2",
  "interface": "I2C @ 0x62, 3.3 V",
  "measurands": [
    {
      "name": "co2",
      "unit": "ppm",
      "range": [400, 5000],
      "accuracy": "±(40 ppm + 5% of reading)",
      "payload_field": {"offset": 0, "size": 2, "encoding": "uint16", "scale": 1}
    }
  ],
  "sampling_period_s": 5,
  "plausibility": {"co2": {"min": 380, "max": 5500, "max_step_per_min": 800}},
  "failure_modes": [
    "reads ~400 ppm flat: sensor not initialised or window open next to inlet",
    "slow creep with no occupancy: check ASC (automatic self-calibration) history"
  ],
  "mounting": "breathing-zone height 1.1-1.7 m, away from windows, doors, and people closer than 50 cm",
  "packaged_dimensions_mm": "[PLACEHOLDER]",
  "connector": "[PLACEHOLDER: keyed harness part number]",
  "datasheet_uri": "resources/datasheets/scd41.pdf"
}
```

Third parties add a sensor to the platform by publishing a card plus a `sensor_type_id` registration. That is the ecosystem play.

## 6. SIM Firmware Code Structure

One repository, one common core, five build targets. A student flashing SIM4 for the SCT-013 versus the SPL changes one build flag, not the codebase.

```
sim-firmware/
├── platformio.ini              # env per SIM variant: sim1_onewire ... sim5_rs485
├── common/
│   ├── adv_builder.[ch]        # packs the 31-byte frame: seq, tick_ms, status, payload
│   ├── seq.[ch]                # persistent sequence counter (survives light sleep)
│   ├── sched.[ch]              # sample -> encode -> advertise cadence; deep-sleep option
│   ├── power.[ch]              # sensor rail switching, battery sense, low_batt flag
│   ├── selftest.[ch]           # boot-time sensor presence check -> status.sensor_ok
│   └── fault_inject.[ch]       # instructor mode: stuck value, offset, dropout
│                               #   (sets status.fault_injected; the adversarial
│                               #    validation labs from the AI-first review)
├── interfaces/
│   ├── onewire_drv.[ch]        # SIM1: bus master, ROM search, CRC
│   ├── i2c_drv.[ch]            # SIM2: bus scan, per-device mutex
│   ├── gpio_event_drv.[ch]     # SIM3: debounced edge capture with tick timestamps
│   ├── adc_drv.[ch]            # SIM4: oversampling, attenuation config, mV calibration
│   ├── pulse_capture.[ch]      # SIM4/SIM3: trigger + echo timing (JSN-SR04T)
│   └── rs485_modbus.[ch]       # SIM5: Modbus RTU master, register map tables
├── sensors/                    # one file per sensor; each fills a payload struct
│   ├── ds18b20.c   bme688.c   scd41.c    veml7700.c  pir.c
│   ├── reed.c      at42qt1010.c  spl.c   jsn_sr04t.c
│   ├── sct013.c    # 1 kHz burst sampling, RMS in firmware, one reading/s
│   ├── sen0193.c   # dry/wet calibration constants in NVS
│   ├── water_level.c           # duty-cycled excitation to avoid trace electrolysis
│   └── analog_420ma.c          # generic 4-20 mA: scale per transmitter config
└── main/
    └── main.c                  # variant switch: which interface + sensor drivers run
```

Design rules the firmware must obey:

1. **The SIM never interprets, it measures.** Conversion to engineering units happens in firmware (students should see real units), but validation, fusion, and inference belong to the gateway and agents. No thresholds in SIM code except self-protection.
2. **Everything that can fail sets a status bit.** A CRC failure on One-Wire, a Modbus timeout, an ADC rail at 0 V: these become `sensor_ok = 0`, never a plausible-looking number. Silent garbage is the enemy of every downstream agent.
3. **Fault injection is a first-class feature, not a hack.** The instructor can command a stuck value or an offset; the frame carries `fault_injected` so the instructor's tooling knows the truth while the student's agent has to find out from the data.

## 7. Edge Device (Gateway) Code Structure

The gateway is a contract, not a board: BLE scan in, timeseries store, MCP endpoint out. Reference implementations target Raspberry Pi, Arduino Uno Q (MCU side does nothing here; the Linux side runs this stack), and a plain laptop with its own BLE radio.

```
gateway/
├── scanner/
│   ├── ble_scan.py             # passive scan (Linux: needs bluetoothd Experimental=true; see gateway/README); filter on Company ID; RSSI logging
│   └── dedupe.py               # drop repeated adv of same (kit, type, seq)
├── decoder/
│   ├── registry.py             # sensor_type_id + schema_version -> card -> parser
│   └── reconcile.py            # tick_ms vs arrival-time alignment; loss stats from seq
├── store/
│   ├── db.py                   # SQLite WAL; one readings table, indexed (sensor, ts)
│   └── downsample.py           # continuous aggregates; protects eMMC on Uno Q
├── cards/                      # the JSON sensor cards (Section 5), one per sensor
├── mcp_server/
│   ├── server.py               # FastMCP entry point (stdio local, SSE for cloud)
│   ├── tools/
│   │   ├── list_sensors.py     # live inventory with last-seen and delivery ratio
│   │   ├── describe_sensor.py  # returns the full card
│   │   ├── read_latest.py
│   │   ├── query_timeseries.py # start, end, aggregation
│   │   ├── capture_experiment.py  # named multi-sensor capture -> dataset handle
│   │   ├── annotate.py         # deployment journal: mounting, events, "window opened"
│   │   ├── validate_reading.py # card plausibility bounds + rate limits -> verdict
│   │   └── deploy_rule.py      # writes an edge rule; gated by capability token
│   ├── resources/              # datasheets, schematics, cards, calibration tables
│   └── prompts/                # experiment templates ("AC efficiency", "when to water")
├── rules/
│   ├── engine.py               # deterministic rule runner (edge loop, no LLM in path)
│   └── rules.d/                # LLM-authored, human-approved rule specs (YAML/JSON)
├── agents/
│   ├── orchestrator.py         # cloud loop: routes questions to tool-calling agents
│   └── recipes/                # fusion recipes: occupancy, cold chain, water audit
└── dashboard/                  # local viz; deliberately thin, the MCP is the product
```

### The MCP tool surface is the syllabus

Every lab maps to tool calls a student can watch the model make:

1. *Acquire* → `list_sensors`, `read_latest`
2. *Validate* → `validate_reading`, plus the fault-injection game (the model, or the student, must catch the lie)
3. *Compare* → `describe_sensor` across alternatives; cards carry accuracy-vs-range
4. *Visualise* → dashboard reads the same store the agent reads
5. *Combine* → `capture_experiment` + `query_timeseries` across sensors, reconciled on `tick_ms`
6. *Act* → `deploy_rule` (edge loop) or agent action with human approval (cloud loop)

### Agent orchestration (cloud loop)

The cloud side runs an MCP client harness (Claude with the gateway's MCP server mounted). Orchestration pattern:

- **Question agents:** each capstone question ("is my AC efficient?") is a prompt template plus a fusion recipe naming the sensors, the alignment window, and the decision to output.
- **Watchdog agents:** scheduled runs that call `query_timeseries`, check drift against card plausibility, and open an annotation when something looks wrong. They never actuate.
- **Action path:** any actuation goes through `deploy_rule` with an explicit capability token and a human confirmation. An LLM is never in a control loop that must survive a dropped link.

## 8. Capstone Catalog (referenced by the sensor decks)

| ID | Question | Core sensors |
|----|----------|--------------|
| C1 | Is this room healthy and is the HVAC earning its energy bill? | SCD41, PIR, DS18B20, SCT-013, reed |
| C2 | Should the lights be on at all? | VEML7700, PIR, SCT-013 |
| C3 | Is this space comfortable by the numbers? | BME688, SCD41, DS18B20, SPL |
| C4 | Is the canteen safe and how long is the queue? | DS18B20, reed, JSN-SR04T, SPL, AT42QT1010 |
| C5 | Is the restricted zone secure against more than one threat? | Reed, PIR, VEML7700, SCT-013, water level |
| C6 | Where does the campus water actually go? | JSN-SR04T, water level, SEN0193, industrial transmitters |
| C7 | When should we water, and did it work? | SEN0193, VEML7700, DS18B20, BME688 |
| C8 | What does the machine's electrical signature say before it fails? | SCT-013, SPL, DS18B20, RS485 sensors |

Full capstone briefs, with the agentic patterns of Section 9 called back by name and pattern-aware assessment items, are in `15_CAPSTONES_WITH_PATTERN_CALLBACKS.md`.

## 9. Slide Deck Conventions

Each of the 14 sensor decks contains nine slides. The first three form the AI-first opening: they tune the student to think of the AI as the primary actor in the system, not as an assistant to consult afterwards. The opening is deliberately simple (short bullets, one analogy per slide, conversational narration, no tool-name jargon): it introduces a new perspective to a wide audience, and depth belongs to the later slides.

1. **AI-First, the old way and the new way:** a person reading a number and deciding, versus an AI perceiving this quantity continuously and acting, anchored in one everyday moment with this sensor.
2. **AI-First, what the AI must know about this sensor:** trust and limits. The sensor's ID card (the card of Section 5, in plain words), what this sensor can and cannot be trusted to say, and why the AI is only as good as what it knows about its senses.
3. **The Agentic Pattern:** one named agentic design pattern per deck, stated plainly with one analogy, anchored in this sensor's physics. Across 14 decks the students accumulate a pattern vocabulary (see table below).
4. **What it is:** sensing principle, one paragraph a non-technical person can follow.
5. **What it does in practice:** general applications, the sensor's day job in the world.
6. **Technical card:** measurand, range, accuracy, original package, output type, packaged dimensions **[PLACEHOLDER]**, interface details **[PLACEHOLDER]**, SIM assignment.
7. **Climate change applications:** mitigation, adaptation, and measurement roles.
8. **Fusion partners:** which other kit sensors multiply its value, and the agent-mediated inference each pairing enables.
9. **Capstone:** the project from the catalog above, stated as a question with a decision at the end.

### The agentic pattern vocabulary

| Deck | Pattern | Core lesson |
|------|---------|-------------|
| 01 DS18B20 | Predict, Then Measure | The agent commits a prediction, then scores itself against the ±0.5 °C band |
| 02 BME688 | Adjudicating Two Witnesses | Treat embedded-ML outputs (IAQ, eCO2) as testimony, resolve against SCD41 with evidence |
| 03 PIR | Absence of Evidence | Silence is not emptiness; the agent keeps a decaying belief state and seeks corroboration |
| 04 4-20 mA | Design for the Failure Path | The live-zero encodes fault semantics the agent acts on; out-of-band is a fault, not a reading |
| 05 RS485 | Contracts All the Way Down | Register maps are tool schemas; the agent codes from the contract, never guesses |
| 06 SCD41 | Evidence With Latency | Match each stream's time constant to the question; slow integrators confirm fast channels |
| 07 VEML7700 | The Agent Writes the Rule | Design-time rule authoring; the model designs and audits, the deterministic rule runs alone |
| 08 SPL | Architect What the AI Cannot Know | Privacy enforced in hardware (envelope, no audio); data minimization by physics, not policy |
| 09 JSN-SR04T | One Sensor Corrects Another | Temperature-compensated speed of sound; cross-sensor correction assembled from cards |
| 10 Reed | Events, Not Samples | State transitions trigger agent workflows; one bit disambiguates causes in other streams |
| 11 SCT-013 | The Agent Audits Itself | Measured kWh closes the loop on the agent's own recommendation |
| 12 SEN0193 | No Meaning Without Calibration | Readings are anchored to per-probe calibration history carried in the card |
| 13 Water trace | Is Silence Good News? | Liveness vs value; heartbeat via seq counter; watchdog agents guard the quiet sensor |
| 14 AT42QT1010 | Context Gates Meaning | One bit gates the validity of other streams; the cheapest form of fusion |

Every slide carries a narration block written to be spoken, matching the Rev5 notes style but question-driven rather than part-number-driven.

# Observation: BME688 eco2_ppm vs SCD41 co2_ppm deviation (2026-09-02)

## What was observed

Dashboard readings from the same run, both sensors live on SIM2:

| Sensor | Field | Value |
|---|---|---|
| BME688 (1:2) | `eco2_ppm` | 500.00 |
| SCD41 (1:6) | `co2_ppm` | 1504.00 |

A ~1000 ppm gap between the two "CO2" readings.

## Why they disagree

This is expected behavior, not a bug — the kit is deliberately built around this exact
disagreement (see `sensor_decks/02_BME688_gas_iaq.md`, pattern "Adjudicating Two Witnesses").

- **BME688 `eco2_ppm` is not a CO2 measurement.** The chip has no way to sense CO2 molecules.
  It has a heated metal-oxide plate whose resistance changes when VOCs (breath, solvents,
  cleaning products, cooking, etc.) touch it. Bosch's BSEC library converts that raw gas
  resistance into an *inferred* "equivalent CO2," assuming VOCs and exhaled CO2 correlate.
  The card (`gateway/cards/02_bme688.json`) explicitly marks this field's accuracy as
  "estimate derived from VOC response; SCD41 is the reference," and lists a known failure
  mode: `iaq stuck at 25 with accuracy flag low: BSEC still calibrating (first 5-30 min)`.
  A flat `500.00` (the round BSEC baseline) is consistent with the algorithm still being in
  that calibration window rather than reporting a converged estimate.

- **SCD41 `co2_ppm` is a direct physical measurement.** It uses photoacoustic NDIR: a 4.26 µm
  infrared emitter pulses light through a sealed cell, CO2 molecules absorb it, and the
  resulting micro pressure pulse is picked up by an internal microphone. More CO2, stronger
  pulse. This is a real count of the gas, not an inference — treat `1504.00` as the accurate
  ambient CO2 reading.

## How to interpret it

Per the sensor deck's guidance: **do not average the two values.** Adjudicate:

- SCD41 is ground truth for actual CO2 concentration.
- BME688's `eco2_ppm` is only useful as a secondary VOC-activity signal, and disagreement
  between the two is itself diagnostic (e.g. a VOC spike with flat measured CO2 suggests a
  solvent/sanitiser source rather than occupancy).
- A low/flat `eco2_ppm` against a high real `co2_ppm` (this case) most likely means BSEC
  hasn't converged yet (needs a 5-30 min burn-in) rather than a real air-quality reading.

## Reference

- `sensor_decks/02_BME688_gas_iaq.md` — full "Adjudicating Two Witnesses" explanation
- `sensor_decks/06_SCD41_co2.md` — SCD41 measurement principle and dynamics
- `gateway/cards/02_bme688.json` — field-level accuracy/estimate flags and failure modes

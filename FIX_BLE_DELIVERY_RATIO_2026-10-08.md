# Low delivery ratio on the Uno Q: BLE scan mode (2026-10-08)

## Symptom

The dashboard's Delivery column read about 20% for the PIR (1:3), with
`seq` gaps of 5-6 between consecutive stored frames, while the node itself
advertises every 100 ms and publishes a new `seq` every 2 s (about 20 copies
of each frame on the air).

## Finding

The loss was not over the air. The gateway was hearing each node about once per
10.5 s, whatever its transmit rate, so the apparent delivery ratio was roughly
`sample period / 10.5 s`.

Measured on the Uno Q (BlueZ 5.82, bleak 3.0.2, kernel 6.16), 60 s per run,
11 nodes powered:

| Scan mode | Frames per node in 60 s | Gap between frames | `seq` captured |
|---|---|---|---|
| Active, `DuplicateData=False` (what the gateway was using) | 6 | 10.4-10.6 s | 12-75% depending on the node's sample rate (PIR 21%, STPM32 75%) |
| Active, `DuplicateData=True` | 6 for types 1-16 (type 17 differed) | 10.4-10.6 s | unchanged |
| Passive, advertisement monitor with `or_patterns` | every `seq` | node's own rate | 100% on all 11 types |

After patching the gateway and restarting it, the last 60 s of stored data
showed 100% of `seq` values for 10 of 11 sensors (BME688 96%).

## Cause

`ble_scan.py` asked bleak for `scanning_mode="passive"` without `or_patterns`,
and bleak also requires BlueZ experimental interfaces for passive scanning on
Linux. bleak raised, the `except` in `BleSource.run` swallowed it, and the
gateway fell back to an active scan with no log line. The active scan's
duplicate filtering is what thins the stream to one report per node per ~10.5 s.

What was not established: which layer does the thinning (controller, kernel or
bluetoothd). Turning `DuplicateData` on did not change it for types 1-16, and
`btmon` needs root, so the HCI stream could not be inspected.

## Fix

1. `Experimental = true` in `/etc/bluetooth/main.conf` on the Uno Q, then
   `sudo systemctl restart bluetooth` (done 2026-10-08; backup
   `main.conf.bak-20261008`). Setup steps are in `gateway/README.md`.
2. `gateway/scanner/ble_scan.py` passes `or_patterns` (AD type 0xFF, company ID
   bytes) for Linux passive scanning and logs `BLE scan mode: passive` or
   `active (passive unavailable: ...)`. Other platforms are unchanged.

## Consequences

- Every frame now arrives, so the stored row rate rose to roughly 890,000 rows
  per day (about 80 MB/day). Downsampling exists (`python -m gateway
  downsample`) but is not scheduled.
- The sensors-table `rx_count` / `lost_count` are cumulative, so the dashboard
  ratio recovers slowly unless the database is reset.
- The reconciler still cannot tell scanner loss from radio loss; it only sees
  `seq` gaps. After this fix a gap is much more likely to be real loss.

## Not covered

- Only 60 s runs; no longer-duration soak test.
- The type-17 (SHT40) difference under `DuplicateData=True` is unexplained.
- Other boards were not tested; the setup scripts do not enable the flag.

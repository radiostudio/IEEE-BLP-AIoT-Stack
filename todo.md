# TODO

## [ ] Define actuator command frames in the architecture doc (`00_ARCHITECTURE_AND_CODE_STRUCTURE.md`)

**Why:** the first actuator node (`IEEE-BLP-RelayActuator`, sensor_type_id 18) exists and works on the
bench, but nothing in the architecture doc or the card format describes it. Its command layout, its
beep indication and its de-duplication rule are the firmware author's choices, written down only in
`gateway/cards/18_relay_actuator.json` (provisional) and that repo's README. The gateway ignores the
card's `role`, `command_payload` and `indication` fields. Until the doc defines them, every future
actuator node would invent its own.

**Where it goes:** a new subsection after Section 4 (BLE Advertisement Payload) for the frame, and an
"Actuator cards" paragraph in Section 5 (Sensor Cards). Section 6 gets a short "actuator node"
variant, and Section 7's action path gets the transmit side.

### Proposal text (draft)

> #### 4a. Command frames (gateway to actuator node)
>
> An actuator node is a SIM that **receives** instead of broadcasting. It scans (passive, continuous,
> duplicate filtering off) and acts on a CONTRACT frame addressed to it. It does not advertise.
>
> **Frame.** Same layout as Section 4: company ID `0xFFFF`, then `kit_id`, `sensor_type_id`,
> `schema_version`, `seq`, `tick_ms`, `status`, payload (n <= 12). `sensor_type_id` identifies the
> actuator card, `seq` identifies the command, `tick_ms` is the sender's clock and is informational.
> The payload is defined by the card's `command_payload` list, using the same `payload_field`
> encodings as sensor measurands.
>
> **Acceptance.** A node acts on a frame only if `kit_id`, `sensor_type_id` and `schema_version` all
> match its own. Frames with a malformed payload (wrong length, value outside the card's range) are
> rejected and logged, never partially applied.
>
> **Repeats and new commands.** A sender repeats one command for several seconds, so a new `seq` means
> a new command and the same `seq` as the last acted-on command means a repeat to ignore. A sender
> MUST use a fresh `seq` for every new command, including one that restates the current state.
> (Open question: wrap-aware ordering, so that a stale frame replayed late cannot undo a newer command.)
>
> **State on power-up.** An actuator MUST power up in its safe state (relay OFF, valve closed...) and
> MUST NOT persist a commanded state across a reset. Safe state is declared in the card.
>
> **Indication.** Every state change MUST be announced locally so a person at the node can tell a
> command was applied. The card's `indication` field declares the pattern. Reference pattern for a
> binary actuator: **one 200 ms beep for ON/active, two 200 ms beeps (150 ms gap) for OFF/inactive.**
> A repeated command that does not change state is accepted silently. The indication is local only;
> the node does not report state over BLE.
>
> **Safety.** The gateway never sends a command from an LLM or an unapproved rule. All commands come
> from rules deployed through `deploy_rule` with a capability token and human approval (Section 7).
> The command channel itself is unauthenticated, so an actuator MUST NOT drive a load whose
> unintended switching is dangerous until authentication exists (see open decisions).
>
> #### 5a. Actuator cards
>
> An actuator card has `"role": "actuator"`, an empty `measurands`, a `command_payload` list (same
> field format as `measurands`, plus `values` describing each code), a `safe_state`, and an
> `indication` object. The registry still loads it like any card; decoding is not applicable.

### Open decisions to settle before writing it into the doc

- [ ] **Type ID range.** Is 18 acceptable for the first actuator, or should actuators get their own
      range (e.g. 100+) so sensor ids 1-99 stay sensors?
- [ ] **Indication contract.** Keep the buzzer pattern as a rule for all actuators, or leave the
      indication per-card and only require that one exists? (Ties to the bench-confirmed 1/2-beep
      pattern, so changing it later means reflashing nodes.)
- [ ] **Authentication.** Any device that knows kit, type and schema can switch the relay. Options:
      HMAC over the frame (needs a shared key and a monotonic counter), or accept it for the workshop
      and document the risk.
- [ ] **Acknowledgement.** Nodes are silent today, so the gateway cannot know a command landed
      (measured link at about -103 dBm lost some commands). Options: the node advertises an ack
      frame (scan and advertise together), or the sender repeats until observed on serial in labs.
- [ ] **Sequence rule.** "Different from the last seq" is simple but replay-prone; "newer than last"
      (wrap-aware) breaks if the sender restarts its counter. Pick one.
- [ ] **Gateway transmit path.** The scanner (bleak) is receive-only. Decide how the gateway
      advertises (BlueZ advertising on the Uno Q, WinRT publisher on Windows) and how the rule engine
      invokes it. The `gpio` rule action is still a print stub.

### Related work in the code, not yet done

- [ ] Implement the transmit path above and a `relay` rule action in `gateway/rules/engine.py` that
      sends a type-18 frame (the `python -m gateway relay on|off` command only prints the bytes today).
- [ ] Make the registry/validation understand `role: actuator` (today it ignores the field and
      `validate_reading` / `describe_sensor` treat the card as a sensor with no measurands).
- [ ] Add the retry-until-confirmed option to `IEEE-BLP-RelayActuator/tools/relay_cmd.py`
      (PC advert reached the node at -103 dBm; about one run in three lost a command).
- [ ] Promote card 18 from provisional once the doc section is agreed, and update
      `IEEE-BLP-RelayActuator/README.md` to point at it.
- [ ] Draft a deck/capstone mention (Section 8) if actuation is to be taught.

### Packages and system setup for the gateway transmit path (Windows PC and Uno Q)

Target: the gateway sends the type-18 command frame itself, from both the Windows PC and the Uno Q.
Nothing below has been installed or tried for transmit yet; every item is a candidate to confirm.

**Already installed in `.venv-gateway` (receive side)**

- `bleak` 3.0.2, scan only. It cannot advertise.
- `winrt-Windows.Devices.Bluetooth.Advertisement`, `winrt-Windows.Devices.Bluetooth`,
  `winrt-Windows.Devices.Radios`, `winrt-Windows.Foundation(.Collections)`,
  `winrt-Windows.Storage.Streams`, `winrt-runtime` (3.2.1), pulled in by bleak on Windows.

**Windows PC**

- [ ] Check that the installed `winrt-Windows.Devices.Bluetooth.Advertisement` package is enough to use
      `BluetoothLEAdvertisementPublisher` with a manufacturer-data section (company ID `0xFFFF`).
      If it is, no new package is needed and `gateway/requirements.txt` only needs a comment.
- [ ] Confirm the PC's Bluetooth adapter can advertise while the scanner runs (the receive and
      transmit roles share one radio). Record the result.
- [ ] Windows may refuse or alter a publisher advertisement for some payloads (length, flags). Check
      the 17-byte manufacturer data goes out unmodified, using nRF Connect on a phone.

**Uno Q (Linux, BlueZ)**

- [ ] BlueZ advertising goes through D-Bus (`org.bluez.LEAdvertisingManager1`). Pick one Python
      binding and test it: `dbus-next`, `bluez-peripheral`, or `dbus-fast` (already used by bleak on
      Linux, so check `pip list` on the board before adding anything).
- [ ] Keep `Experimental = true` in `/etc/bluetooth/main.conf` (already set for the passive scan;
      advertising may also need it). Restart `bluetooth` after any change.
- [ ] Run the pending `btmgmt` checks to see whether the Uno Q's controller supports scanning and
      advertising at the same time (`btmgmt info`, look at supported and current settings, including
      `le` and `advertising`). Record the result in `unoq_board_gateway_ops` notes or in this file.
- [ ] If dual role is not supported, decide whether the gateway pauses the scan while it sends a
      command, then resumes. This affects delivery ratio, so measure it.

**Both platforms**

- [ ] Add the chosen transmit packages to `gateway/requirements.txt` as optional extras, with a
      platform marker where needed (for example `; sys_platform == "linux"`), and keep the current
      "standard library only" core.
- [ ] Update `setup.bat` / `setup.sh` and `PREREQUISITES.md` if a new package or system setting is
      required, then re-run the fresh-install test on Windows and on the Uno Q.
- [ ] Add a transmit-side test with a fake advertiser, like `gateway/tests/test_relay_command.py`, so
      the rule engine path is covered without a radio.

**Relay node firmware (separate repo `IEEE-BLP-RelayActuator`)**

- ESP-IDF v5.4.1. v5.5.3 fails to build (`esp_bt.h` include path regression).
- Bench link lost about one command in three at -103 dBm, so any transmit path needs repeats.

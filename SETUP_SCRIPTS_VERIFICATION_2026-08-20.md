# Setup Scripts Verification (2026-08-20)

Branch: `feature/onboarding-scripts`

This records the checks run against the new student setup tooling
(`start_installation.py`, `setup.sh`, `setup.bat`, `gateway.sh`,
`gateway.bat`) before asking for review. The macOS/Linux checks were run
directly in this sandbox; the Windows checks were run afterward on a real
Windows machine, since none was available here.

## Bug found and fixed along the way

The very first test run failed the gateway's own self-test with:
`cards loaded (14 expected) got 15`.

Cause: `gateway/tests/smoke_test.py` had a hardcoded expectation of 14
sensor cards, but `gateway/cards/` actually has 15 files - a 15th card
(`15_rs485_soil.json`, a soil moisture probe) was added at some point and
marked "PROVISIONAL, not yet confirmed" in its own notes, but the smoke
test was never updated to match.

Fix: changed that one check in `gateway/tests/smoke_test.py` to count the
actual card files on disk instead of a hardcoded number, so it can't go
stale again if a 16th card is added later. The other two places that
mention "14" were left alone - they describe how many sensor types the
simulator actually produces today (14), which is still accurate, since the
new 15th card was never wired into the simulator.

## What was tested (macOS/Linux, run directly on this machine)

| # | Check | Result |
|---|---|---|
| 1 | Fresh build: `python3 start_installation.py --recreate` - creates the environment, installs everything, runs the self-test | Passed, self-test passed, exit code 0 |
| 2 | Running it again right after - should reuse the environment instead of rebuilding it | Passed - printed "Reusing existing .venv-gateway", still succeeded |
| 3 | `python3 start_installation.py --with-anthropic` - should also install the optional package for the "bring your own API key" option | Passed - `anthropic` package confirmed installed afterward |
| 4 | `bash gateway.sh smoke` - running a gateway command with no manual "activate" step at all | Passed |
| 5 | `bash setup.sh` run directly, skipping `start_installation.py` entirely - should still work standalone | Passed |
| 6 | A simulated old Python (3.9) put first on the PATH, to confirm the "your Python is too old" message actually triggers | Correctly detected and stopped with the right message, exit code 2 |

The one-time Bluetooth permission step (Linux only) was also exercised on
every run above: since this sandbox's `sudo` requires a password and none
was available non-interactively, it correctly failed fast (no hang) and
fell back to printing the exact manual command, without failing the rest
of setup. On a student's own machine, typing a `sudo` password when
prompted would let this step complete automatically instead.

## Bugs found and fixed testing on Windows

The first real-Windows run failed immediately, right after the banner
line, with the generic batch error `... was unexpected at this time.` and
nothing else - no line number, no further detail. This took two rounds to
fully track down, because Windows batch has a specific, well-known trap
that this script fell into twice, in two different disguises.

**What was actually wrong:** Windows batch decides where an `if (...)`
block ends by literally counting `(` and `)` characters in the script's own
text. It does this whether or not those characters were "meant" as plain
text - a parenthesis inside a quoted string, or even inside a plain `echo`
message, still counts. `setup.bat` had two kinds of these:

1. Python code being run via `python -c "..."` that legitimately needed
   parentheses (e.g. `sys.exit(0 if ... else 1)`), written inline inside an
   `if (...)` block - fixed by moving that code into a variable set
   *outside* the block, and referencing the variable inside the block
   instead, so the block's own literal text has no stray parentheses left
   for batch to miscount.
2. Plain English echo messages that happened to use parentheses for a
   parenthetical aside (e.g. `echo Removing existing .venv-gateway
   (--recreate was passed)...`), also sitting inside an `if (...)` block -
   fixed by rewording those messages to not use parentheses at all.

The first fix (commit `2f25bb6`) caught every instance of the first kind.
The second Windows test run still failed at the same point, which is what
led to a full, deliberate audit of every single `(` character in the file
(rather than guessing again) - that's what turned up the second kind,
fixed in commit `c778e32`. Everything after that audit is confirmed either
a legitimate block delimiter, a standalone line outside any block (safe),
or hidden inside a variable (safe) - there shouldn't be a third instance of
this bug left.

This class of bug is specific to Windows batch's parser and has no
equivalent on macOS/Linux - `setup.sh` (bash) was never affected, since
bash actually understands quoting properly.

## What was tested on the real Windows machine (after both fixes)

| # | Check | Result |
|---|---|---|
| 1 | `python .\start_installation.py` from a fresh clone, in PowerShell, from a folder path that itself contains a space (`D:\E Drive\Projects-2026\IEEE-BLP-AIoT-Stack`) | Passed - environment created, dependencies installed, self-test passed, ended with "Setup complete!" |
| 2 | `.\gateway.bat simulate` afterward, no manual activation step | Passed - dashboard started, all 14 simulated sensors came online, frames received/stored counts printed, stopped cleanly with Ctrl+C |

Notable, expected details from this run, not bugs:
- The machine had Python 3.14 installed (well above the 3.10 minimum), and
  pip automatically pulled in several Windows-only packages that macOS/Linux
  never see - `pywin32`, `colorama`, and a set of `winrt-*` packages (the
  Windows Bluetooth stack bindings `bleak` needs on Windows). This is
  `pip`/`requirements.txt` working exactly as intended: the same
  `requirements.txt` file installs the right thing per platform with no
  changes needed.
- The folder path containing a space ("E Drive") caused no problems -
  confirms the quoting throughout `setup.bat` and `start_installation.py`
  is correct.
- Stopping `gateway.bat simulate` with Ctrl+C brought up Windows' own
  standard `Terminate batch job (Y/N)?` prompt before it actually stopped.
  This is normal `cmd.exe` behavior for any batch file wrapping a running
  program, not something these scripts can or need to suppress - worth
  mentioning to students once so it doesn't surprise them, but not a bug.

## ZIP-bootstrap one-liner, tested on a second, separate Windows machine

After the repo was made temporarily public for testing, `bootstrap.ps1`
(the one-liner entry point that downloads the ZIP directly, no git
involved at all) was tried on a different, fresh Windows machine than the
one used for the git-clone tests above.

- **First attempt failed** with a PowerShell error:
  `Cannot convert 'System.Object' to the type 'System.Uri' required by
  parameter 'Uri'. Specified method is not supported.` This looked like it
  could be a real bug in how the one-liner passes the URL to
  `Invoke-WebRequest`, so as a workaround it was split into three separate
  statements (assign the URL to a variable, fetch it, then
  `Invoke-Expression` the result) to isolate the failure.
- **Retried the original one-liner again afterward, and it worked.** Since
  it wasn't run enough times back-to-back to isolate a reliable repro, the
  working theory is a one-off terminal paste/line-wrap issue with the long
  single-line command, rather than a bug in `bootstrap.ps1` itself - but
  this isn't confirmed, and the 3-statement form above is a safe fallback
  to hand a student if they hit the same error.
- Once it ran, the full flow succeeded end to end: ZIP downloaded and
  extracted with no git installed on that machine, `start_installation.py`
  ran automatically, setup completed, and afterward `python -m gateway run`
  showed the live dashboard in a browser - confirming not just the
  simulated demo path but the real BLE-scanning command too.
- This machine already had Python 3.10+ installed, so this run only
  exercises the happy path - it does not confirm what happens when
  `bootstrap.ps1` has to print its "no Python found" message on a genuinely
  bare machine.

## Bug found and fixed: the one-liner closed the window before showing the result

On a separate fresh-Windows attempt, the one-liner ran and (per the user
checking manually afterward) actually succeeded - but the PowerShell
window closed on its own right at the end, without ever showing whether
it had worked. A student would have no way to know if setup succeeded or
failed.

**Cause:** `bootstrap.ps1` ended with `exit $LASTEXITCODE`. When a
script's content is piped into `iex` (`Invoke-Expression`) - exactly what
the one-liner does - that content runs inline in the *current* PowerShell
session, not as a separate child process. A bare `exit` in that context
doesn't just end the script, it closes the entire PowerShell window
instantly, wiping out all the scrollback (including "Setup complete!",
which had already printed) before anyone can read it.

**Fix:** moved all the logic into a function and replaced every `exit N`
with `return N` (which only leaves the function, not the session), then
added an explicit final status message ("Setup finished successfully" or
"did NOT finish successfully", with the exit code) plus a `Read-Host
"Press Enter to close this window"` at the very end, so the window always
stays open until the student has read the result and chosen to close it.
Also fixed a related bug this introduced: moving the logic into a
function meant `$args` inside it referred to the function's own
(unbound) arguments rather than the outer script's - fixed by passing the
script-level `$args` into the function explicitly as a parameter.

`setup.sh`/`setup.bat` were never at risk of this specific bug -
`start_installation.py` always launches them as real child processes,
never through an inline-eval mechanism like `iex`.

**Also added:** the final success message (in `bootstrap.ps1`,
`setup.sh`, and `setup.bat` alike) now tells the student to read
`PREREQUISITES.md` before actually using the gateway - that's where the
"Bluetooth must be switched on" and other one-time, one-per-machine notes
live.

## Bug found and fixed: the function-wrapper fix above created a second bug

Re-tested the fix above (same idempotent one-liner, second run on the same
machine, reusing the existing `.venv-gateway`). The window stayed open this
time - that part of the fix worked - but the final message was garbled:
it printed the *entire* nested setup output crammed into the "exit code"
placeholder, something like `Setup did NOT finish successfully (exit code
== AIoT Gateway setup (Windows) == ... Setup complete! ... 0).`, and took
the failure branch even though `SMOKE TEST PASSED` and `Setup complete!`
had both printed - i.e. the real result was success, but it reported
failure.

**Cause:** the previous fix's function-plus-`return` pattern was called as
`$AiotExitCode = Invoke-AiotBootstrap ...`. In PowerShell, assigning a
function call to a variable captures *everything the function emits*, not
just its explicit `return` value - including every console-output line
from the nested `& $PyExe ... start_installation.py` call inside it, since
that output wasn't redirected anywhere. So `$AiotExitCode` became an array
of all that text with the real exit code (`0`) as its last element, not a
plain integer. PowerShell then evaluates a single-element array like
`@(0)` as falsy in an `if` condition (it unwraps the array and judges the
element, and integer `0` is falsy) - so a genuinely successful run
(`$AiotExitCode -eq 0` matched, wrapped as `@(0)`, evaluated falsy) took
the "did NOT finish successfully" branch.

**Fix:** removed the function entirely. `bootstrap.ps1` now uses a plain
top-level `:main do { ... } while ($false)` block with `break main` for
every early-exit path, and a plain script-scope `$ExitCode` variable set
directly at each exit point - never through a captured function-call
assignment. Nothing is ever collected from an assignment, so there is no
mechanism left that could pollute the exit code with unrelated output.

This is a good example of a fix introducing a new, non-obvious bug of its
own - worth remembering before reaching for a "wrap it in a function"
pattern again in a script whose job includes visibly streaming a nested
process's output.

**Confirmed fixed:** re-ran the same one-liner a third time, on the same
machine (reusing the existing `.venv-gateway` again). One wrinkle first -
the immediate retry after pushing served the *previous* (buggy) version,
because `raw.githubusercontent.com` sits behind a CDN with up to a
5-minute cache (`cache-control: max-age=300`); a cache-busting query
string (`?cb=1`) forced a fresh fetch. With the real fix served, the run
completed cleanly end to end: full setup output streamed normally,
`SMOKE TEST PASSED`, followed by a correct `== Setup finished
successfully. ==` message (no garbling, no false failure), the
`PREREQUISITES.md` reminder, and `Press Enter to close this window`
staying up until dismissed. One minor, harmless redundancy noted: the
`PREREQUISITES.md` reminder currently prints twice (once from
`setup.bat`'s own message, once from `bootstrap.ps1`'s final banner) -
not fixed, just noted in case it's worth trimming later.

## Not yet tested

- `setup.bat` run standalone, skipping `start_installation.py` (already
  confirmed working this way on macOS/Linux)
- `--recreate`, `--with-anthropic`, and `--with-pptx` specifically exercised
  on Windows (same code path as macOS/Linux, and now proven to parse
  correctly, but not individually run through on a Windows machine yet)
- Behaviour when only the non-functional Microsoft Store Python placeholder
  is present, instead of a real install
- `bootstrap.ps1`'s "no Python found" message, on a machine with no Python
  at all
- A reliable repro of the one-off `Invoke-WebRequest` / `System.Uri` error
  above - if it recurs, note exactly how the command was typed/pasted

## Full raw output

The complete terminal output for the macOS/Linux checks (including all the
pip install logs) was saved during testing to a temporary scratch file, not
committed to the repo. The Windows run's full output is in the
conversation this file was generated from. Ask for either to be re-run if a
fresh copy is needed.

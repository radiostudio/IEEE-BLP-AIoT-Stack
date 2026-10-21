# Reference: How the Onboarding Scripts Fit Together

This is a map of the whole "get a student's laptop working" system we
built on `feature/onboarding-scripts` - what calls what, why each piece
exists, and where to look for more detail on any part of it.

## The problem this solves

Before any of this existed, getting the Python `gateway/` code running on
a student's laptop meant several manual steps written out as prose in
`gateway/README.md`: create a virtual environment, `pip install`, run a
test, hope nothing went wrong. Multiply that by ~30 students on Windows,
Mac, and Linux laptops, some locked down, on workshop Wi-Fi, with no one
able to walk each of them through it individually - and manual steps
become the thing most likely to eat the first hour of Day 1.

Everything below exists to turn that into one thing a student pastes into
a terminal.

## The full call chain, start to finish

```
Student pastes ONE line into a terminal
         |
         v
 bootstrap.sh (macOS/Linux)  OR  bootstrap.ps1 (Windows)
   - downloads the repo ZIP straight from GitHub (no git needed)
   - extracts it into a new IEEE-BLP-AIoT-Stack folder
   - cds into it
         |
         v
 start_installation.py
   - figures out which OS this is
   - hands off to whichever script actually knows how to set this OS up
         |
         +---------------------------+
         v                           v
    setup.sh (macOS/Linux)      setup.bat (Windows)
    - finds a Python 3.10+ interpreter
    - creates/reuses .venv-gateway
    - pip installs gateway/requirements.txt
    - (optionally) installs anthropic / python-pptx
    - runs `python -m gateway smoke` <- the actual pass/fail gate
    - (Linux only) tries to fix the Bluetooth permission
    - prints "Setup complete!"
         |
         v
Student now has a working .venv-gateway, and uses:
    gateway.sh / gateway.bat <command>
    (e.g. "bash gateway.sh simulate", "gateway.bat run")
    - always calls the venv's own Python - no manual "activate" step, ever
```

Two different students can enter this chain at different points, and both
end up in the same place:

- **A student with nothing yet** starts at `bootstrap.sh`/`bootstrap.ps1`
  (the one-liner in `README.md` / `19_GETTING_STARTED_SLIDE.md`).
- **A student who already has the code** (cloned with git, or downloaded
  and extracted the ZIP by hand) starts directly at
  `start_installation.py` - which is exactly what running the bootstrap
  script does for you automatically as its last step.

## What each file is actually responsible for

| File | Job | Notes |
|---|---|---|
| `bootstrap.sh` / `bootstrap.ps1` | Get the code onto a machine that has nothing yet, then call `start_installation.py` | Needs the repo to be reachable at the hardcoded GitHub URL inside it (repo is public for the workshop) |
| `start_installation.py` | Detect the OS, dispatch to the right setup script | Deliberately does **no** real setup work itself - just a dispatcher |
| `setup.sh` / `setup.bat` | The actual setup: find Python, build/reuse the venv, install dependencies, run the smoke test, (Linux) fix the Bluetooth permission | Each written natively for its own OS - not a shared script - see "why two full copies" below |
| `gateway.sh` / `gateway.bat` | Run any `python -m gateway ...` command afterward, through the venv, with no activation step | Thin wrappers - `gateway.sh smoke` and `gateway.bat simulate` are the only two commands that matter day to day |
| `gateway/tests/smoke_test.py` | The actual pass/fail check every script above defers to | Not new - this already existed; we only fixed a stale hardcoded count inside it |
| `PREREQUISITES.md` | What a student/instructor needs installed, and every way to get the code (one-liner, manual ZIP, git clone) | Read this first if the one-liner ever needs updating (e.g. after merging to `main`) |
| `README.md` / `gateway/README.md` | Student-facing quick start, pointing at the one-liner | The very first thing a student reads |
| `19_GETTING_STARTED_SLIDE.md` | The literal Day 1, 09:00-09:30 script for instructors | Scoped to exactly what that slot's pass criterion is (the smoke test) - not the later live-dashboard checkpoint |
| `SETUP_SCRIPTS_VERIFICATION_2026-08-20.md` | The test log: what was tried, what broke, what fixed it | Read this before touching `setup.bat` especially - see below |

## A few design decisions worth remembering

- **Why `setup.sh` and `setup.bat` are two full, separate scripts instead
  of one shared Python file:** this was a deliberate choice (not the
  original design) - each script can run fully standalone, native to its
  OS, at the cost of the same logic existing twice. If you change
  something in one (e.g. add a new dependency step), check whether the
  other needs the same change.
- **Why `gateway.sh`/`gateway.bat` exist at all:** without them, a student
  would need to "activate" the virtual environment by hand before every
  command - one more manual step to forget. These wrappers make that
  concept disappear entirely.
- **Why the Bluetooth permission fix (Linux) is opportunistic, not
  required:** it needs `sudo`, which the scripts otherwise never require
  to finish successfully. `setup.sh` tries it automatically and falls back
  to a printed manual command if it can't - it never blocks the rest of
  setup on it. This is a different thing from Bluetooth simply being
  **switched on** - that's an OS-level hardware toggle, applies on every
  OS (not just Linux), and no script can flip it for you. Setup itself,
  `smoke`, and `simulate` never need real Bluetooth at all; only `run`
  (live sensor scanning) does, and only once a kit is actually in hand -
  see `PREREQUISITES.md` and `gateway/README.md`.
- **Why `anthropic` and `python-pptx` are opt-in flags
  (`--with-anthropic`, `--with-pptx`) instead of always installed:**
  neither is needed by most students, and every unnecessary package is one
  more thing that can fail to download over workshop Wi-Fi.
- **Why `setup.bat` looks more defensive than `setup.sh` in places (code
  stored in variables instead of written inline):** Windows batch has a
  specific parser trap - it miscounts parentheses inside an `if (...)`
  block even when they're just plain text or inside quotes. This bit us
  twice during real Windows testing; the full story is in the verification
  doc.
- **Why `bootstrap.ps1` never calls `exit`:** when its content is piped
  into `iex` (`Invoke-Expression`) - the whole point of the one-liner - it
  runs inline in the *current* PowerShell session, not as a separate
  process. A bare `exit` in that context closes the entire PowerShell
  window instantly, which is exactly what happened during real testing:
  the window closed before the student could see whether setup had
  actually succeeded. `setup.sh`/`setup.bat` don't have this problem,
  since `start_installation.py` always launches them as genuine child
  processes, never via an inline-eval mechanism like `iex`.
- **Why `bootstrap.ps1` doesn't wrap its logic in a function either:** the
  first fix for the `exit` problem above did exactly that (a function
  using `return`, called as `$code = MyFunction`) - and it introduced a
  *second* real bug: capturing a function's return value in PowerShell
  captures everything it emits, not just the explicit `return`, including
  every line of console output from the nested setup process invoked
  inside it. The "exit code" variable ended up as a giant array of that
  text with the real number tacked on the end, and PowerShell evaluates a
  single-element array like `@(0)` as falsy in an `if` - so a genuinely
  successful run printed "did NOT finish successfully." The fix was to
  drop the function entirely and use a plain top-level `:main do { ... }
  while ($false)` block with `break main` for early exits - nothing is
  ever captured from an assignment, so this failure mode can't recur.

## If something breaks

Read `SETUP_SCRIPTS_VERIFICATION_2026-08-20.md` first - it has the actual
bugs found so far (a stale sensor-card count in the smoke test, two rounds
of the Windows batch parenthesis trap, a one-off unreproduced PowerShell
error) and exactly how each was diagnosed and fixed. If a new failure
looks similar to one of those, that doc's reasoning likely still applies.

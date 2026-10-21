# Prerequisites

What you need installed before working with this repo, split by role.

## Getting the code onto your machine

### Fastest: one command does everything

The repo is public for the workshop, so a student can go from nothing to a
fully set-up gateway with a single command - no manual download, no git,
nothing to click through on GitHub:

```
curl -fsSL https://raw.githubusercontent.com/sriram-rs/IEEE-BLP-AIoT-Stack/feature/onboarding-scripts/bootstrap.sh | bash
```
(macOS/Linux - paste into Terminal)

```
iwr https://raw.githubusercontent.com/sriram-rs/IEEE-BLP-AIoT-Stack/feature/onboarding-scripts/bootstrap.ps1 -UseBasicParsing | iex
```
(Windows - paste into PowerShell)

This downloads the code into a new `IEEE-BLP-AIoT-Stack` folder in whatever
directory you run it from, then immediately runs the same one-command setup
described below. If this stops working (e.g. the repo has gone back to
private, or this branch has merged - check whether the URL above should
say `main` instead of `feature/onboarding-scripts`), fall back to one of
the manual options next.

### Manual alternatives (no internet trust required, or if the one-liner stops working)

- **Download the ZIP, no git needed:** on GitHub, switch the branch
  dropdown to `feature/onboarding-scripts` (until it merges to `main`),
  then Code -> Download ZIP, and extract it. One quirk: a ZIP download
  loses `setup.sh`'s "you're allowed to run this" permission flag, so on
  macOS/Linux run it as `bash setup.sh` rather than `./setup.sh` (running
  it via `python3 start_installation.py` already does this for you
  automatically). Windows batch files don't have this issue.
- **If you already have git set up**, cloning is a fine alternative and
  makes pulling later updates easier:
  ```
  git clone https://github.com/sriram-rs/IEEE-BLP-AIoT-Stack.git
  cd IEEE-BLP-AIoT-Stack
  git checkout feature/onboarding-scripts   # until this merges to main
  ```

Whichever way you get the code, nothing beyond Python (below) is required
to actually run the setup - git is only a convenience for getting/updating
the code, never something `start_installation.py` itself needs.

## Students (workshop laptop)

Just Python 3.10 or newer. Everything else is handled automatically:

```
python3 start_installation.py     # macOS/Linux
python start_installation.py      # Windows
```

This one command creates the environment and installs everything the
gateway needs (see `gateway/requirements.txt`). No manual `pip install`
required. See `README.md` and `gateway/README.md` for what to do next.

One thing this can't set up for you: **Bluetooth needs to be turned on**
on your laptop before `python -m gateway run` (live sensor scanning) will
find any sensors - that's an OS-level setting, not something a script can
switch on. Not needed for setup itself, or for `smoke`/`simulate`, which
never touch real hardware - only for `run`, later, once you have a kit in
hand.

## Instructors / content authors (regenerating slides)

Everything above, plus `python-pptx`, only needed to turn the markdown
sensor decks in `sensor_decks/` into PowerPoint files via
`tools/md2pptx.py`. Students never need this.

Install it into the same environment with one extra flag on first setup
(or any time afterward - safe to run again):

```
python3 start_installation.py --with-pptx     # macOS/Linux
python start_installation.py --with-pptx      # Windows
```

Then generate the slides, using the same environment directly (`gateway.sh`
only runs gateway subcommands, so this one step goes straight to the
environment's own Python instead):

```
.venv-gateway/bin/python3 tools/md2pptx.py         # macOS/Linux
.venv-gateway\Scripts\python.exe tools\md2pptx.py   # Windows
```

(`python-pptx` isn't part of the default student setup on purpose - it's
an extra package nobody but the instructor needs, and every unnecessary
package is one more thing that can fail to download over a workshop
room's Wi-Fi. `--with-anthropic`, for the "bring your own API key" option
in Phase B, follows this same opt-in pattern.)

# Getting Started: Day 1 Setup Slide (09:00-09:30)

Companion to `18_WORKSHOP_SCHEDULE.md`'s Setup slot: "Registration; Python
+ gateway install check (`python -m gateway smoke` is the pass criterion);
kit issue." This is the slide/script for that slot - it stops at the
smoke-test pass criterion. The live dashboard with real sensor values is a
separate, later checkpoint (S2: Kit Anatomy + Bring-Up, 10:15-11:00), once
kits are actually wired up - don't show `gateway run` here, it isn't this
slot's job and there's no kit connected yet.

## Slide: One command gets your laptop ready

**Slide content:**
- Open a terminal (macOS/Linux) or PowerShell (Windows)
- Paste one line, press Enter, wait
- macOS/Linux:
  `curl -fsSL https://raw.githubusercontent.com/sriram-rs/IEEE-BLP-AIoT-Stack/feature/onboarding-scripts/bootstrap.sh | bash`
- Windows:
  `iwr https://raw.githubusercontent.com/sriram-rs/IEEE-BLP-AIoT-Stack/feature/onboarding-scripts/bootstrap.ps1 -UseBasicParsing | iex`
- No git required, no manual download - this one line does everything
- You'll know it worked when you see: `SMOKE TEST PASSED` and `Setup
  complete!`
- Windows only: at the very end it says "Press Enter to continue" - that's
  expected, read the message first, then press Enter (the window stays
  open either way, ready for your next command)

**Narration:**
This is the only thing you need to type all morning. Open a terminal - on
Windows that's PowerShell, on a Mac or Linux laptop it's Terminal - and
paste the line for your operating system, then press Enter. It downloads
the course code, sets up an isolated Python environment just for this
course so it can never conflict with anything else already on your
machine, installs everything it needs, and then runs its own built-in
self-test. You don't need git installed, you don't need to know how to
use GitHub, you don't need to type a second command. If your Wi-Fi is
slow this can take a minute or two - that's normal, let it run. You'll
know it worked when the last few lines say `SMOKE TEST PASSED` followed
by `Setup complete!`. If you see anything else - a Python version
complaint, a download failure, or the self-test itself reporting a
failure - raise your hand, and keep the error message on screen so we can
read it. The setup script itself will also tell you to take a look at
`PREREQUISITES.md` once it's done - that file covers the couple of
one-time, one-per-machine things it can't do for you, like turning
Bluetooth on, so actually go read it before S2, don't just skim past it.

## Slide: If something goes wrong

**Slide content:**
- No Python found: message tells you where to download it (needs Python
  3.10+); install it, then run the same line again
- Locked-down/managed laptop, can't install anything: raise your hand
- Anything else printed in red or ending in an error: raise your hand,
  keep the terminal open, don't close it
- Safe to run the same line again as many times as you want - it won't
  break anything or redo work that's already done

**Narration:**
A few honest possibilities. If your laptop has no Python installed at
all, the script will tell you so directly and give you a link - install
it and paste the same line again, it'll pick up right where it left off.
If this is a school- or work-managed laptop where you can't install
software, that's exactly the kind of thing to flag now, not at 10am when
we're mid-lesson. And if you see anything else that looks like an error,
don't close the terminal - the error message is the fastest way for us to
help you, and closing it loses that. One thing worth knowing: this command
is completely safe to run again. If it seems stuck, or you want to double
check, running it a second time won't redo work it's already finished, it
just picks up from wherever it left off.

## Note for the instructor console

`kit issue` happens in this same slot per the schedule but is independent
of this slide - hand out kits while laptops are finishing setup, don't
wait for every laptop to finish before starting distribution. The next
checkpoint (`gateway run` showing live values on the dashboard) is S2's
job once kits are actually connected, not this one.

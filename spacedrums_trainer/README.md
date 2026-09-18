# Space Drums Trainer

A gamified way to learn the Space Drums air-drumming kit. Notes fall down a
highway, you play them on the sticks and pedals, and the tempo climbs from a
crawl to full speed while you play.

For hardware, firmware and the serial protocol, see [README.md](README.md).

---

## 1. What it does

**Learn to Play** — twelve numbered levels, one standard groove each, from
quarter notes on the snare to a two-bar groove-and-fill. Reach 65% accuracy to
unlock the next level. Every run starts at half speed and ramps to the
groove's target tempo, so you are never thrown in cold.

**Learn Rhythms** — seven standalone grooves you can listen to first. Pick one,
choose your own starting BPM, and it ramps to full speed the same way.

**Custom Rhythms** — MIDI import. Coming soon.

### Reading the screen

| You see | It means |
| :--- | :--- |
| **Blue** note | play it with your **left hand** |
| **Red** note | play it with your **right hand** |
| **Amber** bar or band | a **foot** |
| Solid disc | a drum (snare, toms) |
| Ring | a cymbal (crash, hi-hat, ride) |
| Amber bar, right half | **kick** — right foot |
| Amber band labelled `LIFT`, left half | **lift the left foot** to open the hi-hat, put it back down at the top edge |
| Line joining two notes | play them **together** |
| Extra amber ring around a hi-hat | that hi-hat is **open** |

Lanes are only shown for the drums the groove actually uses, ordered
left-to-right to match where they sit in the air. The pads under the hit line
sit on two tiers: upper for the drums you reach up to, lower for the rest.

---

## 2. Install

You need **Python 3.10 or newer**. Only two packages are required:
`pygame-ce` and `pyserial`.

### Linux (Fedora)

```bash
sudo dnf install python3 python3-pip
cd /path/to/sd2
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Add yourself to the `dialout` group once so the app can open the hub without
root, then log out and back in:

```bash
sudo usermod -aG dialout $USER
```

### Windows

```powershell
cd C:\path\to\sd2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks the activate script, either run
`Set-ExecutionPolicy -Scope Process RemoteSigned` first, or skip activation and
call the interpreter directly as shown below.

### Drum samples

Nine `.wav` files go in an `audio/` folder next to this README:

```
audio/crash.wav   audio/snare.wav    audio/tom1.wav
audio/tom2.wav    audio/ride.wav     audio/floor_tom.wav
audio/kick.wav    audio/hihat_open.wav   audio/hihat_closed.wav
```

Any file that is missing falls back to a soft buzz and the app tells you which
ones it could not find, so a partial set still runs.

---

## 3. Run

Linux, with the venv activated:

```bash
python -m spacedrums_trainer
```

Windows, without activating:

```powershell
.\.venv\Scripts\python.exe -m spacedrums_trainer
```

### Options

| Flag | Effect |
| :--- | :--- |
| `--fullscreen` | start fullscreen (`F11` toggles at any time) |
| `--port /dev/ttyACM0` | skip auto-detect and use this serial port |
| `--no-metronome` | start with the click track off (`M` toggles) |
| `--no-bloom` | disable the glow pass on slow machines |

The hub is found automatically — the app scans the serial ports, prefers
USB CDC devices, and reconnects on its own if you unplug it. The status line at
the bottom of the home screen tells you what it found.

---

## 4. Controls

| Key | Action |
| :--- | :--- |
| Arrow keys | move around menus |
| `Enter` | choose / start |
| `Space` | in the rhythm list, listen to the highlighted groove |
| `Esc` | back, or quit from the home screen |
| `F11` | fullscreen |
| `M` | metronome on/off while playing |
| `F3` | frame rate and CPU cost |

You can also play without the hardware, which is handy for testing:

| Key | Drum |
| :--- | :--- |
| `A` `S` `D` `F` `G` `H` `J` | crash, hi-hat, tom 1, snare, tom 2, floor, ride |
| `Space` | kick |
| `Shift` (hold) | lift the hi-hat pedal |

---

## 5. How scoring works

Each note is judged on how close your hit was to its target time. The windows
are deliberately generous — air drumming has no rebound surface and this is a
beginner tool — and they shrink as the tempo climbs so they never overlap
neighbouring notes.

| Grade | Points |
| :--- | :--- |
| Perfect | 100 |
| Good | 75 |
| OK | 45 |
| Miss | 0 |

Accuracy is your points as a share of a perfect run. Stray hits that match no
note are counted and shown at the end, but they do not break your combo.

The open hi-hat band is guidance, not a graded note. The hub does not reliably
report pedal *releases*, so lifting the foot changes the hi-hat sound but is
never scored against you.

At the end you get accuracy, stars, XP, and a one-line read on your timing —
for example *"You are running 24 ms late"*. That last number is the most useful
thing on the screen.

**Stars:** 1 star at 65%, 2 at 80%, 3 at 92%.
**Unlock:** 65% clears a level.

---

## 6. Where your progress lives

```
~/.config/spacedrums/profile.json     XP, unlocked levels, best scores, streak
~/.config/spacedrums/settings.json    port, volume, metronome, input offset
```

Delete either file to reset. `settings.json` is written on first run and
accepts:

| Key | Default | Purpose |
| :--- | :--- | :--- |
| `port` | `null` | `null` means auto-detect |
| `baud` | `500000` | must match the hub |
| `volume` | `0.9` | master volume |
| `input_offset_ms` | `0` | raise it if your hits register late |
| `metronome` | `true` | click track |
| `lookahead_s` | `2.6` | how long notes are visible before they land |

---

## 7. Troubleshooting

**No hub found.** Check the cable, then `ls /dev/ttyACM*` on Linux or Device
Manager on Windows, and pass the port explicitly with `--port`. On Linux a
"permission denied" almost always means you are not in the `dialout` group yet.

**Nothing makes a sound.** The app prints which samples are missing on
startup. Check the `audio/` folder name and the nine filenames above.

**Notes feel consistently early or late.** Raise or lower `input_offset_ms` in
`settings.json`. Positive values compensate for hits arriving late.

**The window will not go fullscreen on Wayland.** Run with
`SDL_VIDEODRIVER=x11 python -m spacedrums_trainer`.

**Choppy animation.** Start with `--no-bloom`. Press `F3` to see the frame
cost.

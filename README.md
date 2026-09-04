# Space Drums 2.0 Operating Guide

Reference for the air-drumming system: two ESP32-S3 sticks --> ESP32-S3 hub --> Python audio engine.


## 1. System overview

```
[Stick 0 / LEFT ]  ESP-NOW ->
                              foot pedal hub  -->  android/PC app
[Stick 1 / RIGHT]  ESP-NOW ->       
```

| File | Runs on | Purpose |
| :--- | :--- | :--- |
| `stick_firmware.ino` | Both sticks | IMU fusion, hit detection, calibration, battery |
| `spacedrums_2_hub.ino` | ESP32-S3 | ESP-NOW receiver, foot pedals, serial bridge |
| `audio_hub.py` | PC |Optional. Sample playback, kit UI, battery display. |
| `SpaceDrums.apk` | Android | Use this instead of the PC app. Sample playback, kit UI, battery display. |

---

## 2. Hardware

### 2.1 Stick pinout (ESP32-S3-MINI-1-N8)

| Function | GPIO | Notes |
| :--- | :--- | :--- |
| SPI MOSI / MISO / SCK | 35 / 37 / 36 | Shared by both IMUs |
| IMU1 CS (U5, tip) | 5 | ICM-42688-P |
| IMU2 CS (U4, base) | 9 | ICM-42688-P: **used for orientation and hit detection** |
| I2C SDA / SCL | 7 / 8 | MMC5983MA magnetometer + DRV2605L haptic |
| Status LED | 41 | Active high |
| PMIC KILL | 11 | Hold **HIGH** to keep power on (active-low kill, 0.6 V threshold) |
| PMIC INT | 12 | LTC2954 button press, active low |
| Battery sense | 4 | ADC1_CH3, R9/R10 = 100k/100k divider, C21 = 0.1 uF |

Only IMU2 (U4, near the base) drives orientation and swing detection. IMU1 is read but currently unused, it sees less useful gravity data mid-swing because it is further from the pivot.

### 2.2 Foot pedals (wired to the hub)

| Pedal | XIAO pin | GPIO |
| :--- | :--- | :--- |
| Left | D0 | 1 |
| Right | D1 | 2 |

Wire each momentary switch **between the pin and GND**. Firmware sets `INPUT_PULLUP`, so it is active-low.

Resistors: internal pull-ups alone are fine for short leads. For pedal-length cable, per channel add:

- **10 kΩ** pin 3V3 (swamps the weak ~45 kΩ internal pull-up)
- **100 nF** pin GND (~1 ms RC, kills noise spikes)
- optional **100 Ω** in series for ESD protection

---

## 3. Build and flash

### 3.1 Arduino IDE settings: sticks (ESP32-S3-MINI-1-N8)

| Setting | Value |
| :--- | :--- |
| **USB CDC On Boot** | **Enabled** |
| USB Mode | Hardware CDC and JTAG |
| Flash Size | 8MB (64Mb) |
| Partition Scheme | any 8MB scheme |
| PSRAM | **Disabled** (N8 has none) |

### 3.2 Per-stick edits

1. `STICK_ID` : `0` for left, `1` for right.
2. `hubAddress[]` : must match the MAC the hub prints at boot.

### 3.3 Order of operations

Flash the **hub first**, read its MAC from serial at 500000 baud, put that into both sticks, then flash the sticks.


---

## 4. Python setup

```powershell
pip install -r requirements.txt
python audio_hub.py
```

Set `COM_PORT` at the top of `audio_hub.py` to the **hub's** port.

Required samples in the same folder:

```
crash.wav  snare.wav  tom1.wav  tom2.wav  ride.wav  hihat.wav  floor_tom.wav
kick.wav   hihat_pedal.wav
```

A missing file falls back to a buzz instead of crashing.

Flags at the top of the file:

| Flag | Default | Effect |
| :--- | :--- | :--- |
| `SHOW_UI` | `True` | `False` = headless terminal mode |
| `CONSOLE_LOG` | `False` | Per-hit printing. Costs milliseconds on Windows — leave off while playing |

---

## 5. Everyday use

### 5.1 Power on

Hold the stick **pointing at where the snare will be** and press the power button.

| Stage | LED | Haptic |
| :--- | :--- | :--- |
| Settling (1.5 s) | solid | - |
| Calibrating | **5 Hz flash** | single click at start |
| Playing | 1 Hz heartbeat | double click when done |

Hold still through the flashing (~1.2 s). If you move, the window silently restarts and keeps flashing, just steady up.

**A long double-buzz instead of a double-click** means it gave up after 8 s and the zero is rough. Short-press to redo.

### 5.2 Re-zero mid-song

**Short-press** the power button. Same 1.5 s sequence. Use it any time the kit feels rotated.

**Long press still powers off** 

### 5.3 What calibration actually does

Sets pitch and yaw to zero **at wherever you are pointing**, plus re-measures gyro bias and builds the attitude from gravity. It is independent of magnetic north, so it works in any room, facing any direction.

---

## 6. Serial commands (stick, 115200)

> **Set the Serial Monitor line ending to "Newline"** — with "No line ending" nothing will run.

| Command | Effect |
| :--- | :--- |
| `help` | List commands |
| `status` | Live pitch/yaw, gyro bias, battery, mag calibration state |
| `cal` | Re-zero orientation (same as a short button press) |
| `magcal` | Run the 18 s figure-8 magnetometer calibration |
| `magclear` | Erase stored magnetometer calibration |
| `magyaw on` / `magyaw off` | Enable/disable the magnetometer yaw anchor |

The banner reprints whenever a serial monitor attaches, so you can connect at any time.

---

## 7. The figure-8 calibration

**Run once per stick. Only on fresh firmware install.**

It calibrates hard/soft-iron distortion from the stick's *own* magnetics: battery, haptic actuator, copper. 

### Procedure

1. Move away from speakers, PCs, steel furniture. Use a long USB cable, the PC itself is a disturber.
2. Type `magcal`. You get 18 seconds.
3. Trace slow figure-8s like you would do in a smartphone to calibrate the compass.
4. Read the verdict.


| Failure | Meaning | Fix |
| :--- | :--- | :--- |
| Not enough samples | Ended early | Keep moving the full 18 s |
| Poor coverage | Only one plane covered | Roll the stick as well as sweeping it |
| High residual | Nearby iron distorted the field | Move further away and retry |

**Bad data is never saved**, a FAIL leaves your previous calibration intact.


---

## 8. Drum layout

Zones are measured in degrees from your calibrated snare aim.

**Top row**: selected when pitch >= 25°, gated at +-110°:

| Aim | Drum |
| :--- | :--- |
| -110° ... -45° | Crash |
| -45° ... 0° | Tom 1 |
| 0° ... +45° | Tom 2 |
| +45° ... +110° | Ride |

**Bottom row**: pitch < 25°, gated at +-90°:

| Aim | Drum |
| :--- | :--- |
| -90° ... -30° | Hi-hat |
| -30° ... +30° | Snare |
| +30° ... +90° | Floor tom |

Outside the outer gates, nothing fires.

### Pedals

- **Right pedal** --> always kick.
- **Left pedal** --> kick *or* hi-hat close, selectable in the UI.

The firmware only reports *which pedal moved*; app decides the sound, so changing modes never needs a reflash.

---

## 9. Python UI

| Element | Meaning |
| :--- | :--- |
| Drum lights up | Cyan = left stick, orange = right stick; brightness scales with velocity |
| Pedal box | Flashes green; shows its current assignment |
| Battery bars | Green / amber <=45% / red <=20%; greyed and "old" if silent >60 s |
| Top-left text | Hub connection status (auto-reconnects every 2 s) |

| Key / action | Effect |
| :--- | :--- |
| Click left pedal box, or **L** | Toggle left pedal between hi-hat and kick |
| **Z** / **X** | Simulate left / right pedal (testing without hardware) |
| **ESC** or close window | Quit |

---

## 10. Serial protocol (hub → PC, 500000 baud)

| Line | Meaning |
| :--- | :--- |
| `H,<stick_id>,<drum_id>,<velocity>` | Hit. velocity 1-6 |
| `B,<stick_id>,<percent>,<millivolts>` | Battery, every 10 s per stick |
| `P,<pedal_id>[,<velocity>]` | Pedal. 0 = left, 1 = right. Velocity optional |

Drum IDs: `1` crash, `2` snare, `3` tom1, `4` tom2, `5` ride, `6` hihat, `7` floor_tom, `8` kick, `9` hihat_pedal.

ESP-NOW packet (7 bytes, packed, identical on stick and hub):

```
type | stick_id | drum_id | velocity | battery_pct | battery_mv(16-bit)
```

`type`: 0 = hit, 1 = battery, 2 = pedal (hub-generated only). The hub drops any packet whose length does not match, so mismatched firmware cannot produce garbage hits.

---

## 11. Tuning reference

All in the tunables block near the top of `stick_firmware.ino`.

### Feel / mapping

| Constant | Default | Raise it to... |
| :--- | :--- | :--- |
| `TOP_ROW_PITCH` | 25° | Require a higher aim for cymbals/toms |
| `TOP_YAW_CRASH` / `TOP_YAW_RIDE` | -+45° | Push crash/ride further out |
| `TOP_YAW_OUTER` | 110° | Widen the top catch area (lower to ~95 if you get phantom crashes) |
| `BOT_YAW_HIHAT` / `BOT_YAW_FLOOR` | -+30° | Widen the snare zone |
| `SWING_START_THRESHOLD` | 4000 | Require a harder swing to arm |
| `HIT_DECEL_THRESHOLD` | 3000 | Require sharper deceleration to fire |

### Orientation quality

| Constant | Default | Purpose |
| :--- | :--- | :--- |
| `ACC_KP` | 0.5 | Gravity correction strength (~2 s time constant) |
| `ZUPT_ALPHA` | 0.002 | How fast gyro bias re-learns while at rest |
| `MAG_YAW_GAIN` | 0.004 | Magnetometer yaw pull (~5 s time constant) |
| `CAL_GYRO_STILL_LSB` | 200 | Stillness required during calibration (~12 °/s) |

### Battery

| Constant | Default | Purpose |
| :--- | :--- | :--- |
| `VBAT_CAL_SCALE` | 1.0 | Trim if the reading disagrees with a multimeter |
| `VBAT_SEND_MS` | 10000 | Report interval |

### Hub

| Constant | Default | Purpose |
| :--- | :--- | :--- |
| `PEDAL_LOCKOUT_MS` | 35 | Debounce lock-out. Raise to 50 if a press produces repeats; stay under ~75 for fast double bass |
| `PEDAL_VELOCITY` | 6 | Pedal loudness (1-6) |

import os
import serial
import sys
import threading
import pygame
import time

# ==========================================
# CONFIGURATION
# ==========================================
COM_PORT = '/dev/ttyACM0'   #  XIAO'S COM PORT. Eg. '/dev/ttyACM0' for linux or 'COM3' for windows
BAUD_RATE = 500000  # Matches the ultra-fast hub baud rate

SHOW_UI = True
CONSOLE_LOG = False   # printing from the audio thread costs milliseconds on Windows
WINDOW_SIZE = (860, 620)
TARGET_FPS = 60
FLASH_SEC = 0.28      # how long a struck drum stays lit

# Samples live next to this script in ./audio
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio")

VOLUME_MAP = {1: 0.20, 2: 0.40, 3: 0.60, 4: 0.80, 5: 0.90, 6: 1.00}
DRUM_MAP = {1: "crash", 2: "snare", 3: "tom1", 4: "tom2", 5: "ride", 6: "hihat", 7: "floor_tom"}
HIHAT_DRUM_ID = 6
SAMPLE_NAMES = ("crash", "snare", "tom1", "tom2", "ride", "floor_tom",
                "hihat_open", "hihat_closed", "kick")
STICK_NAMES = {0: "LEFT", 1: "RIGHT"}
LOW_BATTERY_PCT = 20

# The firmware only reports pedal position; this side decides what it means.
PEDAL_SOUND_NAMES = {"kick": "KICK", "hihat": "HI-HAT"}
LEFT_PEDAL_DEFAULT = "hihat"
PEDAL_LEFT, PEDAL_RIGHT = 0, 1
HIHAT_CHOKE_MS = 60   # closing the pedal damps a ringing open hi-hat

# Kit layout: drum_id -> (x, y, radius, label)
DRUM_LAYOUT = {
    1: (128, 175, 64, "CRASH"),
    3: (330, 180, 54, "TOM 1"),
    4: (520, 180, 54, "TOM 2"),
    5: (722, 175, 64, "RIDE"),
    6: (158, 385, 58, "HIHAT"),
    2: (425, 395, 74, "SNARE"),
    7: (690, 385, 68, "FLOOR"),
}
CYMBALS = {1, 5, 6}

# Pedal layout: pedal_id -> (x, y, w, h, label)
PEDAL_LAYOUT = {
    PEDAL_LEFT:  (240, 498, 170, 56, "LEFT PEDAL"),
    PEDAL_RIGHT: (450, 498, 170, 56, "RIGHT PEDAL"),
}

# The GIL can stall the audio thread for a whole switch interval; 1 ms keeps the
# UI from ever delaying a hit by a perceptible amount.
sys.setswitchinterval(0.001)

# Shared state. Plain dict writes are atomic under the GIL, so the audio thread
# never takes a lock on the hit path.
battery_state = {}    # stick_id -> {"pct", "mv", "time"}
hit_flash = {}        # drum_id  -> (timestamp, stick_id, velocity_zone)
pedal_flash = {}      # pedal_id -> (timestamp, mode, velocity_zone)
pedal_pressed = {PEDAL_LEFT: False, PEDAL_RIGHT: False}
left_pedal_mode = {"value": LEFT_PEDAL_DEFAULT}
serial_status = {"text": "connecting...", "ok": False}
open_hihat_channel = {"ch": None}


def battery_bar(pct, width=10):
    filled = int(round(pct / 100 * width))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def handle_battery(stick_id, pct, mv):
    prev = battery_state.get(stick_id)
    battery_state[stick_id] = {"pct": pct, "mv": mv, "time": time.time()}
    if CONSOLE_LOG and (prev is None or prev["pct"] != pct):
        name = STICK_NAMES.get(stick_id, f"STICK{stick_id}")
        warn = "  <-- LOW BATTERY" if pct <= LOW_BATTERY_PCT else ""
        print(f"[BATTERY] {name:<5} {battery_bar(pct)} {pct:3d}%  ({mv / 1000:.2f} V){warn}")


def battery_summary():
    if not battery_state:
        return "no battery reports yet"
    now = time.time()
    parts = []
    for stick_id in sorted(battery_state):
        s = battery_state[stick_id]
        name = STICK_NAMES.get(stick_id, f"STICK{stick_id}")
        stale = " (stale)" if now - s["time"] > 60 else ""
        parts.append(f"{name} {s['pct']}% / {s['mv'] / 1000:.2f}V{stale}")
    return "  |  ".join(parts)


# ==========================================
# PYGAME SOUND GENERATION 
# ==========================================
pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=256)
pygame.init()
pygame.mixer.set_num_channels(32) 

drum_samples = {}
for name in SAMPLE_NAMES:
    path = os.path.join(AUDIO_DIR, f"{name}.wav")
    try:
        drum_samples[name] = pygame.mixer.Sound(path)
    except FileNotFoundError:
        print(f"Warning: '{path}' not found.")
        drum_samples[name] = pygame.mixer.Sound(buffer=b'\x00\x7F' * 1000)

print(f"Audio Engine Ready. Listening to Receiver Hub on {COM_PORT} at {BAUD_RATE} baud...")


def hihat_is_closed():
    return left_pedal_mode["value"] == "hihat" and pedal_pressed[PEDAL_LEFT]


def sample_for_drum(drum_id):
    if drum_id == HIHAT_DRUM_ID:
        return "hihat_closed" if hihat_is_closed() else "hihat_open"
    return DRUM_MAP.get(drum_id)


def choke_open_hihat():
    ch = open_hihat_channel["ch"]
    if ch is not None and ch.get_busy() and ch.get_sound() is drum_samples["hihat_open"]:
        ch.fadeout(HIHAT_CHOKE_MS)
    open_hihat_channel["ch"] = None


def toggle_left_pedal():
    left_pedal_mode["value"] = "kick" if left_pedal_mode["value"] == "hihat" else "hihat"


def handle_pedal(pedal_id, velocity_zone, pressed):
    pedal_pressed[pedal_id] = pressed
    mode = "kick" if pedal_id == PEDAL_RIGHT else left_pedal_mode["value"]

    if mode == "hihat":
        # Silent pedal: it only decides which hi-hat sample the sticks trigger.
        if pressed:
            choke_open_hihat()
        pedal_flash[pedal_id] = (time.time(), mode, velocity_zone)
        if CONSOLE_LOG:
            print(f"[PEDAL LEFT] HI-HAT {'CLOSED' if pressed else 'OPEN'}")
        return

    if not pressed or velocity_zone not in VOLUME_MAP:
        return

    target_channel = pygame.mixer.find_channel()
    if target_channel:
        volume = VOLUME_MAP[velocity_zone]
        target_channel.set_volume(volume, volume)  # pedals sit centre, no panning
        target_channel.play(drum_samples["kick"])

    pedal_flash[pedal_id] = (time.time(), mode, velocity_zone)
    if CONSOLE_LOG:
        side = "LEFT" if pedal_id == PEDAL_LEFT else "RIGHT"
        print(f"[PEDAL {side}] {PEDAL_SOUND_NAMES[mode]}")


# ==========================================
# HIGH-SPEED SERIAL LISTENER
# ==========================================
def serial_listener():
    while True:
        try:
            # No timeout: readline() blocks until a full line arrives.
            ser = serial.Serial(COM_PORT, BAUD_RATE)
            serial_status["text"] = f"Hub connected  {COM_PORT} @ {BAUD_RATE}"
            serial_status["ok"] = True
        except Exception as e:
            serial_status["text"] = f"Cannot open {COM_PORT}: {e}"
            serial_status["ok"] = False
            time.sleep(2)
            continue

        try:
            while True:
                raw_line = ser.readline().decode('utf-8', errors='ignore').strip()

                if raw_line.startswith("H,"):
                    parts = raw_line.split(",")
                    if len(parts) == 4:
                        stick_id = int(parts[1])
                        drum_id = int(parts[2])
                        velocity_zone = int(parts[3])
                        sample = sample_for_drum(drum_id)

                        if sample in drum_samples and velocity_zone in VOLUME_MAP:
                            target_channel = pygame.mixer.find_channel()
                            if target_channel:
                                volume = VOLUME_MAP[velocity_zone]

                                # Stereo Panning
                                if stick_id == 0:
                                    target_channel.set_volume(volume * 0.9, volume * 0.4)
                                else:
                                    target_channel.set_volume(volume * 0.4, volume * 0.9)

                                target_channel.play(drum_samples[sample])
                                if sample == "hihat_open":
                                    open_hihat_channel["ch"] = target_channel

                            # Presentation only - the sound is already on its way out.
                            hit_flash[drum_id] = (time.time(), stick_id, velocity_zone)
                            if CONSOLE_LOG:
                                side_str = STICK_NAMES.get(stick_id, str(stick_id))
                                print(f"[{side_str}] {sample.upper()} | "
                                      f"Vol: {int(VOLUME_MAP[velocity_zone] * 100)}%")

                elif raw_line.startswith("B,"):
                    parts = raw_line.split(",")
                    if len(parts) == 4:
                        handle_battery(int(parts[1]), int(parts[2]), int(parts[3]))

                elif raw_line.startswith("P,"):
                    # P,<pedal_id>,<velocity_zone>,<pressed>  - trailing fields optional
                    parts = raw_line.split(",")
                    if len(parts) in (2, 3, 4):
                        handle_pedal(int(parts[1]),
                                     int(parts[2]) if len(parts) >= 3 else 6,
                                     int(parts[3]) == 1 if len(parts) == 4 else True)
        except Exception as e:
            serial_status["text"] = f"Serial error: {e}"
            serial_status["ok"] = False
            try:
                ser.close()
            except Exception:
                pass
            time.sleep(1)


# ==========================================
# LIGHTWEIGHT UI
# ==========================================
BG           = (16, 18, 24)
PANEL        = (26, 30, 38)
OUTLINE      = (70, 78, 92)
TEXT         = (196, 204, 218)
TEXT_DIM     = (110, 120, 138)
DRUM_BASE    = (44, 52, 68)
CYMBAL_BASE  = (74, 64, 38)
PEDAL_BASE   = (38, 44, 58)
PEDAL_HOT    = (150, 220, 150)
STICK_COLORS = {0: (64, 208, 255), 1: (255, 150, 64)}
GOOD         = (90, 210, 130)
WARN         = (240, 190, 70)
BAD          = (235, 90, 90)


def lerp(c1, c2, t):
    return (int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t))


def battery_color(pct):
    if pct <= LOW_BATTERY_PCT:
        return BAD
    return WARN if pct <= 45 else GOOD


def draw_battery_panel(screen, font_small, font_tiny, now):
    x, y, w = WINDOW_SIZE[0] - 268, 18, 248
    pygame.draw.rect(screen, PANEL, (x, y, w, 88), border_radius=8)
    for i, stick_id in enumerate((0, 1)):
        row_y = y + 16 + i * 36
        name = STICK_NAMES.get(stick_id, str(stick_id))
        screen.blit(font_small.render(name, True, STICK_COLORS[stick_id]), (x + 12, row_y))
        bar_x, bar_w, bar_h = x + 74, 92, 14
        pygame.draw.rect(screen, (40, 46, 58), (bar_x, row_y + 2, bar_w, bar_h), border_radius=4)

        s = battery_state.get(stick_id)
        if s is None:
            screen.blit(font_tiny.render("--", True, TEXT_DIM), (bar_x + bar_w + 10, row_y + 3))
            continue

        stale = (now - s["time"]) > 60
        col = TEXT_DIM if stale else battery_color(s["pct"])
        pygame.draw.rect(screen, col, (bar_x, row_y + 2, max(2, int(bar_w * s["pct"] / 100)), bar_h),
                         border_radius=4)
        label = f"{s['pct']:3d}% {s['mv'] / 1000:.2f}V" + (" old" if stale else "")
        screen.blit(font_tiny.render(label, True, col), (bar_x + bar_w + 10, row_y + 3))


def draw_pedals(screen, name_labels, mode_labels, hint_label, now):
    for pid, (x, y, w, h, _) in PEDAL_LAYOUT.items():
        mode = "kick" if pid == PEDAL_RIGHT else left_pedal_mode["value"]
        ev = pedal_flash.get(pid)
        glow = 0.0
        if mode == "hihat" and pedal_pressed[pid]:
            glow = 1.0   # a held hi-hat pedal stays lit, it is not a one-shot
        elif ev is not None:
            age = now - ev[0]
            if age < FLASH_SEC:
                glow = (1.0 - age / FLASH_SEC) * (0.45 + 0.55 * ev[2] / 6.0)

        rect = (x, y, w, h)
        pygame.draw.rect(screen, lerp(PEDAL_BASE, PEDAL_HOT, glow), rect, border_radius=10)
        pygame.draw.rect(screen, OUTLINE, rect, 2, border_radius=10)

        name = name_labels[pid]
        screen.blit(name, (x + w // 2 - name.get_width() // 2, y + 9))

        if mode == "hihat":
            key = "hihat_closed" if pedal_pressed[pid] else "hihat_open"
        else:
            key = "kick"
        sound = mode_labels[key]
        screen.blit(sound, (x + w // 2 - sound.get_width() // 2, y + 31))

    lx, ly, lw, lh, _ = PEDAL_LAYOUT[PEDAL_LEFT]
    screen.blit(hint_label, (lx + lw // 2 - hint_label.get_width() // 2, ly + lh + 6))


def run_ui():
    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption("Space Drums 2.0")
    clock = pygame.time.Clock()
    font_small = pygame.font.SysFont("consolas", 16, bold=True)
    font_tiny = pygame.font.SysFont("consolas", 13)

    # Rasterise once: font.render every frame is the expensive part of a pygame UI.
    labels = {did: font_small.render(v[3], True, TEXT) for did, v in DRUM_LAYOUT.items()}
    pedal_names = {pid: font_small.render(v[4], True, TEXT) for pid, v in PEDAL_LAYOUT.items()}
    pedal_modes = {
        "kick": font_tiny.render("-> KICK", True, TEXT_DIM),
        "hihat_open": font_tiny.render("-> HI-HAT OPEN", True, TEXT_DIM),
        "hihat_closed": font_tiny.render("-> HI-HAT CLOSED", True, TEXT_DIM),
    }
    pedal_hint = font_tiny.render("click or press L to change", True, TEXT_DIM)
    hint = font_tiny.render("ESC or close the window to quit", True, TEXT_DIM)
    left_pedal_rect = pygame.Rect(PEDAL_LAYOUT[PEDAL_LEFT][:4])

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_l:
                    toggle_left_pedal()
                elif event.key == pygame.K_z:
                    handle_pedal(PEDAL_LEFT, 6, True)
                elif event.key == pygame.K_x:
                    handle_pedal(PEDAL_RIGHT, 6, True)
            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_z:
                    handle_pedal(PEDAL_LEFT, 6, False)
                elif event.key == pygame.K_x:
                    handle_pedal(PEDAL_RIGHT, 6, False)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if left_pedal_rect.collidepoint(event.pos):
                    toggle_left_pedal()

        now = time.time()
        screen.fill(BG)

        for did, (x, y, r, _) in DRUM_LAYOUT.items():
            base = CYMBAL_BASE if did in CYMBALS else DRUM_BASE
            ev = hit_flash.get(did)
            glow = 0.0
            stick_id = 0
            if ev is not None:
                age = now - ev[0]
                if age < FLASH_SEC:
                    stick_id = ev[1]
                    glow = (1.0 - age / FLASH_SEC) * (0.45 + 0.55 * ev[2] / 6.0)

            if glow > 0.0:
                hot = STICK_COLORS.get(stick_id, GOOD)
                pygame.draw.circle(screen, lerp(BG, hot, glow * 0.45), (x, y), int(r + 14 * glow))
                pygame.draw.circle(screen, lerp(base, hot, glow), (x, y), r)
            else:
                pygame.draw.circle(screen, base, (x, y), r)
            pygame.draw.circle(screen, OUTLINE, (x, y), r, 2)

            lab = labels[did]
            screen.blit(lab, (x - lab.get_width() // 2, y - lab.get_height() // 2))

        draw_pedals(screen, pedal_names, pedal_modes, pedal_hint, now)
        draw_battery_panel(screen, font_small, font_tiny, now)
        screen.blit(font_small.render(serial_status["text"], True,
                                      GOOD if serial_status["ok"] else BAD), (24, 24))
        screen.blit(hint, (24, WINDOW_SIZE[1] - 28))

        pygame.display.flip()
        clock.tick(TARGET_FPS)   # sleeps out the rest of the frame, releasing the GIL


if __name__ == "__main__":
    net_thread = threading.Thread(target=serial_listener, daemon=True)
    net_thread.start()

    try:
        if SHOW_UI:
            run_ui()
        else:
            while True:
                time.sleep(30)
                print(f"[STATUS] {battery_summary()}")
    except KeyboardInterrupt:
        pass
    finally:
        print("\nClosing Air Drum System.")
        pygame.quit()

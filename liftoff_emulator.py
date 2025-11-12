import json, os, sys, time
import pygame
import pyvjoy

# === загрузка конфигурации ===
CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    print(f"[config] {CONFIG_FILE} not found")
    sys.exit(1)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    cfg = json.load(f)

ctrl = cfg.get("control", {})
MIN_US = ctrl.get("min_us", 1000)
MID_US = ctrl.get("mid_us", 1500)
MAX_US = ctrl.get("max_us", 2000)
STEP = ctrl.get("step", 2)
FAST_STEP = ctrl.get("fast_step", 5)
BUFF_SIZE = ctrl.get("buff_size", 200)

# === инициализация vJoy и pygame ===
try:
    j = pyvjoy.VJoyDevice(1)
except pyvjoy.vJoyException:
    print("❌ Не удалось подключиться к vJoy. Убедись, что драйвер установлен и включён vJoy Device #1")
    sys.exit(1)

pygame.init()
screen = pygame.display.set_mode((1000, 600))
pygame.display.set_caption("Liftoff Keyboard → vJoy Emulator")
font = pygame.font.SysFont("DejaVu Sans", 26)
font_small = pygame.font.SysFont("DejaVu Sans", 20)
clock = pygame.time.Clock()

# === функции ===
def clamp(v, lo=MIN_US, hi=MAX_US):
    return lo if v < lo else hi if v > hi else v

def approach(v, target, delta):
    if v < target - delta: return v + delta
    if v > target + delta: return v - delta
    return target

def map_to_vjoy(v):
    return int((v - MIN_US) / (MAX_US - MIN_US) * 32767)

def next_three(v):
    """циклический переключатель 3 положения"""
    if v <= MIN_US + 10:
        return MID_US
    elif v < MAX_US - 10:
        return MAX_US
    else:
        return MIN_US

# === состояние каналов ===
ch = [MID_US] * 8
ch[2] = MIN_US  # throttle снизу
for i in range(4, 8):
    ch[i] = MIN_US  # AUX в LOW

RETURN_SPEED = 25
SEND_HZ = 50

running = True
while running:
    dt = clock.tick(120) / 1000.0
    keys = pygame.key.get_pressed()
    fast = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
    step = FAST_STEP if fast else STEP

    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False
        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                running = False
            elif e.key == pygame.K_SPACE:
                ch[2] = MIN_US  # Kill throttle
            elif e.key == pygame.K_c:
                for i in range(4, 8):
                    ch[i] = MIN_US
            elif e.key == pygame.K_5:
                ch[4] = next_three(ch[4])
            elif e.key == pygame.K_6:
                ch[5] = next_three(ch[5])
            elif e.key == pygame.K_7:
                ch[6] = next_three(ch[6])
            elif e.key == pygame.K_8:
                ch[7] = next_three(ch[7])

    # === логика ARM/DISARM ===
    armed = ch[7] > MID_US
    if not armed:
        ch[2] = MIN_US  # DISARMED → throttle всегда 0
    else:
        # стики активны
        if keys[pygame.K_LEFT]:  ch[0] = clamp(ch[0] - step)
        if keys[pygame.K_RIGHT]: ch[0] = clamp(ch[0] + step)
        if keys[pygame.K_UP]:    ch[1] = clamp(ch[1] + step)
        if keys[pygame.K_DOWN]:  ch[1] = clamp(ch[1] - step)
        if keys[pygame.K_w]: ch[2] = clamp(ch[2] + step)
        if keys[pygame.K_s]: ch[2] = clamp(ch[2] - step)
        if keys[pygame.K_a]: ch[3] = clamp(ch[3] - step)
        if keys[pygame.K_d]: ch[3] = clamp(ch[3] + step)

    # возврат стиков в центр (кроме throttle)
    for i in (0, 1, 3):
        if (i == 0 and not (keys[pygame.K_LEFT] or keys[pygame.K_RIGHT])) \
           or (i == 1 and not (keys[pygame.K_UP] or keys[pygame.K_DOWN])) \
           or (i == 3 and not (keys[pygame.K_a] or keys[pygame.K_d])):
            ch[i] = approach(ch[i], MID_US, RETURN_SPEED)

    # === отправка в vJoy ===
    j.set_axis(pyvjoy.HID_USAGE_X,  map_to_vjoy(ch[0]))  # Roll
    j.set_axis(pyvjoy.HID_USAGE_Y,  map_to_vjoy(ch[1]))  # Pitch
    j.set_axis(pyvjoy.HID_USAGE_Z,  map_to_vjoy(ch[2]))  # Throttle
    j.set_axis(pyvjoy.HID_USAGE_RZ, map_to_vjoy(ch[3]))  # Yaw

    # === интерфейс ===
    screen.fill((18, 18, 25))
    txt = font.render("Liftoff Keyboard → vJoy (Esc = Exit)", True, (200, 200, 210))
    screen.blit(txt, (40, 20))

    # ARM статус
    arm_state = "ARMED" if armed else "DISARMED"
    arm_color = (0, 255, 0) if armed else (255, 80, 80)
    arm_label = font.render(arm_state, True, arm_color)
    screen.blit(arm_label, (750, 20))

    # каналы визуально
    labels = ["Roll", "Pitch", "Throttle", "Yaw", "AUX5", "AUX6", "AUX7", "AUX8"]
    base_y = 100
    bar_w = 600
    for i, v in enumerate(ch):
        y = base_y + i * 55
        pygame.draw.rect(screen, (80, 80, 90), (200, y, bar_w, 25), 2)
        t = (v - MIN_US) / (MAX_US - MIN_US)
        pygame.draw.rect(screen, (90, 170, 255), (200, y, int(bar_w * t), 25))
        lbl = font_small.render(f"{labels[i]}: {int(v)}", True, (230, 230, 230))
        screen.blit(lbl, (40, y + 3))
        if i >= 4:
            if v <= MIN_US + 10:
                state = ("LOW", (255, 120, 120))
            elif v >= MAX_US - 10:
                state = ("HIGH", (120, 255, 120))
            else:
                state = ("MID", (255, 255, 120))
            s_txt = font_small.render(state[0], True, state[1])
            screen.blit(s_txt, (850, y + 3))

    help_lines = [
        "←/→ Roll | ↑/↓ Pitch | W/S Throttle | A/D Yaw",
        "5–8: AUX (3-pos) | C: reset AUX | Space: Kill Throttle",
        "CH8 controls ARM/DISARM (DISARM locks sticks)"
    ]
    for j, t in enumerate(help_lines):
        tip = font_small.render(t, True, (180, 180, 190))
        screen.blit(tip, (40, 520 + j * 24))

    pygame.display.flip()

pygame.quit()

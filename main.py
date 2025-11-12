import time
import sys
import pygame
import serial

MIN_US, MID_US, MAX_US = 1000, 1500, 2000

CANDIDATE_PORTS = [
    "/dev/ttyUSB0", "/dev/ttyUSB1",
    "/dev/ttyACM0", "/dev/ttyACM1",
    "COM3", "COM4", "COM5"
]
BAUD = 115200
SEND_HZ = 50
STEP = 2
FAST_STEP = 5
RETURN_SPEED = 25
BUFF_SIZE = 200


# === вспомогательные функции ===
def clamp(v, lo=MIN_US, hi=MAX_US): return lo if v < lo else hi if v > hi else v


def is_mid(v): return MID_US - BUFF_SIZE <= v <= MID_US + BUFF_SIZE


def next_three(v):
    """циклический переключатель 3 положения"""
    if v <= MIN_US + 10:
        return MID_US
    elif v < MAX_US - 10:
        return MAX_US
    else:
        return MIN_US


def try_open_port():
    for p in CANDIDATE_PORTS:
        try:
            ser = serial.Serial(p, BAUD, timeout=0)
            time.sleep(0.2)
            print(f"[serial] connected: {p}")
            return ser, p
        except Exception:
            continue
    print("[serial] no port — running in NO SERIAL mode")
    return None, "OFF"


def send_line(ser, ch):
    if ser is None:
        return
    line = ",".join(str(v) for v in ch) + "\n"
    try:
        ser.write(line.encode("ascii"))
    except Exception as e:
        print(f"[serial] write error: {e}")


# === отрисовка ===
def draw_ui(screen, font, font_small, ch, fps, portname, ser_connected):
    screen.fill((15, 15, 18))
    w, h = screen.get_size()
    left, top = 180, 80
    bar_w, bar_h, gap = w - left - 120, 45, 25

    # статус строки
    if ser_connected:
        header = font.render(f"Serial: {portname}   FPS: {fps:.0f}", True, (220, 220, 220))
    else:
        header = font.render(f"NO SERIAL CONNECTION", True, (255, 60, 60))
    screen.blit(header, (40, 20))

    for i, v in enumerate(ch):
        y = top + i * (bar_h + gap)
        pygame.draw.rect(screen, (70, 70, 80), (left, y, bar_w, bar_h), 2, border_radius=8)
        t = (v - MIN_US) / (MAX_US - MIN_US)
        fill = int(bar_w * t)
        pygame.draw.rect(screen, (90, 170, 255), (left + 3, y + 3, max(0, fill - 6), bar_h - 6), 0, border_radius=8)

        # подписи
        label = font.render(f"CH{i + 1}", True, (230, 230, 240))
        screen.blit(label, (60, y + 8))
        val = font.render(str(v), True, (255, 255, 255))
        screen.blit(val, (left + bar_w + 25, y + 8))
        cx = left + int(bar_w * (MID_US - MIN_US) / (MAX_US - MIN_US))
        pygame.draw.line(screen, (100, 100, 120), (cx, y), (cx, y + bar_h), 1)

        # подписи ON/OFF/3 pos для AUX
        if i >= 4:
            if v <= MIN_US + 10:
                state = ("LOW", (255, 120, 120))
            elif v >= MAX_US - 10:
                state = ("HIGH", (120, 255, 120))
            else:
                state = ("MID", (255, 255, 120))
            txt = font_small.render(state[0], True, state[1])
            screen.blit(txt, (20, y + 12))

    help_lines = [
        "Right stick: ←/→ = CH1 (Roll), ↑/↓ = CH2 (Pitch)",
        "Left stick: W/S = CH3 (Throttle), A/D = CH4 (Yaw)",
        "AUX 1..4 = CH5..CH8 (3-position) | C: center (CH3->MIN) | X: all MIN | Shift: fast | Esc: exit",
    ]
    for j, tline in enumerate(help_lines):
        tip = font_small.render(tline, True, (190, 190, 200))
        screen.blit(tip, (40, h - 100 + j * 26))


# === основная логика ===
def main():
    ser, portname = try_open_port()
    ser_connected = ser is not None

    pygame.init()
    pygame.display.set_caption("PPM Keyboard → (Arduino) → TX12")
    screen = pygame.display.set_mode((1280, 750))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("DejaVu Sans", 26)
    font_small = pygame.font.SysFont("DejaVu Sans", 20)

    # каналы
    ch = [MID_US] * 8
    ch[2] = MIN_US  # Throttle
    for i in range(4, 8):  # AUX стартуют в MIN
        ch[i] = MIN_US

    send_interval = 1.0 / SEND_HZ
    last_send = 0.0

    running = True
    while running:
        dt = clock.tick(120) / 1000.0
        keys = pygame.key.get_pressed()
        fast = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
        step = FAST_STEP if fast else STEP

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                # трёхтактные AUX
                elif event.key == pygame.K_5:
                    ch[4] = next_three(ch[4])
                elif event.key == pygame.K_6:
                    ch[5] = next_three(ch[5])
                elif event.key == pygame.K_7:
                    ch[6] = next_three(ch[6])
                elif event.key == pygame.K_8:
                    ch[7] = next_three(ch[7])
                elif event.key == pygame.K_SPACE: ch[2] = MIN_US

        # управление стиками
        if keys[pygame.K_LEFT]:  ch[0] = clamp(ch[0] - step)
        if keys[pygame.K_RIGHT]: ch[0] = clamp(ch[0] + step)
        if keys[pygame.K_UP]:    ch[1] = clamp(ch[1] + step)
        if keys[pygame.K_DOWN]:  ch[1] = clamp(ch[1] - step)
        if keys[pygame.K_w]: ch[2] = clamp(ch[2] + step)
        if keys[pygame.K_s]: ch[2] = clamp(ch[2] - step)
        if keys[pygame.K_a]: ch[3] = clamp(ch[3] - step)
        if keys[pygame.K_d]: ch[3] = clamp(ch[3] + step)

        # возврат стиков в центр (CH1, CH2, CH4)
        def approach(v, target, delta):
            if v < target - delta: return v + delta
            if v > target + delta: return v - delta
            return target

        for i in (0, 1, 3):
            if (i == 0 and not (keys[pygame.K_LEFT] or keys[pygame.K_RIGHT])) \
                    or (i == 1 and not (keys[pygame.K_UP] or keys[pygame.K_DOWN])) \
                    or (i == 3 and not (keys[pygame.K_a] or keys[pygame.K_d])):
                ch[i] = approach(ch[i], MID_US, RETURN_SPEED)

        # отправка
        now = time.time()
        if now - last_send >= send_interval:
            send_line(ser, ch)
            last_send = now

        draw_ui(screen, font, font_small, ch, 1.0 / dt if dt > 0 else 0, portname, ser_connected)
        pygame.display.flip()

    if ser: ser.close()
    pygame.quit()


if __name__ == "__main__":
    main()

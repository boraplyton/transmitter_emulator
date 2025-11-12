import time
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
RETURN_SPEED = 25  # скорость возврата стиков в центр (мкс/тик)
BUFF_SIZE = 200  # мёртвая зона для AUX-тогглов


def is_mid(v): return MID_US - BUFF_SIZE <= v <= MID_US + BUFF_SIZE


def clamp(v, lo=MIN_US, hi=MAX_US): return lo if v < lo else hi if v > hi else v


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
    if ser is None: return
    line = ",".join(str(v) for v in ch) + "\n"
    try:
        ser.write(line.encode("ascii"))
    except Exception as e:
        print(f"[serial] write error: {e}")


def draw_ui(screen, font, ch, fps, portname):
    screen.fill((18, 18, 22))
    w, h = screen.get_size()
    left, top = 120, 40
    bar_w, bar_h, gap = w - left - 40, 30, 18

    header = font.render(f"Serial: {portname}   FPS: {fps:.0f}", True, (230, 230, 230))
    screen.blit(header, (20, 10))

    for i, v in enumerate(ch):
        y = top + i * (bar_h + gap)
        pygame.draw.rect(screen, (60, 60, 70), (left, y, bar_w, bar_h), 2, border_radius=6)
        t = (v - MIN_US) / (MAX_US - MIN_US)
        fill = int(bar_w * t)
        pygame.draw.rect(screen, (90, 170, 255), (left + 2, y + 2, max(0, fill - 4), bar_h - 4), 0, border_radius=6)
        label = font.render(f"CH{i + 1}", True, (200, 200, 210))
        screen.blit(label, (20, y + 4))
        val = font.render(str(v), True, (240, 240, 240))
        screen.blit(val, (left + bar_w + 10, y + 4))
        cx = left + int(bar_w * (MID_US - MIN_US) / (MAX_US - MIN_US))
        pygame.draw.line(screen, (120, 120, 140), (cx, y), (cx, y + bar_h), 1)

    help_lines = [
        "Right stick: ←/→ = CH1 (Roll), ↑/↓ = CH2 (Pitch)",
        "Left stick: W/S = CH3 (Throttle, без возврата), A/D = CH4 (Yaw)",
        "AUX: 1..4 = CH5..CH8 toggle | C: center (CH3->MIN) | X: all MIN | Shift: fast | Esc: exit",
        "NO SERIAL = только визуализация. Подключи Arduino → начнёт слать команды."
    ]
    for j, tline in enumerate(help_lines):
        tip = font.render(tline, True, (180, 180, 190))
        screen.blit(tip, (20, h - 100 + j * 22))


def next_three(v):
    """циклический переход 1000→1500→2000→1000"""
    if v <= MIN_US + 10:  # 1000 → 1500
        return MID_US
    elif v < MAX_US - 10:  # 1500 → 2000
        return MAX_US
    else:  # 2000 → 1000
        return MIN_US


def main():
    ser, portname = try_open_port()

    pygame.init()
    pygame.display.set_caption("PPM Keyboard → (Arduino) → TX12")
    screen = pygame.display.set_mode((900, 560))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("DejaVu Sans", 18)

    ch = [MID_US] * 8
    ch[2] = MIN_US
    for i in range(4, 8):
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
                elif event.key == pygame.K_5:  # CH5
                    ch[4] = next_three(ch[4])
                elif event.key == pygame.K_6:  # CH6
                    ch[5] = next_three(ch[5])
                elif event.key == pygame.K_7:  # CH7
                    ch[6] = next_three(ch[6])
                elif event.key == pygame.K_8:  # CH8
                    ch[7] = next_three(ch[7])
                elif event.key == pygame.K_SPACE:
                    ch[2] = MIN_US

        # управление клавой
        # Правый стик: CH1/CH2
        if keys[pygame.K_LEFT]:  ch[0] = clamp(ch[0] - step)
        if keys[pygame.K_RIGHT]: ch[0] = clamp(ch[0] + step)
        if keys[pygame.K_UP]:    ch[1] = clamp(ch[1] + step)
        if keys[pygame.K_DOWN]:  ch[1] = clamp(ch[1] - step)
        # Левый стик: CH3/CH4
        if keys[pygame.K_w]: ch[2] = clamp(ch[2] + step)
        if keys[pygame.K_s]: ch[2] = clamp(ch[2] - step)
        if keys[pygame.K_a]: ch[3] = clamp(ch[3] - step)
        if keys[pygame.K_d]: ch[3] = clamp(ch[3] + step)

        # ----- возврат в центр -----
        def approach(v, target, delta):
            if v < target - delta: return v + delta
            if v > target + delta: return v - delta
            return target

        # CH1, CH2, CH4 возвращаются в центр
        for i in (0, 1, 3):
            # если не нажаты управляющие клавиши для канала
            if (i == 0 and not (keys[pygame.K_LEFT] or keys[pygame.K_RIGHT])) \
                    or (i == 1 and not (keys[pygame.K_UP] or keys[pygame.K_DOWN])) \
                    or (i == 3 and not (keys[pygame.K_a] or keys[pygame.K_d])):
                ch[i] = approach(ch[i], MID_US, RETURN_SPEED)

        # CH3 (Throttle) не возвращается

        # отправка
        now = time.time()
        if now - last_send >= send_interval:
            send_line(ser, ch)
            last_send = now

        draw_ui(screen, font, ch, 1.0 / dt if dt > 0 else 0, portname)
        pygame.display.flip()

    if ser: ser.close()
    pygame.quit()


if __name__ == "__main__":
    main()

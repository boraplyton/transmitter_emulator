import time
import pygame
import serial
import json, os, sys

from djitellopy import Tello  # управление Tello
import cv2                    # видео с камеры Tello

# === загрузка конфигурации ===
CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    print(f"[config] Файл {CONFIG_FILE} не найден!")
    sys.exit(1)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    cfg = json.load(f)

# ==== применяем параметры ====
serial_cfg = cfg.get("serial", {})
ui_cfg = cfg.get("ui", {})
ctrl_cfg = cfg.get("control", {})

CANDIDATE_PORTS = serial_cfg.get("ports", [])
BAUD = serial_cfg.get("baud", 115200)

MIN_US = ctrl_cfg.get("min_us", 1000)
MID_US = ctrl_cfg.get("mid_us", 1500)
MAX_US = ctrl_cfg.get("max_us", 2000)
STEP = ctrl_cfg.get("step", 2)
FAST_STEP = ctrl_cfg.get("fast_step", 5)
BUFF_SIZE = ctrl_cfg.get("buff_size", 200)
RETURN_SPEED = ui_cfg.get("return_speed", 25)
SEND_HZ = ui_cfg.get("send_hz", 50)

# ---------- настройки Tello ----------
TELLO_MANUAL_SPEED = 40        # ручное управление
TELLO_AUTO_SPEED = 30          # авто-полет (M) влево/вправо
TELLO_AUTO_INTERVAL = 2.0      # каждые N секунд меняем направление

TELLO_SQUARE_SPEED = 20        # квадрат (N) — маленький для квартиры
TELLO_SQUARE_STEP_TIME = 2.0   # длительность одной стороны квадрата, сек

TELLO_FPS = 20                 # "целевая" частота отправки RC-команд
TELLO_SIM_IF_NO_DRONE = True   # включать "симуляцию", если Tello не подключился


# === вспомогательные функции ===
def clamp(v, lo=MIN_US, hi=MAX_US):
    return lo if v < lo else hi if v > hi else v


def is_mid(v):
    return MID_US - BUFF_SIZE <= v <= MID_US + BUFF_SIZE


def next_two(v):
    """двухпозиционный переключатель: MIN <-> MAX"""
    return MAX_US if v <= MIN_US + 10 else MIN_US


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


# === отрисовка UI ===
def draw_ui(screen, font, font_small,
            ch, fps, portname, ser_connected,
            tello_connected, tello_simulation, tello_flying,
            auto_mode, square_mode,
            tello_lr, tello_fb, tello_ud, tello_yw,
            video_surface):

    screen.fill((18, 18, 22))
    w, h = screen.get_size()

    # =======================
    #  Верхняя строка статуса
    # =======================
    if ser_connected:
        hdr = font.render(f"Serial: {portname} | FPS: {fps:.0f}", True, (230, 230, 230))
    else:
        hdr = font.render("NO SERIAL CONNECTION", True, (255, 70, 70))
    screen.blit(hdr, (25, 20))

    armed = ch[7] > MID_US
    arm_text = "ARMED" if armed else "DISARMED"
    arm_color = (0, 255, 0) if armed else (255, 60, 60)
    arm_lbl = font.render(arm_text, True, arm_color)
    screen.blit(arm_lbl, (w - 200, 20))

    # =======================
    #  Левый блок — каналы
    # =======================
    left_x = 40
    top_y = 80
    bar_w = 460
    bar_h = 40
    gap = 18

    for i, v in enumerate(ch):
        y = top_y + i * (bar_h + gap)

        # рамка
        pygame.draw.rect(screen, (70, 70, 80), (left_x, y, bar_w, bar_h), 2, border_radius=6)

        # заполнение
        t = (v - MIN_US) / (MAX_US - MIN_US)
        fill = int(bar_w * t)
        pygame.draw.rect(
            screen, (90, 170, 255),
            (left_x + 3, y + 3, max(fill - 6, 0), bar_h - 6),
            border_radius=6
        )

        # подпись канала
        label = font_small.render(f"CH{i+1}", True, (230, 230, 240))
        screen.blit(label, (left_x - 55, y + 8))

        # значение
        val = font_small.render(str(v), True, (255, 255, 255))
        screen.blit(val, (left_x + bar_w + 15, y + 8))

        # центральная линия
        cx = left_x + int(bar_w * (MID_US - MIN_US) / (MAX_US - MIN_US))
        pygame.draw.line(screen, (110, 110, 130), (cx, y), (cx, y + bar_h), 1)

        # LOW/MID/HIGH для AUX
        if i >= 4:
            if v <= MIN_US + 10:
                state = ("LOW", (255, 120, 120))
            elif v >= MAX_US - 10:
                state = ("HIGH", (120, 255, 120))
            else:
                state = ("MID", (255, 255, 120))
            txt = font_small.render(state[0], True, state[1])
            screen.blit(txt, (left_x - 100, y + 10))

    # =======================
    #   Правый блок — видео + подсказки
    # =======================
    help_x = 600
    line_h = 22

    help_y_start = 80

    # Видео (если есть кадр)
    if video_surface is not None:
        screen.blit(video_surface, (help_x, help_y_start))
        help_y = help_y_start + video_surface.get_height() + 10
    else:
        help_y = help_y_start

    help_lines = [
        "PPM / TX12 Controls:",
        "  ←/→ = CH1 (Roll)",
        "  ↑/↓ = CH2 (Pitch)",
        "  W/S = CH3 (Throttle)",
        "  A/D = CH4 (Yaw)",
        "  5/6/7 = AUX5–7 (2-pos)",
        "  8 = ARM/DISARM",
        "  Space = kill AUX,  C = reset AUX",
        "",
        "Tello Controls:",
        "  Коннект при запуске (если доступен).",
        "  CH5 HIGH (при ARM) → Throw&Go / симуляция взлёта.",
        "  g/j = yaw, y/h = up/down",
        "  k/; = left/right",
        "  o/l = forward/back",
        "  M = авто-маятник (LR)",
        "  N = маленький квадрат",
        "  P = посадка (или стоп симуляции)",
    ]

    for n, line in enumerate(help_lines):
        surf = font_small.render(line, True, (200, 200, 200))
        screen.blit(surf, (help_x, help_y + n * line_h))

    # ===========================
    #   Нижняя строка — статус Tello
    # ===========================
    bottom_y = h - 50

    if tello_connected:
        t_text = "Tello: CONNECTED"
        t_color = (0, 255, 0)
    elif tello_simulation:
        t_text = "Tello: SIMULATION MODE (NO DRONE)"
        t_color = (255, 200, 80)
    else:
        t_text = "Tello: OFF / NO CONNECTION"
        t_color = (255, 80, 80)

    screen.blit(font_small.render(t_text, True, t_color), (40, bottom_y))

    flying_color = (0, 220, 0) if tello_flying else (200, 200, 80)
    screen.blit(font_small.render(f"State: {'FLYING' if tello_flying else 'IDLE'}",
                                  True, flying_color), (320, bottom_y))

    screen.blit(font_small.render(f"Auto M: {'ON' if auto_mode else 'OFF'}",
                                  True, (180, 220, 255)), (520, bottom_y))

    screen.blit(font_small.render(f"Square N: {'ON' if square_mode else 'OFF'}",
                                  True, (180, 220, 255)), (660, bottom_y))

    rc_text = f"TELLO RC: LR={tello_lr} FB={tello_fb} UD={tello_ud} YW={tello_yw}"
    screen.blit(font_small.render(rc_text, True, (120, 200, 255)), (860, bottom_y))


# === основная логика ===
def main():
    # --- serial / PPM ---
    ser, portname = try_open_port()
    ser_connected = ser is not None

    pygame.init()
    pygame.display.set_caption("Каналы управления")
    screen = pygame.display.set_mode((1400, 800))
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("DejaVu Sans", 26)
    font_small = pygame.font.SysFont("DejaVu Sans", 18)

    # --- Tello ---
    drone = None
    frame_read = None
    tello_connected = False
    tello_simulation = False        # режим "управление без дрона"
    tello_flying = False
    tello_takeoff_time = None       # когда делать Throw&Go / старт симуляции

    auto_mode = False
    auto_dir = 1
    last_auto_switch = time.time()
    prev_m_pressed = False

    square_mode = False
    square_step = 0
    square_last_switch = time.time()
    prev_n_pressed = False

    tello_lr = tello_fb = tello_ud = tello_yw = 0

    print("[tello] connecting...")
    try:
        drone = Tello()
        drone.connect()
        try:
            batt = drone.get_battery()
            print(f"[tello] battery: {batt}%")
        except Exception:
            print("[tello] battery read failed")

        # запускаем видео-поток
        drone.streamon()
        frame_read = drone.get_frame_read()

        tello_connected = True
    except Exception as e:
        print(f"[tello] connect failed: {e}")
        drone = None
        tello_connected = False
        frame_read = None
        if TELLO_SIM_IF_NO_DRONE:
            tello_simulation = True
            print("[tello] simulation mode enabled (no physical drone)")

    # --- каналы PPM ---
    ch = [MID_US] * 8
    ch[2] = MIN_US  # Throttle
    for i in range(4, 8):
        ch[i] = MIN_US

    send_interval = 1.0 / SEND_HZ
    last_send = 0.0

    running = True
    while running:
        dt = clock.tick(max(120, TELLO_FPS * 2)) / 1000.0
        keys = pygame.key.get_pressed()
        fast = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
        step = FAST_STEP if fast else STEP

        armed = ch[7] > MID_US
        now = time.time()

        # --- обработка событий ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # ESC: посадить Tello, выйти
                    if (tello_connected or tello_simulation) and tello_flying:
                        print("[tello] ESC → посадка / стоп симуляции")
                        if tello_connected and drone is not None:
                            try:
                                drone.land()
                            except Exception as e:
                                print(f"[tello] land error: {e}")
                        tello_flying = False
                        auto_mode = False
                        square_mode = False
                    running = False

                # CH5–CH7: двухпозиционные при ARM
                if event.key == pygame.K_5 and armed:
                    prev_ch5 = ch[4]
                    ch[4] = next_two(ch[4])

                    # LOW -> HIGH: планируем Throw&Go или симуляцию
                    if prev_ch5 <= MIN_US + 10 and ch[4] >= MAX_US - 10:
                        tello_takeoff_time = now
                        if tello_connected:
                            print("[tello] CH5 HIGH → Throw&Go через 1с, приготовься подбросить дрон")
                        elif tello_simulation:
                            print("[tello] CH5 HIGH → симуляция взлёта через 1с")

                elif event.key == pygame.K_6 and armed:
                    ch[5] = next_two(ch[5])
                elif event.key == pygame.K_7 and armed:
                    ch[6] = next_two(ch[6])

                # CH8 (ARM/DISARM)
                elif event.key == pygame.K_8:
                    ch[7] = next_two(ch[7])

                elif event.key == pygame.K_c:
                    for i in range(4, 8):
                        ch[i] = MIN_US
                elif event.key == pygame.K_SPACE:
                    for i in range(4, 8):
                        ch[i] = MIN_US

                # посадка Tello по P
                elif event.key == pygame.K_p:
                    if (tello_connected or tello_simulation) and tello_flying:
                        print("[tello] P → посадка / стоп симуляции")
                        if tello_connected and drone is not None:
                            try:
                                drone.land()
                            except Exception as e:
                                print(f"[tello] land error: {e}")
                        tello_flying = False
                        auto_mode = False
                        square_mode = False

        # --- PPM логика ---
        armed = ch[7] > MID_US

        if not armed:
            ch[2] = MIN_US
            ch[4] = MIN_US
            ch[5] = MIN_US
            ch[6] = MIN_US
        else:
            if keys[pygame.K_LEFT]:  ch[0] = clamp(ch[0] - step)
            if keys[pygame.K_RIGHT]: ch[0] = clamp(ch[0] + step)
            if keys[pygame.K_UP]:    ch[1] = clamp(ch[1] + step)
            if keys[pygame.K_DOWN]:  ch[1] = clamp(ch[1] - step)
            if keys[pygame.K_w]:     ch[2] = clamp(ch[2] + step)
            if keys[pygame.K_s]:     ch[2] = clamp(ch[2] - step)
            if keys[pygame.K_a]:     ch[3] = clamp(ch[3] - step)
            if keys[pygame.K_d]:     ch[3] = clamp(ch[3] + step)

        def approach(v, target, delta):
            if v < target - delta: return v + delta
            if v > target + delta: return v - delta
            return target

        for i in (0, 1, 3):
            if (i == 0 and not (keys[pygame.K_LEFT] or keys[pygame.K_RIGHT])) \
                    or (i == 1 and not (keys[pygame.K_UP] or keys[pygame.K_DOWN])) \
                    or (i == 3 and not (keys[pygame.K_a] or keys[pygame.K_d])):
                ch[i] = approach(ch[i], MID_US, RETURN_SPEED)

        # --- Tello: запуск Throw&Go / симуляции по таймеру ---
        if tello_takeoff_time is not None and now >= tello_takeoff_time and not tello_flying:
            if tello_connected and drone is not None:
                print("[tello] Throw&Go — подбрось дрон!")
                try:
                    drone.initiate_throw_takeoff()
                    tello_flying = True
                except Exception as e:
                    print(f"[tello] initiate_throw_takeoff error: {e}")
                    tello_flying = False
            elif tello_simulation:
                print("[tello] симуляция: считаем, что Tello взлетел")
                tello_flying = True
            tello_takeoff_time = None

        # --- Tello управление / симуляция ---
        tello_lr = tello_fb = tello_ud = tello_yw = 0

        if (tello_connected or tello_simulation) and tello_flying:
            # ручной ввод
            if keys[pygame.K_g]:
                tello_yw = -TELLO_MANUAL_SPEED
            elif keys[pygame.K_j]:
                tello_yw = TELLO_MANUAL_SPEED

            if keys[pygame.K_y]:
                tello_ud = TELLO_MANUAL_SPEED
            elif keys[pygame.K_h]:
                tello_ud = -TELLO_MANUAL_SPEED

            if keys[pygame.K_k]:
                tello_lr = -TELLO_MANUAL_SPEED
            elif keys[pygame.K_SEMICOLON]:
                tello_lr = TELLO_MANUAL_SPEED

            if keys[pygame.K_o]:
                tello_fb = TELLO_MANUAL_SPEED
            elif keys[pygame.K_l]:
                tello_fb = -TELLO_MANUAL_SPEED

            # M — авто-маятник
            m_pressed = keys[pygame.K_m]
            if m_pressed and not prev_m_pressed:
                auto_mode = not auto_mode
                if auto_mode:
                    square_mode = False
                    auto_dir = 1
                    last_auto_switch = now
                    print("[tello] Auto mode (M) ON")
                else:
                    print("[tello] Auto mode (M) OFF")
            prev_m_pressed = m_pressed

            # N — квадрат
            n_pressed = keys[pygame.K_n]
            if n_pressed and not prev_n_pressed:
                if not square_mode:
                    square_mode = True
                    auto_mode = False
                    square_step = 0
                    square_last_switch = now
                    print("[tello] Square mode (N) START")
            prev_n_pressed = n_pressed

            manual_active = (tello_lr != 0 or tello_fb != 0 or tello_ud != 0 or tello_yw != 0)

            if auto_mode and manual_active:
                auto_mode = False
                print("[tello] Auto mode OFF (перехват руками)")

            if square_mode and manual_active:
                square_mode = False
                print("[tello] Square mode OFF (перехват руками)")

            # логика квадрата
            if square_mode and not manual_active:
                directions = [
                    (0,  TELLO_SQUARE_SPEED),
                    (TELLO_SQUARE_SPEED, 0),
                    (0, -TELLO_SQUARE_SPEED),
                    (-TELLO_SQUARE_SPEED, 0),
                ]
                if square_step < len(directions):
                    tello_lr, tello_fb = directions[square_step]
                    if now - square_last_switch > TELLO_SQUARE_STEP_TIME:
                        square_step += 1
                        square_last_switch = now
                else:
                    square_mode = False
                    tello_lr = tello_fb = 0
                    print("[tello] Square mode DONE")

            # логика маятника
            elif auto_mode and not manual_active:
                if now - last_auto_switch > TELLO_AUTO_INTERVAL:
                    auto_dir *= -1
                    last_auto_switch = now
                tello_lr = auto_dir * TELLO_AUTO_SPEED
                tello_fb = 0

            # отправляем RC в реальный Tello (если есть)
            if tello_connected and drone is not None:
                try:
                    drone.send_rc_control(tello_lr, tello_fb, tello_ud, tello_yw)
                except Exception as e:
                    print(f"[tello] send_rc_control error: {e}")

        # --- получение кадра Tello для отображения ---
        video_surface = None
        if tello_connected and frame_read is not None:
            try:
                frame = frame_read.frame  # numpy (BGR)
                if frame is not None:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    video_w, video_h = 640, 360
                    frame_rgb = cv2.resize(frame_rgb, (video_w, video_h))
                    video_surface = pygame.image.frombuffer(
                        frame_rgb.tobytes(), (video_w, video_h), "RGB"
                    )
            except Exception:
                video_surface = None

        # --- отправка PPM ---
        if now - last_send >= send_interval:
            send_line(ser, ch)
            last_send = now

        # --- отрисовка ---
        fps = 1.0 / dt if dt > 0 else 0.0
        draw_ui(
            screen, font, font_small,
            ch, fps, portname, ser_connected,
            tello_connected, tello_simulation, tello_flying,
            auto_mode, square_mode,
            tello_lr, tello_fb, tello_ud, tello_yw,
            video_surface
        )
        pygame.display.flip()

    # --- выход ---
    if ser:
        ser.close()

    if tello_connected and drone is not None:
        try:
            print("[tello] final landing...")
            drone.send_rc_control(0, 0, 0, 0)
            if tello_flying:
                drone.land()
        except Exception as e:
            print(f"[tello] final land error: {e}")
        try:
            drone.streamoff()
        except Exception:
            pass
        try:
            drone.end()
        except Exception:
            pass

    pygame.quit()


if __name__ == "__main__":
    main()

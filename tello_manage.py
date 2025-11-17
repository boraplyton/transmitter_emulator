from djitellopy import Tello
import time
import pygame

# ---------- настройки ----------
SPEED = 40             # скорость ручного управления
AUTO_SPEED = 30        # скорость авто-полета (M) влево/вправо
AUTO_INTERVAL = 2.0    # каждые N секунд меняем направление в авто-режиме

SQUARE_SPEED = 20      # скорость квадрата (N) — поменьше, чтобы по квартире было безопасно
SQUARE_STEP_TIME = 2 # длительность одного участка квадрата, сек

FPS = 20

pygame.init()
screen = pygame.display.set_mode((520, 460))
pygame.display.set_caption("Tello RC Control (Sticks + Auto M + Square N)")

font = pygame.font.SysFont("Arial", 20)
clock = pygame.time.Clock()

drone = Tello()

def draw_text(text, x, y, color=(255, 255, 255)):
    surf = font.render(text, True, color)
    screen.blit(surf, (x, y))

def main():
    print("Подключение к дрону...")
    drone.connect()
    print("Батарея:", drone.get_battery())

    print("Режим Throw & Go — подбрось дрон в течение 5 секунд!")
    drone.initiate_throw_takeoff()

    print("Ждём стабилизации...")
    time.sleep(6)

    running = True

    # --- состояние авто-режима (M) ---
    auto_mode = False
    auto_dir = 1  # 1 = вправо, -1 = влево
    last_auto_switch = time.time()
    prev_m_pressed = False

    # --- состояние квадрата (N) ---
    square_mode = False
    square_step = 0           # 0..3 — четыре стороны квадрата
    square_last_switch = time.time()
    prev_n_pressed = False

    while running:
        lr = 0
        fb = 0
        ud = 0
        yw = 0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()

        # ===== ЛЕВЫЙ СТИК: g y h j (throttle + yaw) =====
        if keys[pygame.K_g]:
            yw = -SPEED      # поворот влево
        elif keys[pygame.K_j]:
            yw = SPEED       # поворот вправо

        if keys[pygame.K_y]:
            ud = SPEED       # вверх
        elif keys[pygame.K_h]:
            ud = -SPEED      # вниз

        # ===== ПРАВЫЙ СТИК: k o l ; (roll + pitch) =====
        if keys[pygame.K_k]:
            lr = -SPEED      # влево
        elif keys[pygame.K_SEMICOLON]:
            lr = SPEED       # вправо

        if keys[pygame.K_o]:
            fb = SPEED       # вперёд
        elif keys[pygame.K_l]:
            fb = -SPEED      # назад

        # ----- посадка -----
        if keys[pygame.K_p]:
            print("P — посадка...")
            running = False

        if keys[pygame.K_ESCAPE]:
            print("ESC — посадка...")
            running = False

        # ===== обработка клавиши M (вкл/выкл авто-маятник) =====
        m_pressed = keys[pygame.K_m]
        if m_pressed and not prev_m_pressed:
            auto_mode = not auto_mode
            if auto_mode:
                # при включении M — выключаем квадрат
                square_mode = False
                print("Auto mode (M) ON")
                auto_dir = 1
                last_auto_switch = time.time()
            else:
                print("Auto mode (M) OFF")
        prev_m_pressed = m_pressed

        # ===== обработка клавиши N (запуск маленького квадрата) =====
        n_pressed = keys[pygame.K_n]
        if n_pressed and not prev_n_pressed:
            # запускаем квадрат, если он не идёт
            if not square_mode:
                square_mode = True
                auto_mode = False  # выключаем авто-маятник при старте квадрата
                square_step = 0
                square_last_switch = time.time()
                print("Square mode (N) START — маленький квадрат")
        prev_n_pressed = n_pressed

        # ===== определяем, есть ли ручной ввод =====
        manual_active = (lr != 0 or fb != 0 or ud != 0 or yw != 0)

        # если включен авто-режим (M) и пилот тронул стики — отключаем авто
        if auto_mode and manual_active:
            auto_mode = False
            print("Auto mode OFF (перехват руками)")

        # если идёт квадрат (N) и пилот тронул стики — отключаем квадрат
        if square_mode and manual_active:
            square_mode = False
            print("Square mode OFF (перехват руками)")

        now = time.time()

        # ===== логика квадрата (N) =====
        if square_mode and not manual_active:
            # описываем 4 стороны квадрата:
            # шаг 0: вперёд
            # шаг 1: вправо
            # шаг 2: назад
            # шаг 3: влево
            directions = [
                (0,  SQUARE_SPEED),   # (lr, fb) forward
                (SQUARE_SPEED, 0),    # right
                (0, -SQUARE_SPEED),   # back
                (-SQUARE_SPEED, 0),   # left
            ]

            if square_step < len(directions):
                lr, fb = directions[square_step]

                if now - square_last_switch > SQUARE_STEP_TIME:
                    square_step += 1
                    square_last_switch = now
            else:
                # квадрат завершён
                square_mode = False
                lr = 0
                fb = 0
                print("Square mode (N) DONE")

        # ===== логика авто-маятника (M), если квадрат не активен =====
        elif auto_mode and not manual_active:
            if now - last_auto_switch > AUTO_INTERVAL:
                auto_dir *= -1
                last_auto_switch = now
            lr = auto_dir * AUTO_SPEED   # влево/вправо
            fb = 0
            # высоту и yaw авто-режим не трогает

        # отправляем команду в дрон
        drone.send_rc_control(lr, fb, ud, yw)

        # ----- РИСОВАНИЕ ОКНА -----
        screen.fill((0, 0, 0))

        draw_text("Управление:", 20, 20)
        draw_text("Левый стик (g y h j): высота + поворот", 20, 50)
        draw_text("  g = yaw left", 40, 80)
        draw_text("  j = yaw right", 40, 100)
        draw_text("  y = up", 40, 120)
        draw_text("  h = down", 40, 140)

        draw_text("Правый стик (k o l ;): движение", 20, 180)
        draw_text("  k = left", 40, 210)
        draw_text("  ; = right", 40, 230)
        draw_text("  o = forward", 40, 250)
        draw_text("  l = back", 40, 270)

        draw_text("Дополнительно:", 20, 310)
        draw_text("  p = посадка", 40, 340)
        draw_text("  ESC = посадка + выход", 40, 360)
        draw_text("  m = авто-полет влево/вправо (маятник)", 40, 380)
        draw_text("  n = маленький квадрат (one-shot)", 40, 400)

        # статус режимов и стиков
        draw_text(f"Auto mode (M):   {'ON' if auto_mode else 'OFF'}", 300, 20)
        draw_text(f"Square mode (N): {'ON' if square_mode else 'OFF'}", 300, 45)

        draw_text(f"LR (roll):     {lr}", 300, 80)
        draw_text(f"FB (pitch):    {fb}", 300, 110)
        draw_text(f"UD (throttle): {ud}", 300, 140)
        draw_text(f"YW (yaw):      {yw}", 300, 170)

        pygame.display.flip()
        clock.tick(FPS)

    # ----- ВЫХОД -----
    drone.send_rc_control(0, 0, 0, 0)
    print("Посадка...")
    try:
        drone.land()
    except:
        pass
    drone.end()
    pygame.quit()

if __name__ == "__main__":
    main()

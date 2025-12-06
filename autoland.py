import time


class AutoLandController:
    """
    Контроллер автопосадки большого дрона по PPM.

    Режимы:
    - fast: быстрое снижение газа
    - slow: более плавное, медленное снижение

    Поведение:
    - управляет ТОЛЬКО газом (CH3) до land_throttle_us за время descend_time_(fast|slow)
    - остальные оси (roll/pitch/yaw) остаются под управлением пилота
    - по желанию может дёргать ARM (CH8) в MIN_US, если disarm_on_land=True

    Дополнительно:
    - если автопосадка включена при газе МЕНЬШЕ mid_us (обычно 1500),
      сценарий не тянет газ, а сразу дизармит (если disarm_on_land=True).
    """

    def __init__(
        self,
        throttle_idx=2,          # CH3
        arm_idx=7,               # CH8
        min_us=1000,
        mid_us=1500,
        descend_time_fast=3.0,
        descend_time_slow=7.0,
        settle_time=1.0,
        attitude_delta=20,       # сейчас только для стартового центрирования, если надо
        land_throttle_us=None,
        disarm_on_land=False
    ):
        self.throttle_idx = throttle_idx
        self.arm_idx = arm_idx
        self.min_us = min_us
        self.mid_us = mid_us
        self.descend_time_fast = descend_time_fast
        self.descend_time_slow = descend_time_slow
        self.settle_time = settle_time
        self.attitude_delta = attitude_delta

        # если не задано явно — тянем до нижнего конца диапазона
        self.land_throttle_us = land_throttle_us if land_throttle_us is not None else self.min_us
        self.disarm_on_land = disarm_on_land

        self.active = False
        self._phase = "idle"
        self._start_time = None
        self._settle_start = None
        self._start_throttle = None
        self._finished = False
        self._current_mode = None
        self._current_descend_time = None

    # --- публичный API ---

    def start(self, ch, now=None, mode="fast"):
        if self.active:
            return
        if now is None:
            now = time.time()

        if mode not in ("fast", "slow"):
            mode = "fast"

        self._current_mode = mode
        self._current_descend_time = (
            self.descend_time_fast if mode == "fast" else self.descend_time_slow
        )

        self._start_throttle = ch[self.throttle_idx]

        # === НОВАЯ ЛОГИКА: если газ ниже середины (1500), сразу дизармим ===
        if self._start_throttle < self.mid_us:
            if self.disarm_on_land:
                ch[self.arm_idx] = self.min_us
                print(
                    f"[big] AUTOLAND IMMEDIATE DISARM: throttle={self._start_throttle} < {self.mid_us}"
                )
            else:
                print(
                    f"[big] AUTOLAND: throttle={self._start_throttle} < {self.mid_us}, сценарий не запускается"
                )
            # считаем сценарий мгновенно завершённым
            self.active = False
            self._phase = "done"
            self._finished = True
            self._current_mode = None
            self._current_descend_time = None
            self._start_time = None
            self._settle_start = None
            return

        # обычный запуск автопосадки
        self.active = True
        self._finished = False
        self._phase = "descend"
        self._start_time = now
        self._settle_start = None

        print(
            f"[big] AUTOLAND START mode={self._current_mode}, "
            f"descend_time={self._current_descend_time:.1f}s, "
            f"target_throttle={self.land_throttle_us}, "
            f"disarm_on_land={self.disarm_on_land}, "
            f"start_throttle={self._start_throttle}"
        )

    def abort(self):
        if self.active:
            print("[big] AUTOLAND ABORT")
        self.active = False
        self._phase = "idle"
        self._start_time = None
        self._start_throttle = None
        self._settle_start = None
        self._finished = False
        self._current_mode = None
        self._current_descend_time = None

    def is_active(self):
        return self.active

    def is_finished(self):
        return self._finished

    def current_mode(self):
        return self._current_mode  # "fast", "slow" или None

    def update(self, ch, now=None):
        """
        Меняем ТОЛЬКО канал газа ch[throttle_idx].
        """
        if not self.active:
            return ch

        if now is None:
            now = time.time()

        descend_time = self._current_descend_time or self.descend_time_fast
        target_throttle = self.land_throttle_us

        # --- Фаза 1: плавное снижение газа ---
        if self._phase == "descend":
            if self._start_time is None:
                self._start_time = now

            t_norm = (now - self._start_time) / max(descend_time, 0.01)
            if t_norm >= 1.0:
                ch[self.throttle_idx] = target_throttle
                self._phase = "settle"
                self._settle_start = now
            else:
                start = self._start_throttle
                cur = int(start + t_norm * (target_throttle - start))
                ch[self.throttle_idx] = cur

        # --- Фаза 2: «оседание» ---
        elif self._phase == "settle":
            ch[self.throttle_idx] = target_throttle
            if self._settle_start is None:
                self._settle_start = now

            if now - self._settle_start >= self.settle_time:
                if self.disarm_on_land:
                    ch[self.arm_idx] = self.min_us
                    print("[big] AUTOLAND DONE → DISARM AUX")
                else:
                    print("[big] AUTOLAND DONE (THROTTLE HOLD, NO DISARM)")

                self._phase = "done"
                self.active = False
                self._finished = True
                self._current_mode = None
                self._current_descend_time = None

        return ch

    # --- вспомогательное, если всё-таки хочешь слегка выровнять перед началом ---

    def _center_attitude(self, ch):
        for idx in (0, 1, 3):  # roll, pitch, yaw
            ch[idx] = self._approach(ch[idx], self.mid_us, self.attitude_delta)

    @staticmethod
    def _approach(v, target, delta):
        if v < target - delta:
            return v + delta
        if v > target + delta:
            return v - delta
        return target

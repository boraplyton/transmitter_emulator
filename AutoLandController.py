# autoland.py
import time


class AutoLandController:
    """
    Простейший контроллер автопосадки большого дрона по PPM:
    - выравнивает крен/тангаж/курс (CH1, CH2, CH4) к MID_US
    - плавно тянет газ (CH3) до MIN_US за заданное время
    - даёт паузу на «оседание»
    - дизармит (CH8 -> MIN_US)
    """

    def __init__(
        self,
        throttle_idx=2,   # CH3
        arm_idx=7,        # CH8
        min_us=1000,
        mid_us=1500,
        descend_time=3.0,  # секунд падения от текущего газа до минимума
        settle_time=1.0,   # задержка на «оседание» перед DISARM
        attitude_delta=25  # шаг подведения attitude-каналов к MID
    ):
        self.throttle_idx = throttle_idx
        self.arm_idx = arm_idx
        self.min_us = min_us
        self.mid_us = mid_us
        self.descend_time = descend_time
        self.settle_time = settle_time
        self.attitude_delta = attitude_delta

        self.active = False
        self._phase = "idle"
        self._start_time = None
        self._settle_start = None
        self._start_throttle = None
        self._finished = False

    # --- публичный API ---

    def start(self, ch, now=None):
        """Запуск сценария автопосадки."""
        if self.active:
            return
        if now is None:
            now = time.time()

        self.active = True
        self._finished = False
        self._phase = "descend"
        self._start_time = now
        self._start_throttle = ch[self.throttle_idx]
        self._settle_start = None
        # На старте уже немного центрируем стики
        self._center_attitude(ch)

    def abort(self):
        """Принудительное отключение автопосадки."""
        self.active = False
        self._phase = "idle"
        self._start_time = None
        self._start_throttle = None
        self._settle_start = None
        self._finished = False

    def is_active(self):
        return self.active

    def is_finished(self):
        return self._finished

    def update(self, ch, now=None):
        """
        Обновляет каналы ch по таймлайну автопосадки.
        Вызывать на каждом кадре, пока active == True.
        """
        if not self.active:
            return ch

        if now is None:
            now = time.time()

        # Центруем крен/тангаж/рыскание к MID_US
        self._center_attitude(ch)

        # --- Фаза 1: плавное снижение газа ---
        if self._phase == "descend":
            if self._start_time is None:
                self._start_time = now

            t_norm = (now - self._start_time) / max(self.descend_time, 0.01)
            if t_norm >= 1.0:
                ch[self.throttle_idx] = self.min_us
                self._phase = "settle"
                self._settle_start = now
            else:
                # Линейно интерполируем газ от стартового до минимума
                start = self._start_throttle
                target = self.min_us
                cur = int(start + t_norm * (target - start))
                ch[self.throttle_idx] = cur

        # --- Фаза 2: «оседание» на земле ---
        elif self._phase == "settle":
            ch[self.throttle_idx] = self.min_us
            if self._settle_start is None:
                self._settle_start = now
            if now - self._settle_start >= self.settle_time:
                # дизармим
                ch[self.arm_idx] = self.min_us
                self._phase = "done"
                self.active = False
                self._finished = True

        return ch

    # --- внутренние вспомогательные методы ---

    def _center_attitude(self, ch):
        # CH1 (roll), CH2 (pitch), CH4 (yaw)
        for idx in (0, 1, 3):
            ch[idx] = self._approach(ch[idx], self.mid_us, self.attitude_delta)

    @staticmethod
    def _approach(v, target, delta):
        if v < target - delta:
            return v + delta
        if v > target + delta:
            return v - delta
        return target

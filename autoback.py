class AutoBackController:
    """
    Циклический автоматический полёт назад по каналу pitch (CH2).

    Сценарий одного цикла:
        1) back  — плавное отклонение назад
        2) hold  — удержание
        3) return — плавное возвращение в MID

    После return сценарий сразу начинает новую фазу back.
    Останавливается только по abort().
    """

    def __init__(
        self,
        pitch_idx=1,          # CH2
        min_us=1000,
        mid_us=1500,
        back_amplitude=200,   # на сколько мкс отклоняться от MID назад
        ramp_time=0.5,        # время разгона/торможения, сек
        hold_time=1.5         # время удержания, сек
    ):
        self.pitch_idx = pitch_idx
        self.min_us = min_us
        self.mid_us = mid_us
        self.back_amplitude = back_amplitude
        self.ramp_time = ramp_time
        self.hold_time = hold_time

        self.active = False
        self._phase = "idle"          # "back" / "hold" / "return"
        self._start_time = None
        self._hold_start = None
        self._return_start = None
        self._target_back = max(self.min_us, self.mid_us - self.back_amplitude)

    # --- публичный API ---

    def start(self, ch, now=None):
        """Запуск циклического сценария полёта назад."""
        if self.active:
            # если уже активен — вход означает "остановить"
            self.abort()
            return

        if now is None:
            now = time.time()

        self.active = True
        self._phase = "back"
        self._start_time = now
        self._hold_start = None
        self._return_start = None
        self._target_back = max(self.min_us, self.mid_us - self.back_amplitude)

        print(f"[big] AUTOBACK CYCLE START: target={self._target_back}, "
              f"ramp={self.ramp_time}s, hold={self.hold_time}s")

    def abort(self):
        """Остановка цикла."""
        if self.active:
            print("[big] AUTOBACK CYCLE STOP")
        self.active = False
        self._phase = "idle"
        self._start_time = None
        self._hold_start = None
        self._return_start = None

    def is_active(self):
        return self.active

    # --- основной апдейт ---

    def update(self, ch, now=None):
        """
        Обновляет pitch в ch по циклическому сценарию.
        Вызывать каждый кадр.
        """
        if not self.active:
            return ch

        if now is None:
            now = time.time()

        idx = self.pitch_idx

        # ======== ФАЗА 1: разгон "назад" ========
        if self._phase == "back":
            if self._start_time is None:
                self._start_time = now

            t = (now - self._start_time) / max(self.ramp_time, 0.01)

            if t >= 1.0:
                ch[idx] = self._target_back
                self._phase = "hold"
                self._hold_start = now
            else:
                start = self.mid_us
                target = self._target_back
                ch[idx] = int(start + t * (target - start))

        # ======== ФАЗА 2: удержание ========
        elif self._phase == "hold":
            ch[idx] = self._target_back

            if self._hold_start is None:
                self._hold_start = now

            if now - self._hold_start >= self.hold_time:
                self._phase = "return"
                self._return_start = now

        # ======== ФАЗА 3: возврат ========
        elif self._phase == "return":
            if self._return_start is None:
                self._return_start = now

            t = (now - self._return_start) / max(self.ramp_time, 0.01)

            if t >= 1.0:
                ch[idx] = self.mid_us
                # ---- цикл повторяется ----
                self._phase = "back"
                self._start_time = now
                print("[big] AUTOBACK CYCLE LOOP")
            else:
                start = self._target_back
                target = self.mid_us
                ch[idx] = int(start + t * (target - start))

        return ch

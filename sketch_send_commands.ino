// Radiomaster TX12 Trainer PPM (инверсный, idle=HIGH, импульс=LOW)
// D9 -> тренерский вход (через 1–2 кОм или делитель ~3.3 В)
// GND -> общий с пультом
// У тебя рабочий контакт — RING (средний контакт TRS).

#define PPM_PIN              9
#define CHANNEL_NUMBER       8
#define PPM_FRAME_LENGTH     23500   // мкс
#define PPM_PULSE_LENGTH     400     // мкс
#define PPM_ON_STATE         1       // активный импульс = HIGH? (У ТЕБЯ РАБОТАЕТ ТАК)
#define MIN_SYNC_US          3200    // мкс

#define MIN_US 1000
#define MID_US 1500
#define MAX_US 2000

volatile uint16_t ppm[CHANNEL_NUMBER];

void setup() {
  // старт: центр
  for (uint8_t i=0; i<CHANNEL_NUMBER; i++) ppm[i] = MID_US;

  pinMode(PPM_PIN, OUTPUT);
  digitalWrite(PPM_PIN, !PPM_ON_STATE); // idle

  // UART
  Serial.begin(115200);

  // Timer1 на PPM
  cli();
  TCCR1A = 0; TCCR1B = 0; TCNT1 = 0;
  TCCR1B |= (1 << WGM12); // CTC
  TCCR1B |= (1 << CS11);  // /8 => 0.5 мкс/тик
  OCR1A = 1000;
  TIMSK1 |= (1 << OCIE1A);
  sei();
}

ISR(TIMER1_COMPA_vect) {
  static bool state = true;
  static uint8_t ch = 0;
  static uint16_t rest = 0;

  if (state) {
    // активный импульс
    digitalWrite(PPM_PIN, PPM_ON_STATE);
    OCR1A = PPM_PULSE_LENGTH * 2;
    state = false;
  } else {
    // фон
    digitalWrite(PPM_PIN, !PPM_ON_STATE);
    state = true;

    if (ch >= CHANNEL_NUMBER) {
      ch = 0;
      rest = PPM_FRAME_LENGTH;

      for (uint8_t i=0; i<CHANNEL_NUMBER; i++) rest -= ppm[i];
      rest -= PPM_PULSE_LENGTH * (CHANNEL_NUMBER + 1);
      if (rest < MIN_SYNC_US) rest = MIN_SYNC_US;

      OCR1A = rest * 2; // sync
    } else {
      OCR1A = (ppm[ch] - PPM_PULSE_LENGTH) * 2;
      ch++;
    }
  }
}

void loop() {
  // читаем строки вида: "1500,1500,1000,2000,1500,1500,1500,1500\n"
  static char buf[96];
  static uint8_t n = 0;

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      buf[n] = 0;
      parse_line(buf);
      n = 0;
    } else {
      if (n < sizeof(buf)-1) buf[n++] = c;
    }
  }
}

void parse_line(char* s) {
  for (uint8_t i=0; i<CHANNEL_NUMBER; i++) {
    // atoi безопасно обрабатывает нечисла как 0
    int v = atoi(s);
    if (v < MIN_US) v = MIN_US;
    if (v > MAX_US) v = MAX_US;
    ppm[i] = (uint16_t)v;

    // пропускаем до следующей запятой
    while (*s && *s != ',') s++;
    if (*s == ',') s++;
  }
}

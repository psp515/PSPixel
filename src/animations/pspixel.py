from animations.base import Animation

FRAME_MS = 30
ANCHORS = 5
PALETTE = (
    (59, 130, 246),
    (124, 92, 245),
    (179, 76, 224),
    (224, 82, 159),
    (242, 135, 74),
)
BASE_SCALE = 32
GRAD_SHIFT = 10
GRAD_UNIT = 1 << GRAD_SHIFT
DOT_MIN = 3
DOT_DIVISOR = 20
PULSE_STEPS = 64
PULSE_MASK = PULSE_STEPS - 1
PULSE_PEAK = 29
PULSE_RATE = 145
PULSE_PHASE = 9
PULSE_MIN = 128
TRAILS_MAX = 4


class PSPixel(Animation):
    interval_ms = FRAME_MS
    segmenting_compatible = False

    def __init__(self, mode, params):
        super().__init__(mode, params)
        trails = params.get("trails", 2)
        if trails < 1:
            trails = 1
        elif trails > TRAILS_MAX:
            trails = TRAILS_MAX
        self._trails = trails
        length = params.get("length", 10)
        if length < 1:
            length = 1
        self._length = length
        dot_size = params.get("dot_size", 0)
        if dot_size < 0:
            dot_size = 0
        self._dot_size = dot_size
        speed = mode.speed
        if speed < 1:
            speed = 1
        self._step = max(1, speed * 256 * FRAME_MS // 1000)
        self._span = length * 256
        self._half = self._span // 2
        self._pulse = self._build_pulse()
        self._tmp = [0, 0, 0]
        self._base = None
        self._anchors = None
        self._radius = 1
        self._total = 0
        self._gap = 0

    def _build_pulse(self):
        lut = bytearray(PULSE_STEPS)
        for s in range(PULSE_STEPS):
            if s <= PULSE_PEAK:
                t = s * 256 // PULSE_PEAK
            else:
                t = (PULSE_STEPS - s) * 256 // (PULSE_STEPS - PULSE_PEAK)
            if t > 255:
                t = 255
            eased = t * t >> 8
            lut[s] = PULSE_MIN + ((255 - PULSE_MIN) * eased >> 8)
        return lut

    def _sample(self, pos, count, out):
        last = count - 1
        if last < 1:
            last = 1
        t = pos * GRAD_UNIT * (ANCHORS - 1) // last
        seg = t >> GRAD_SHIFT
        if seg > ANCHORS - 2:
            seg = ANCHORS - 2
        local = t - (seg << GRAD_SHIFT)
        a = PALETTE[seg]
        b = PALETTE[seg + 1]
        out[0] = a[0] + (b[0] - a[0]) * local // GRAD_UNIT
        out[1] = a[1] + (b[1] - a[1]) * local // GRAD_UNIT
        out[2] = a[2] + (b[2] - a[2]) * local // GRAD_UNIT

    def _prepare(self, count):
        rgb = self._tmp
        base = bytearray(count * 3)
        for i in range(count):
            self._sample(i, count, rgb)
            j = i * 3
            base[j] = rgb[1] * BASE_SCALE >> 8
            base[j + 1] = rgb[0] * BASE_SCALE >> 8
            base[j + 2] = rgb[2] * BASE_SCALE >> 8
        self._base = base
        size = self._dot_size
        if size < 1:
            size = max(DOT_MIN, count // DOT_DIVISOR)
        self._radius = max(1, size // 2)
        last = count - 1
        if last < 1:
            last = 1
        self._anchors = [i * last // (ANCHORS - 1) for i in range(ANCHORS)]
        self._total = count * 256
        self._gap = self._total // self._trails

    def _blend(self, buffer, i, g, r, b):
        v = buffer[i] + g
        buffer[i] = 255 if v > 255 else v
        v = buffer[i + 1] + r
        buffer[i + 1] = 255 if v > 255 else v
        v = buffer[i + 2] + b
        buffer[i + 2] = 255 if v > 255 else v

    def _draw_anchors(self, buffer, count, frame):
        lut = self._pulse
        step = frame * PULSE_RATE >> 8
        radius = self._radius
        span = radius + 1
        for a in range(ANCHORS):
            level = lut[(step + a * PULSE_PHASE) & PULSE_MASK]
            color = PALETTE[a]
            center = self._anchors[a]
            for d in range(-radius, radius + 1):
                pos = center + d
                if pos < 0 or pos >= count:
                    continue
                fall = (span - (d if d >= 0 else -d)) * 256 // span
                scale = level * fall >> 8
                self._blend(
                    buffer,
                    pos * 3,
                    color[1] * scale >> 8,
                    color[0] * scale >> 8,
                    color[2] * scale >> 8,
                )

    def _draw_comets(self, buffer, count, frame):
        rgb = self._tmp
        span = self._span
        half = self._half
        total = self._total
        lead = frame * self._step % total
        for t in range(self._trails):
            head_fp = (lead + t * self._gap) % total
            head = head_fp >> 8
            frac = head_fp & 255
            self._sample(head, count, rgb)
            r = rgb[0]
            g = rgb[1]
            b = rgb[2]
            for k in range(self._length + 1):
                dist = k * 256 + frac
                if dist >= span:
                    break
                if dist <= half:
                    scale = dist * 256 // half
                else:
                    scale = (span - dist) * 256 // half
                self._blend(
                    buffer,
                    (head - k) % count * 3,
                    g * scale >> 8,
                    r * scale >> 8,
                    b * scale >> 8,
                )

    def render(self, buffer, count, frame):
        if self._base is None or len(self._base) != count * 3:
            self._prepare(count)
        buffer[:] = self._base
        self._draw_anchors(buffer, count, frame)
        self._draw_comets(buffer, count, frame)
        self.apply_brightness(buffer, count)

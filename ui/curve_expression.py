import math


class CurveExpressionError(ValueError):
    pass


class CurveExpressionParser:
    def __init__(self, text):
        self.text = text or ""
        self.pos = 0

    def parse(self):
        node = self._parse_expr()
        self._skip_ws()
        if self.pos != len(self.text):
            raise CurveExpressionError(f"Unexpected token at {self.pos}: {self.text[self.pos:]}")
        return node

    def _skip_ws(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self):
        self._skip_ws()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _consume(self, char):
        if self._peek() != char:
            raise CurveExpressionError(f"Expected '{char}' at {self.pos}")
        self.pos += 1

    def _parse_expr(self):
        node = self._parse_term()
        while True:
            op = self._peek()
            if op not in ("+", "-"):
                return node
            self.pos += 1
            node = ("bin", op, node, self._parse_term())

    def _parse_term(self):
        node = self._parse_unary()
        while True:
            op = self._peek()
            if op not in ("*", "/"):
                return node
            self.pos += 1
            node = ("bin", op, node, self._parse_unary())

    def _parse_unary(self):
        op = self._peek()
        if op in ("+", "-"):
            self.pos += 1
            return ("unary", op, self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self):
        ch = self._peek()
        if not ch:
            raise CurveExpressionError("Unexpected end of expression")
        if ch == "(":
            self.pos += 1
            node = self._parse_expr()
            self._consume(")")
            return node
        if ch == "[":
            return self._parse_bracket_curve_ref()
        if ch == "/":
            return self._parse_curve_ref()
        if ch.isdigit() or ch == ".":
            return self._parse_number()
        if ch.isalpha() or ch == "_":
            return self._parse_call()
        raise CurveExpressionError(f"Unexpected token at {self.pos}: {ch}")

    def _parse_curve_ref(self):
        self._consume("/")
        start = self.pos
        stop_chars = set("()+-*/, \t\r\n")
        while self.pos < len(self.text) and self.text[self.pos] not in stop_chars:
            self.pos += 1
        name = self.text[start:self.pos].strip()
        if not name:
            raise CurveExpressionError(f"Missing curve name after '/' at {start}")
        return ("ref", name)

    def _parse_bracket_curve_ref(self):
        self._consume("[")
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] != "]":
            self.pos += 1
        if self.pos >= len(self.text):
            raise CurveExpressionError(f"Missing closing ']' for curve reference at {start - 1}")
        name = self.text[start:self.pos].strip()
        self.pos += 1
        if not name:
            raise CurveExpressionError(f"Missing curve name inside brackets at {start}")
        return ("ref", name)

    def _parse_number(self):
        start = self.pos
        saw_digit = False
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            saw_digit = True
            self.pos += 1
        if self.pos < len(self.text) and self.text[self.pos] == ".":
            self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                saw_digit = True
                self.pos += 1
        if self.pos < len(self.text) and self.text[self.pos] in ("e", "E"):
            exp_pos = self.pos
            self.pos += 1
            if self.pos < len(self.text) and self.text[self.pos] in ("+", "-"):
                self.pos += 1
            exp_digits = self.pos
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1
            if exp_digits == self.pos:
                self.pos = exp_pos
        if not saw_digit:
            raise CurveExpressionError(f"Invalid number at {start}")
        return ("num", float(self.text[start:self.pos]))

    def _parse_call(self):
        start = self.pos
        while self.pos < len(self.text) and (self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
            self.pos += 1
        name = self.text[start:self.pos]
        self._consume("(")
        args = []
        if self._peek() != ")":
            while True:
                args.append(self._parse_expr())
                if self._peek() != ",":
                    break
                self.pos += 1
        self._consume(")")
        return ("call", name, args)


def expression_validation_errors(node):
    if node is None:
        return ["Empty expression"]
    kind = node[0]
    if kind in ("num", "ref"):
        return []
    if kind == "unary":
        return expression_validation_errors(node[2])
    if kind == "bin":
        return expression_validation_errors(node[2]) + expression_validation_errors(node[3])
    if kind != "call":
        return [f"Unknown expression node: {kind}"]

    name = node[1].lower()
    if name == "soomth":
        name = "smooth"
    args = node[2]
    expected = {
        "d": (1,),
        "smooth": (2,),
        "sg": (4,),
        "sign": (1,),
        "clip": (2, 3),
        "joint_tau": (7,),
    }
    allowed = expected.get(name)
    errors = []
    if allowed is None:
        errors.append(f"Unknown function: {node[1]}")
    elif len(args) not in allowed:
        if len(allowed) == 1:
            count = allowed[0]
            noun = "argument" if count == 1 else "arguments"
            errors.append(f"{name}() expects {count} {noun}")
        else:
            counts = " or ".join(str(count) for count in allowed)
            errors.append(f"{name}() expects {counts} arguments")
    for arg in args:
        errors.extend(expression_validation_errors(arg))
    return errors


def resolve_clip_bounds(limit_or_min, upper=None):
    try:
        first = float(limit_or_min)
        if upper is None:
            limit = abs(first)
            lower = -limit
            upper_value = limit
        else:
            lower = first
            upper_value = float(upper)
    except (TypeError, ValueError):
        return None

    if not (math.isfinite(lower) and math.isfinite(upper_value)):
        return None
    if lower > upper_value:
        return None
    return lower, upper_value


def clip_scalar(value, lower, upper):
    try:
        number = float(value)
        lower = float(lower)
        upper = float(upper)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(number) and math.isfinite(lower) and math.isfinite(upper)):
        return None
    if lower > upper:
        return None
    return min(max(number, lower), upper)


def clip_series(ts, vs, lower, upper):
    out_ts = []
    out_vs = []
    for timestamp, value in zip(ts, vs):
        try:
            timestamp = float(timestamp)
        except (TypeError, ValueError):
            continue
        clipped = clip_scalar(value, lower, upper)
        if not math.isfinite(timestamp) or clipped is None:
            continue
        out_ts.append(timestamp)
        out_vs.append(clipped)
    return out_ts, out_vs

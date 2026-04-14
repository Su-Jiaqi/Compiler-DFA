from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Tuple


# ============================================================
# Token / IR data structures
# ============================================================

@dataclass
class Token:
    typ: str     # KEY, temp, d, l, k, aop, rop, =, ;
    val: str


@dataclass
class TemplateIR:
    kind: str
    attrs: dict


# ============================================================
# Tokenizer
# ============================================================

KEYWORDS = {"LABEL", "GOTO", "IF", "THEN", "ELSE", "RETURN", "NOP"}

RELOPS = {"<=", ">=", "==", "!=", "<", ">"}
AOPS = {"+", "-", "*", "/"}

def classify_identifier(name: str) -> Token:
    """
    Classify an identifier into temp / label / d.

    Supported temp styles:
      - t1, t2, ...
      - T_1, T_2, ...

    Supported label styles:
      - l0, l1, ...
      - L_0, L_1, ...
      - start, loop, done, ok, fail ... (generic labels)

    Rule:
      - temp first
      - explicit l/L_ labels next
      - otherwise treat as generic identifier 'd'
        (and later let parser reinterpret contextually after LABEL/GOTO/THEN/ELSE)
    """
    if re.fullmatch(r"t\d+", name) or re.fullmatch(r"T_\d+", name):
        return Token("temp", name)

    if re.fullmatch(r"l\d+", name) or re.fullmatch(r"L_\d+", name):
        return Token("l", name)

    return Token("d", name)

def is_label_like(tok: Token) -> bool:
    return tok.typ in {"l", "d"}


def consume_label(ts: TokenStream) -> Token:
    tk = ts.consume()
    if not is_label_like(tk):
        raise ValueError(f"Expected label-like token, got {tk.typ}:{tk.val}")
    return Token("l", tk.val)


def tokenize(source: str) -> List[Token]:
    """
    Convert QTAC source into a flat token stream.
    """
    token_spec = [
        ("SPACE", r"[ \t\r\n]+"),
        ("ROP", r"(<=|>=|==|!=|<|>)"),
        ("AOP", r"[\+\-\*/]"),
        ("EQ", r"="),
        ("SEMI", r";"),
        ("INT", r"\d+"),
        ("ID", r"[A-Za-z_][A-Za-z0-9_]*"),
        ("MISMATCH", r"."),
    ]

    master = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in token_spec))
    tokens: List[Token] = []

    for m in master.finditer(source):
        kind = m.lastgroup
        text = m.group()

        if kind == "SPACE":
            continue
        if kind == "ROP":
            tokens.append(Token("rop", text))
        elif kind == "AOP":
            tokens.append(Token("aop", text))
        elif kind == "EQ":
            tokens.append(Token("=", "_"))
        elif kind == "SEMI":
            tokens.append(Token(";", "_"))
        elif kind == "INT":
            tokens.append(Token("k", text))
        elif kind == "ID":
            if text in KEYWORDS:
                tokens.append(Token("KEY", text))
            else:
                tokens.append(classify_identifier(text))
        else:
            raise ValueError(f"Unexpected character in input: {text!r}")

    return tokens


def format_pass1(tokens: List[Token]) -> str:
    """
    Pretty-print pass 1 token stream, close to the teacher's style.
    """
    parts = []
    for tk in tokens:
        if tk.typ in {"=", ";"}:
            parts.append(f"({tk.typ},{tk.val})")
        else:
            parts.append(f"({tk.typ},{tk.val})")
    return " ".join(parts)


# ============================================================
# Small token stream helper
# ============================================================

class TokenStream:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.i = 0

    def eof(self) -> bool:
        return self.i >= len(self.tokens)

    def peek(self, offset: int = 0) -> Optional[Token]:
        j = self.i + offset
        if 0 <= j < len(self.tokens):
            return self.tokens[j]
        return None

    def consume(self, typ: Optional[str] = None, val: Optional[str] = None) -> Token:
        tk = self.peek()
        if tk is None:
            raise ValueError("Unexpected end of token stream")
        if typ is not None and tk.typ != typ:
            raise ValueError(f"Expected type {typ}, got {tk.typ} ({tk.val})")
        if val is not None and tk.val != val:
            raise ValueError(f"Expected value {val}, got {tk.val}")
        self.i += 1
        return tk

    def match(self, typ: Optional[str] = None, val: Optional[str] = None) -> bool:
        tk = self.peek()
        if tk is None:
            return False
        if typ is not None and tk.typ != typ:
            return False
        if val is not None and tk.val != val:
            return False
        return True


# ============================================================
# Parser / template recognizer (Pass 2)
# ============================================================

def is_q(tok: Token) -> bool:
    return tok.typ in {"d", "temp"}


def is_a(tok: Token) -> bool:
    return tok.typ in {"d", "temp", "k"}


def tok_repr(tok: Token) -> str:
    return f"({tok.typ},{tok.val})"


def parse_templates(tokens: List[Token]) -> List[TemplateIR]:
    """
    Pass 2: recognize high-level templates from token stream.

    Supported:
      - T_LABEL
      - T_GOTO
      - T_RETURN
      - T_MOVE
      - T_AOP
      - T_IF
      - T_IF_LABEL   (if an IF is immediately followed by LABEL l1; or LABEL l2;)
      - T_NOP
    """
    ts = TokenStream(tokens)
    out: List[TemplateIR] = []

    while not ts.eof():
        # LABEL l;
        if ts.match("KEY", "LABEL"):
            ts.consume("KEY", "LABEL")
            l = consume_label(ts)
            ts.consume(";", "_")
            out.append(TemplateIR("T_LABEL", {"label": l.val}))
            continue

        # GOTO l;
        if ts.match("KEY", "GOTO"):
            ts.consume("KEY", "GOTO")
            l = consume_label(ts)
            ts.consume(";", "_")
            out.append(TemplateIR("T_GOTO", {"label": l.val}))
            continue

        # RETURN a;
        if ts.match("KEY", "RETURN"):
            ts.consume("KEY", "RETURN")
            a = ts.consume()
            if not is_a(a):
                raise ValueError(f"RETURN expects a, got {a.typ}:{a.val}")
            ts.consume(";", "_")
            out.append(TemplateIR("T_RETURN", {"a": a}))
            continue

        # NOP;
        if ts.match("KEY", "NOP"):
            ts.consume("KEY", "NOP")
            ts.consume(";", "_")
            out.append(TemplateIR("T_NOP", {}))
            continue

        # IF q rop a THEN l1 ELSE l2;
        if ts.match("KEY", "IF"):
            ts.consume("KEY", "IF")
            q = ts.consume()
            if not is_q(q):
                raise ValueError(f"IF expects q, got {q.typ}:{q.val}")

            rop = ts.consume("rop")
            a = ts.consume()
            if not is_a(a):
                raise ValueError(f"IF expects a, got {a.typ}:{a.val}")

            ts.consume("KEY", "THEN")
            l1 = consume_label(ts)
            ts.consume("KEY", "ELSE")
            l2 = consume_label(ts)
            ts.consume(";", "_")

            # Optional fold into T_IF_LABEL if next statement is LABEL l1; or LABEL l2;
            if (
                ts.match("KEY", "LABEL")
                and ts.peek(1)
                and is_label_like(ts.peek(1))
                and ts.peek(2)
                and ts.peek(2).typ == ";"
            ):
                next_label = ts.peek(1).val
                if next_label in {l1.val, l2.val}:
                    out.append(
                        TemplateIR(
                            "T_IF_LABEL",
                            {
                                "q": q,
                                "rop": rop.val,
                                "a": a,
                                "l1": l1.val,
                                "l2": l2.val,
                                "fallthrough": next_label,
                            },
                        )
                    )
                    continue

            out.append(
                TemplateIR(
                    "T_IF",
                    {
                        "q": q,
                        "rop": rop.val,
                        "a": a,
                        "l1": l1.val,
                        "l2": l2.val,
                    },
                )
            )
            continue

        # Assignment family:
        # q = a;
        # q = q aop a;
        lhs = ts.peek()
        if lhs is not None and is_q(lhs) and ts.peek(1) and ts.peek(1).typ == "=":
            lhs = ts.consume()
            ts.consume("=", "_")

            first = ts.consume()
            if not is_a(first):
                raise ValueError(f"Assignment RHS malformed near {first.typ}:{first.val}")

            # q = q aop a;
            if ts.peek() is not None and ts.peek().typ == "aop":
                op = ts.consume("aop")
                second = ts.consume()
                if not is_a(second):
                    raise ValueError(f"AOP RHS malformed near {second.typ}:{second.val}")
                ts.consume(";", "_")
                if not is_q(first):
                    raise ValueError("Left operand of arithmetic op must be q (d/temp)")
                out.append(
                    TemplateIR(
                        "T_AOP",
                        {
                            "dst": lhs,
                            "src1": first,
                            "aop": op.val,
                            "src2": second,
                        },
                    )
                )
            else:
                # q = a;
                ts.consume(";", "_")
                out.append(TemplateIR("T_MOVE", {"dst": lhs, "src": first}))
            continue

        tk = ts.peek()
        raise ValueError(f"Cannot parse token sequence starting at {tk.typ}:{tk.val}")

    return out


def format_pass2(templates: List[TemplateIR]) -> str:
    lines = []
    for t in templates:
        if t.kind == "T_LABEL":
            lines.append(f"(T_LABEL,(l,{t.attrs['label']}))")
        elif t.kind == "T_GOTO":
            lines.append(f"(T_GOTO,(l,{t.attrs['label']}))")
        elif t.kind == "T_RETURN":
            a = t.attrs["a"]
            lines.append(f"(T_RETURN,a is {'k' if a.typ == 'k' else 'q'},{tok_repr(a)})")
        elif t.kind == "T_MOVE":
            dst = t.attrs["dst"]
            src = t.attrs["src"]
            lines.append(f"(T_MOVE,a is {'k' if src.typ == 'k' else 'q'},{tok_repr(dst)},{tok_repr(src)})")
        elif t.kind == "T_AOP":
            dst = t.attrs["dst"]
            src1 = t.attrs["src1"]
            src2 = t.attrs["src2"]
            op = t.attrs["aop"]
            lines.append(f"(T_AOP,a is {'k' if src2.typ == 'k' else 'q'},{tok_repr(dst)},{tok_repr(src1)},(aop,{op}),{tok_repr(src2)})")
        elif t.kind == "T_IF":
            q = t.attrs["q"]
            a = t.attrs["a"]
            rop = t.attrs["rop"]
            l1 = t.attrs["l1"]
            l2 = t.attrs["l2"]
            lines.append(f"(T_IF,{tok_repr(q)},(rop,{rop}),{tok_repr(a)},(l,{l1}),(l,{l2}))")
        elif t.kind == "T_IF_LABEL":
            q = t.attrs["q"]
            a = t.attrs["a"]
            rop = t.attrs["rop"]
            l1 = t.attrs["l1"]
            l2 = t.attrs["l2"]
            fallthrough = t.attrs["fallthrough"]
            lines.append(
                f"(T_IF_LABEL,fallthrough={fallthrough},{tok_repr(q)},(rop,{rop}),{tok_repr(a)},(l,{l1}),(l,{l2}))"
            )
        elif t.kind == "T_NOP":
            lines.append("(T_NOP)")
        else:
            lines.append(f"(UNKNOWN,{t.kind})")
    return "\n".join(lines)


# ============================================================
# Pass 3: emit virtual ARM64
# ============================================================

def vreg(name: str) -> str:
    return f"X{name}"


def emit_operand(tok: Token) -> str:
    if tok.typ == "k":
        return f"#{tok.val}"
    return vreg(tok.val)


AOP_Q_MAP = {
    "+": "ADD",
    "-": "SUB",
    "*": "MUL",
    "/": "SDIV",
}

# For immediate arithmetic, AArch64 only supports ADD/SUB in our simplified subset
AOP_K_MAP = {
    "+": "ADD",
    "-": "SUB",
}

# Direct condition
DIRECT_BRANCH = {
    "==": "B.EQ",
    "!=": "B.NE",
    ">=": "B.GE",
    ">": "B.GT",
    "<=": "B.LE",
    "<": "B.LT",
}

# Inverse condition
INVERSE_BRANCH = {
    "==": "B.NE",
    "!=": "B.EQ",
    ">=": "B.LT",
    ">": "B.LE",
    "<=": "B.GT",
    "<": "B.GE",
}


def emit_templates_to_arm(templates: List[TemplateIR]) -> List[str]:
    lines: List[str] = []

    for t in templates:
        kind = t.kind

        if kind == "T_LABEL":
            lines.append(f"{t.attrs['label']}:")
            continue

        if kind == "T_GOTO":
            lines.append(f"B {t.attrs['label']};")
            continue

        if kind == "T_NOP":
            lines.append("NOP;")
            continue

        if kind == "T_RETURN":
            a = t.attrs["a"]
            if a.typ == "k":
                lines.append(f"MOV X0, #{a.val};")
            else:
                lines.append(f"MOV X0, {vreg(a.val)};")
            lines.append("RET;")
            continue

        if kind == "T_MOVE":
            dst = t.attrs["dst"]
            src = t.attrs["src"]
            if src.typ == "k":
                lines.append(f"MOV {vreg(dst.val)}, #{src.val};")
            else:
                lines.append(f"MOV {vreg(dst.val)}, {vreg(src.val)};")
            continue

        if kind == "T_AOP":
            dst = t.attrs["dst"]
            src1 = t.attrs["src1"]
            src2 = t.attrs["src2"]
            op = t.attrs["aop"]

            if src2.typ == "k":
                if op not in AOP_K_MAP:
                    raise ValueError(
                        f"Immediate arithmetic only supports + or - in this version, but got {op!r}"
                    )
                arm_op = AOP_K_MAP[op]
                lines.append(f"{arm_op} {vreg(dst.val)}, {vreg(src1.val)}, #{src2.val};")
            else:
                arm_op = AOP_Q_MAP[op]
                lines.append(f"{arm_op} {vreg(dst.val)}, {vreg(src1.val)}, {vreg(src2.val)};")
            continue

        if kind == "T_IF":
            q = t.attrs["q"]
            a = t.attrs["a"]
            rop = t.attrs["rop"]
            l1 = t.attrs["l1"]
            l2 = t.attrs["l2"]

            # If a is immediate, materialize it into a scratch virtual register.
            if a.typ == "k":
                scratch = "__cmpimm"
                lines.append(f"MOV {vreg(scratch)}, #{a.val};")
                lines.append(f"CMP {vreg(q.val)}, {vreg(scratch)};")
            else:
                lines.append(f"CMP {vreg(q.val)}, {vreg(a.val)};")

            lines.append(f"{DIRECT_BRANCH[rop]} {l1};")
            lines.append(f"B {l2};")
            continue

        if kind == "T_IF_LABEL":
            q = t.attrs["q"]
            a = t.attrs["a"]
            rop = t.attrs["rop"]
            l1 = t.attrs["l1"]
            l2 = t.attrs["l2"]
            fallthrough = t.attrs["fallthrough"]

            if a.typ == "k":
                scratch = "__cmpimm"
                lines.append(f"MOV {vreg(scratch)}, #{a.val};")
                lines.append(f"CMP {vreg(q.val)}, {vreg(scratch)};")
            else:
                lines.append(f"CMP {vreg(q.val)}, {vreg(a.val)};")

            # Fall through to one label, branch to the other
            if fallthrough == l1:
                lines.append(f"{INVERSE_BRANCH[rop]} {l2};")
            else:
                lines.append(f"{DIRECT_BRANCH[rop]} {l1};")
            continue

        raise ValueError(f"Unsupported template kind: {kind}")

    return lines


def format_pass3(lines: List[str]) -> str:
    return "\n".join(lines)


# ============================================================
# Pass 4: virtual -> physical registers
# ============================================================

def collect_virtual_names(templates: List[TemplateIR]) -> List[str]:
    """
    Collect virtual register names from templates.
    Excludes immediates and labels.
    """
    seen = []
    used = set()

    def add_name(name: str) -> None:
        if name not in used:
            used.add(name)
            seen.append(name)

    for t in templates:
        for value in t.attrs.values():
            if isinstance(value, Token) and value.typ in {"d", "temp"}:
                add_name(value.val)
            elif isinstance(value, str):
                # labels are plain str too, so do not treat arbitrary strings as vregs
                pass

    # Some helper scratch regs may be synthesized later.
    return seen


def allocate_register_map(templates: List[TemplateIR]) -> Dict[str, str]:
    """
    Fixed but automatic mapping:
      X0 is return register, so we avoid it.
      Start from X9 as in the teacher's example.
    """
    names = collect_virtual_names(templates)

    reg_map: Dict[str, str] = {}
    next_reg = 9

    for name in names:
        reg_map[name] = f"X{next_reg}"
        next_reg += 1

    # Reserve scratch if needed
    if "__cmpimm" not in reg_map:
        reg_map["__cmpimm"] = f"X{next_reg}"
        next_reg += 1

    return reg_map


def apply_register_map(arm_lines: List[str], reg_map: Dict[str, str]) -> List[str]:
    """
    Replace Xfoo virtual names with physical AArch64 registers.
    Longer names first to avoid partial replacement issues.
    """
    out = []
    items = sorted(reg_map.items(), key=lambda kv: len(kv[0]), reverse=True)

    for line in arm_lines:
        new_line = line
        for name, preg in items:
            new_line = re.sub(rf"\bX{re.escape(name)}\b", preg, new_line)
        out.append(new_line)
    return out


def format_pass4(lines: List[str]) -> str:
    return "\n".join(lines)


# ============================================================
# Full standalone AArch64 program emitter
# ============================================================

def emit_full_program(body_lines: List[str], reg_map: Dict[str, str]) -> str:
    """
    Emit a full standalone Linux AArch64 assembly program.

    Convention for demo:
      - if variables n / a exist, initialize them as factorial inputs:
          n = 5, a = 1
      - otherwise initialize all mapped virtual registers to 0
    """
    init_lines = []

    names_by_reg = {v: k for k, v in reg_map.items()}

    # Initialize all ordinary registers to 0 (except scratch)
    for reg, name in sorted(names_by_reg.items()):
        if name == "__cmpimm":
            continue
        init_lines.append(f"    MOV {reg}, #0")

    # Friendly defaults for factorial demo if present
    if "n" in reg_map:
        init_lines.append(f"    MOV {reg_map['n']}, #5")
    if "a" in reg_map:
        init_lines.append(f"    MOV {reg_map['a']}, #1")

    body = "\n".join(f"    {ln}" if ln and not ln.endswith(":") else ln for ln in body_lines)

    program = f""".global _start
.section .text

_start:
{"\n".join(init_lines)}
    BL my_func

    // Linux AArch64 sys_exit(status = X0)
    MOV X8, #93
    SVC #0

my_func:
{body}
"""
    return program


# ============================================================
# Main driver
# ============================================================
#     tokens = tokenize(source_text)
#     templates = parse_templates(tokens)
#     arm_virtual = emit_templates_to_arm(templates)
#     reg_map = allocate_register_map(templates)
#     arm_physical = apply_register_map(arm_virtual, reg_map)
#     full_program = emit_full_program(arm_physical, reg_map)

#     out_dir.mkdir(parents=True, exist_ok=True)

#     pass1_text = format_pass1(tokens)
#     pass2_text = format_pass2(templates)
#     pass3_text = format_pass3(arm_virtual)
#     pass4_text = format_pass4(arm_physical)
#     regmap_text = "\n".join(f"{k} -> {v}" for k, v in sorted(reg_map.items()))

#     case_dir = out_dir / stem
#     case_dir.mkdir(parents=True, exist_ok=True)

#     (out_dir / f"{stem}.pass1.txt").write_text(pass1_text, encoding="utf-8")
#     (out_dir / f"{stem}.pass2.txt").write_text(pass2_text, encoding="utf-8")
#     (out_dir / f"{stem}.pass3_virtual_arm.s").write_text(pass3_text, encoding="utf-8")
#     (out_dir / f"{stem}.pass4_physical_arm.s").write_text(pass4_text, encoding="utf-8")
#     (out_dir / f"{stem}.regmap.txt").write_text(regmap_text, encoding="utf-8")
#     (out_dir / f"{stem}.full_program.s").write_text(full_program, encoding="utf-8")

#     print("=" * 72)
#     print(f"Input: {stem}")
#     print("=" * 72)
#     print("[Pass 1] Tokens")
#     print(pass1_text)
#     print()
#     print("[Pass 2] Templates")
#     print(pass2_text)
#     print()
#     print("[Pass 3] Virtual ARM64")
#     print(pass3_text)
#     print()
#     print("[Pass 4] Physical ARM64")
#     print(pass4_text)
#     print()
#     print("[Register Map]")
#     print(regmap_text)
#     print()
#     print(f"Generated files in: {case_dir.resolve()}")
def run_pipeline(source_text: str, out_dir: Path, stem: str) -> None:
    tokens = tokenize(source_text)
    templates = parse_templates(tokens)
    arm_virtual = emit_templates_to_arm(templates)
    reg_map = allocate_register_map(templates)
    arm_physical = apply_register_map(arm_virtual, reg_map)
    full_program = emit_full_program(arm_physical, reg_map)

    case_dir = out_dir / stem
    case_dir.mkdir(parents=True, exist_ok=True)

    pass1_text = format_pass1(tokens)
    pass2_text = format_pass2(templates)
    pass3_text = format_pass3(arm_virtual)
    pass4_text = format_pass4(arm_physical)
    regmap_text = "\n".join(f"{k} -> {v}" for k, v in sorted(reg_map.items()))

    (case_dir / "pass1.txt").write_text(pass1_text, encoding="utf-8")
    (case_dir / "pass2.txt").write_text(pass2_text, encoding="utf-8")
    (case_dir / "pass3_virtual_arm.s").write_text(pass3_text, encoding="utf-8")
    (case_dir / "pass4_physical_arm.s").write_text(pass4_text, encoding="utf-8")
    (case_dir / "regmap.txt").write_text(regmap_text, encoding="utf-8")
    (case_dir / "full_program.s").write_text(full_program, encoding="utf-8")

    print("=" * 72)
    print(f"Input: {stem}")
    print("=" * 72)
    print("[Pass 1] Tokens")
    print(pass1_text)
    print()
    print("[Pass 2] Templates")
    print(pass2_text)
    print()
    print("[Pass 3] Virtual ARM64")
    print(pass3_text)
    print()
    print("[Pass 4] Physical ARM64")
    print(pass4_text)
    print()
    print("[Register Map]")
    print(regmap_text)
    print()
    print(f"Generated files in: {case_dir.resolve()}")

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python codegen.py <input.qtac> [more.qtac ...]")
        sys.exit(1)

    out_dir = Path("output")

    for path_str in sys.argv[1:]:
        path = Path(path_str)
        if not path.exists():
            print(f"Input file not found: {path}")
            continue

        source = path.read_text(encoding="utf-8")
        run_pipeline(source, out_dir, path.stem)


if __name__ == "__main__":
    main()
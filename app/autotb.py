"""Builds a testbench automatically from a reference solution.

Idea: put the reference solution and the submission side by side, feed both the
same inputs, and compare their outputs. The author of a problem then only has
to supply a correct solution.

Steps:
  1. Read the module name from the starter code.
  2. Parse that module's ports (name, direction, width) from the reference.
  3. Rename every module in the reference to  ref___TOKEN___<name>.  The runner
     swaps __TOKEN__ for a random value on every run, so a submission cannot
     simply instantiate the reference and forward its outputs.
  4. Write the testbench:
       - no clock port:  try every input combination if there are few input
         bits, otherwise all-zeros, all-ones and random values
       - clock port:     reset, then random inputs on every cycle, comparing
         just after each rising edge

Limits: fixed port widths only (no parameters in ranges), no inout ports, and
clocked designs must use the rising edge of a port named clk or clock.
"""
import re

PREFIX = "ref___TOKEN___"
CLOCK_NAMES = {"clk", "clock", "i_clk", "clk_i"}
RESET_HIGH = {"rst", "reset", "arst", "areset", "srst", "i_rst", "rst_i"}
RESET_LOW = {"rst_n", "reset_n", "resetn", "rstn", "nrst", "nreset", "aresetn", "arst_n"}

EXHAUSTIVE_MAX_BITS = 10     # up to 1024 combinations are all tried
RANDOM_VECTORS = 1000        # combinational designs with more input bits
RANDOM_CYCLES = 300          # clocked designs

IDENT = r"[A-Za-z_]\w*"
PORT = re.compile(
    r"^\s*(?:(input|output|inout)\b)?\s*(?:(?:wire|reg|logic|tri)\b)?\s*(?:signed\b)?\s*"
    r"(?:\[([^\]]+)\])?\s*(" + IDENT + r")\s*(?:=.*)?$", re.S)


class AutoTBError(ValueError):
    """The reference solution cannot be turned into a testbench; the message says why."""


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


def module_names(code: str) -> list:
    return re.findall(r"\bmodule\s+(" + IDENT + ")", code)


def _balanced(text: str, start: int):
    """text[start] is '('. Returns (text inside the brackets, index just after ')')."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    raise AutoTBError("Unbalanced brackets in the module header.")


def _width(rng, name: str) -> int:
    if rng is None:
        return 1
    m = re.fullmatch(r"\s*(\d+)\s*:\s*(\d+)\s*", rng)
    if not m:
        raise AutoTBError(f"Port '{name}' has the width [{rng.strip()}]. Automatic testbenches "
                          "need plain numbers such as [7:0].")
    return abs(int(m[1]) - int(m[2])) + 1


def parse_ports(code: str, name: str) -> list:
    """Ports of module `name` as [{'name', 'dir', 'width'}], in header order.
    `code` must already have its comments stripped."""
    m = re.search(r"\bmodule\s+" + re.escape(name) + r"\b", code)
    if not m:
        raise AutoTBError(f"The reference solution has no module named '{name}' "
                          "(the name is taken from the starter code).")
    rest = code[m.end():]
    end = re.search(r"\bendmodule\b", rest)
    rest = rest[:end.start()] if end else rest

    i = len(rest) - len(rest.lstrip())
    if rest[i:i + 1] == "#":                           # parameter list: skip it
        _, i = _balanced(rest, rest.index("(", i))
        i += len(rest[i:]) - len(rest[i:].lstrip())
    if rest[i:i + 1] != "(":
        raise AutoTBError(f"Module '{name}' has no port list.")
    header, i = _balanced(rest, i)
    body = rest[i:]

    items = [re.match(PORT, part) for part in header.split(",") if part.strip()]
    if not items or None in items:
        raise AutoTBError("Could not understand the port list of the reference solution.")

    ports = []
    if any(it[1] for it in items):
        # ANSI style:  module m(input [3:0] a, b, output y);
        direction, rng = None, None
        for it in items:
            if it[1]:
                direction, rng = it[1], it[2]          # `b` above inherits both from `a`
            ports.append({"name": it[3], "dir": direction, "width": _width(rng, it[3])})
    else:
        # Older style:  module m(a, b, y);  input [3:0] a, b;  output y;
        declared = {}
        for d in re.finditer(r"\b(input|output|inout)\b([^;]*);", body):
            first = re.match(PORT, d[1] + " " + d[2].split(",")[0])
            if not first:
                raise AutoTBError("Could not understand a port declaration in the reference solution.")
            names = [first[3]] + [n.strip() for n in d[2].split(",")[1:]]
            for n in names:
                declared[n] = (d[1], _width(first[2], n))
        for it in items:
            if it[3] not in declared:
                raise AutoTBError(f"Port '{it[3]}' has no input/output declaration.")
            ports.append({"name": it[3], "dir": declared[it[3]][0], "width": declared[it[3]][1]})

    if any(p["dir"] is None for p in ports):
        raise AutoTBError("Every port needs a direction (input or output).")
    return ports


# ---------- small helpers for writing Verilog text ----------

def _decl(kind: str, p: dict, suffix: str = "") -> str:
    rng = f"[{p['width'] - 1}:0] " if p["width"] > 1 else ""
    return f"  {kind} {rng}{p['name']}{suffix};"


def _fmt(ports, suffix: str = ""):
    """('a=%0d b=%b', 'a, b') for a $display call."""
    text = " ".join(f"{p['name']}={'%0d' if p['width'] > 1 else '%b'}" for p in ports)
    return text, ", ".join(p["name"] + suffix for p in ports)


def _random(p: dict) -> str:
    words = (p["width"] + 31) // 32                    # $urandom gives 32 bits at a time
    value = "$urandom" if words == 1 else "{" + ", ".join(["$urandom"] * words) + "}"
    return f"{p['name']} = {value};"


def _const(p: dict, bit: str) -> str:
    value = f"1'b{bit}" if p["width"] == 1 else f"{{{p['width']}{{1'b{bit}}}}}"
    return f"{p['name']} = {value};"


def generate(starter: str, solution: str) -> str:
    """Returns the full testbench text (reference solution included, renamed)."""
    names = module_names(strip_comments(starter))
    if not names:
        raise AutoTBError("The starter code has no module.")
    top = names[0]
    ref = strip_comments(solution)
    ports = parse_ports(ref, top)

    if any(p["dir"] == "inout" for p in ports):
        raise AutoTBError("inout ports are not supported by automatic testbenches.")
    ins = [p for p in ports if p["dir"] == "input"]
    outs = [p for p in ports if p["dir"] == "output"]
    if not outs:
        raise AutoTBError("The module has no outputs to check.")

    def find(wanted):
        return next((p for p in ins if p["width"] == 1 and p["name"].lower() in wanted), None)

    clk = find(CLOCK_NAMES)
    rst = find(RESET_HIGH | RESET_LOW)
    data = [p for p in ins if p is not clk and p is not rst]
    if not clk and rst:                                # a "reset" on a clockless module is just an input
        data, rst = ins, None
    if not data and not clk:
        raise AutoTBError("The module has no inputs to drive.")

    ref_modules = module_names(ref)
    clash = {p["name"] for p in ports} & set(ref_modules)
    if clash:
        raise AutoTBError(f"A port and a module are both named '{clash.pop()}'; rename one.")
    pattern = r"\b(" + "|".join(sorted(map(re.escape, ref_modules), key=len, reverse=True)) + r")\b"
    ref = re.sub(pattern, lambda m: PREFIX + m[1], ref)

    shown_in = [p for p in ins if p is not clk]        # the clock is noise in a mismatch message
    in_text, in_args = _fmt(shown_in)
    got_text, got_args = _fmt(outs)
    _, exp_args = _fmt(outs, "__exp")
    when = 'At t=%0d ns: ' if clk else ""
    when_arg = "$time, " if clk else ""
    sep = ", " if shown_in else ""
    got_cat = "{" + ", ".join(p["name"] for p in outs) + "}"
    exp_cat = "{" + ", ".join(p["name"] + "__exp" for p in outs) + "}"

    L = ["`timescale 1ns/1ps", ref.strip(), "", "`timescale 1ns/1ps", "module tb;"]
    L += [_decl("reg", p) for p in ins]
    L += [_decl("wire", p) for p in outs]
    L += [_decl("wire", p, "__exp") for p in outs]
    L += ["  integer tb_errors, tb_checks, tb_known, tb_i;", ""]
    L += [f"  {top} dut(" + ", ".join(f".{p['name']}({p['name']})" for p in ports) + ");"]
    L += [f"  {PREFIX}{top} tb_ref(" + ", ".join(
        f".{p['name']}({p['name']}{'__exp' if p['dir'] == 'output' else ''})" for p in ports) + ");", ""]
    L += [
        "  task tb_check;",
        "    begin",
        "      tb_checks = tb_checks + 1;",
        f"      if (^{exp_cat} !== 1'bx) tb_known = tb_known + 1;   // reference fully 0/1 here",
        f"      if ({got_cat} !== {exp_cat}) begin",
        "        tb_errors = tb_errors + 1;",
        "        if (tb_errors <= 5)",
        f'          $display("{when}Mismatch: {in_text} -> {got_text}, expected {got_text}",',
        f"                   {when_arg}{in_args}{sep}{got_args}, {exp_args});",
        "      end",
        "    end",
        "  endtask",
        "",
    ]

    if clk:
        c = clk["name"]
        L += [f"  initial {c} = 0;", f"  always #5 {c} = ~{c};", ""]
    L += ["  initial begin", "    tb_errors = 0; tb_checks = 0; tb_known = 0;"]
    L += ["    " + _const(p, "0") for p in data]

    if not clk:
        bits = sum(p["width"] for p in data)
        if bits <= EXHAUSTIVE_MAX_BITS:
            cat = "{" + ", ".join(p["name"] for p in data) + "}"
            L += [f"    // {bits} input bits: try all {2 ** bits} combinations",
                  f"    for (tb_i = 0; tb_i < {2 ** bits}; tb_i = tb_i + 1) begin",
                  f"      {cat} = tb_i;", "      #1; tb_check;", "    end"]
        else:
            L += [f"    // {bits} input bits is too many to try them all: corners, then random values",
                  "    #1; tb_check;"]
            L += ["    " + _const(p, "1") for p in data]
            L += ["    #1; tb_check;",
                  f"    for (tb_i = 0; tb_i < {RANDOM_VECTORS}; tb_i = tb_i + 1) begin"]
            L += ["      " + _random(p) for p in data]
            L += ["      #1; tb_check;", "    end"]
    else:
        c = clk["name"]
        if rst:
            r = rst["name"]
            on, off = ("1'b0", "1'b1") if r.lower() in RESET_LOW else ("1'b1", "1'b0")
            L += [f"    {r} = {on};", f"    repeat (2) @(posedge {c});", "    #1; tb_check;", f"    {r} = {off};"]
        L += [f"    for (tb_i = 0; tb_i < {RANDOM_CYCLES}; tb_i = tb_i + 1) begin",
              f"      @(negedge {c});          // change inputs away from the rising edge"]
        L += ["      " + _random(p) for p in data]
        if rst:
            L += [f"      {r} = ($urandom % 16 == 0) ? {on} : {off};   // occasional reset mid-run"]
        L += [f"      @(posedge {c}); #1; tb_check;", "    end"]

    L += [
        "    if (tb_known == 0)",
        '      $display("RESULT FAIL: the reference outputs never became a known 0/1 value (missing reset?)");',
        '    else if (tb_errors == 0) $display("RESULT __TOKEN__ PASS");',
        '    else $display("RESULT FAIL: %0d of %0d checks wrong", tb_errors, tb_checks);',
        "    $finish;",
        "  end",
        "endmodule",
        "",
    ]
    return "\n".join(L)

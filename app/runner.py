"""Compiles and simulates one submission with Icarus Verilog.

Three ideas keep a submission from faking a pass:

1. The hidden testbench prints a random per-run token only when every check
   passes, so printing "PASS" from the design does nothing.
2. The simulation runs in an empty directory. The compiled file (which
   contains the token) lives in a second, randomly named directory, so the
   design cannot open and print it with $fopen.
3. The testbench's top module is renamed from `tb` to `tb_<random>` on every
   run. Verilog lets any module reach into another by name (for example
   `force tb.errors = 0;`), so the name must be impossible to guess.

For the waveform, a tiny extra module is compiled alongside the testbench. It
tells the simulator to record every signal of the submitted module (the
instance `dut` inside the testbench) into wave.vcd, which is then parsed and sent to the page.
"""
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

from .vcd import parse_vcd

COMPILE_TIMEOUT_S = 10
RUN_TIMEOUT_S = 5
MAX_OUTPUT_CHARS = 8000
MAX_VCD_BYTES = 2_000_000

DUMP_MODULE = """
module judge_dump;
  initial begin
    $dumpfile("wave.vcd");
    $dumpvars(1, __TOP__.dut);
  end
endmodule
"""


def _result(verdict: str, output: str, waveform=None) -> dict:
    output = output.strip()
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
    return {"verdict": verdict, "output": output, "waveform": waveform}


def _read_waveform(path: Path):
    try:
        if not path.is_file() or path.stat().st_size > MAX_VCD_BYTES:
            return None
        return parse_vcd(path.read_text(errors="replace"))
    except Exception:
        return None             # a broken dump must never break the verdict


def run_submission(code: str, testbench: str) -> dict:
    token = secrets.token_hex(16)
    pass_line = f"RESULT {token} PASS"
    top = f"tb_{token}"
    tb_text = re.sub(r"\bmodule\s+tb\b", f"module {top}", testbench.replace("__TOKEN__", token), count=1)
    tb_text += DUMP_MODULE.replace("__TOP__", top)

    with tempfile.TemporaryDirectory(prefix="build_") as build_tmp, \
         tempfile.TemporaryDirectory(prefix="run_") as run_tmp:
        build = Path(build_tmp)
        (build / "design.v").write_text(code)
        (build / "tb.v").write_text(tb_text)

        # Step 1: compile the testbench together with the submitted design.
        try:
            comp = subprocess.run(
                ["iverilog", "-g2012", "-s", top, "-s", "judge_dump",
                 "-o", "sim.vvp", "tb.v", "design.v"],
                cwd=build, capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return _result("TIMEOUT", "Compilation took too long.")
        if comp.returncode != 0:
            return _result("COMPILE_ERROR", (comp.stdout + comp.stderr).replace(token, ""))

        # Step 2: run the simulation in the empty directory, with a time limit.
        try:
            sim = subprocess.run(
                ["vvp", "-n", str(build / "sim.vvp")],
                cwd=run_tmp, capture_output=True, text=True, timeout=RUN_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return _result(
                "TIMEOUT",
                f"Simulation did not finish within {RUN_TIMEOUT_S} seconds "
                "(possible combinational loop or zero-delay infinite loop).",
            )

        waveform = _read_waveform(Path(run_tmp) / "wave.vcd")

        out = sim.stdout + sim.stderr
        passed = pass_line in out
        out = out.replace(pass_line, "All tests passed.").replace(token, "")
        # Drop the simulator's own "VCD info: dumpfile ... opened" notices.
        out = "\n".join(line for line in out.splitlines() if not line.startswith("VCD "))
        if passed:
            return _result("PASS", out, waveform)
        if "RESULT FAIL" not in out:
            out += "\nSimulation ended before the testbench finished."
        return _result("FAIL", out, waveform)

"""Checks the automatic testbench generator."""
import pytest

from app.autotb import AutoTBError, generate, parse_ports
from app.runner import run_submission


def judge(starter, solution, submission):
    return run_submission(submission, generate(starter, solution))


# ---------- reading port lists ----------

def test_ports_modern_style_with_inherited_width():
    ports = parse_ports("module m(input [3:0] a, b, input wire clk, output reg [7:0] q); endmodule", "m")
    assert ports == [{"name": "a", "dir": "input", "width": 4}, {"name": "b", "dir": "input", "width": 4},
                     {"name": "clk", "dir": "input", "width": 1}, {"name": "q", "dir": "output", "width": 8}]


def test_ports_older_style():
    ports = parse_ports("module m(a, b, y); input [1:0] a, b; output y; assign y = a == b; endmodule", "m")
    assert [(p["name"], p["dir"], p["width"]) for p in ports] == [("a", "input", 2), ("b", "input", 2), ("y", "output", 1)]


def test_ports_skip_parameter_list():
    ports = parse_ports("module m #(parameter N = 4) (input a, output y); endmodule", "m")
    assert [p["name"] for p in ports] == ["a", "y"]


def test_parameter_widths_are_refused_with_a_reason():
    with pytest.raises(AutoTBError, match="plain numbers"):
        parse_ports("module m #(parameter N = 4) (input [N-1:0] a, output y); endmodule", "m")


# ---------- combinational, few inputs: every combination ----------

MUX_START = "module mux2(input a, input b, input sel, output y);\nendmodule"
MUX_OK = "module mux2(input a, input b, input sel, output y); assign y = sel ? b : a; endmodule"
MUX_OTHER_OK = "module mux2(input a, input b, input sel, output y); assign y = (a & ~sel) | (b & sel); endmodule"
MUX_WRONG = "module mux2(input a, input b, input sel, output y); assign y = sel ? a : b; endmodule"


def test_small_combinational():
    assert "all 8 combinations" in generate(MUX_START, MUX_OK)
    assert judge(MUX_START, MUX_OK, MUX_OTHER_OK)["verdict"] == "PASS"
    wrong = judge(MUX_START, MUX_OK, MUX_WRONG)
    assert wrong["verdict"] == "FAIL" and "Mismatch: a=0 b=1 sel=0 -> y=1, expected y=0" in wrong["output"]
    assert judge(MUX_START, MUX_OK, MUX_START)["verdict"] == "FAIL"


# ---------- combinational, many inputs: random values ----------

ADD_START = "module add16(input [15:0] a, input [15:0] b, output [16:0] s);\nendmodule"
ADD_OK = "module add16(input [15:0] a, input [15:0] b, output [16:0] s); assign s = a + b; endmodule"
ADD_NO_CARRY = "module add16(input [15:0] a, input [15:0] b, output [16:0] s); assign s = {1'b0, a[15:0] + b[15:0]}; endmodule"


def test_wide_combinational_uses_random_values():
    assert "random values" in generate(ADD_START, ADD_OK)
    assert judge(ADD_START, ADD_OK, ADD_OK)["verdict"] == "PASS"
    assert judge(ADD_START, ADD_OK, ADD_NO_CARRY)["verdict"] == "FAIL"


# ---------- clocked ----------

CNT_START = "module counter(input clk, input rst, input en, output reg [3:0] q);\nendmodule"
CNT_OK = ("module counter(input clk, input rst, input en, output reg [3:0] q);"
          " always @(posedge clk) if (rst) q <= 0; else if (en) q <= q + 1; endmodule")
CNT_IGNORES_EN = ("module counter(input clk, input rst, input en, output reg [3:0] q);"
                  " always @(posedge clk) if (rst) q <= 0; else q <= q + 1; endmodule")
CNT_NO_RESET = ("module counter(input clk, input rst, input en, output reg [3:0] q);"
                " initial q = 0; always @(posedge clk) if (en) q <= q + 1; endmodule")


def test_clocked_design_with_reset():
    assert judge(CNT_START, CNT_OK, CNT_OK)["verdict"] == "PASS"
    assert judge(CNT_START, CNT_OK, CNT_IGNORES_EN)["verdict"] == "FAIL"
    assert judge(CNT_START, CNT_OK, CNT_NO_RESET)["verdict"] == "FAIL"   # caught by the mid-run resets


def test_active_low_reset_is_recognised():
    start = "module r(input clk, input rst_n, input d, output reg q);\nendmodule"
    ok = "module r(input clk, input rst_n, input d, output reg q); always @(posedge clk) if (!rst_n) q <= 0; else q <= d; endmodule"
    assert "rst_n = 1'b0;" in generate(start, ok)
    assert judge(start, ok, ok)["verdict"] == "PASS"


def test_reference_that_never_becomes_known_is_refused():
    start = "module c(input clk, output reg [3:0] q);\nendmodule"
    ref = "module c(input clk, output reg [3:0] q); always @(posedge clk) q <= q + 1; endmodule"
    result = judge(start, ref, ref)
    assert result["verdict"] == "FAIL" and "never became a known" in result["output"]


# ---------- reference with helper modules ----------

FA_START = "module adder2(input [1:0] a, input [1:0] b, output [2:0] s);\nendmodule"
FA_OK = """
module fa(input a, input b, input c, output s, output co);
  assign {co, s} = a + b + c;
endmodule
module adder2(input [1:0] a, input [1:0] b, output [2:0] s);  // uses two full adders
  wire c;
  fa f0(a[0], b[0], 1'b0, s[0], c);
  fa f1(a[1], b[1], c, s[1], s[2]);
endmodule
"""


def test_submission_may_reuse_the_reference_module_names():
    # The submission defines its own `fa`; the reference's copy is renamed, so no clash.
    assert judge(FA_START, FA_OK, FA_OK)["verdict"] == "PASS"


# ---------- cheating ----------

def test_cannot_instantiate_the_reference():
    cheat = ("module mux2(input a, input b, input sel, output y);"
             " ref_mux2 r(a, b, sel, y); endmodule")
    assert judge(MUX_START, MUX_OK, cheat)["verdict"] == "COMPILE_ERROR"


@pytest.mark.parametrize("line", [
    "initial force tb.tb_errors = 0;",
    "assign y = tb.y__exp;",
    "assign y = tb.tb_ref.y;",
])
def test_cannot_reach_into_the_testbench(line):
    cheat = f"module mux2(input a, input b, input sel, output y); {line} endmodule"
    assert judge(MUX_START, MUX_OK, cheat)["verdict"] != "PASS"


def test_generated_text_never_leaks_the_token_placeholder_unreplaced():
    result = judge(MUX_START, MUX_OK, "module mux2(input a, output y) endmodule")
    assert result["verdict"] == "COMPILE_ERROR" and "__TOKEN__" not in result["output"]

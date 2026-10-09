"""Checks the judge itself: correct designs pass, wrong ones fail, cheats fail.

Run from the project folder with:  python -m pytest tests
(needs iverilog installed, or run inside the container)
"""
from app.problems import BY_ID
from app.runner import run_submission

MUX_OK = "module mux2(input a, input b, input sel, output y); assign y = sel ? b : a; endmodule"
MUX_WRONG = "module mux2(input a, input b, input sel, output y); assign y = sel ? a : b; endmodule"
ADDER_OK = ("module adder4(input [3:0] a, input [3:0] b, input cin, output [3:0] sum, output cout);"
            " assign {cout, sum} = a + b + cin; endmodule")
ADDER_NO_CARRY = ("module adder4(input [3:0] a, input [3:0] b, input cin, output [3:0] sum, output cout);"
                  " assign sum = a + b + cin; assign cout = 0; endmodule")
COUNTER_OK = ("module counter(input clk, input rst, output reg [3:0] q);"
              " always @(posedge clk) if (rst) q <= 0; else q <= q + 1; endmodule")
COUNTER_NO_RESET = ("module counter(input clk, input rst, output reg [3:0] q);"
                    " initial q = 0; always @(posedge clk) q <= q + 1; endmodule")
FAKE_PASS = ("module mux2(input a, input b, input sel, output y);"
             ' initial begin $display("RESULT PASS"); $display("All tests passed."); $finish; end'
             " endmodule")
INFINITE_LOOP = ("module mux2(input a, input b, input sel, output y);"
                 " initial forever begin end endmodule")
SYNTAX_ERROR = "module mux2(input a, input b, input sel, output y) assign y = ; endmodule"


def verdict(problem_id, code):
    return run_submission(code, BY_ID[problem_id]["testbench"])["verdict"]


def test_correct_designs_pass():
    assert verdict("mux2", MUX_OK) == "PASS"
    assert verdict("adder4", ADDER_OK) == "PASS"
    assert verdict("counter", COUNTER_OK) == "PASS"


def test_wrong_designs_fail():
    assert verdict("mux2", MUX_WRONG) == "FAIL"
    assert verdict("adder4", ADDER_NO_CARRY) == "FAIL"
    assert verdict("counter", COUNTER_NO_RESET) == "FAIL"


def test_printing_pass_does_not_pass():
    assert verdict("mux2", FAKE_PASS) == "FAIL"


def test_infinite_loop_times_out():
    assert verdict("mux2", INFINITE_LOOP) == "TIMEOUT"


def test_syntax_error_is_reported():
    assert verdict("mux2", SYNTAX_ERROR) == "COMPILE_ERROR"


def test_token_never_leaks():
    out = run_submission(MUX_OK, BY_ID["mux2"]["testbench"])["output"]
    assert "RESULT" not in out and "All tests passed." in out


def test_waveform_has_module_signals():
    wave = run_submission(MUX_OK, BY_ID["mux2"]["testbench"])["waveform"]
    assert {s["name"] for s in wave["signals"]} == {"a", "b", "sel", "y"}
    assert wave["end_ns"] == 8.0


def test_waveform_bus_values_are_decimal():
    wave = run_submission(COUNTER_OK, BY_ID["counter"]["testbench"])["waveform"]
    q = next(s for s in wave["signals"] if s["name"] == "q")
    values = [v for _, v in q["changes"]]
    assert q["width"] == 4 and values[0] == "x" and values[1:5] == ["0", "1", "2", "3"]


def test_no_waveform_on_compile_error():
    assert run_submission(SYNTAX_ERROR, BY_ID["mux2"]["testbench"])["waveform"] is None

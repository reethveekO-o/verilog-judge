"""Problem set. Each problem has a statement, starter code and a hidden testbench.

To add a problem, append a dict here. The testbench must:
  - have a top module called `tb`
  - print  RESULT __TOKEN__ PASS  only when every check passes
  - print  RESULT FAIL ...        otherwise
"""

MUX2_TB = r"""
`timescale 1ns/1ps
module tb;
  reg a, b, sel;
  wire y;
  integer i, errors;
  mux2 dut(.a(a), .b(b), .sel(sel), .y(y));
  initial begin
    errors = 0;
    for (i = 0; i < 8; i = i + 1) begin
      {sel, a, b} = i[2:0];
      #1;
      if (y !== (sel ? b : a)) begin
        errors = errors + 1;
        $display("Mismatch: a=%b b=%b sel=%b -> y=%b, expected %b", a, b, sel, y, sel ? b : a);
      end
    end
    if (errors == 0) $display("RESULT __TOKEN__ PASS");
    else $display("RESULT FAIL: %0d of 8 cases wrong", errors);
    $finish;
  end
endmodule
"""

ADDER4_TB = r"""
`timescale 1ns/1ps
module tb;
  reg [3:0] a, b;
  reg cin;
  wire [3:0] sum;
  wire cout;
  integer i, errors;
  reg [4:0] expected;
  adder4 dut(.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
  initial begin
    errors = 0;
    for (i = 0; i < 512; i = i + 1) begin
      {cin, a, b} = i[8:0];
      #1;
      expected = a + b + cin;
      if ({cout, sum} !== expected) begin
        errors = errors + 1;
        if (errors <= 5)
          $display("Mismatch: a=%0d b=%0d cin=%b -> cout=%b sum=%0d, expected cout=%b sum=%0d",
                   a, b, cin, cout, sum, expected[4], expected[3:0]);
      end
    end
    if (errors == 0) $display("RESULT __TOKEN__ PASS");
    else $display("RESULT FAIL: %0d of 512 cases wrong", errors);
    $finish;
  end
endmodule
"""

COUNTER_TB = r"""
`timescale 1ns/1ps
module tb;
  reg clk, rst;
  wire [3:0] q;
  integer i, errors;
  reg [3:0] expected;
  counter dut(.clk(clk), .rst(rst), .q(q));
  initial clk = 0;
  always #5 clk = ~clk;

  task check;
    begin
      if (q !== expected) begin
        errors = errors + 1;
        if (errors <= 5)
          $display("Mismatch at t=%0t: q=%0d, expected %0d", $time, q, expected);
      end
    end
  endtask

  initial begin
    errors = 0;
    rst = 1;
    @(posedge clk); #1;
    expected = 0; check;
    rst = 0;
    // count through a full wrap-around
    for (i = 0; i < 20; i = i + 1) begin
      @(posedge clk); #1;
      expected = expected + 1; check;
    end
    // reset in the middle of counting
    rst = 1;
    @(posedge clk); #1;
    expected = 0; check;
    rst = 0;
    for (i = 0; i < 3; i = i + 1) begin
      @(posedge clk); #1;
      expected = expected + 1; check;
    end
    if (errors == 0) $display("RESULT __TOKEN__ PASS");
    else $display("RESULT FAIL: %0d checks wrong", errors);
    $finish;
  end
endmodule
"""

PROBLEMS = [
    {
        "id": "mux2",
        "title": "2-to-1 Multiplexer",
        "difficulty": "Easy",
        "statement": "Build a 2-to-1 multiplexer. When sel is 0 the output y equals a; "
                     "when sel is 1 it equals b.",
        "starter": "module mux2(\n    input  a,\n    input  b,\n    input  sel,\n    output y\n);\n"
                   "    // your code here\n\nendmodule\n",
        "testbench": MUX2_TB,
    },
    {
        "id": "adder4",
        "title": "4-bit Adder",
        "difficulty": "Easy",
        "statement": "Build a 4-bit adder with carry-in and carry-out. "
                     "{cout, sum} must equal a + b + cin.",
        "starter": "module adder4(\n    input  [3:0] a,\n    input  [3:0] b,\n    input        cin,\n"
                   "    output [3:0] sum,\n    output       cout\n);\n    // your code here\n\nendmodule\n",
        "testbench": ADDER4_TB,
    },
    {
        "id": "counter",
        "title": "4-bit Counter",
        "difficulty": "Medium",
        "statement": "Build a 4-bit up counter. On every rising clock edge q increases by 1 and "
                     "wraps from 15 to 0. When rst is 1 at a rising edge, q becomes 0 "
                     "(synchronous reset).",
        "starter": "module counter(\n    input            clk,\n    input            rst,\n"
                   "    output reg [3:0] q\n);\n    // your code here\n\nendmodule\n",
        "testbench": COUNTER_TB,
    },
]

BY_ID = {p["id"]: p for p in PROBLEMS}

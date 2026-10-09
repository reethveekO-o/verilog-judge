# Verilog Judge

A small online judge for Verilog: pick a problem, write a module, and the server
compiles and simulates it against a hidden testbench.

## Run it

Needs Docker Desktop.

```
docker compose up --build
```

Then open http://localhost:8000

## How it works

1. The page sends your code to `POST /api/submit` (FastAPI, `app/main.py`).
2. `app/runner.py` writes the code and the problem's hidden testbench to a
   temporary folder, compiles them with Icarus Verilog (`iverilog`) and runs the
   simulation (`vvp`) with a 5 second limit.
3. The testbench prints a random per-run token only if every check passes.
   The runner looks for that token to decide the verdict:
   `PASS`, `FAIL`, `COMPILE_ERROR` or `TIMEOUT`.
4. A small extra module makes the simulator record every signal of your module
   into a VCD file. `app/vcd.py` parses it and the page draws it as an SVG
   waveform (single bits as stepped lines, buses as labelled boxes).

5. Problems and every submission are stored in PostgreSQL (`app/db.py`), in a
   Docker volume, so they survive restarts and rebuilds.

## Adding problems from the site

Click **+ Add problem** and fill in the statement, starter code and a reference
solution (type them or load `.v` files). The server stores the problem only if
the reference solution passes the testbench and the starter code does not.

### Editing and deleting

On a problem's page, the pencil icon opens it in the same form (an edit goes
through the same checks as a new problem) and the bin icon deletes it together
with its submissions. Under "Your submissions", the cross removes one entry and
"Clear all" removes them all. Deleting asks for a second click to confirm.

### Automatic testbenches

By default you do not write a testbench. `app/autotb.py` reads the port list of
your reference solution and generates one that drives the reference and the
submission with the same inputs and compares their outputs:

- no clock port: every input combination when there are at most 10 input bits,
  otherwise all-zeros, all-ones and 1000 random values
- a port named `clk`: reset (if there is a `rst` or `rst_n` port), then 300
  cycles of random inputs with occasional resets, compared after each rising edge

"Preview testbench" shows what would be generated. For anything it cannot
handle (parameterised widths, inout ports, free-running designs such as a ring
oscillator) untick the box and write the testbench by hand.

## Safety measures

- Simulation runs as a non-root user in a container with a read-only
  filesystem, no extra Linux capabilities, and memory, CPU and process limits.
- The pass token is random per run, and the simulation runs in an empty folder
  so a submission cannot read the testbench or the compiled file.
- The testbench's top module is renamed to a random name on every run, so a
  submission cannot reach into it (for example `force tb.errors = 0;`).
- In automatic testbenches the reference solution's modules also get random
  names, so a submission cannot instantiate the reference and copy its outputs.
- Compile and run steps both have time limits; output is capped.

## Writing a testbench by hand

Use the form on the site. (`app/problems.py` only holds the three starter
problems loaded into an empty database.) A hand-written testbench needs a top
module named `tb`, must instantiate the design as `dut` (the waveform records
`tb.dut`), and must print `RESULT __TOKEN__ PASS` on success and
`RESULT FAIL ...` otherwise.

## Tests

```
docker compose run --rm judge python -m pytest tests -p no:cacheprovider
```

The tests use a temporary SQLite file, so they never touch your real data.
`.github/workflows/tests.yml` runs the same tests on GitHub after every push.

## Useful commands

```
docker compose down          # stop; data is kept
docker compose down -v       # stop and wipe the database
docker compose exec db psql -U judge -d judge -c "select id, slug, title from problems"
```

## Not built yet

User accounts (anyone who can open the site can add, edit or delete problems),
a job queue, cloud deployment.

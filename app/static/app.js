const $ = id => document.getElementById(id);
const LABELS = { PASS:"Passed", FAIL:"Failed", COMPILE_ERROR:"Compile error", TIMEOUT:"Timed out" };
let problems = [], current = null;
const drafts = {};   // code typed so far, kept per problem while the page is open

const TB_TEMPLATE = `\`timescale 1ns/1ps
module tb;
  // 1. declare a reg for every input and a wire for every output
  reg  a;
  wire y;
  integer errors;

  // 2. the instance MUST be called dut
  my_module dut(.a(a), .y(y));

  initial begin
    errors = 0;

    // 3. drive inputs, wait, compare with the expected value
    a = 0; #1;
    if (y !== 1'b0) begin errors = errors + 1; $display("Mismatch: a=%b -> y=%b", a, y); end

    // 4. keep these two lines exactly as they are
    if (errors == 0) $display("RESULT __TOKEN__ PASS");
    else $display("RESULT FAIL: %0d checks wrong", errors);
    $finish;
  end
endmodule
`;

function show(view) {
  $("solveView").hidden = view !== "solve";
  $("addView").hidden = view !== "add";
  $("addBtn").classList.toggle("active", view === "add");
}

function renderNav() {
  $("list").replaceChildren();
  for (const p of problems) {
    const b = document.createElement("button");
    b.dataset.id = p.id;
    b.textContent = p.title;
    const s = document.createElement("small");
    s.textContent = p.difficulty;
    b.appendChild(s);
    b.onclick = () => select(p.id);
    $("list").appendChild(b);
  }
}

function select(id) {
  if (current) drafts[current.id] = $("code").value;
  current = problems.find(p => p.id === id);
  show("solve");
  $("title").textContent = current.title;
  $("statement").textContent = current.statement;
  $("code").value = drafts[id] ?? current.starter;
  $("verdict").textContent = "";
  $("output").textContent = "Simulator output appears here.";
  showWave(null);
  for (const b of $("list").children) b.classList.toggle("active", b.dataset.id === id);
  loadHistory();
}

async function load() {
  problems = await (await fetch("/api/problems")).json();
  renderNav();
  if (problems.length) select(problems[0].id); else openForm(null);
}

$("submit").onclick = async () => {
  $("submit").disabled = true;
  $("verdict").className = "";
  $("verdict").textContent = "Running...";
  try {
    const res = await fetch("/api/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem_id: current.id, code: $("code").value }),
    });
    if (!res.ok) throw new Error("Server returned " + res.status);
    const data = await res.json();
    $("verdict").className = data.verdict;
    $("verdict").textContent = LABELS[data.verdict] ?? data.verdict;
    $("output").textContent = data.output || "(no output)";
    showWave(data.waveform);
    loadHistory();
  } catch (e) {
    $("verdict").className = "FAIL";
    $("verdict").textContent = "Error";
    $("output").textContent = String(e);
    showWave(null);
  }
  $("submit").disabled = false;
};

// Tab key inserts spaces instead of leaving the editor.
document.addEventListener("keydown", e => {
  const t = e.target;
  if (e.key !== "Tab" || t.tagName !== "TEXTAREA" || t.id === "nbStatement") return;
  e.preventDefault();
  const s = t.selectionStart;
  t.value = t.value.slice(0, s) + "    " + t.value.slice(t.selectionEnd);
  t.selectionStart = t.selectionEnd = s + 4;
});

/* ---------- submission history (stored in the database) ---------- */
async function loadHistory() {
  const id = current.id;
  let rows = [];
  try { rows = await (await fetch(`/api/problems/${id}/submissions`)).json(); } catch (e) {}
  if (!current || current.id !== id) return;          // user switched problem meanwhile
  $("historyPanel").hidden = rows.length === 0;
  $("history").replaceChildren();
  for (const r of rows) {
    const row = document.createElement("div");
    row.className = "hrow";
    const b = document.createElement("button");
    b.className = "load";
    const v = document.createElement("b");
    v.className = r.verdict;
    v.textContent = LABELS[r.verdict] ?? r.verdict;
    const t = document.createElement("span");
    t.className = "hint";
    t.textContent = new Date(r.created_at).toLocaleString();
    b.append(v, t);
    b.onclick = () => { $("code").value = r.code; $("code").focus(); };
    const x = document.createElement("button");
    x.className = "icon danger";
    x.title = "Delete this submission";
    x.setAttribute("aria-label", "Delete this submission");
    x.textContent = "\u00d7";
    x.onclick = async () => { await fetch(`/api/submissions/${r.id}`, { method: "DELETE" }); loadHistory(); };
    row.append(b, x);
    $("history").appendChild(row);
  }
}

/* ---------- delete / clear, with a second click to confirm ---------- */
function confirmClick(btn, action) {
  const reset = () => { clearTimeout(btn._timer); btn.classList.remove("armed"); btn.innerHTML = btn._label; btn._armed = false; };
  if (btn._armed) { reset(); action(); return; }
  btn._armed = true;
  btn._label = btn.innerHTML;
  btn.classList.add("armed");
  btn.textContent = "Click again to confirm";
  btn._timer = setTimeout(reset, 3500);
}

$("clearHistory").onclick = () => confirmClick($("clearHistory"), async () => {
  await fetch(`/api/problems/${current.id}/submissions`, { method: "DELETE" });
  loadHistory();
});

$("deleteBtn").onclick = () => confirmClick($("deleteBtn"), async () => {
  const id = current.id;
  const res = await fetch(`/api/problems/${id}`, { method: "DELETE" });
  if (!res.ok) return;
  problems = problems.filter(p => p.id !== id);
  delete drafts[id];
  current = null;
  renderNav();
  if (problems.length) select(problems[0].id); else openForm(null);
});

$("editBtn").onclick = async () => {
  const res = await fetch(`/api/problems/${current.id}/edit`);
  if (res.ok) openForm(await res.json());
};

/* ---------- add a problem ---------- */
let editing = null;      // id of the problem being edited, or null when adding a new one

function clearForm() {
  for (const id of ["nbTitle", "nbStatement", "nbStarter", "nbSolution", "nbTestbench"]) $(id).value = "";
  $("nbDifficulty").value = "Easy";
  $("nbAuto").checked = true;
  $("addMsg").textContent = "";
  $("addOutput").hidden = true;
}

// full = a problem with its hidden parts (edit), or null (new problem)
function openForm(full) {
  if (current) drafts[current.id] = $("code").value;
  if (full || editing !== null) clearForm();     // keep a half-typed new problem, drop anything else
  editing = full ? full.id : null;
  if (full) {
    $("nbTitle").value = full.title;
    $("nbDifficulty").value = full.difficulty;
    $("nbStatement").value = full.statement;
    $("nbStarter").value = full.starter;
    $("nbSolution").value = full.solution;
    $("nbAuto").checked = full.auto_testbench;
    if (!full.auto_testbench) $("nbTestbench").value = full.testbench;
  }
  if (!$("nbTestbench").value) $("nbTestbench").value = TB_TEMPLATE;
  $("formTitle").textContent = full ? "Edit problem" : "Add a problem";
  $("saveProblem").textContent = full ? "Check and save changes" : "Check and save";
  $("cancelEdit").hidden = !full;
  for (const b of $("list").children) b.classList.toggle("active", !!full && b.dataset.id === full.id);
  syncAuto();
  show("add");
  $("addBtn").classList.toggle("active", !full);
}

$("addBtn").onclick = () => openForm(null);
$("cancelEdit").onclick = () => { const id = editing; clearForm(); editing = null; select(id); };

function syncAuto() {
  const auto = $("nbAuto").checked;
  $("nbManual").hidden = auto;
  $("nbAutoHint").hidden = !auto;
  $("previewTb").hidden = !auto;
}
$("nbAuto").onchange = syncAuto;

function addError(res, data) {
  const msg = $("addMsg"), out = $("addOutput");
  msg.className = "FAIL";
  if (res.status === 422) {
    msg.textContent = "Fill in every box (the title needs at least 3 characters).";
  } else {
    msg.textContent = data.detail?.message ?? "Something went wrong.";
    if (data.detail?.output) { out.textContent = data.detail.output; out.hidden = false; }
  }
}

$("previewTb").onclick = async () => {
  const msg = $("addMsg"), out = $("addOutput");
  msg.className = ""; msg.textContent = ""; out.hidden = true;
  try {
    const res = await fetch("/api/testbench/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ starter: $("nbStarter").value, solution: $("nbSolution").value }),
    });
    const data = await res.json();
    if (res.ok) { out.textContent = data.testbench; out.hidden = false; }
    else if (res.status === 422) { msg.className = "FAIL"; msg.textContent = "Fill in the starter code and the reference solution first."; }
    else addError(res, data);
  } catch (e) { msg.className = "FAIL"; msg.textContent = String(e); }
};

// "Choose file" buttons copy a .v file's text into the box above them.
for (const input of document.querySelectorAll("input[type=file]")) {
  input.onchange = async () => {
    if (input.files[0]) $(input.dataset.target).value = await input.files[0].text();
    input.value = "";
  };
}

$("saveProblem").onclick = async () => {
  const msg = $("addMsg"), out = $("addOutput");
  $("saveProblem").disabled = true;
  msg.className = ""; msg.textContent = "Checking..."; out.hidden = true;
  try {
    const res = await fetch(editing ? `/api/problems/${editing}` : "/api/problems", {
      method: editing ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: $("nbTitle").value, difficulty: $("nbDifficulty").value,
        statement: $("nbStatement").value, starter: $("nbStarter").value,
        testbench: $("nbAuto").checked ? "" : $("nbTestbench").value, solution: $("nbSolution").value,
      }),
    });
    const data = await res.json();
    if (res.ok) {
      if (editing) {
        problems = problems.map(p => p.id === data.id ? data : p);
        delete drafts[data.id];                  // the starter code may have changed
        current = null;
      } else {
        problems.push(data);
      }
      renderNav();
      clearForm();
      editing = null;
      select(data.id);
    } else {
      addError(res, data);
    }
  } catch (e) {
    msg.className = "FAIL";
    msg.textContent = String(e);
  }
  $("saveProblem").disabled = false;
};

/* ---------- waveform viewer ----------
   The server sends { end_ns, signals:[{ name, width, changes:[[time, value], ...] }] }.
   Each signal becomes one row of an SVG: a stepped line for single bits,
   labelled boxes for buses. */
const SVG = "http://www.w3.org/2000/svg";
let wave = null, zoom = 1;

function el(tag, attrs, text) {
  const e = document.createElementNS(SVG, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}

function showWave(w) {
  wave = w && w.signals && w.signals.length ? w : null;
  zoom = 1;
  $("wavePanel").hidden = !wave;
  drawWave();
}

function drawWave() {
  const box = $("wave");
  box.replaceChildren();
  if (!wave) return;

  const NAME_W = 96, ROW_H = 32, SIG_H = 18, TOP = 24, PAD = 12;
  const end = wave.end_ns > 0 ? wave.end_ns : 1;
  const plotW = Math.max(300, box.clientWidth - NAME_W - PAD - 2) * zoom;
  const height = TOP + wave.signals.length * ROW_H + 6;
  const X = t => NAME_W + (t / end) * plotW;
  const svg = el("svg", { width: NAME_W + plotW + PAD, height });

  // time axis: pick a round step (1, 2 or 5 times a power of ten) about 80px apart
  const raw = end / (plotW / 80);
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].find(m => m * pow >= raw) * pow;
  for (let t = 0; t <= end + 1e-9; t += step) {
    svg.appendChild(el("line", { class: "w-grid", x1: X(t), x2: X(t), y1: TOP - 4, y2: height }));
    svg.appendChild(el("text", { class: "w-tick", x: X(t) + 3, y: 12 }, String(+t.toFixed(6))));
  }

  wave.signals.forEach((sig, row) => {
    const yTop = TOP + row * ROW_H + (ROW_H - SIG_H) / 2;
    const yBot = yTop + SIG_H, yMid = yTop + SIG_H / 2;
    const label = sig.width > 1 ? `${sig.name}[${sig.width - 1}:0]` : sig.name;
    svg.appendChild(el("text", { class: "w-name", x: 8, y: yMid + 4 }, label));

    const points = [];
    sig.changes.forEach(([t0, val], k) => {
      const t1 = k + 1 < sig.changes.length ? sig.changes[k + 1][0] : end;
      const x0 = X(t0), x1 = Math.max(X(t1), x0);
      const unknown = val === "x" || val === "z";
      if (sig.width === 1 && !unknown) {
        const y = val === "1" ? yTop : yBot;
        points.push(`${x0},${y}`, `${x1},${y}`);      // vertical edges come for free
      } else {
        if (sig.width === 1) points.push(`${x0},${yMid}`, `${x1},${yMid}`);
        svg.appendChild(el("rect", { class: unknown ? "w-unk" : "w-bus",
                                     x: x0, y: yTop, width: x1 - x0, height: SIG_H }));
        if (x1 - x0 > val.length * 7 + 6)
          svg.appendChild(el("text", { class: "w-val", x: (x0 + x1) / 2, y: yMid + 4 }, val));
      }
    });
    if (points.length) svg.appendChild(el("polyline", { class: "w-bit", points: points.join(" ") }));
  });

  box.appendChild(svg);
}

$("zoomIn").onclick  = () => { zoom = Math.min(zoom * 2, 64); drawWave(); };
$("zoomOut").onclick = () => { zoom = Math.max(zoom / 2, 1);  drawWave(); };
window.addEventListener("resize", drawWave);

syncAuto();
load();

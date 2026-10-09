"""Checks the web API together with the database."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

MUX_OK = "module mux2(input a, input b, input sel, output y); assign y = sel ? b : a; endmodule"

# A new problem: 1-bit inverter.
INV_STARTER = "module inv(input a, output y);\n\nendmodule\n"
INV_OK = "module inv(input a, output y); assign y = ~a; endmodule"
INV_WRONG = "module inv(input a, output y); assign y = a; endmodule"
INV_TB = r"""
module tb;
  reg a; wire y; integer errors;
  inv dut(.a(a), .y(y));
  initial begin
    errors = 0;
    a = 0; #1; if (y !== 1'b1) errors = errors + 1;
    a = 1; #1; if (y !== 1'b0) errors = errors + 1;
    if (errors == 0) $display("RESULT __TOKEN__ PASS");
    else $display("RESULT FAIL: %0d checks wrong", errors);
    $finish;
  end
endmodule
"""


def new_problem(**changes):
    body = {"title": "Inverter", "difficulty": "Easy", "statement": "y is the opposite of a.",
            "starter": INV_STARTER, "testbench": INV_TB, "solution": INV_OK}
    body.update(changes)
    return body


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:      # the `with` runs startup, which creates and seeds the tables
        yield c


def test_starter_problems_are_seeded_without_secrets(client):
    data = client.get("/api/problems").json()
    assert [p["id"] for p in data][:3] == ["mux2", "adder4", "counter"]
    assert all("testbench" not in p and "solution" not in p for p in data)


def test_submissions_are_saved_newest_first(client):
    client.post("/api/submit", json={"problem_id": "mux2", "code": "garbage"})
    client.post("/api/submit", json={"problem_id": "mux2", "code": MUX_OK})
    rows = client.get("/api/problems/mux2/submissions").json()
    assert [r["verdict"] for r in rows[:2]] == ["PASS", "COMPILE_ERROR"]
    assert rows[0]["code"] == MUX_OK


def test_valid_problem_is_stored_and_solvable(client):
    res = client.post("/api/problems", json=new_problem())
    assert res.status_code == 201 and res.json()["id"] == "inverter"
    assert "inverter" in [p["id"] for p in client.get("/api/problems").json()]
    verdict = client.post("/api/submit", json={"problem_id": "inverter", "code": INV_OK}).json()["verdict"]
    assert verdict == "PASS"
    # same title again gets a different short name instead of clashing
    assert client.post("/api/problems", json=new_problem()).json()["id"] == "inverter-2"


def test_problem_with_wrong_solution_is_rejected(client):
    res = client.post("/api/problems", json=new_problem(title="Bad one", solution=INV_WRONG))
    assert res.status_code == 400 and "did not pass" in res.json()["detail"]["message"]
    assert "bad-one" not in [p["id"] for p in client.get("/api/problems").json()]


def test_problem_whose_starter_passes_is_rejected(client):
    res = client.post("/api/problems", json=new_problem(title="Too easy", starter=INV_OK))
    assert res.status_code == 400


def test_testbench_without_token_is_rejected(client):
    tb = INV_TB.replace("__TOKEN__", "")
    assert client.post("/api/problems", json=new_problem(title="No token", testbench=tb)).status_code == 400


def test_unknown_problem_is_404(client):
    assert client.post("/api/submit", json={"problem_id": "nope", "code": "x"}).status_code == 404


def test_problem_without_testbench_gets_one_generated(client):
    body = new_problem(title="Auto inverter", testbench="")
    res = client.post("/api/problems", json=body)
    assert res.status_code == 201
    slug = res.json()["id"]
    assert client.post("/api/submit", json={"problem_id": slug, "code": INV_OK}).json()["verdict"] == "PASS"
    assert client.post("/api/submit", json={"problem_id": slug, "code": INV_WRONG}).json()["verdict"] == "FAIL"


def test_preview_shows_the_generated_testbench(client):
    res = client.post("/api/testbench/preview", json={"starter": INV_STARTER, "solution": INV_OK})
    assert res.status_code == 200 and "inv dut(" in res.json()["testbench"]


def test_unsupported_reference_explains_why(client):
    sol = "module inv #(parameter N = 2) (input [N-1:0] a, output y); assign y = ~a[0]; endmodule"
    res = client.post("/api/problems", json=new_problem(title="Param", testbench="", solution=sol))
    assert res.status_code == 400 and "plain numbers" in res.json()["detail"]["message"]


# ---------- editing and deleting ----------

def test_edit_keeps_the_short_name_and_rechecks(client):
    slug = client.post("/api/problems", json=new_problem(title="To edit", testbench="")).json()["id"]
    full = client.get(f"/api/problems/{slug}/edit").json()
    assert full["solution"] == INV_OK and full["auto_testbench"] is True

    res = client.put(f"/api/problems/{slug}", json=new_problem(title="Edited", difficulty="Hard", testbench=""))
    assert res.status_code == 200 and res.json()["id"] == slug and res.json()["title"] == "Edited"

    # an edit that breaks the problem is refused and changes nothing
    bad = client.put(f"/api/problems/{slug}", json=new_problem(title="Broken", testbench="", solution=INV_WRONG.replace("a;", "a")))
    assert bad.status_code == 400
    assert client.get(f"/api/problems/{slug}/edit").json()["title"] == "Edited"


def test_hand_written_testbench_is_reported_as_such(client):
    slug = client.post("/api/problems", json=new_problem(title="Manual tb")).json()["id"]
    full = client.get(f"/api/problems/{slug}/edit").json()
    assert full["auto_testbench"] is False and "RESULT __TOKEN__ PASS" in full["testbench"]


def test_delete_one_submission_then_clear_all(client):
    slug = client.post("/api/problems", json=new_problem(title="History", testbench="")).json()["id"]
    for code in (INV_OK, INV_WRONG, INV_OK):
        client.post("/api/submit", json={"problem_id": slug, "code": code})
    rows = client.get(f"/api/problems/{slug}/submissions").json()
    assert len(rows) == 3
    assert client.delete(f"/api/submissions/{rows[0]['id']}").status_code == 204
    assert client.delete(f"/api/submissions/{rows[0]['id']}").status_code == 404
    assert len(client.get(f"/api/problems/{slug}/submissions").json()) == 2
    assert client.delete(f"/api/problems/{slug}/submissions").status_code == 204
    assert client.get(f"/api/problems/{slug}/submissions").json() == []


def test_delete_problem_removes_it_and_its_submissions(client):
    slug = client.post("/api/problems", json=new_problem(title="Doomed", testbench="")).json()["id"]
    client.post("/api/submit", json={"problem_id": slug, "code": INV_OK})
    assert client.delete(f"/api/problems/{slug}").status_code == 204
    assert slug not in [p["id"] for p in client.get("/api/problems").json()]
    assert client.get(f"/api/problems/{slug}/submissions").status_code == 404
    assert client.delete(f"/api/problems/{slug}").status_code == 404

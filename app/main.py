"""Web API for the Verilog judge."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .autotb import PREFIX, AutoTBError, generate
from .runner import run_submission

STATIC = Path(__file__).parent / "static"
CODE = Field(min_length=1, max_length=50_000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()                   # runs once when the server starts
    yield


app = FastAPI(title="Verilog Judge", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")   # CSS, JavaScript, fonts


class Submission(BaseModel):
    problem_id: str
    code: str = Field(max_length=50_000)


class NewProblem(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    difficulty: Literal["Easy", "Medium", "Hard"]
    statement: str = Field(min_length=1, max_length=4000)
    starter: str = CODE
    solution: str = CODE
    testbench: str = Field(default="", max_length=50_000)   # empty = generate it automatically


class PreviewRequest(BaseModel):
    starter: str = CODE
    solution: str = CODE


def _reject(message: str, output: str = ""):
    raise HTTPException(status_code=400, detail={"message": message, "output": output})


def _generate(starter: str, solution: str) -> str:
    try:
        return generate(starter, solution)
    except AutoTBError as e:
        _reject(f"Could not build a testbench automatically: {e}")


def _problem_or_404(slug: str):
    problem = db.get_problem(slug)
    if problem is None:
        raise HTTPException(status_code=404, detail="Unknown problem")
    return problem


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/problems")
def list_problems():
    return db.list_problems()


def _checked_testbench(p: NewProblem) -> str:
    """A problem is only stored if it proves itself: the reference solution must
    pass the testbench, and the starter code must not. Returns the testbench to store."""
    testbench = p.testbench if p.testbench.strip() else _generate(p.starter, p.solution)
    if "__TOKEN__" not in testbench:
        _reject('The testbench must print "RESULT __TOKEN__ PASS" when every check passes.')
    check = run_submission(p.solution, testbench)
    if check["verdict"] != "PASS":
        _reject(f"The reference solution did not pass the testbench ({check['verdict']}).",
                check["output"])
    if run_submission(p.starter, testbench)["verdict"] == "PASS":
        _reject("The starter code already passes the testbench, so the tests check nothing.")
    return testbench


@app.post("/api/problems", status_code=201)
def create_problem(p: NewProblem):
    testbench = _checked_testbench(p)
    return db.add_problem(p.title.strip(), p.difficulty, p.statement.strip(),
                          p.starter, testbench, p.solution)


@app.get("/api/problems/{slug}/edit")
def problem_for_editing(slug: str):
    """Everything about a problem, including the hidden parts, for the edit form."""
    row = _problem_or_404(slug)
    return {**db.public(row), "solution": row.solution or "", "testbench": row.testbench,
            "auto_testbench": PREFIX in row.testbench}   # generated testbenches contain this marker


@app.put("/api/problems/{slug}")
def update_problem(slug: str, p: NewProblem):
    row = _problem_or_404(slug)
    testbench = _checked_testbench(p)                    # same checks as a new problem
    return db.update_problem(row.id, p.title.strip(), p.difficulty, p.statement.strip(),
                             p.starter, testbench, p.solution)


@app.delete("/api/problems/{slug}", status_code=204)
def delete_problem(slug: str):
    db.delete_problem(_problem_or_404(slug).id)


@app.delete("/api/problems/{slug}/submissions", status_code=204)
def clear_history(slug: str):
    db.clear_submissions(_problem_or_404(slug).id)


@app.delete("/api/submissions/{submission_id}", status_code=204)
def delete_submission(submission_id: int):
    if not db.delete_submission(submission_id):
        raise HTTPException(status_code=404, detail="Unknown submission")


@app.post("/api/testbench/preview")
def preview_testbench(req: PreviewRequest):
    """Shows the author the testbench that would be generated, without saving anything."""
    return {"testbench": _generate(req.starter, req.solution)}


# A plain `def` endpoint runs in FastAPI's thread pool, so a slow simulation
# does not block the rest of the server.
@app.post("/api/submit")
def submit(sub: Submission):
    problem = _problem_or_404(sub.problem_id)
    result = run_submission(sub.code, problem.testbench)
    db.add_submission(problem.id, sub.code, result["verdict"], result["output"])
    return result


@app.get("/api/problems/{slug}/submissions")
def history(slug: str):
    return db.list_submissions(_problem_or_404(slug).id)

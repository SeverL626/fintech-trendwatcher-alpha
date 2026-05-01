import subprocess
import sys

from flask import Flask, jsonify

try:
    from back.init_db import PROJECT_ROOT, DB_PATH
except ModuleNotFoundError:
    from init_db import PROJECT_ROOT, DB_PATH


app = Flask(__name__)
app.config["DB_PATH"] = DB_PATH


@app.route("/")
def hello():
    return jsonify({
        "ok": True,
        "message": "Welcom to main page of the Alfa-HackItOn backend!",
        "routes": ["/parser", "/parser/source/<id>", "/tests/all", "/tests/db"],
    })


@app.route("/parser")
def run_parser():
    return jsonify({
        "ok": True,
        "parser": run_parser_from_db(app.config["DB_PATH"]),
    })


@app.route("/parser/source/<int:source_id>")
def run_parser_for_source(source_id):
    result = run_parser_for_source_id(app.config["DB_PATH"], source_id)
    return jsonify({
        "ok": "error" not in result,
        "parser": result,
    }), 200 if "error" not in result else 404


@app.route("/tests/all")
def run_all_tests():
    return run_tests(["discover", "-s", "tests"])


@app.route("/tests/db")
def run_db_tests():
    return run_tests(["tests.test_database"])


def run_tests(test_args):
    result = subprocess.run(
        [sys.executable, "-m", "unittest", *test_args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    return jsonify({
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }), 200 if result.returncode == 0 else 500


def run_parser_from_db(db_path):
    try:
        from back.parser import run_parser_from_db as parser_runner
    except ModuleNotFoundError:
        from parser import run_parser_from_db as parser_runner

    return parser_runner(db_path)


def run_parser_for_source_id(db_path, source_id):
    try:
        from back.parser import run_parser_for_source_id as parser_runner
    except ModuleNotFoundError:
        from parser import run_parser_for_source_id as parser_runner

    return parser_runner(db_path, source_id)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

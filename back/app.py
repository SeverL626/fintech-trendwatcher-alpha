from flask import Flask, jsonify

try:
    from back.init_db import DB_PATH
except ModuleNotFoundError:
    from init_db import DB_PATH


app = Flask(__name__)
app.config["DB_PATH"] = DB_PATH
app.json.ensure_ascii = False
app.json.compact = False


@app.route("/")
def hello():
    return jsonify({
        "ok": True,
        "message": "Welcom to main page of the Alfa-HackItOn backend!",
        "routes": ["/parser"],
    })


@app.route("/parser")
def run_parser():
    return jsonify({
        "ok": True,
        "parser": run_parser_from_db(app.config["DB_PATH"]),
    })


def run_parser_from_db(db_path):
    try:
        from back.parser import run_parser_from_db as parser_runner
    except ModuleNotFoundError:
        from parser import run_parser_from_db as parser_runner

    return parser_runner(db_path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

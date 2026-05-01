import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import back.app as app_module  # noqa: E402


app = app_module.app


class AppRoutesTest(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_root_route_works(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["routes"], ["/parser", "/parser/source/<id>", "/tests/all", "/tests/db"])

    def test_parser_route_runs_parser(self):
        original = app_module.run_parser_from_db
        app_module.run_parser_from_db = lambda _db_path: {
            "sources": 1,
            "created": 2,
            "skipped": 0,
            "results": [],
        }
        try:
            response = self.client.get("/parser")
        finally:
            app_module.run_parser_from_db = original

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["parser"]["created"], 2)

    def test_parser_source_route_runs_single_source_parser(self):
        original = app_module.run_parser_for_source_id
        app_module.run_parser_for_source_id = lambda _db_path, source_id: {
            "sources": 1,
            "created": 1,
            "skipped": 0,
            "summary": [f"source {source_id}: найдено 1"],
            "results": [],
        }
        try:
            response = self.client.get("/parser/source/9")
        finally:
            app_module.run_parser_for_source_id = original

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["parser"]["created"], 1)
        self.assertIn("source 9", payload["parser"]["summary"][0])

    def test_test_routes_run_unittest(self):
        response = self.client.get("/tests/db")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("OK", payload["stderr"])

    def test_db_and_sources_routes_are_removed(self):
        self.assertEqual(self.client.get("/sources").status_code, 404)
        self.assertEqual(self.client.post("/sources", json={}).status_code, 404)
        self.assertEqual(self.client.get("/root/db/").status_code, 404)
        self.assertEqual(self.client.get("/root/db/tables").status_code, 404)
        self.assertEqual(self.client.get("/root/db/sources").status_code, 404)
        self.assertEqual(self.client.get("/root/db/tests").status_code, 404)
        self.assertEqual(self.client.get("/roor/db/tests").status_code, 404)


if __name__ == "__main__":
    unittest.main()

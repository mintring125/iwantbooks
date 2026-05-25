import unittest
from unittest.mock import patch

import requests

import app as app_module


class DummySearchResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"item": []}


class SearchBooksTest(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_aladin_search_uses_https_endpoint(self):
        with patch.object(app_module.requests, "get", return_value=DummySearchResponse()) as mock_get:
            response = self.client.get("/api/search?q=test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"books": []})
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://www.aladin.co.kr/ttb/api/ItemSearch.aspx",
        )

    def test_aladin_search_hides_upstream_exception_details(self):
        with patch.object(
            app_module.requests,
            "get",
            side_effect=requests.exceptions.ConnectTimeout(
                "HTTPConnectionPool(host='www.aladin.co.kr', port=80): timed out"
            ),
        ):
            response = self.client.get("/api/search?q=test")

        data = response.get_json()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(data["books"], [])
        self.assertIn("알라딘", data["error"])
        self.assertNotIn("HTTPConnectionPool", data["error"])
        self.assertNotIn("ttbkey", data["error"])


if __name__ == "__main__":
    unittest.main()

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
        self.api_key_patch = patch.object(app_module, "ALADIN_API_KEY", "test-key")
        self.api_key_patch.start()
        app_module.bestseller_cache["items"] = []
        app_module.bestseller_cache["expires_at"] = 0.0

    def tearDown(self):
        self.api_key_patch.stop()

    def test_aladin_search_uses_https_endpoint(self):
        with patch.object(app_module.requests, "get", return_value=DummySearchResponse()) as mock_get:
            response = self.client.get("/api/search?q=test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"books": []})
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://aladin.co.kr/ttb/api/ItemSearch.aspx",
        )

    def test_aladin_search_hides_upstream_exception_details(self):
        with patch.object(
            app_module.requests,
            "get",
            side_effect=requests.exceptions.ConnectTimeout(
                "HTTPConnectionPool(host='aladin.co.kr', port=443): timed out"
            ),
        ):
            response = self.client.get("/api/search?q=test")

        data = response.get_json()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(data["books"], [])
        self.assertIn("알라딘", data["error"])
        self.assertNotIn("HTTPConnectionPool", data["error"])
        self.assertNotIn("ttbkey", data["error"])

    def test_children_bestsellers_use_children_category_and_fifty_results(self):
        with patch.object(app_module.requests, "get", return_value=DummySearchResponse()) as mock_get:
            response = self.client.get("/api/bestsellers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"books": []})
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://www.aladin.co.kr/ttb/api/ItemList.aspx",
        )
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["QueryType"], "Bestseller")
        self.assertEqual(params["CategoryId"], 1108)
        self.assertEqual(params["MaxResults"], 50)

    def test_catalog_rows_support_second_row_dls_header(self):
        rows = [
            ["황지중앙초등학교도서관 도서목록"],
            ["", "번호", "등록번호", "서명(자료명)", "저자"],
            ["", 1, "EM0001", "아낌없이 주는 나무", "쉘 실버스타인"],
            ["", 2, "EM0002", "긴긴밤", "루리"],
        ]

        self.assertEqual(
            app_module.extract_catalog_rows(rows),
            [
                {"title": "아낌없이 주는 나무", "isbn": ""},
                {"title": "긴긴밤", "isbn": ""},
            ],
        )


if __name__ == "__main__":
    unittest.main()

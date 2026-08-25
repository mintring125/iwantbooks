import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import sleep
from unittest.mock import patch

import requests

import app as app_module


class DummySearchResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"item": []}


class DummyBestsellerResponse(DummySearchResponse):
    def json(self):
        return {"item": [{"title": "긴긴밤", "author": "루리"}]}


class DummyMixedSearchResponse(DummySearchResponse):
    def json(self):
        return {
            "item": [
                {"title": "마법천자문 세트 - 전 5권"},
                {"title": "흔한남매 1~10 전권"},
                {"title": "[하나북 세트] 긴긴밤+5번 레인"},
                {"title": "[하나북] 나나 올리브에게+긴긴밤"},
                {"title": "문학동네 보름달문고 베스트 5종 (긴긴밤 포함)"},
                {"title": "마법천자문 1 - 불어라 바람 풍! (세트 낱권)"},
                {"title": "세트로 배우는 어린이 과학", "author": "김과학"},
                {"title": "긴긴밤", "author": "루리"},
            ]
        }


class SearchBooksTest(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.api_key_patch = patch.object(app_module, "ALADIN_API_KEY", "test-key")
        self.api_key_patch.start()
        app_module.bestseller_cache["items"] = []
        app_module.bestseller_cache["expires_at"] = 0.0
        app_module.bestseller_cache["retry_after"] = 0.0
        for cache in app_module.grade_popular_caches.values():
            cache["items"] = []
            cache["expires_at"] = 0.0
            cache["retry_after"] = 0.0
        app_module.invalidate_catalog_cache()
        app_module.aladin_backoff["until"] = 0.0

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

    def test_repeated_search_uses_memory_cache(self):
        with patch.object(
            app_module.requests,
            "get",
            return_value=DummySearchResponse(),
        ) as mock_get:
            first_response = self.client.get("/api/search?q=긴긴밤")
            second_response = self.client.get("/api/search?q=%20긴긴밤%20")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(mock_get.call_count, 1)

    def test_simultaneous_identical_searches_share_one_upstream_request(self):
        def slow_search(*_args, **_kwargs):
            sleep(0.05)
            return []

        def search_once():
            with app_module.app.test_client() as client:
                return client.get("/api/search?q=긴긴밤").status_code

        with (
            patch.object(
                app_module,
                "request_aladin_items",
                side_effect=slow_search,
            ) as mock_request,
            patch.object(app_module, "serialize_aladin_books", return_value=[]),
        ):
            with ThreadPoolExecutor(max_workers=32) as executor:
                statuses = list(executor.map(lambda _index: search_once(), range(100)))

        self.assertEqual(statuses, [200] * 100)
        self.assertEqual(mock_request.call_count, 1)

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

    def test_aladin_search_excludes_set_products(self):
        with patch.object(
            app_module.requests,
            "get",
            return_value=DummyMixedSearchResponse(),
        ):
            response = self.client.get("/api/search?q=어린이책")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [book["title"] for book in response.get_json()["books"]],
            [
                "마법천자문 1 - 불어라 바람 풍! (세트 낱권)",
                "세트로 배우는 어린이 과학",
                "긴긴밤",
            ],
        )

    def test_children_bestsellers_use_children_category_and_fifty_results(self):
        with (
            patch.object(
                app_module,
                "load_persisted_bestsellers",
                return_value=([], None),
            ),
            patch.object(
                app_module.requests,
                "get",
                return_value=DummyBestsellerResponse(),
            ) as mock_get,
        ):
            response = self.client.get("/api/bestsellers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["books"][0]["title"], "긴긴밤")
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://aladin.co.kr/ttb/api/ItemList.aspx",
        )
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["QueryType"], "Bestseller")
        self.assertEqual(params["CategoryId"], 1108)
        self.assertEqual(params["MaxResults"], 50)

    def test_grade_popular_books_use_matching_aladin_category(self):
        with (
            patch.object(
                app_module,
                "load_persisted_grade_popular",
                return_value=([], None),
            ),
            patch.object(app_module, "save_persisted_grade_popular"),
            patch.object(
                app_module.requests,
                "get",
                return_value=DummyBestsellerResponse(),
            ) as mock_get,
        ):
            first_response = self.client.get("/api/popular-books?grade=1")
            second_response = self.client.get("/api/popular-books?grade=2")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.get_json()["gradeBand"], "1·2학년")
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(mock_get.call_count, 1)
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["QueryType"], "Bestseller")
        self.assertEqual(params["CategoryId"], 48803)
        self.assertEqual(params["MaxResults"], 30)

    def test_grade_popular_category_mapping_covers_all_school_grades(self):
        self.assertEqual(
            {
                grade: app_module.GRADE_POPULAR_GROUPS[group_key]["category_id"]
                for grade, group_key in app_module.GRADE_TO_POPULAR_GROUP.items()
            },
            {
                "1": 48803,
                "2": 48803,
                "3": 48804,
                "4": 48804,
                "5": 48805,
                "6": 48805,
            },
        )

    def test_grade_popular_books_reject_invalid_grade(self):
        with patch.object(app_module.requests, "get") as mock_get:
            response = self.client.get("/api/popular-books?grade=7")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["books"], [])
        mock_get.assert_not_called()

    def test_recommendation_lists_use_switchable_tabs_and_hide_catalog_upload(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="bestsellerTab"', html)
        self.assertIn('id="gradePopularTab"', html)
        self.assertIn('id="gradePopularView" class="recommendation-group grade-popular-group hidden"', html)
        self.assertIn('class="admin-catalog-box hidden"', html)

    def test_recommendation_export_deduplicates_counts_and_sorts_books(self):
        submissions = [
            {
                "grade": "3",
                "classNum": "1",
                "books": [
                    {"title": "긴긴밤", "author": "루리", "publisher": "문학동네", "price": 11500},
                    {"title": "긴 긴밤", "author": "루리", "publisher": "문학동네", "price": 11500},
                    {"title": "체리새우: 비밀글입니다", "author": "황영미", "price": 11500},
                ],
            },
            {
                "grade": "3",
                "classNum": "1",
                "books": [
                    {"title": "긴긴밤", "author": "루리", "publisher": "문학동네", "price": 11500},
                    {"title": "마법천자문 1", "author": "스튜디오 시리얼", "price": 14000},
                ],
            },
            {
                "grade": "3",
                "classNum": "1",
                "books": [
                    {"title": "긴긴밤", "author": "루리", "publisher": "문학동네", "price": 11500},
                    {"title": "체리새우 비밀글입니다", "author": "황영미", "price": 11500},
                ],
            },
        ]

        aggregated = app_module.aggregate_recommended_books(submissions)
        self.assertEqual(
            [(book["title"], book["recommendationCount"]) for book in aggregated],
            [("긴긴밤", 3), ("체리새우: 비밀글입니다", 2), ("마법천자문 1", 1)],
        )

        worksheet = app_module.build_admin_workbook(submissions).active
        self.assertEqual(worksheet["C2"].value, "희망 인원")
        self.assertEqual(worksheet["B3"].value, "긴긴밤")
        self.assertEqual(worksheet["C3"].value, 3)
        self.assertEqual(worksheet["B4"].value, "체리새우: 비밀글입니다")
        self.assertEqual(worksheet["C4"].value, 2)
        self.assertEqual(worksheet["F3"].value, 1)

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

    def test_title_match_avoids_unrelated_partial_titles(self):
        titles = {app_module.normalize_title("아낌없이 주는 나무")}

        self.assertTrue(
            app_module.is_catalog_duplicate(
                "아낌없이 주는 나무 (양장)",
                "",
                titles,
                set(),
            )
        )
        self.assertFalse(
            app_module.is_catalog_duplicate(
                "아낌없이 주는 나무는 없다 - 도시의 나무와 함께 살아가는 법",
                "",
                titles,
                set(),
            )
        )

    def test_series_volume_matches_long_subtitle_without_matching_other_volumes(self):
        titles = {
            app_module.normalize_title(f"환생학교 요괴반. {volume}")
            for volume in range(1, 5)
        }

        for volume in range(1, 5):
            self.assertTrue(
                app_module.is_catalog_duplicate(
                    f"환생학교 요괴반 {volume} - 웃소의 판타지 미션 코믹북",
                    "",
                    titles,
                    set(),
                )
            )

        for volume in (5, 8, 10):
            self.assertFalse(
                app_module.is_catalog_duplicate(
                    f"환생학교 요괴반 {volume} - 웃소의 판타지 미션 코믹북",
                    "",
                    titles,
                    set(),
                )
            )

    def test_bestsellers_use_fresh_persisted_cache_without_api_call(self):
        cached_item = {
            "title": "긴긴밤",
            "author": "루리",
            "isbn13": "9788954677158",
        }
        with (
            patch.object(
                app_module,
                "load_persisted_bestsellers",
                return_value=([cached_item], datetime.now()),
            ),
            patch.object(app_module.requests, "get") as mock_get,
        ):
            response = self.client.get("/api/bestsellers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["books"][0]["title"], "긴긴밤")
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()

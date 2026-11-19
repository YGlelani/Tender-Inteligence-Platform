"""Category points come from tender-ml when it answers, and from the keyword rule when it does not."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

import ml_categories  # noqa: E402
from matcher import rank_tenders, score_tender  # noqa: E402

PROFILE = {
    "industries": ["Information technology"],
    "services": ["laptop supply"],
    "service_areas": [],
    "description": "We supply laptops and servers.",
}
TENDER = {"tender_number": "RFQ-1", "title": "Supply of laptops", "category_name": "Supplies: Computer Equipment"}


class ScoreTenderTest(unittest.TestCase):
    def test_ml_category_match_earns_fifteen_points_with_a_reason(self):
        tender = dict(TENDER, category_name="Services: General")  # no keyword overlap with the services
        with_ml, reasons = score_tender(tender, PROFILE, {"RFQ-1": "Supplies: Computer Equipment"})
        without_ml, _ = score_tender(tender, PROFILE, None)

        self.assertEqual(with_ml - without_ml, 15)
        self.assertIn("Category matches your business (ML: Supplies: Computer Equipment)", reasons)

    def test_keyword_rule_still_applies_when_the_ml_finds_no_shared_category(self):
        tender = dict(TENDER, category_name="Laptop supply and repairs")
        for ml_matches in (None, {}):
            score, reasons = score_tender(tender, PROFILE, ml_matches)

            self.assertTrue(any(reason.startswith("Category aligned with service:") for reason in reasons))
            self.assertEqual(score, score_tender(tender, PROFILE)[0])

    def test_the_ml_never_lowers_a_score(self):
        for category in ("Laptop supply and repairs", "Services: General", None):
            tender = dict(TENDER, category_name=category)
            for ml_matches in ({}, {"RFQ-1": "Supplies: Computer Equipment"}):
                self.assertGreaterEqual(score_tender(tender, PROFILE, ml_matches)[0], score_tender(tender, PROFILE)[0])

    def test_rank_tenders_passes_the_ml_answer_to_every_tender(self):
        ranked = rank_tenders([TENDER], PROFILE, min_score=0, ml_matches={"RFQ-1": "Supplies: Computer Equipment"})

        self.assertIn("Category matches your business (ML: Supplies: Computer Equipment)", ranked[0]["reasons"])


class SharedCategoriesTest(unittest.TestCase):
    def test_request_body_stays_inside_tender_ml_limits(self):
        profile = dict(PROFILE, services=["x" * 5000] * 300)
        body = ml_categories.request_body(profile, [TENDER, {"title": "no key"}])

        self.assertEqual(len(body["company"]["services"]), 200)
        self.assertEqual(len(body["company"]["services"][0]), 1000)
        self.assertEqual([t["id"] for t in body["tenders"]], ["RFQ-1"])
        self.assertEqual(body["tenders"][0]["category"], "Supplies: Computer Equipment")

    def test_unreachable_service_returns_none_so_the_keyword_rule_is_used(self):
        client = mock.AsyncMock()
        client.post.side_effect = httpx.ConnectError("tender-ml is down")
        client_factory = mock.MagicMock()
        client_factory.return_value.__aenter__.return_value = client

        with mock.patch.object(ml_categories.httpx, "AsyncClient", client_factory):
            result = asyncio.run(ml_categories.shared_categories(PROFILE, [TENDER]))

        self.assertIsNone(result)

    def test_no_tenders_needs_no_request(self):
        self.assertEqual(asyncio.run(ml_categories.shared_categories(PROFILE, [])), {})


if __name__ == "__main__":
    unittest.main()

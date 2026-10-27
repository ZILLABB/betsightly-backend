"""Network-free validation for private NBA-only scheduled settlement trigger."""
import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request

from scripts.nba_stage_settlement_ping import STAGING_URL, VerificationFailure, invoke

TOKEN = "synthetic-nba-staging-token" + "x" * 50


def payload(**updates):
    return {
        "status": "settled_and_verified", "research_only": True,
        "not_bookable": True, "provider_status": "ok", "failed_dates": [],
        "archive_digest": "a" * 64, "new_finals": 9,
        "new_settlements": {"moneyline": 9, "original_score": 9,
                            "advanced_score": 9},
        **updates,
    }


class Response:
    status = 200

    def __init__(self, value):
        self.data = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size):
        return self.data[:size]


class PrivateScheduledSettlements(unittest.TestCase):
    def test_exact_staging_endpoint_and_authorization_only(self):
        def fetch(request, timeout):
            self.assertIsInstance(request, Request)
            self.assertEqual(request.full_url, STAGING_URL)
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(
                request.get_header("X-betsightly-nba-settle-token"), TOKEN)
            self.assertGreater(timeout, 100)
            return Response(payload())
        self.assertEqual(invoke(TOKEN, opener=fetch)["new_model_grades"], 27)

    def test_no_token_no_network_request(self):
        def forbidden(*args, **kwargs):
            self.fail("Tokenless workflow must never call staging.")
        for token in ("", "too-short", "x" * 32 + "\\n"):
            with self.subTest(token_length=len(token)):
                with self.assertRaisesRegex(VerificationFailure, "NOT_CONFIGURED"):
                    invoke(token, opener=forbidden)

    def test_partial_or_unverified_finals_never_pass(self):
        bad = [
            payload(provider_status="partial"),
            payload(failed_dates=[{"date": "2026-10-26"}]),
            payload(archive_digest="not-signed"),
            payload(research_only=False),
            payload(not_bookable=False),
            payload(status="provider_failed"),
            payload(new_settlements={"moneyline": 9}),
            payload(new_finals=True),
        ]
        for value in bad:
            with self.subTest(result=value.get("status")):
                with self.assertRaises(VerificationFailure):
                    invoke(TOKEN, opener=lambda request, timeout: Response(value))

    def test_retry_only_transient_provider_response(self):
        attempts = []
        def fetch(request, timeout):
            attempts.append(True)
            if len(attempts) == 1:
                raise HTTPError(STAGING_URL, 503, "unavailable", {}, None)
            return Response(payload(status="no_new_verified_finals",
                                    new_finals=0))
        output = invoke(TOKEN, opener=fetch,
                        sleeper=lambda s: self.assertEqual(s, 18))
        self.assertEqual(output["new_finals"], 0)
        self.assertEqual(len(attempts), 2)

    def test_rejects_authorization_error_without_retry(self):
        attempts = []
        def fetch(request, timeout):
            attempts.append(True)
            raise HTTPError(STAGING_URL, 404, "forbidden", {}, None)
        with self.assertRaisesRegex(VerificationFailure, "HTTP_404"):
            invoke(TOKEN, opener=fetch,
                   sleeper=lambda s: self.fail("No authorization retry"))
        self.assertEqual(len(attempts), 1)

    def test_network_failure_does_not_invent_outcome(self):
        attempts = []
        def fetch(request, timeout):
            attempts.append(True)
            raise URLError("network error")
        with self.assertRaisesRegex(VerificationFailure, "TRANSPORT_UNAVAILABLE"):
            invoke(TOKEN, opener=fetch, sleeper=lambda _: None)
        self.assertEqual(len(attempts), 2)

    def test_healthy_idle(self):
        empty = payload(
            status="idle", provider_status="idle", new_finals=0,
            new_settlements={"moneyline": 0, "original_score": 0, "advanced_score": 0})
        output = invoke(TOKEN, opener=lambda request, timeout: Response(empty))
        self.assertEqual(output["status"], "idle")


if __name__ == "__main__":
    unittest.main()

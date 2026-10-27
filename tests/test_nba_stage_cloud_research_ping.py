"""Network-free regression tests for isolated NBA cloud research jobs."""
import unittest
from urllib.error import HTTPError, URLError
import json

from scripts.nba_stage_cloud_research_ping import (
    HOST, JOBS, PrivateStageFailure, RejectRedirect, invoke, verified_receipt
)

TOKEN = "test-only-private-research-token-" + "q"*70


class Reply:
    status = 200

    def __init__(self, value):
        self.encoded = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, maximum):
        return self.encoded[:maximum]


class NbaCloudResearchContractTests(unittest.TestCase):
    def test_forecast_bounded_original_models(self):
        result={
            "status":"archived_before_tipoff", "research_only":True,
            "not_bookable":True, "archive_digest":"a"*64,
            "new_forecasts":{"moneyline":4,"original_score":4,"advanced_score":0},
            "advanced_model_recomputed":False,
        }
        self.assertEqual(verified_receipt("forecast",result)["new_forecasts"],8)
        self.assertEqual(verified_receipt("forecast",{
            **result, "status":"no_upcoming_eligible_source_window",
            "new_forecasts":{},
        })["new_forecasts"],0)
        for update in [
            {"status":"source_not_fresh"}, {"not_bookable":False},
            {"advanced_model_recomputed":True},
            {"archive_digest":"wrong"}, {"new_forecasts":{"moneyline":True}},
        ]:
            with self.subTest(update=update):
                with self.assertRaises(PrivateStageFailure):
                    verified_receipt("forecast",{**result,**update})

    def test_bookmaker_receipt_no_public_or_calibrated_betting_outputs(self):
        result={
            "status":"saved","research_only":True,"not_bookable":True,
            "archive_unchanged":True,"digest":"b"*64,
            "calibrated_betting_edge":False,"public_publishing_enabled":False,
            "fixture_matches":9,
        }
        self.assertEqual(verified_receipt("market",result)["fixture_matches"],9)
        for update in [
            {"status":"partial"}, {"research_only":False},
            {"archive_unchanged":False}, {"digest":"oops"},
            {"calibrated_betting_edge":True},
            {"public_publishing_enabled":True}, {"fixture_matches":True},
        ]:
            with self.subTest(update=update):
                with self.assertRaises(PrivateStageFailure):
                    verified_receipt("market",{**result,**update})

    def test_only_staging_url_and_approved_header(self):
        for kind,(path,header,_) in JOBS.items():
            def fetch(request, timeout):
                self.assertEqual(request.full_url, HOST+path)
                self.assertEqual(request.get_method(),"POST")
                self.assertEqual(request.get_header(header.capitalize()),TOKEN)
                self.assertGreater(timeout,100)
                if kind=="forecast":
                    return Reply({"status":"no_new_eligible_forecasts",
                        "research_only":True,"not_bookable":True,
                        "archive_digest":"c"*64,"new_forecasts":{}})
                return Reply({"status":"already_saved","research_only":True,
                    "not_bookable":True,"archive_unchanged":True,
                    "digest":"d"*64,"calibrated_betting_edge":False,
                    "public_publishing_enabled":False,"fixture_matches":0})
            self.assertEqual(invoke(kind,TOKEN,opener=fetch)["kind"],kind)

    def test_no_missing_token_no_unknown_endpoint(self):
        for kind in JOBS:
            for token in ["","short","a"*55+"\n"]:
                with self.assertRaises(PrivateStageFailure):
                    invoke(kind,token,opener=lambda *a,**k:self.fail("No request"))
        with self.assertRaises(PrivateStageFailure):
            invoke("football",TOKEN)

    def test_reject_external_redirect(self):
        with self.assertRaisesRegex(PrivateStageFailure, "REDIRECT"):
            RejectRedirect().redirect_request(
                None,None,302,"moved",{},"https://example.com/exfiltrate",
            )

    def test_server_error_retries_once_without_claiming_result(self):
        calls=[]
        def fetch(request,timeout):
            calls.append(1)
            raise HTTPError(request.full_url,503,"provider offline",{},None)
        with self.assertRaisesRegex(PrivateStageFailure, "HTTP_503"):
            invoke("forecast",TOKEN,opener=fetch,sleeper=lambda _:None)
        self.assertEqual(len(calls),2)

    def test_network_error_retries_and_fails_closed(self):
        calls=[]
        def fetch(request,timeout):
            calls.append(1)
            raise URLError("network fail")
        with self.assertRaisesRegex(PrivateStageFailure,"NETWORK_UNAVAILABLE"):
            invoke("market",TOKEN,opener=fetch,sleeper=lambda _:None)
        self.assertEqual(len(calls),2)


if __name__=="__main__":
    unittest.main()

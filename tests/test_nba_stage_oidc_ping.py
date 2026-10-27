"""Pure offline tests for short-lived GitHub OIDC NBA scheduler client."""
import json
import unittest
from urllib.error import HTTPError

from scripts.nba_stage_oidc_ping import (
    AUDIENCE, ENDPOINT, JobFailure, github_identity, invoke, validate_receipt
)

JWT = "test-signed-opaque-oidc-jwt-" + "x" * 150
GITHUB_ENV = {
    "ACTIONS_ID_TOKEN_REQUEST_URL":
        "https://pipelines.actions.githubusercontent.com/identity?token=opaque",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runner-request-identity-token-" + "s" * 80,
}


class Reply:
    status = 200
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit):
        return self.body[:limit]


class TestSignedNbaCron(unittest.TestCase):
    def test_github_issuer_request_uses_fixed_audience_and_runner_token(self):
        def opener(request, timeout):
            self.assertIn("pipelines.actions.githubusercontent.com", request.full_url)
            self.assertIn("audience=" + AUDIENCE, request.full_url)
            self.assertEqual(request.get_header("Authorization"),
                             "bearer " + GITHUB_ENV["ACTIONS_ID_TOKEN_REQUEST_TOKEN"])
            return Reply({"value": JWT})
        self.assertEqual(github_identity(environ=GITHUB_ENV, opener=opener), JWT)

    def test_deny_unsafe_oidc_url_or_absent_identity(self):
        for url in (
            "http://pipelines.actions.githubusercontent.com/id",
            "https://evil.example/id",
            "https://pipelines.actions.githubusercontent.com.evil.example/id",
        ):
            with self.subTest(url=url), self.assertRaises(JobFailure):
                github_identity(environ={**GITHUB_ENV,
                    "ACTIONS_ID_TOKEN_REQUEST_URL":url},opener=lambda *a,**kw: self.fail("network"))
        with self.assertRaises(JobFailure):
            github_identity(environ={}, opener=lambda *a,**kw:self.fail("network"))

    def test_stage_receipt_only_accepts_research_and_exact_job(self):
        for job,status in (
            ("settlement","settled_and_verified"), ("settlement","idle"),
            ("forecast","archived_before_tipoff"), ("market","saved"),
        ):
            result = validate_receipt(job, {
                "job":job,"status":status,"research_only":True,"not_bookable":True
            })
            self.assertEqual(result["job"],job)
        for values in (
            {"job":"football"}, {"research_only":False}, {"not_bookable":False},
            {"status":"source_not_fresh"}, {"failed_dates":[{"date":"bad"}]},
        ):
            with self.assertRaises(JobFailure):
                validate_receipt("settlement",{
                    "job":"settlement","status":"settled_and_verified",
                    "research_only":True,"not_bookable":True,**values
                })

    def test_post_fixed_stage_endpoint_using_only_ephemeral_jwt(self):
        requests=[]
        def opener(request, timeout):
            requests.append(request)
            if "pipelines.actions.githubusercontent.com" in request.full_url:
                return Reply({"value": JWT})
            self.assertEqual(request.full_url, ENDPOINT)
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + JWT)
            self.assertEqual(json.loads(request.data), {"job":"market"})
            return Reply({"job":"market","status":"saved","research_only":True,
                          "not_bookable":True})
        self.assertEqual(
            invoke("market",environ=GITHUB_ENV,opener=opener)["status"],"saved"
        )
        self.assertEqual(len(requests),2)

    def test_provider_failure_does_not_claim_settlement(self):
        def opener(request,timeout):
            if "pipelines.actions.githubusercontent.com" in request.full_url:
                return Reply({"value": JWT})
            raise HTTPError(request.full_url,503,"retryable",{},None)
        with self.assertRaisesRegex(JobFailure,"HTTP_503"):
            invoke("settlement",environ=GITHUB_ENV,opener=opener,
                   sleeper=lambda _:None)


if __name__=="__main__":
    unittest.main()

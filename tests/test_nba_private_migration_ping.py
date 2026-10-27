"""No-token, no-network contract tests for migration runner."""
import unittest
from scripts.nba_stage_migration_ping import (
    invoke, JobFailure, MIGRATION_ENDPOINT
)

class Reply:
    status=200
    def __init__(self, payload):
        import json
        self.value=json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self,lim): return self.value[:lim]

class Tests(unittest.TestCase):
    def test_probe_has_fixed_url_and_only_mode(self):
        def open_request(req, *, timeout):
            import json
            self.assertEqual(req.full_url, MIGRATION_ENDPOINT)
            self.assertEqual(req.get_method(),"POST")
            self.assertEqual(req.get_header("Authorization"),"Bearer "+("signed-jwt-"+"x"*120))
            self.assertEqual(json.loads(req.data),{"mode":"probe"})
            return Reply({"job":"migration","status":"target_empty",
                          "source_unchanged":True,"research_only":True,
                          "not_bookable":True,"schema":"nba_research"})
        answer=invoke("probe",identity_provider=lambda:"signed-jwt-"+"x"*120,
                      opener=open_request)
        self.assertEqual(answer["status"],"target_empty")

    def test_cannot_claim_restore_without_signed_receipt(self):
        for response in (
            {"status":"target_empty"},
            {"status":"restored_and_verified", "job":"migration",
             "research_only":True,"not_bookable":True,
             "source_unchanged":False},
            {"status":"restored_and_verified", "job":"other",
             "research_only":True,"not_bookable":True,
             "source_unchanged":True},
        ):
            with self.subTest(response=response),self.assertRaises(JobFailure):
                invoke("restore",identity_provider=lambda:"opaque",
                       opener=lambda *a,**kw:Reply(response))

    def test_only_explicit_modes_allowed_without_network(self):
        for mode in ("", "cutover", "delete", "postgres", "backup"):
            with self.subTest(mode=mode),self.assertRaises(JobFailure):
                invoke(mode, identity_provider=lambda:self.fail("token requested"))

if __name__=="__main__":
    unittest.main()

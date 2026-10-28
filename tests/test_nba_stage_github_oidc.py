"""Offline proof that forged identities cannot invoke private NBA jobs."""
import base64
import time
import unittest

from jose import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, NoEncryption,
)
from basketball.research_oidc import (
    AUDIENCE, ISSUER, REPOSITORY, BRANCH, REPOSITORY_ID,
    WORKFLOWS, verify_github_job,
)

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA = KEY.public_key().public_numbers()
def b64(n):
    return base64.urlsafe_b64encode(
        n.to_bytes((n.bit_length() + 7) // 8, "big")
    ).rstrip(b"=").decode("ascii")
JWK = {"kid": "signed-test-key", "kty": "RSA", "use": "sig", "alg": "RS256",
       "n": b64(RSA.n), "e": b64(RSA.e)}
PRIVATE = KEY.private_bytes(
    Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
).decode("ascii")
NOW = int(time.time())


def signed(job="settlement", **changes):
    claims = {
        "iss": ISSUER, "aud": AUDIENCE,
        "sub": "repo:" + REPOSITORY + ":ref:" + BRANCH,
        "iat": NOW, "exp": NOW + 300,
        "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "ref": BRANCH, "workflow_ref": WORKFLOWS[job],
        "event_name": "schedule",
    }
    claims.update(changes)
    return jwt.encode(claims, PRIVATE, algorithm="RS256",
                      headers={"kid": "signed-test-key"})


def verify(token, job="settlement"):
    return verify_github_job(
        token, job, jwks_provider=lambda: {"keys": [JWK]},
        clock=lambda: NOW + 20,
    )


class TestPrivateNbaGithubOIDC(unittest.TestCase):
    def test_verified_signed_job_for_every_schedule(self):
        for job in WORKFLOWS:
            with self.subTest(job=job):
                self.assertEqual(verify(signed(job), job)["repository_id"],
                                 REPOSITORY_ID)
                self.assertEqual(
                    verify(signed(job, event_name="workflow_dispatch"), job)["event_name"],
                    "workflow_dispatch",
                )

    def test_cross_job_workflow_cannot_settle(self):
        with self.assertRaises(ValueError):
            verify(signed("market"), "settlement")

    def test_source_scope_claims_must_all_match(self):
        changes = [
            {"repository_id": "123456"},
            {"repository": "attacker/betsightly-backend"},
            {"ref": "refs/heads/devil"},
            {"sub": "repo:attacker/repo:ref:refs/heads/dev"},
            {"workflow_ref": "ZILLABB/betsightly-backend/.github/workflows/evil.yml@refs/heads/dev"},
            {"event_name": "pull_request"},
            {"aud": "unrelated-cloud"},
            {"iss": "https://evil.test"},
            {"exp": NOW - 5},
            {"iat": NOW - 20000},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify(signed(**change))

    def test_external_public_key_does_not_verify(self):
        with self.assertRaises(ValueError):
            verify_github_job(signed(), "settlement",
                              jwks_provider=lambda: {"keys": []})

    def test_no_key_fetch_for_invalid_job(self):
        with self.assertRaises(ValueError):
            verify_github_job(signed(), "football",
                              jwks_provider=lambda: self.fail("no key fetch"))

    def test_unsigned_payload_and_empty_fail_closed(self):
        for token in ("", "a" * 100):
            with self.assertRaises(ValueError):
                verify(token)


if __name__ == "__main__":
    unittest.main()

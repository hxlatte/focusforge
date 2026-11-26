"""Exercise the REAL firebase_admin ID-token verifier with locally signed tokens.

Only the network fetch of Google's public certificates is replaced (by a locally
generated certificate). Signature, issuer, audience, expiry, subject and algorithm
checks are all performed by firebase_admin / google-auth, not by test doubles.

This proves our wiring, not Google's service: it does NOT prove that a token issued
by your real Firebase project verifies. See the local checklist for that.
"""
import datetime as dt
import time

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

PROJECT = "focusforge-3a4f7"
KID = "test-kid-1"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30)).sign(key, hashes.SHA256()))
    return (key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()),
            cert.public_bytes(serialization.Encoding.PEM).decode())


PRIV, CERT = _keypair()
OTHER_PRIV, _ = _keypair()


@pytest.fixture(autouse=True)
def real_verifier(monkeypatch):
    import firebase_admin
    import google.oauth2.id_token as gid

    from app import auth
    monkeypatch.setattr(gid, "_fetch_certs", lambda request, url: {KID: CERT})
    for a in list(firebase_admin._apps.values()):  # noqa: SLF001
        firebase_admin.delete_app(a)
    monkeypatch.setattr(auth, "_firebase_ready", False)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    from firebase_admin import credentials
    sa = {"type": "service_account", "project_id": PROJECT, "private_key_id": "x",
          "private_key": PRIV.decode(), "client_email": f"t@{PROJECT}.iam.gserviceaccount.com",
          "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"}
    firebase_admin.initialize_app(credentials.Certificate(sa), {"projectId": PROJECT})
    monkeypatch.setattr(auth, "_firebase_ready", True)
    yield
    for a in list(firebase_admin._apps.values()):  # noqa: SLF001
        firebase_admin.delete_app(a)


def token(uid="alice", key=PRIV, alg="RS256", kid=KID, **over):
    now = int(time.time())
    claims = {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
              "sub": uid, "iat": now - 5, "auth_time": now - 5, "exp": now + 3600,
              "email": f"{uid}@x.com"}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def verify(tok):
    from app.auth import verify_token
    return verify_token(tok)


def test_valid_token_yields_uid():
    u = verify(token("alice"))
    assert u.uid == "alice" and u.email == "alice@x.com"


@pytest.mark.parametrize("label,tok", [
    ("expired", lambda: token(exp=int(time.time()) - 600, iat=int(time.time()) - 4000,
                              auth_time=int(time.time()) - 4000)),
    ("wrong audience", lambda: token(aud="some-other-project")),
    ("wrong issuer", lambda: token(iss="https://securetoken.google.com/other")),
    ("missing sub", lambda: token(sub=None)),
    ("empty sub", lambda: token(sub="")),
    ("signed with another key", lambda: token(key=OTHER_PRIV)),
    ("unknown kid", lambda: token(kid="nope")),
    ("future iat", lambda: token(iat=int(time.time()) + 7200)),
    ("garbage", lambda: "not.a.jwt"),
    ("empty", lambda: ""),
])
def test_bad_tokens_rejected(label, tok):
    with pytest.raises(ValueError):
        verify(tok())


def test_tampered_payload_rejected():
    h, p, s = token("alice").split(".")
    forged = jwt.encode({"sub": "bob"}, "x", algorithm="HS256").split(".")[1]
    with pytest.raises(ValueError):
        verify(f"{h}.{forged}.{s}")


def test_alg_none_and_hs256_confusion_rejected():
    now = int(time.time())
    claims = {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, "sub": "bob",
              "iat": now - 5, "auth_time": now - 5, "exp": now + 3600}
    none_tok = jwt.encode(claims, key=None, algorithm="none", headers={"kid": KID})
    with pytest.raises(ValueError):
        verify(none_tok)
    # classic algorithm-confusion: HMAC-sign with the public certificate text
    import base64, hashlib, hmac, json

    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    signing = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode()) + "." + \
        b64(json.dumps(claims).encode())
    hs = signing + "." + b64(hmac.new(CERT.encode(), signing.encode(), hashlib.sha256).digest())
    with pytest.raises(ValueError):
        verify(hs)


def test_end_to_end_through_api_uses_verified_uid_only():
    """No dependency overrides: real HTTP auth path. Body/query uid is ignored."""
    from app.main import app, get_repo
    from app.repo import InMemoryRepo

    repo = InMemoryRepo()
    repo.seed("alice", "sessions", {"a": {"subject": "Maths", "duration": 25,
                                          "date": "2026-11-20T10:00:00Z", "type": "manual"}})
    repo.seed("bob", "sessions", {"b": {"subject": "Secret", "duration": 25,
                                        "date": "2026-11-20T10:00:00Z", "type": "manual"}})
    app.dependency_overrides.clear()
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        c = TestClient(app)
        assert c.get("/v1/me").status_code == 401
        assert c.get("/v1/me", headers={"Authorization": "Basic abc"}).status_code == 401
        assert c.get("/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401
        ok = c.get("/v1/me", headers={"Authorization": f"Bearer {token('alice')}"})
        assert ok.status_code == 200 and ok.json()["uid"] == "alice"
        r = c.get("/v1/data-summary?uid=bob",
                  headers={"Authorization": f"Bearer {token('alice')}", "X-Uid": "bob"})
        assert r.status_code == 200
        assert r.json()["sessions_total"] == 1  # alice only, never bob
        exp = token(exp=int(time.time()) - 600, iat=int(time.time()) - 4000,
                    auth_time=int(time.time()) - 4000)
        assert c.get("/v1/me", headers={"Authorization": f"Bearer {exp}"}).status_code == 401
    finally:
        app.dependency_overrides.clear()

"""Security hardening 2026-11-14 (owner: "add some security features to make it secure"; 20-point auth checklist audit).
Each test names the checklist item it covers. Thresholds are implementation choices (docs/PRD_GAPS.md)."""
import pyotp
import pytest

from backend.api.v1 import auth as auth_router
from backend.auth.security import LoginThrottle, UsedCodes
from tests.conftest import make_settings
from tests.test_security_and_api import bearer, make_client


# ---- #5 lockout: failures are also counted per client address, so spraying many accounts is slowed ----
def test_login_failures_are_limited_per_client_address_across_accounts():
    c, svc, *_ = make_client()
    auth_router.ip_throttle = LoginThrottle(max_failures=3, window=60)
    try:
        codes = [c.post("/v1/auth/login", json={"identifier": f"nobody{i}", "password": "x"}).status_code for i in range(4)]
        assert codes == [401, 401, 401, 429]
        assert c.post("/v1/auth/login", json={"identifier": "emp_104", "password": "pw"}).status_code == 429
    finally:
        auth_router.ip_throttle = LoginThrottle(max_failures=auth_router.IP_LOGIN_MAX_FAILURES)


# ---- #1 OTP: a code that was just accepted cannot be used again (replay inside the 90 s window) ----
def test_used_totp_code_is_rejected_the_second_time():
    u = UsedCodes(ttl=90)
    assert u.first_use("user1", "123456", now=0) and not u.first_use("user1", "123456", now=30)
    assert u.first_use("user2", "123456", now=30)                  # per user
    assert u.first_use("user1", "123456", now=200)                 # after the window it is a new code


def test_mfa_verify_refuses_a_replayed_code():
    c, svc, *_ = make_client()
    uid = svc.users.rows["emp_104"]["id"]
    secret = pyotp.random_base32()
    from backend.auth.security import encrypt_secret
    svc.users.rows["emp_104"].update(mfa_enabled_at="2026-11-14", mfa_secret_enc=encrypt_secret(secret, svc.settings.field_encryption_key))
    code = pyotp.TOTP(secret).now()
    h1, h2 = bearer(svc), bearer(svc)
    assert c.post("/v1/auth/mfa/verify", headers=h1, json={"code": code}).status_code == 200
    assert c.post("/v1/auth/mfa/verify", headers=h2, json={"code": code}).status_code == 401
    assert uid


# ---- #16: turning two-step sign-in on signs out every other session ----
def test_enabling_mfa_revokes_the_users_other_sessions():
    c, svc, *_ = make_client()
    other = bearer(svc)
    h = bearer(svc)
    setup = c.post("/v1/auth/mfa/setup", headers=h).json()
    assert c.post("/v1/auth/mfa/enable", headers=h, json={"code": pyotp.TOTP(setup["secret"]).now()}).status_code == 200
    assert c.get("/v1/auth/session", headers=other).status_code == 401
    assert c.get("/v1/auth/session", headers=h).status_code == 200


# ---- state-changing MFA setup is a POST (CSRF-checked), not a GET ----
def test_mfa_setup_is_post_only():
    c, svc, *_ = make_client()
    h = bearer(svc)
    assert c.get("/v1/auth/mfa/setup", headers=h).status_code == 405
    assert c.post("/v1/auth/mfa/setup", headers=h).status_code == 200


# ---- #4: password reset mail is sent after the response, so timing does not reveal which accounts exist ----
def test_password_reset_mail_is_sent_in_the_background(monkeypatch):
    from fastapi import BackgroundTasks
    c, svc, *_ = make_client()
    queued = []
    real = BackgroundTasks.add_task
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, fn, *a, **k: (queued.append(fn), real(self, fn, *a, **k))[1])
    monkeypatch.setattr(auth_router, "send_safely", lambda *a, **k: None)
    svc.one_time = type("OneTime", (), {"issue": lambda self, *a: "tok"})()
    assert c.post("/v1/auth/password-reset", json={"identifier": "nobody@q.ai"}).status_code == 202
    assert not queued
    assert c.post("/v1/auth/password-reset", json={"identifier": "a@q.ai"}).status_code == 202
    assert queued == [auth_router.send_safely], "the reset mail must be sent after the response"


# ---- #7 / #2 / #20: unsafe production settings are refused at start-up ----
@pytest.mark.parametrize("field", ["session_secret", "field_encryption_key"])
def test_placeholder_secrets_are_refused(field):
    with pytest.raises(ValueError, match="placeholder"):
        make_settings(**{field: "change-me-change-me-change-me-change-me"})


def test_https_deployment_requires_real_mail_and_admin_mfa():
    with pytest.raises(ValueError, match="mail_backend"):
        make_settings(public_url="https://ai.example.com", mail_backend="console", admin_mfa_required=True)
    with pytest.raises(ValueError, match="admin_mfa_required"):
        make_settings(public_url="https://ai.example.com", mail_backend="smtp", admin_mfa_required=False,
                      smtp_host="smtp.example.com", smtp_port=587, mail_from="ai@example.com")
    assert make_settings(public_url="https://ai.example.com", mail_backend="smtp", admin_mfa_required=True,
                         smtp_host="smtp.example.com", smtp_port=587, mail_from="ai@example.com")
    assert make_settings(public_url="http://localhost:8000", mail_backend="console", admin_mfa_required=False)


# ---- throttle memory stays bounded: checking an identifier does not store it ----
def test_checking_unknown_identifiers_does_not_grow_the_throttle():
    t = LoginThrottle(max_failures=3, window=60)
    for i in range(1000):
        t.blocked(f"user{i}", now=1)
    t.failure("x", now=1); t.success("x")
    assert len(t._fails) == 0


# ---- F2: Content-Security-Policy on every response (defence in depth against injected scripts) ----
def test_every_response_has_a_content_security_policy():
    c, svc, *_ = make_client()
    r = c.get("/v1/auth/session")                    # also on error responses
    assert r.status_code == 401
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp and "unsafe-eval" not in csp and "script-src 'self' 'unsafe-inline'" not in csp

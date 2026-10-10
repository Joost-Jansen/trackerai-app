import time

from app.core import security


def test_password_hash_roundtrip():
    h = security.hash_password("correct horse battery staple")
    assert h.startswith("$2b$")
    assert security.verify_password("correct horse battery staple", h)
    assert not security.verify_password("wrong password", h)


#: A real digest of "shared-secret" produced by streamlit_authenticator's
#: stauth.Hasher (itself a bcrypt wrapper, cost 12), captured before that app
#: was retired. Hashes of exactly this shape are still sitting in the live
#: auth_config.yaml for every account created through the old UI.
_HASHED_BY_THE_STREAMLIT_APP = "$2b$12$8gLcJSuGyiZc6jcZz4FFy.2K/BwD1sqhKZ.fnPPtshIMaPdOsXs8i"


def test_an_account_made_in_the_old_streamlit_app_can_still_log_in():
    """
    The Streamlit app is gone (container removed 2026-08-07), but the accounts
    it created are not: their passwords live on as bcrypt digests in the shared
    auth_config.yaml. Pinned as a literal rather than re-hashed through
    streamlit_authenticator, which is no longer a dependency of this repo — and
    a literal is the better test anyway, since it is what is actually stored.
    """
    assert security.verify_password("shared-secret", _HASHED_BY_THE_STREAMLIT_APP)
    assert not security.verify_password("wrong password", _HASHED_BY_THE_STREAMLIT_APP)


def test_jwt_roundtrip():
    token = security.create_access_token("alice", secret="test-secret", expiry_days=30)
    assert security.decode_access_token(token, "test-secret") == "alice"


def test_jwt_rejects_wrong_secret():
    token = security.create_access_token("alice", secret="test-secret", expiry_days=30)
    assert security.decode_access_token(token, "other-secret") is None


def test_jwt_rejects_expired_token():
    token = security.create_access_token("alice", secret="test-secret", expiry_days=0)
    time.sleep(1.1)
    assert security.decode_access_token(token, "test-secret") is None


def test_jwt_rejects_garbage():
    assert security.decode_access_token("not-a-jwt", "test-secret") is None

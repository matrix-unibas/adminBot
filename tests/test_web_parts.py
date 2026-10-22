"""Pure parts of the webapp and link delivery."""
from aiohttp.test_utils import make_mocked_request

from adminbot.delivery import CsvDelivery, InlineDelivery, SignupLink
from adminbot.signups import (
    RESET_CODE_ALPHABET,
    check_password,
    hash_reset_code,
    hash_token,
    new_reset_code,
    new_token,
    normalize_reset_code,
)
from adminbot.web.pages import done, recover_form, signup_form
from adminbot.web.ratelimit import FailureCounter, RateLimiter, client_ip, parse_networks


def test_token_is_random_and_only_hash_is_stored():
    raw, token_hash = new_token()
    assert len(raw) >= 43 and raw != token_hash
    assert hash_token(raw) == token_hash
    assert new_token()[0] != raw


def test_reset_code_format_and_normalisation():
    code = new_reset_code()
    groups = code.split("-")
    assert [len(g) for g in groups] == [4] * 5
    assert set("".join(groups)) <= set(RESET_CODE_ALPHABET)
    assert new_reset_code() != code
    # Case, spaces and dashes are ignored; I/L read as 1, O as 0.
    assert normalize_reset_code(" ab1o-xyz0 ") == "AB10XYZ0"
    assert normalize_reset_code("il") == "11"
    assert hash_reset_code(code.lower().replace("-", " ")) == hash_reset_code(code)


def test_failure_counter():
    now = [0.0]
    counter = FailureCounter(limit=2, window=100, clock=lambda: now[0])
    counter.fail("@a:x")
    assert not counter.locked("@a:x")
    counter.fail("@a:x")
    assert counter.locked("@a:x") and not counter.locked("@b:x")
    now[0] = 101
    assert not counter.locked("@a:x")


def test_check_password():
    assert check_password("a" * 12, "b" * 12, 12) == "web.error.password_mismatch"
    assert check_password("short", "short", 12) == "web.error.password_short"
    assert check_password("a" * 12, "a" * 12, 12) is None


def test_rate_limiter():
    now = [0.0]
    limiter = RateLimiter(per_ip_per_hour=2, global_per_hour=3, clock=lambda: now[0])
    assert limiter.allow("1.1.1.1") and limiter.allow("1.1.1.1")
    assert not limiter.allow("1.1.1.1")
    assert limiter.allow("2.2.2.2")
    assert not limiter.allow("3.3.3.3")  # global limit
    now[0] = 3601
    assert limiter.allow("1.1.1.1")


def test_client_ip_trusts_only_proxies():
    trusted = parse_networks(["172.16.0.0/12"])
    via_proxy = make_mocked_request("GET", "/", headers={"X-Forwarded-For": "9.9.9.9, 131.152.1.2"},
                                    transport=_transport("172.18.0.1"))
    assert client_ip(via_proxy, trusted) == "131.152.1.2"
    direct = make_mocked_request("GET", "/", headers={"X-Forwarded-For": "6.6.6.6"},
                                 transport=_transport("8.8.8.8"))
    assert client_ip(direct, trusted) == "8.8.8.8"


def _transport(ip):
    class Transport:
        def get_extra_info(self, name, default=None):
            return (ip, 12345) if name == "peername" else default

        def is_closing(self):
            return False

    return Transport()


def test_signup_form_escapes():
    html = signup_form('@x:y"><script>', "tok", "nonce", 12, error="<b>")
    assert "<script>" not in html and "&lt;b&gt;" in html


def test_recover_form_and_done_page_escape():
    html = recover_form("n", 12, error="<b>", username='"><script>')
    assert "<script>" not in html and "&lt;b&gt;" in html
    html = done("@x:y", "https://example.com", reset_code="<i>", note_key="web.done_verify")
    assert "<i>" not in html and "&lt;i&gt;" in html


def test_csv_delivery_has_bom_and_rows():
    links = [SignupLink("a@unibas.ch", "@a:x", "https://l/1", "CS101")]
    result = CsvDelivery("https://x").deliver(links)
    name, data, mime = result.files[0]
    assert name == "signup-links.csv" and mime == "text/csv"
    assert data.decode("utf-8").startswith("﻿email,user_id,link,course")
    assert "{link}" in result.text


def test_inline_delivery():
    text = InlineDelivery("https://x").deliver([SignupLink("a@unibas.ch", "@a:x", "https://l/1", None)]).text
    assert "https://l/1" in text and "@a:x" in text

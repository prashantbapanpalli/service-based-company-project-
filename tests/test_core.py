import copy

from app.knowledge import build_instructions, check_playbook, load_kb, load_playbook


def test_playbook_is_valid():
    assert check_playbook(load_playbook()) == []


def test_playbook_covers_every_stage():
    playbook = load_playbook()
    used = {p["stage"] for b in playbook["books"] for p in b["principles"]}
    assert used == {s["id"] for s in playbook["stages"]}


def test_unapproved_price_never_in_instructions():
    kb = load_kb()
    text = build_instructions(kb, load_playbook())
    for product in kb["products"]:
        if not product["price_approved"]:
            assert product["price"] not in text
    assert "₹" not in text


def test_approved_price_is_included():
    kb = copy.deepcopy(load_kb())
    kb["products"][0]["price_approved"] = True
    assert kb["products"][0]["price"] in build_instructions(kb, load_playbook())


def test_instructions_disclose_ai_and_forbid_sensitive_data():
    text = build_instructions()
    assert "You are an AI" in text
    for item in ("Aadhaar", "OTP", "password"):
        assert item in text


def test_check_playbook_catches_bad_entries():
    playbook = copy.deepcopy(load_playbook())
    playbook["books"][0]["principles"][0]["stage"] = "hard_close"
    playbook["quiz"][0]["answer"] = 99
    playbook["objections"][0]["response_en"] = "Please tell me your OTP."
    problems = check_playbook(playbook)
    assert any("unknown stage" in p for p in problems)
    assert any("answer index" in p for p in problems)
    assert any("otp" in p for p in problems)


def test_every_region_has_books():
    playbook = load_playbook()
    for region in playbook["regions"]:
        assert sum(b["region"] == region["id"] for b in playbook["books"]) >= 5


def test_check_playbook_catches_unknown_region():
    playbook = copy.deepcopy(load_playbook())
    playbook["books"][0]["region"] = "martian"
    assert any("unknown region" in p for p in check_playbook(playbook))

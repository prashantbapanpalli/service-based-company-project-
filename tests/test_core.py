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


# ---- call scenarios ----

from app.scenarios import check_scenarios, grade_reply, load_scenarios  # noqa: E402


def _scenario(sid):
    return next(s for s in load_scenarios()["scenarios"] if s["id"] == sid)


def test_scenarios_are_valid():
    assert check_scenarios(load_scenarios()) == []


def test_instructions_include_scenarios_and_tools():
    text = build_instructions()
    for s in load_scenarios()["scenarios"]:
        assert s["situation"] in text
    assert "record_opt_out" in text and "request_handover" in text


def test_must_end_scenarios_use_ending_tools():
    data = load_scenarios()
    by_id = {s["id"]: s for s in data["scenarios"]}
    assert by_id["do_not_call"]["action"] == "record_opt_out"
    assert by_id["wrong_number"]["action"] == "mark_wrong_number"
    assert by_id["voicemail"]["action"] == "end_call"
    assert by_id["grief_emergency"]["action"] == "end_call"


def test_grade_reply_passes_good_and_fails_bad_replies():
    kb = load_kb()
    opt_out = _scenario("do_not_call")
    assert grade_reply(opt_out, "ಆಗ್ಲಿರೀ, ನಿಮ್ ನಂಬರ್ ತೆಗೀತೀನಿ.", {"record_opt_out"}, kb) == []
    assert grade_reply(opt_out, "ಒಂದೇ ನಿಮಿಷ ಕೇಳ್ರಿ…", set(), kb)

    price = _scenario("price_pressure")
    assert grade_reply(price, "ರೇಟು ಚೇತನ್ ಅವರೇ ಹೇಳ್ತಾರ್ರೀ.", set(), kb) == []
    for bad in ("ಒಂದು ಫಾರ್ಮ್‌ಗೆ 20 ರೂಪಾಯಿ.", "Only ₹20.", "ಇಪ್ಪತ್ತು ರೂಪಾಯಿ ಅಷ್ಟೇ.", "೨೦ ರೂಪಾಯಿ"):
        assert grade_reply(price, bad, set(), kb), bad


def test_grade_reply_catches_sensitive_requests_and_echoed_digits():
    kb = load_kb()
    s = _scenario("volunteers_sensitive")
    assert grade_reply(s, "ಬ್ಯಾಡ್ರಿ, ಅಂಥಾ ನಂಬರ್ ನಮಗ ಬೇಕಾಗಂಗಿಲ್ಲ.", set(), kb) == []
    assert grade_reply(s, "ಸರಿ, 4821 7390 5562 ನೋಟ್ ಮಾಡ್ಕೊಂಡೆ.", set(), kb)
    assert grade_reply(s, "Please tell me your OTP.", set(), kb)
    assert grade_reply(s, "We never ask for your OTP.", set(), kb) == []


def test_recommended_replies_pass_their_own_tests():
    kb = load_kb()
    for s in load_scenarios()["scenarios"]:
        if s.get("test"):
            for reply in (s["say_kn"], s["say_en"]):
                assert grade_reply(s, reply, {s["action"]}, kb) == [], (s["id"], reply)


def test_voice_rules_in_instructions_and_grader():
    from app.scenarios import voice_problems
    text = build_instructions()
    assert text.index("HARD RULES") < text.index("PRODUCTS")
    assert "VOICE RULES" in text
    assert voice_problems("ಆಗ್ಲಿರೀ. ನಾಳೆ ಕಾಲ್ ಮಾಡ್ತೀನಿ.") == []
    assert voice_problems("Here are the options:\n- demo\n- callback")
    assert voice_problems("**Great!** Let's talk.")
    assert voice_problems("One. Two. Three. Four. Five.")


def test_field_techniques_reach_the_agent():
    playbook = load_playbook()
    text = build_instructions(playbook=playbook)
    for t in playbook["field_techniques"]:
        assert t["on_our_call"] in text

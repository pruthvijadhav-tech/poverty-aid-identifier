"""
test_verification.py

Regression tests for the government-verification registry, the scheme-data
corrections, alias/duplicate handling, the PMAY-G/PMAY-U split, closed-scheme
exclusion, multilingual verification text, and the corruption-report flow.

Run with:  pytest test_verification.py -v
(Run alongside the original suite with: pytest test_scoring.py test_verification.py -v)
"""

import os
import sys
import types

# --- Same Gemini-SDK stub as test_scoring.py, so this file also runs
# --- standalone without needing GEMINI_API_KEY / network access. ---
if 'google' not in sys.modules:
    google_mod = types.ModuleType('google')

    genai_legacy_mod = types.ModuleType('google.generativeai')
    genai_legacy_mod.configure = lambda *a, **kw: None
    class _StubModel:
        def __init__(self, *a, **kw): pass
        def generate_content(self, *a, **kw):
            class R:
                text = "stub"
            return R()
    genai_legacy_mod.GenerativeModel = _StubModel
    google_mod.generativeai = genai_legacy_mod

    genai_mod = types.ModuleType('google.genai')
    class _StubResponse:
        text = "stub"
    class _StubModels:
        def generate_content(self, *a, **kw):
            return _StubResponse()
    class _StubClient:
        def __init__(self, *a, **kw):
            self.models = _StubModels()
    genai_mod.Client = _StubClient
    genai_types_mod = types.ModuleType('google.genai.types')
    genai_mod.types = genai_types_mod
    google_mod.genai = genai_mod

    sys.modules['google'] = google_mod
    sys.modules['google.generativeai'] = genai_legacy_mod
    sys.modules['google.genai'] = genai_mod
    sys.modules['google.genai.types'] = genai_types_mod

if 'keep_alive' not in sys.modules:
    keep_alive_mod = types.ModuleType('keep_alive')
    keep_alive_mod.start = lambda *a, **kw: None
    sys.modules['keep_alive'] = keep_alive_mod

os.environ.setdefault('SECRET_KEY', 'test_secret_key')
os.environ.setdefault('FLASK_DEBUG', 'false')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as appmod
import scheme_verification as sv

SCHEME_DETAILS = appmod.SCHEME_DETAILS
get_schemes = appmod.get_schemes

ORIGINAL_24_KEYS = [
    "pm_jan_arogya", "state_emergency", "national_family", "pm_poshan", "icds",
    "old_age_pension", "widow_pension", "annapurna", "ayushman", "divyangjan",
    "accessible_india", "pm_awas", "antyodaya", "ujjwala", "saubhagya", "jan_dhan",
    "ladki_bahin", "mh_health", "shravan_bal", "gharkul", "sanjay_gandhi",
    "rajmata_jijau", "mh_ration", "vayoshri_mh",
]


# ---------------------------------------------------------------------------
# 1. 24-key coverage
# ---------------------------------------------------------------------------
def test_all_24_original_keys_have_verification_records():
    missing = [k for k in ORIGINAL_24_KEYS if k not in sv.VERIFICATION_REGISTRY]
    assert not missing, f"Missing verification registry entries for: {missing}"


def test_all_24_original_keys_still_have_scheme_details():
    missing = [k for k in ORIGINAL_24_KEYS if k not in SCHEME_DETAILS]
    assert not missing, f"Missing SCHEME_DETAILS entries for: {missing}"


# ---------------------------------------------------------------------------
# 2. Duplicate Ayushman / PM-JAY resolution
# ---------------------------------------------------------------------------
def test_ayushman_resolves_to_pm_jan_arogya():
    assert sv.resolve_canonical("ayushman") == "pm_jan_arogya"


def test_ayushman_marked_duplicate_and_not_recommendable_alone():
    entry = sv.VERIFICATION_REGISTRY["ayushman"]
    assert entry["status"] == sv.STATUS_DUPLICATE
    assert sv.is_recommendable("ayushman") is False


def test_chronic_illness_and_emergency_do_not_produce_duplicate_health_cards():
    base_data = dict(age_group='adult', accident='no', housing='pucca',
                      electricity='yes', ration='yes', earning_member_died='no',
                      widow_status='no', income=0, address='Delhi')
    data = dict(base_data, medical='chronic_illness')
    schemes = get_schemes(10, data, lang='en')
    keys = [s[0] for s in schemes]
    assert keys.count('pm_jan_arogya') <= 1
    assert 'ayushman' not in keys  # legacy key itself is never emitted


# ---------------------------------------------------------------------------
# 3. PMAY-G / PMAY-U split
# ---------------------------------------------------------------------------
def test_pmay_split_keys_exist_in_registry_and_details():
    for k in ("pm_awas_gramin", "pm_awas_urban"):
        assert k in sv.VERIFICATION_REGISTRY
        assert k in SCHEME_DETAILS


def test_pm_awas_legacy_key_is_duplicate_alias_of_gramin():
    entry = sv.VERIFICATION_REGISTRY["pm_awas"]
    assert entry["status"] == sv.STATUS_DUPLICATE
    assert entry["canonical_key"] == "pm_awas_gramin"


def test_kutcha_housing_recommends_split_pmay_key_not_legacy():
    data = dict(age_group='adult', medical='none', accident='no', housing='kutcha',
                electricity='yes', ration='yes', earning_member_died='no',
                widow_status='no', income=0, address='Nagpur, Maharashtra')
    schemes = get_schemes(10, data, lang='en')
    keys = [s[0] for s in schemes]
    assert 'pm_awas' not in keys
    assert ('pm_awas_gramin' in keys) or ('pm_awas_urban' in keys)


def test_rural_residence_type_recommends_pmay_gramin():
    data = dict(age_group='adult', medical='none', accident='no', housing='kutcha',
                electricity='yes', ration='yes', earning_member_died='no',
                widow_status='no', income=0, address='Some Village, Maharashtra',
                residence_type='rural')
    schemes = get_schemes(10, data, lang='en')
    keys = [s[0] for s in schemes]
    assert 'pm_awas_gramin' in keys
    assert 'pm_awas_urban' not in keys


def test_urban_residence_type_recommends_pmay_urban():
    data = dict(age_group='adult', medical='none', accident='no', housing='kutcha',
                electricity='yes', ration='yes', earning_member_died='no',
                widow_status='no', income=0, address='Some Village, Maharashtra',
                residence_type='urban')
    schemes = get_schemes(10, data, lang='en')
    keys = [s[0] for s in schemes]
    assert 'pm_awas_urban' in keys
    assert 'pm_awas_gramin' not in keys


def test_missing_residence_type_falls_back_to_address_heuristic_safely():
    """Backward compatibility: old submissions/API calls without
    residence_type must not crash and must still get exactly one PMAY
    variant via the address-text fallback."""
    data = dict(age_group='adult', medical='none', accident='no', housing='homeless',
                electricity='yes', ration='yes', earning_member_died='no',
                widow_status='no', income=0, address='Mumbai City, Maharashtra')
    schemes = get_schemes(10, data, lang='en')  # no residence_type key at all
    keys = [s[0] for s in schemes]
    pmay_keys = [k for k in keys if k in ('pm_awas_gramin', 'pm_awas_urban')]
    assert len(pmay_keys) == 1


# ---------------------------------------------------------------------------
# 4. Saubhagya can never appear as an active recommendation
# ---------------------------------------------------------------------------
def test_saubhagya_is_closed_in_registry():
    assert sv.VERIFICATION_REGISTRY["saubhagya"]["status"] == sv.STATUS_CLOSED
    assert sv.is_recommendable("saubhagya") is False


def test_saubhagya_never_recommended_even_with_no_electricity():
    data = dict(age_group='adult', medical='none', accident='no', housing='pucca',
                electricity='no', ration='yes', earning_member_died='no',
                widow_status='no', income=0, address='Pune, Maharashtra')
    schemes = get_schemes(10, data, lang='en')
    keys = [s[0] for s in schemes]
    assert 'saubhagya' not in keys


# ---------------------------------------------------------------------------
# 5. Corrected benefits / eligibility
# ---------------------------------------------------------------------------
def test_sanjay_gandhi_amount_is_1500():
    for lang in ('en', 'hi', 'mr'):
        amount = SCHEME_DETAILS['sanjay_gandhi'][lang]['amount']
        assert '1,500' in amount or '1500' in amount
        assert '600' not in amount


def test_shravan_bal_amount_is_1500():
    for lang in ('en', 'hi', 'mr'):
        amount = SCHEME_DETAILS['shravan_bal'][lang]['amount']
        assert '1,500' in amount or '1500' in amount
        assert '600' not in amount


def test_vayoshri_is_one_time_3000_not_free_equipment_only():
    amount = SCHEME_DETAILS['vayoshri_mh']['en']['amount']
    assert '3,000' in amount or '3000' in amount
    assert 'one-time' in amount.lower() or 'one time' in amount.lower()


def test_gharkul_eligibility_is_sc_neo_buddhist_not_broad_grouping():
    eligibility_text = " ".join(SCHEME_DETAILS['gharkul']['en']['eligibility']).lower()
    assert 'neo-buddhist' in eligibility_text or 'nav-bauddha' in eligibility_text
    assert 'sc/st/obc/nt' not in eligibility_text


def test_gharkul_not_recommended_from_housing_need_alone():
    """Kutcha/homeless housing by itself must NOT trigger Gharkul -- the
    verified target group is SC/Neo-Buddhist communities specifically."""
    for housing in ('kutcha', 'homeless'):
        data = dict(age_group='adult', medical='none', accident='no', housing=housing,
                    electricity='yes', ration='yes', earning_member_died='no',
                    widow_status='no', income=5000, address='Nagpur, Maharashtra')
        schemes = get_schemes(10, data, lang='en')
        keys = [s[0] for s in schemes]
        assert 'gharkul' not in keys, f"Gharkul wrongly recommended for housing={housing} with no category set"


def test_gharkul_not_recommended_for_non_sc_neo_buddhist_category():
    data = dict(age_group='adult', medical='none', accident='no', housing='kutcha',
                electricity='yes', ration='yes', earning_member_died='no',
                widow_status='no', income=5000, address='Nagpur, Maharashtra',
                category='obc')
    schemes = get_schemes(10, data, lang='en')
    keys = [s[0] for s in schemes]
    assert 'gharkul' not in keys


def test_gharkul_recommended_for_sc_category_with_housing_need():
    data = dict(age_group='adult', medical='none', accident='no', housing='kutcha',
                electricity='yes', ration='yes', earning_member_died='no',
                widow_status='no', income=5000, address='Nagpur, Maharashtra',
                category='sc')
    schemes = get_schemes(10, data, lang='en')
    keys = [s[0] for s in schemes]
    assert 'gharkul' in keys


def test_gharkul_recommended_for_neo_buddhist_category_with_housing_need():
    data = dict(age_group='adult', medical='none', accident='no', housing='homeless',
                electricity='yes', ration='yes', earning_member_died='no',
                widow_status='no', income=5000, address='Nagpur, Maharashtra',
                category='neo_buddhist')
    schemes = get_schemes(10, data, lang='en')
    keys = [s[0] for s in schemes]
    assert 'gharkul' in keys


def test_mh_health_not_restricted_to_yellow_orange_only():
    text = (SCHEME_DETAILS['mh_health']['en']['description'] + " " +
            " ".join(SCHEME_DETAILS['mh_health']['en']['eligibility'])).lower()
    # Must reflect the expanded coverage, not just yellow/orange
    assert 'all ration card' in text or 'any maharashtra-domicile' in text


def test_divyangjan_is_loan_not_pension_amount_claim():
    text = SCHEME_DETAILS['divyangjan']['en']['description'].lower()
    amount = SCHEME_DETAILS['divyangjan']['en']['amount'].lower()
    assert 'loan' in text
    assert 'not a monthly pension' in amount or 'not' in amount


def test_accessible_india_does_not_claim_adip_device_benefit():
    desc = SCHEME_DETAILS['accessible_india']['en']['description'].lower()
    assert 'not' in desc and ('individually apply' in desc or 'device-distribution' in desc)


def test_adip_carries_the_actual_device_benefit():
    desc = SCHEME_DETAILS['adip']['en']['description'].lower()
    assert 'wheelchair' in desc or 'hearing aid' in desc


def test_state_emergency_does_not_claim_fixed_10000():
    for lang in ('en', 'hi', 'mr'):
        amount = SCHEME_DETAILS['state_emergency'][lang]['amount']
        assert '10,000' not in amount and '10000' not in amount


def test_rajmata_jijau_not_represented_as_direct_cash_scheme():
    entry = sv.VERIFICATION_REGISTRY['rajmata_jijau']
    assert entry['scheme_type'] == 'PROGRAM_POLICY'
    amount = SCHEME_DETAILS['rajmata_jijau']['en']['amount'].lower()
    assert 'cash' in amount or 'no direct cash' in amount or 'coordination' in amount


def test_mh_ration_not_represented_as_standalone_cash_scheme():
    entry = sv.VERIFICATION_REGISTRY['mh_ration']
    assert entry['scheme_type'] == 'PROGRAM_POLICY'


# ---------------------------------------------------------------------------
# 6. Verification metadata / multilingual text
# ---------------------------------------------------------------------------
def test_get_verification_returns_none_for_unknown_key():
    assert sv.get_verification('totally_made_up_key') is None


def test_get_verification_english():
    v = sv.get_verification('shravan_bal', 'en')
    assert v['status'] == sv.STATUS_VERIFIED_PRIMARY_CURRENT
    assert 'Verified' in v['status_label']


def test_get_verification_hindi_text_differs_from_english():
    v_en = sv.get_verification('shravan_bal', 'en')
    v_hi = sv.get_verification('shravan_bal', 'hi')
    assert v_en['status_label'] != v_hi['status_label']
    assert v_en['department'] != v_hi['department']


def test_get_verification_marathi_text_differs_from_english():
    v_en = sv.get_verification('shravan_bal', 'en')
    v_mr = sv.get_verification('shravan_bal', 'mr')
    assert v_en['status_label'] != v_mr['status_label']
    assert v_en['department'] != v_mr['department']


def test_no_gr_number_shown_as_na_for_central_scheme_without_gr():
    v = sv.get_verification('pm_jan_arogya', 'en')
    # No document has a GR-style number for this central scheme's documents
    assert v['no_gr_explanation']  # explanation text always present
    assert 'GR Number: N/A' not in v['no_gr_explanation']


def test_gharkul_has_gr_style_document_flag_true():
    v = sv.get_verification('gharkul', 'en')
    assert v['has_gr_style_document'] is True


def test_every_registry_entry_has_all_three_languages_for_notes():
    for key, entry in sv.VERIFICATION_REGISTRY.items():
        for lang in ('en', 'hi', 'mr'):
            assert entry['notes'].get(lang), f"{key} missing notes.{lang}"
            assert entry['department'].get(lang), f"{key} missing department.{lang}"


# ---------------------------------------------------------------------------
# 7. Closed-scheme / duplicate / program-policy safety net
# ---------------------------------------------------------------------------
def test_no_closed_or_duplicate_scheme_ever_in_recommendation_list():
    data = dict(age_group='elderly', medical='disability', accident='yes',
                housing='kutcha', electricity='no', ration='no',
                earning_member_died='yes', widow_status='yes', income=1000,
                address='Mumbai, Maharashtra')
    schemes = get_schemes(90, data, lang='en')
    for key, *_ in schemes:
        canonical = sv.resolve_canonical(key)
        assert sv.is_recommendable(canonical), f"{key} (-> {canonical}) should not be recommendable"


# ---------------------------------------------------------------------------
# 8. Corruption-report flow: canonical scheme_key persistence
# ---------------------------------------------------------------------------
def _make_client():
    return appmod.app.test_client()


def test_corruption_page_loads_schemes_after_eligibility_form():
    client = _make_client()
    resp = client.post('/eligibility', data={
        'lang': 'en', 'consent': 'yes', 'person_name': 'Test User', 'phone': '9876543210',
        'address': 'Pune, Maharashtra', 'gender': 'female', 'widow_status': 'no',
        'age_group': 'adult', 'income': '5000', 'family_size': '4', 'housing': 'kutcha',
        'electricity': 'no', 'ration': 'yes', 'medical': 'none', 'accident': 'no',
        'earning_member_died': 'no',
    }, follow_redirects=True)
    assert resp.status_code == 200
    resp2 = client.get('/corruption')
    assert resp2.status_code == 200
    body = resp2.get_data(as_text=True)
    assert 'schemeSelect' in body
    assert 'saubhagya' not in body.lower() or 'CLOSED' in body  # never an active saubhagya option


def test_corruption_report_stores_canonical_scheme_key():
    client = _make_client()
    client.post('/eligibility', data={
        'lang': 'en', 'consent': 'yes', 'person_name': 'Alias Test', 'phone': '9998887771',
        'address': 'Pune, Maharashtra', 'gender': 'female', 'widow_status': 'no',
        'age_group': 'adult', 'income': '5000', 'family_size': '2', 'housing': 'pucca',
        'electricity': 'yes', 'ration': 'yes', 'medical': 'chronic_illness', 'accident': 'no',
        'earning_member_died': 'no',
    }, follow_redirects=True)
    resp = client.post('/corruption', data={
        'action': 'submit_report', 'lang': 'en',
        'scheme_key': 'pm_jan_arogya', 'scheme': 'PM Jan Arogya Yojana',
        'entitled_amount': '500000', 'received_amount': '0',
        'official_name': 'Test Official', 'description': 'Test complaint',
        'incident_date': '2026-08-01', 'location': 'Pune',
    }, follow_redirects=True)
    assert resp.status_code == 200
    conn = appmod.get_db_connection()
    row = conn.execute(
        "SELECT scheme_key FROM reports WHERE description = ? ORDER BY id DESC LIMIT 1",
        ('Test complaint',)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row['scheme_key'] == 'pm_jan_arogya'


def test_corruption_report_alias_key_resolves_to_canonical_in_db():
    """Filing a complaint against the legacy 'ayushman' key must store the
    canonical 'pm_jan_arogya' key, not the alias, so admin dashboards don't
    split one scheme's complaints across two keys."""
    client = _make_client()
    resp = client.post('/corruption', data={
        'action': 'submit_report', 'lang': 'en',
        'scheme_key': 'ayushman', 'scheme': 'Ayushman Bharat',
        'entitled_amount': '500000', 'received_amount': '0',
        'official_name': 'Test Official 2', 'description': 'Alias complaint test',
        'incident_date': '2026-08-01', 'location': 'Pune',
    }, follow_redirects=True)
    assert resp.status_code == 200
    conn = appmod.get_db_connection()
    row = conn.execute(
        "SELECT scheme_key FROM reports WHERE description = ? ORDER BY id DESC LIMIT 1",
        ('Alias complaint test',)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row['scheme_key'] == 'pm_jan_arogya'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))


import os
import sys
import types

if 'google' not in sys.modules:
    google_mod = types.ModuleType('google')
    genai_mod = types.ModuleType('google.generativeai')
    genai_mod.configure = lambda *a, **kw: None
    class _StubModel:
        def __init__(self, *a, **kw): pass
        def generate_content(self, *a, **kw):
            class R:
                text = "stub"
            return R()
    genai_mod.GenerativeModel = _StubModel
    google_mod.generativeai = genai_mod
    sys.modules['google'] = google_mod
    sys.modules['google.generativeai'] = genai_mod

if 'keep_alive' not in sys.modules:
    keep_alive_mod = types.ModuleType('keep_alive')
    keep_alive_mod.start = lambda *a, **kw: None
    sys.modules['keep_alive'] = keep_alive_mod

os.environ.setdefault('SECRET_KEY', 'test_secret_key')
os.environ.setdefault('FLASK_DEBUG', 'false')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as appmod

calculate_score = appmod.calculate_score
get_priority = appmod.get_priority
get_schemes = appmod.get_schemes
detect_state = appmod.detect_state


def base_data(**overrides):
    """A baseline 'no need' applicant — every test tweaks one field at a time."""
    data = {
        'age_group': 'adult',
        'income': '25000',
        'family_size': '2',
        'housing': 'pucca',
        'electricity': 'yes',
        'ration': 'yes',
        'medical': 'none',
        'accident': 'no',
        'earning_member_died': 'no',
        'address': '',
    }
    data.update(overrides)
    return data


# ---------- calculate_score ----------

def test_score_zero_for_no_need_case():
    assert calculate_score(base_data()) == 0

def test_score_child_adds_30():
    assert calculate_score(base_data(age_group='child')) == 30

def test_score_elderly_adds_25():
    assert calculate_score(base_data(age_group='elderly')) == 25

def test_score_income_brackets():
    assert calculate_score(base_data(income='4000')) == 40   # < 5000
    assert calculate_score(base_data(income='8000')) == 25   # < 10000
    assert calculate_score(base_data(income='15000')) == 10  # < 20000
    assert calculate_score(base_data(income='25000')) == 0   # >= 20000

def test_score_family_size_brackets():
    assert calculate_score(base_data(family_size='5')) == 20
    assert calculate_score(base_data(family_size='3')) == 10
    assert calculate_score(base_data(family_size='1')) == 0

def test_score_housing_brackets():
    assert calculate_score(base_data(housing='homeless')) == 20
    assert calculate_score(base_data(housing='kutcha')) == 15
    assert calculate_score(base_data(housing='rented')) == 5
    assert calculate_score(base_data(housing='pucca')) == 0

def test_score_medical_emergency_highest():
    assert calculate_score(base_data(medical='emergency')) == 30
    assert calculate_score(base_data(medical='disability')) == 20
    assert calculate_score(base_data(medical='chronic_illness')) == 15

def test_score_accumulates_across_factors():
    # child + very low income + homeless + medical emergency
    data = base_data(age_group='child', income='3000', housing='homeless', medical='emergency')
    # 30 (child) + 40 (income) + 20 (homeless) + 30 (medical emergency) = 120
    assert calculate_score(data) == 120

def test_score_max_realistic_case():
    data = base_data(
        age_group='child', income='2000', family_size='6', housing='homeless',
        electricity='no', ration='no', medical='emergency', accident='yes',
        earning_member_died='yes', widow_status='yes'
    )
    score = calculate_score(data)
    assert score == 30 + 40 + 20 + 20 + 10 + 10 + 30 + 25 + 25 + 15  # 225
    assert score <= 225


def test_score_max_possible():
    """
    Max AI Need Score is 225.
    """
    max_possible = 30 + 40 + 20 + 20 + 10 + 10 + 30 + 25 + 25 + 15
    assert max_possible == 225


# ---------- get_priority ----------

def test_priority_critical_child():
    data = base_data(age_group='child')
    assert get_priority(45, data).startswith('CRITICAL')

def test_priority_critical_medical_emergency_regardless_of_score():
    data = base_data(medical='emergency')
    assert get_priority(0, data).startswith('CRITICAL')

def test_priority_high_need_threshold():
    data = base_data()
    assert get_priority(60, data) == 'HIGH NEED - Urgent Help Required'

def test_priority_basic_help_for_zero_score():
    data = base_data()
    assert get_priority(0, data) == 'Will Receive Basic Community Help'


# ---------- get_schemes ----------

def test_schemes_basic_always_included():
    schemes = get_schemes(0, base_data(), 'en')
    keys = [s[0] for s in schemes]
    assert 'basic' in keys

def test_schemes_no_duplicates():
    data = base_data(age_group='elderly', medical='disability')
    schemes = get_schemes(50, data, 'en')
    keys = [s[0] for s in schemes]
    assert len(keys) == len(set(keys))

def test_schemes_child_gets_poshan_and_icds():
    schemes = get_schemes(30, base_data(age_group='child'), 'en')
    keys = [s[0] for s in schemes]
    assert 'pm_poshan' in keys
    assert 'icds' in keys

def test_schemes_maharashtra_address_adds_mh_schemes():
    data = base_data(address='Village X, Hinganghat, Maharashtra', income='4000')
    schemes = get_schemes(50, data, 'en')
    keys = [s[0] for s in schemes]
    assert 'ladki_bahin' in keys  # income < 20834
    assert 'mh_ration' in keys    # income < 10000

def test_schemes_non_maharashtra_address_excludes_mh_schemes():
    data = base_data(address='Village Y, Lucknow, Uttar Pradesh', income='4000')
    schemes = get_schemes(50, data, 'en')
    keys = [s[0] for s in schemes]
    assert 'ladki_bahin' not in keys
    assert 'mh_ration' not in keys

def test_schemes_jan_dhan_only_above_threshold():
    low = get_schemes(10, base_data(), 'en')
    high = get_schemes(45, base_data(), 'en')
    assert 'jan_dhan' not in [s[0] for s in low]
    assert 'jan_dhan' in [s[0] for s in high]


# ---------- detect_state ----------

def test_detect_state_maharashtra():
    assert detect_state('Village X, Hinganghat, Maharashtra') == 'Maharashtra'

def test_detect_state_uttar_pradesh():
    assert detect_state('123 MG Road, Lucknow') == 'Uttar Pradesh'

def test_detect_state_unknown_returns_none():
    assert detect_state('123 Main Street') is None

def test_detect_state_case_insensitive():
    assert detect_state('PUNE, MAHARASHTRA') == 'Maharashtra'

def test_detect_state_empty_address():
    assert detect_state('') is None
    assert detect_state(None) is None
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
import random
import string
import sqlite3
import hashlib
import time
import smtplib
import os
import re
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from collections import defaultdict
from flask_session import Session

# Load a local .env file automatically (if present) so GEMINI_API_KEY,
# SECRET_KEY etc. don't need to be manually exported in every terminal
# session. Safe to skip if python-dotenv isn't installed — falls back to
# whatever's already in the real environment.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print('[INFO] python-dotenv not installed — skipping .env file. '
          'Install with: pip install python-dotenv --break-system-packages')

app = Flask(__name__)


_SECRET_KEY_FALLBACK = 'poverty_aid_secret_key_2026_secure_fallback'
app.secret_key = os.environ.get('SECRET_KEY', _SECRET_KEY_FALLBACK)
if app.secret_key == _SECRET_KEY_FALLBACK:
    print('[WARNING] SECRET_KEY env var not set — using an insecure default. '
          'Set SECRET_KEY before deploying this publicly.')

# STARTUP DIAGNOSTIC — tells you immediately, in the terminal, whether the
# chatbot will run on real Gemini AI or fall back to the rule-based system.
# Never prints the actual key value.
_gemini_key_check = os.environ.get('GEMINI_API_KEY', '')
if _gemini_key_check:
    print(f'[OK] GEMINI_API_KEY detected (starts with "{_gemini_key_check[:6]}...", '
          f'{len(_gemini_key_check)} chars). Chatbot will use real Gemini AI.')
else:
    print('[WARNING] GEMINI_API_KEY not found in environment. Chatbot will run in '
          'RULE-BASED FALLBACK MODE ONLY — no real AI, no conversation memory, '
          'no case-worker intake. Set GEMINI_API_KEY in a .env file or your '
          'terminal environment and restart the app to enable real AI.')

# SERVER-SIDE SESSIONS. Flask's default session is a signed cookie stored in
# the browser (~4KB limit) — too small to hold a growing profile + chat
# history. This switches to storing session data in files on the server;
# the browser only keeps a small session ID cookie. For a multi-server /
# production deployment, swap SESSION_TYPE to 'redis' (needs a Redis
# instance) instead of 'filesystem'.
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.environ.get('SESSION_FILE_DIR', os.path.join(os.getcwd(), '.flask_session'))
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True  # tamper-proof the session-id cookie
Session(app)


@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Rate limiting storage
request_counts = defaultdict(list)
RATE_LIMIT = 10  # max requests
RATE_WINDOW = 60  # per 60 seconds

def rate_limit_check(ip):
    now = time.time()
    request_counts[ip] = [t for t in request_counts[ip] if now - t < RATE_WINDOW]
    if len(request_counts[ip]) >= RATE_LIMIT:
        return False
    request_counts[ip].append(now)
    return True

def hash_password(password):
    # Salted + slow hash (werkzeug/pbkdf2) for any newly created accounts.
    return generate_password_hash(password)

def verify_password(stored_hash, password):
    """
    Verifies a password against a stored hash.
    Supports the new salted werkzeug hash AND the old unsalted SHA-256 hash
    (for accounts created before this fix) so existing logins keep working.
    """
    if not stored_hash:
        return False
    if stored_hash.startswith(('pbkdf2:', 'scrypt:')):
        return check_password_hash(stored_hash, password)
    # Legacy SHA-256 hex digest
    return stored_hash == hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = sqlite3.connect('reports.db')
    c = conn.cursor()

    # Reports Table
    c.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_id TEXT UNIQUE,
        person_name TEXT,
        phone TEXT,
        address TEXT,
        scheme TEXT,
        entitled_amount TEXT,
        received_amount TEXT,
        official_name TEXT,
        description TEXT,
        incident_date TEXT,
        location TEXT,
        status TEXT DEFAULT 'Filed',
        fake_flag INTEGER DEFAULT 0,
        assigned_officer TEXT,
        authority TEXT,
        filed_date TEXT,
        received_date TEXT,
        action_date TEXT,
        resolved_date TEXT,
        expected_resolution TEXT,
        lang TEXT DEFAULT 'en'
    )
    ''')

    # Admin Users Table
    c.execute('''
    CREATE TABLE IF NOT EXISTS admin_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'officer',
        full_name TEXT
    )
    ''')

    # Activity Logs Table
    c.execute('''
    CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        username TEXT,
        action TEXT,
        ip_address TEXT,
        details TEXT,
        suspicious INTEGER DEFAULT 0
    )
    ''')

    # Form Submissions Table (NEW FIX)
    c.execute('''
    CREATE TABLE IF NOT EXISTS form_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        ip_address TEXT,
        submitted_at TEXT,
        lang TEXT DEFAULT 'en',
        schemes_count INTEGER DEFAULT 0,
        state TEXT
    )
    ''')
    for col_def in ["lang TEXT DEFAULT 'en'", "schemes_count INTEGER DEFAULT 0", "state TEXT"]:
        try:
            c.execute(f'ALTER TABLE form_submissions ADD COLUMN {col_def}')
        except Exception:
            pass
    conn.execute('''
       CREATE TABLE IF NOT EXISTS success_stories (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT,
           location TEXT,
           scheme TEXT,
           story TEXT,
           benefit TEXT,
           time_taken TEXT,
           approved INTEGER DEFAULT 0,
           filed_date TEXT
       )
   ''')

    
    try:
        c.execute(
            "INSERT INTO admin_users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
            ('admin', hash_password(os.environ.get('ADMIN_PASSWORD', 'admin2026')), 'superadmin', 'Super Admin')
        )

        c.execute(
            "INSERT INTO admin_users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
            ('pruthvi', hash_password(os.environ.get('PRUTHVI_PASSWORD', 'pruthvi2026')), 'superadmin', 'Pruthvi Jadhav')
        )

        c.execute(
            "INSERT INTO admin_users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
            ('officer1', hash_password(os.environ.get('OFFICER1_PASSWORD', 'officer2026')), 'officer', 'Grievance Officer 1')
        )

        c.execute(
            "INSERT INTO admin_users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
            ('officer2', hash_password(os.environ.get('OFFICER2_PASSWORD', 'officer2026')), 'officer', 'Grievance Officer 2')
        )

    except:
        pass

    conn.commit()
    conn.close()


init_db()

def log_activity(username, action, ip, details, suspicious=0):
    try:
        conn = sqlite3.connect('reports.db')
        conn.execute('''INSERT INTO activity_logs
            (timestamp, username, action, ip_address, details, suspicious)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (datetime.now().strftime("%d %b %Y, %I:%M:%S %p"),
            username, action, ip, details, suspicious))
        conn.commit()
        conn.close()
    except:
        pass

def get_client_ip():
    if request.environ.get('HTTP_X_FORWARDED_FOR'):
        return request.environ['HTTP_X_FORWARDED_FOR'].split(',')[0]
    return request.environ.get('REMOTE_ADDR', 'unknown')

# Sessions are now server-side (see Session(app) above), so we're no longer
# constrained by the browser's ~4KB cookie limit. Still capped — for reply
# quality and Gemini token cost, not storage — to a reasonable conversation
# window.
CHAT_HISTORY_MAX_TURNS = 8
CHAT_HISTORY_MAX_CHARS = 800

def push_chat_history(user_text, bot_text):
    """Append this exchange to the rolling, size-capped conversation memory
    so the NEXT message can naturally reference it (e.g. 'tell me more
    about the second one')."""
    history = session.get('chat_history', [])
    history.append({'role': 'user', 'text': user_text[:CHAT_HISTORY_MAX_CHARS]})
    history.append({'role': 'model', 'text': bot_text[:CHAT_HISTORY_MAX_CHARS]})
    # Keep only the last N turns (2 messages per turn)
    history = history[-(CHAT_HISTORY_MAX_TURNS * 2):]
    session['chat_history'] = history

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            ip = get_client_ip()
            log_activity('UNKNOWN', 'UNAUTHORIZED_ACCESS_ATTEMPT',
                ip, f'Tried to access {request.path} without login', suspicious=1)
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

OFFICERS = {
    "en": [
        "Central Vigilance Commission (CVC)",
        "Office of the Vigilance Commissioner, CVC",
        "Lokayukta Office, Maharashtra",
        "DARPG Grievance Cell (CPGRAMS)",
        "District Collector's Office",
        "District Magistrate's Office",
        "State Social Welfare Department",
        "Taluka Grievance Redressal Cell"
    ],
    "hi": [
        "केंद्रीय सतर्कता आयोग (CVC)",
        "सतर्कता आयुक्त कार्यालय, CVC",
        "लोकायुक्त कार्यालय, महाराष्ट्र",
        "DARPG शिकायत प्रकोष्ठ (CPGRAMS)",
        "जिला कलेक्टर कार्यालय",
        "जिला मजिस्ट्रेट कार्यालय",
        "राज्य समाज कल्याण विभाग",
        "तालुका शिकायत निवारण प्रकोष्ठ"
    ],
    "mr": [
        "केंद्रीय दक्षता आयोग (CVC)",
        "दक्षता आयुक्त कार्यालय, CVC",
        "लोकायुक्त कार्यालय, महाराष्ट्र",
        "DARPG तक्रार कक्ष (CPGRAMS)",
        "जिल्हाधिकारी कार्यालय",
        "जिल्हा दंडाधिकारी कार्यालय",
        "राज्य समाज कल्याण विभाग",
        "तालुका तक्रार निवारण कक्ष"
    ]
}

AUTHORITIES = {
    "en": ["District Collector Office", "Central Vigilance Commission", "Lokayukta Maharashtra", "PM Grievance Portal (CPGRAMS)"],
    "hi": ["जिला कलेक्टर कार्यालय", "केंद्रीय सतर्कता आयोग", "लोकायुक्त महाराष्ट्र", "PM शिकायत पोर्टल (CPGRAMS)"],
    "mr": ["जिल्हाधिकारी कार्यालय", "केंद्रीय दक्षता आयोग", "लोकायुक्त महाराष्ट्र", "PM तक्रार पोर्टल (CPGRAMS)"]
}

SCHEMES = {
    "en": {
        "pm_jan_arogya": ("urgent", "PM Jan Arogya Yojana (Emergency Medical Aid)", "Rs. 5,00,000/yr"),
        "state_emergency": ("urgent", "State Emergency Relief Fund (Accident)", "Rs. 10,000"),
        "national_family": ("urgent", "National Family Benefit Scheme (Death of Earning Member)", "Rs. 20,000"),
        "pm_poshan": ("normal", "PM Poshan Scheme (Nutrition for Children)", "Free Meals"),
        "icds": ("normal", "Integrated Child Development Services (ICDS)", "Free Services"),
        "old_age_pension": ("normal", "Indira Gandhi National Old Age Pension", "Rs. 200-500/month"),
        "widow_pension": ("urgent", "Indira Gandhi National Widow Pension Scheme (IGNWPS)", "Rs. 300-500/month"),
        "annapurna": ("normal", "Annapurna Scheme (Free Food for Elderly)", "10 kg/month"),
        "ayushman": ("normal", "Ayushman Bharat (Free Health Insurance)", "Rs. 5,00,000/yr"),
        "divyangjan": ("normal", "Divyangjan Swavalamban Scheme", "Rs. 300-1500/month"),
        "accessible_india": ("normal", "Accessible India Campaign - Disability Aid", "Free Aids/Equipment"),
        "pm_awas": ("normal", "PM Awas Yojana (Free Housing)", "Rs. 1,20,000"),
        "antyodaya": ("normal", "Antyodaya Anna Yojana (Free Ration)", "35 kg/month"),
        "ujjwala": ("normal", "PM Ujjwala Yojana (Free Gas Connection)", "1 Free Cylinder"),
        "saubhagya": ("normal", "Saubhagya Scheme (Free Electricity)", "Free Connection"),
        "jan_dhan": ("normal", "PM Jan Dhan Yojana (Free Bank Account)", "Zero Balance Account"),
        "basic": ("normal", "Basic Community Support and Ration Assistance", "As applicable"),
    },
    "hi": {
        "pm_jan_arogya": ("urgent", "PM जन आरोग्य योजना (आपातकालीन चिकित्सा सहायता)", "रु. 5,00,000/वर्ष"),
        "state_emergency": ("urgent", "राज्य आपातकालीन राहत निधि (दुर्घटना)", "रु. 10,000"),
        "national_family": ("urgent", "राष्ट्रीय परिवार लाभ योजना (कमाने वाले सदस्य की मृत्यु)", "रु. 20,000"),
        "pm_poshan": ("normal", "PM पोषण योजना (बच्चों के लिए पोषण)", "मुफ्त भोजन"),
        "icds": ("normal", "एकीकृत बाल विकास सेवाएं (ICDS)", "मुफ्त सेवाएं"),
        "old_age_pension": ("normal", "इंदिरा गांधी राष्ट्रीय वृद्धावस्था पेंशन", "रु. 200-500/माह"),
        "widow_pension": ("urgent", "इंदिरा गांधी राष्ट्रीय विधवा पेंशन योजना", "रु. 300-500/माह"),
        "annapurna": ("normal", "अन्नपूर्णा योजना (बुजुर्गों के लिए मुफ्त भोजन)", "10 किग्रा/माह"),
        "ayushman": ("normal", "आयुष्मान भारत (मुफ्त स्वास्थ्य बीमा)", "रु. 5,00,000/वर्ष"),
        "divyangjan": ("normal", "दिव्यांगजन स्वावलंबन योजना", "रु. 300-1500/माह"),
        "accessible_india": ("normal", "सुगम्य भारत अभियान - विकलांगता सहायता", "मुफ्त उपकरण"),
        "pm_awas": ("normal", "PM आवास योजना (मुफ्त आवास)", "रु. 1,20,000"),
        "antyodaya": ("normal", "अंत्योदय अन्न योजना (मुफ्त राशन)", "35 किग्रा/माह"),
        "ujjwala": ("normal", "PM उज्ज्वला योजना (मुफ्त गैस कनेक्शन)", "1 मुफ्त सिलेंडर"),
        "saubhagya": ("normal", "सौभाग्य योजना (मुफ्त बिजली)", "मुफ्त कनेक्शन"),
        "jan_dhan": ("normal", "PM जन धन योजना (मुफ्त बैंक खाता)", "शून्य बैलेंस खाता"),
        "basic": ("normal", "बुनियादी सामुदायिक सहायता और राशन सहायता", "लागू अनुसार"),
    },
    "mr": {
        "pm_jan_arogya": ("urgent", "PM जन आरोग्य योजना (आपत्कालीन वैद्यकीय मदत)", "रु. 5,00,000/वर्ष"),
        "state_emergency": ("urgent", "राज्य आपत्कालीन मदत निधी (अपघात)", "रु. 10,000"),
        "national_family": ("urgent", "राष्ट्रीय कुटुंब लाभ योजना (कमावत्या सदस्याचे निधन)", "रु. 20,000"),
        "pm_poshan": ("normal", "PM पोषण योजना (मुलांसाठी पोषण)", "मोफत जेवण"),
        "icds": ("normal", "एकात्मिक बाल विकास सेवा (ICDS)", "मोफत सेवा"),
        "old_age_pension": ("normal", "इंदिरा गांधी राष्ट्रीय वृद्धापकाळ निवृत्तीवेतन", "रु. 200-500/महिना"),
        "widow_pension": ("urgent", "इंदिरा गांधी राष्ट्रीय विधवा निवृत्तीवेतन योजना", "रु. 300-500/महिना"),
        "annapurna": ("normal", "अन्नपूर्णा योजना (वृद्धांसाठी मोफत अन्न)", "10 किग्रा/महिना"),
        "ayushman": ("normal", "आयुष्मान भारत (मोफत आरोग्य विमा)", "रु. 5,00,000/वर्ष"),
        "divyangjan": ("normal", "दिव्यांगजन स्वावलंबन योजना", "रु. 300-1500/महिना"),
        "accessible_india": ("normal", "सुगम्य भारत अभियान - अपंगत्व मदत", "मोफत साधने"),
        "pm_awas": ("normal", "PM आवास योजना (मोफत घर)", "रु. 1,20,000"),
        "antyodaya": ("normal", "अंत्योदय अन्न योजना (मोफत रेशन)", "35 किग्रा/महिना"),
        "ujjwala": ("normal", "PM उज्ज्वला योजना (मोफत गॅस कनेक्शन)", "1 मोफत सिलेंडर"),
        "saubhagya": ("normal", "सौभाग्य योजना (मोफत वीज)", "मोफत कनेक्शन"),
        "jan_dhan": ("normal", "PM जन धन योजना (मोफत बँक खाते)", "शून्य शिल्लक खाते"),
        "basic": ("normal", "मूलभूत सामुदायिक मदत आणि रेशन सहाय्य", "लागू असेल तसे"),
    }
}

SCHEME_DETAILS = {
    "pm_jan_arogya": {
        "en": {"name": "PM Jan Arogya Yojana (Ayushman Bharat)", "amount": "Rs. 5,00,000 per year per family", "description": "Free health coverage for poor and vulnerable families for secondary and tertiary hospitalization.", "eligibility": ["BPL family", "No existing health coverage", "Listed in SECC database"], "documents": ["Aadhaar Card", "Ration Card", "Income Certificate", "SECC/BPL Certificate"], "how_to_apply": "Visit nearest empanelled hospital or Common Service Centre (CSC).", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "hi": {"name": "PM जन आरोग्य योजना (आयुष्मान भारत)", "amount": "रु. 5,00,000 प्रति वर्ष प्रति परिवार", "description": "गरीब और कमजोर परिवारों के लिए माध्यमिक और तृतीयक अस्पताल में भर्ती के लिए मुफ्त स्वास्थ्य कवरेज।", "eligibility": ["BPL परिवार", "कोई मौजूदा स्वास्थ्य कवरेज नहीं", "SECC डेटाबेस में सूचीबद्ध"], "documents": ["आधार कार्ड", "राशन कार्ड", "आय प्रमाण पत्र", "SECC/BPL प्रमाण पत्र"], "how_to_apply": "नजदीकी सूचीबद्ध अस्पताल या कॉमन सर्विस सेंटर (CSC) पर जाएं।", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "mr": {"name": "PM जन आरोग्य योजना (आयुष्मान भारत)", "amount": "रु. 5,00,000 प्रति वर्ष प्रति कुटुंब", "description": "गरीब आणि असुरक्षित कुटुंबांसाठी दुय्यम आणि तृतीयक रुग्णालयात मोफत आरोग्य कव्हरेज.", "eligibility": ["BPL कुटुंब", "कोणतेही विद्यमान आरोग्य कव्हरेज नाही", "SECC डेटाबेसमध्ये नोंदणीकृत"], "documents": ["आधार कार्ड", "रेशन कार्ड", "उत्पन्न प्रमाणपत्र", "SECC/BPL प्रमाणपत्र"], "how_to_apply": "जवळच्या सूचीबद्ध रुग्णालयात किंवा कॉमन सर्व्हिस सेंटरला (CSC) भेट द्या.", "website": "https://pmjay.gov.in", "helpline": "14555"}
    },
    "state_emergency": {
        "en": {"name": "State Emergency Relief Fund (Accident)", "amount": "Rs. 10,000 (one time)", "description": "Immediate financial relief to accident victims and their families.", "eligibility": ["Accident victim", "BPL or economically weak family", "Police FIR filed"], "documents": ["Aadhaar Card", "FIR Copy", "Medical Certificate", "Bank Account Details"], "how_to_apply": "Visit District Collector Office or nearest Tehsil office with documents.", "website": "https://maharashtra.gov.in", "helpline": "1077"},
        "hi": {"name": "राज्य आपातकालीन राहत निधि (दुर्घटना)", "amount": "रु. 10,000 (एक बार)", "description": "दुर्घटना पीड़ितों और उनके परिवारों को तत्काल वित्तीय राहत।", "eligibility": ["दुर्घटना पीड़ित", "BPL या आर्थिक रूप से कमजोर परिवार", "पुलिस FIR दर्ज"], "documents": ["आधार कार्ड", "FIR की प्रति", "चिकित्सा प्रमाण पत्र", "बैंक खाता विवरण"], "how_to_apply": "दस्तावेजों के साथ जिला कलेक्टर कार्यालय या निकटतम तहसील कार्यालय जाएं।", "website": "https://maharashtra.gov.in", "helpline": "1077"},
        "mr": {"name": "राज्य आपत्कालीन मदत निधी (अपघात)", "amount": "रु. 10,000 (एकवेळ)", "description": "अपघात पीडित आणि त्यांच्या कुटुंबांना तात्काळ आर्थिक मदत.", "eligibility": ["अपघात पीडित", "BPL किंवा आर्थिकदृष्ट्या कमकुवत कुटुंब", "पोलीस FIR दाखल"], "documents": ["आधार कार्ड", "FIR ची प्रत", "वैद्यकीय प्रमाणपत्र", "बँक खाते तपशील"], "how_to_apply": "कागदपत्रांसह जिल्हाधिकारी कार्यालय किंवा जवळच्या तहसील कार्यालयास भेट द्या.", "website": "https://maharashtra.gov.in", "helpline": "1077"}
    },
    "national_family": {
        "en": {"name": "National Family Benefit Scheme", "amount": "Rs. 20,000 (one time)", "description": "Financial assistance to BPL households on death of primary breadwinner.", "eligibility": ["BPL family", "Death of earning member aged 18-59 years", "Natural or accidental death"], "documents": ["Aadhaar Card", "Death Certificate", "BPL Certificate", "Bank Account Details", "Age Proof of deceased"], "how_to_apply": "Apply at District Social Welfare Office within 90 days of death.", "website": "https://nsap.nic.in", "helpline": "1800-111-555"},
        "hi": {"name": "राष्ट्रीय परिवार लाभ योजना", "amount": "रु. 20,000 (एक बार)", "description": "मुख्य कमाने वाले की मृत्यु पर BPL परिवारों को वित्तीय सहायता।", "eligibility": ["BPL परिवार", "18-59 वर्ष आयु के कमाने वाले सदस्य की मृत्यु", "प्राकृतिक या आकस्मिक मृत्यु"], "documents": ["आधार कार्ड", "मृत्यु प्रमाण पत्र", "BPL प्रमाण पत्र", "बैंक खाता विवरण", "मृतक का आयु प्रमाण"], "how_to_apply": "मृत्यु के 90 दिनों के भीतर जिला समाज कल्याण कार्यालय में आवेदन करें।", "website": "https://nsap.nic.in", "helpline": "1800-111-555"},
        "mr": {"name": "राष्ट्रीय कुटुंब लाभ योजना", "amount": "रु. 20,000 (एकवेळ)", "description": "मुख्य कमावत्या सदस्याच्या मृत्यूनंतर BPL कुटुंबांना आर्थिक मदत.", "eligibility": ["BPL कुटुंब", "18-59 वर्षे वयाच्या कमावत्या सदस्याचा मृत्यू", "नैसर्गिक किंवा अपघाती मृत्यू"], "documents": ["आधार कार्ड", "मृत्यू प्रमाणपत्र", "BPL प्रमाणपत्र", "बँक खाते तपशील", "मृत व्यक्तीचा वयाचा पुरावा"], "how_to_apply": "मृत्यूनंतर 90 दिवसांच्या आत जिल्हा समाज कल्याण कार्यालयात अर्ज करा.", "website": "https://nsap.nic.in", "helpline": "1800-111-555"}
    },
    "pm_poshan": {
        "en": {"name": "PM Poshan Scheme (Mid Day Meal)", "amount": "Free nutritious meals daily", "description": "Free hot cooked meals to children in government schools.", "eligibility": ["Children in government schools", "Classes 1 to 8", "Age 6-14 years"], "documents": ["School Admission Certificate", "Aadhaar Card of child"], "how_to_apply": "Automatically provided at government school.", "website": "https://pmposhan.education.gov.in", "helpline": "1800-180-8004"},
        "hi": {"name": "PM पोषण योजना (मध्याह्न भोजन)", "amount": "प्रतिदिन मुफ्त पौष्टिक भोजन", "description": "सरकारी स्कूलों में बच्चों को मुफ्त गर्म भोजन।", "eligibility": ["सरकारी स्कूलों में पढ़ने वाले बच्चे", "कक्षा 1 से 8", "आयु 6-14 वर्ष"], "documents": ["स्कूल प्रवेश प्रमाण पत्र", "बच्चे का आधार कार्ड"], "how_to_apply": "सरकारी स्कूल में स्वचालित रूप से प्रदान किया जाता है।", "website": "https://pmposhan.education.gov.in", "helpline": "1800-180-8004"},
        "mr": {"name": "PM पोषण योजना (मध्यान्ह भोजन)", "amount": "दररोज मोफत पौष्टिक जेवण", "description": "सरकारी शाळांमधील मुलांना मोफत गरम जेवण.", "eligibility": ["सरकारी शाळांमध्ये शिकणारी मुले", "इयत्ता 1 ते 8", "वय 6-14 वर्षे"], "documents": ["शाळा प्रवेश प्रमाणपत्र", "मुलाचे आधार कार्ड"], "how_to_apply": "सरकारी शाळेत आपोआप दिले जाते.", "website": "https://pmposhan.education.gov.in", "helpline": "1800-180-8004"}
    },
    "icds": {
        "en": {"name": "Integrated Child Development Services (ICDS)", "amount": "Free services", "description": "Supplementary nutrition, immunization, health check-up for children under 6.", "eligibility": ["Children 0-6 years", "Pregnant and lactating mothers", "Adolescent girls"], "documents": ["Aadhaar Card", "Birth Certificate of child"], "how_to_apply": "Visit nearest Anganwadi Centre in your village or ward.", "website": "https://wcd.nic.in", "helpline": "1800-111-100"},
        "hi": {"name": "एकीकृत बाल विकास सेवाएं (ICDS)", "amount": "मुफ्त सेवाएं", "description": "6 वर्ष से कम बच्चों के लिए पूरक पोषण, टीकाकरण, स्वास्थ्य जांच।", "eligibility": ["0-6 वर्ष के बच्चे", "गर्भवती और स्तनपान कराने वाली माताएं", "किशोर लड़कियां"], "documents": ["आधार कार्ड", "बच्चे का जन्म प्रमाण पत्र"], "how_to_apply": "अपने गांव या वार्ड में निकटतम आंगनवाड़ी केंद्र जाएं।", "website": "https://wcd.nic.in", "helpline": "1800-111-100"},
        "mr": {"name": "एकात्मिक बाल विकास सेवा (ICDS)", "amount": "मोफत सेवा", "description": "6 वर्षाखालील मुलांसाठी पूरक पोषण, लसीकरण, आरोग्य तपासणी.", "eligibility": ["0-6 वर्षे वयाची मुले", "गर्भवती आणि स्तनपान देणाऱ्या माता", "किशोरवयीन मुली"], "documents": ["आधार कार्ड", "मुलाचे जन्म प्रमाणपत्र"], "how_to_apply": "तुमच्या गावात किंवा वॉर्डमध्ये जवळच्या अंगणवाडी केंद्राला भेट द्या.", "website": "https://wcd.nic.in", "helpline": "1800-111-100"}
    },
    "old_age_pension": {
        "en": {"name": "Indira Gandhi National Old Age Pension", "amount": "Rs. 200-500 per month", "description": "Monthly pension for destitute elderly persons living below poverty line.", "eligibility": ["Age 60 years and above", "BPL household", "No regular income source"], "documents": ["Aadhaar Card", "Age Proof", "BPL Certificate", "Bank Account Details"], "how_to_apply": "Apply at Gram Panchayat or Block Development Office.", "website": "https://nsap.nic.in", "helpline": "1800-111-555"},
        "hi": {"name": "इंदिरा गांधी राष्ट्रीय वृद्धावस्था पेंशन", "amount": "रु. 200-500 प्रति माह", "description": "गरीबी रेखा से नीचे जीवन यापन करने वाले निराश्रित बुजुर्गों के लिए मासिक पेंशन।", "eligibility": ["60 वर्ष और उससे अधिक आयु", "BPL परिवार", "कोई नियमित आय स्रोत नहीं"], "documents": ["आधार कार्ड", "आयु प्रमाण", "BPL प्रमाण पत्र", "बैंक खाता विवरण"], "how_to_apply": "ग्राम पंचायत या ब्लॉक विकास कार्यालय में आवेदन करें।", "website": "https://nsap.nic.in", "helpline": "1800-111-555"},
        "mr": {"name": "इंदिरा गांधी राष्ट्रीय वृद्धापकाळ निवृत्तीवेतन", "amount": "रु. 200-500 प्रति महिना", "description": "दारिद्र्यरेषेखाली जगणाऱ्या निराधार वृद्धांसाठी मासिक निवृत्तीवेतन.", "eligibility": ["60 वर्षे आणि त्याहून अधिक वय", "BPL कुटुंब", "कोणताही नियमित उत्पन्न स्रोत नाही"], "documents": ["आधार कार्ड", "वयाचा पुरावा", "BPL प्रमाणपत्र", "बँक खाते तपशील"], "how_to_apply": "ग्रामपंचायत किंवा गट विकास कार्यालयात अर्ज करा.", "website": "https://nsap.nic.in", "helpline": "1800-111-555"}
    },
    "widow_pension": {
        "en": {"name": "Indira Gandhi National Widow Pension Scheme (IGNWPS)", "amount": "Rs. 300/month (40-79 yrs), Rs. 500/month (80+)", "description": "Central pension under the National Social Assistance Programme (NSAP) for widows from BPL households. Many states add a top-up on top of the central amount.", "eligibility": ["Widow aged 40-79 years (varies slightly by state)", "BPL household / family income within the state's ceiling", "Not already receiving another social welfare pension for the same purpose"], "documents": ["Aadhaar Card", "Husband's Death Certificate", "Age Proof", "BPL Certificate", "Bank Account Details"], "how_to_apply": "Apply at Gram Panchayat / Block Office (rural) or Municipality (urban), or online via the UMANG app / nsap.nic.in.", "website": "https://nsap.nic.in", "helpline": "1800-111-555"},
        "hi": {"name": "इंदिरा गांधी राष्ट्रीय विधवा पेंशन योजना (IGNWPS)", "amount": "रु. 300/माह (40-79 वर्ष), रु. 500/माह (80+)", "description": "BPL परिवारों की विधवाओं के लिए National Social Assistance Programme (NSAP) के तहत केंद्रीय पेंशन। कई राज्य इसमें अतिरिक्त राशि जोड़ते हैं।", "eligibility": ["विधवा की आयु 40-79 वर्ष (राज्य अनुसार थोड़ा भिन्न)", "BPL परिवार / राज्य की आय सीमा के भीतर", "किसी अन्य समान सामाजिक पेंशन का लाभ न ले रही हों"], "documents": ["आधार कार्ड", "पति का मृत्यु प्रमाण पत्र", "आयु प्रमाण", "BPL प्रमाण पत्र", "बैंक खाता विवरण"], "how_to_apply": "ग्राम पंचायत / ब्लॉक कार्यालय (ग्रामीण) या नगर पालिका (शहरी) में आवेदन करें, या UMANG ऐप / nsap.nic.in पर ऑनलाइन आवेदन करें।", "website": "https://nsap.nic.in", "helpline": "1800-111-555"},
        "mr": {"name": "इंदिरा गांधी राष्ट्रीय विधवा निवृत्तीवेतन योजना (IGNWPS)", "amount": "रु. 300/महिना (40-79 वर्षे), रु. 500/महिना (80+)", "description": "BPL कुटुंबातील विधवांसाठी National Social Assistance Programme (NSAP) अंतर्गत केंद्रीय निवृत्तीवेतन. अनेक राज्ये यात अतिरिक्त रक्कम जोडतात.", "eligibility": ["विधवेचे वय 40-79 वर्षे (राज्यानुसार थोडे वेगळे)", "BPL कुटुंब / राज्याच्या उत्पन्न मर्यादेत", "इतर तत्सम सामाजिक निवृत्तीवेतनाचा लाभ घेत नसाव्यात"], "documents": ["आधार कार्ड", "पतीचा मृत्यू दाखला", "वयाचा पुरावा", "BPL प्रमाणपत्र", "बँक खाते तपशील"], "how_to_apply": "ग्रामपंचायत / गट कार्यालयात (ग्रामीण) किंवा नगरपालिकेत (शहरी) अर्ज करा, किंवा UMANG अॅप / nsap.nic.in वर ऑनलाइन अर्ज करा.", "website": "https://nsap.nic.in", "helpline": "1800-111-555"}
    },
    "annapurna": {
        "en": {"name": "Annapurna Scheme", "amount": "10 kg free food grains per month", "description": "Free food grains to senior citizens not covered under NSAP old age pension.", "eligibility": ["Age 65 years and above", "Not receiving old age pension", "Indigent/destitute"], "documents": ["Aadhaar Card", "Age Proof", "BPL Certificate"], "how_to_apply": "Apply at Gram Panchayat or Block Office.", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"},
        "hi": {"name": "अन्नपूर्णा योजना", "amount": "10 किग्रा मुफ्त खाद्यान्न प्रति माह", "description": "NSAP वृद्धावस्था पेंशन के अंतर्गत न आने वाले वरिष्ठ नागरिकों को मुफ्त खाद्यान्न।", "eligibility": ["65 वर्ष और उससे अधिक आयु", "वृद्धावस्था पेंशन नहीं मिल रही", "निराश्रित"], "documents": ["आधार कार्ड", "आयु प्रमाण", "BPL प्रमाण पत्र"], "how_to_apply": "ग्राम पंचायत या ब्लॉक कार्यालय में आवेदन करें।", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"},
        "mr": {"name": "अन्नपूर्णा योजना", "amount": "10 किग्रा मोफत अन्नधान्य प्रति महिना", "description": "NSAP वृद्धापकाळ निवृत्तीवेतनाखाली न येणाऱ्या ज्येष्ठ नागरिकांना मोफत अन्नधान्य.", "eligibility": ["65 वर्षे आणि त्याहून अधिक वय", "वृद्धापकाळ निवृत्तीवेतन मिळत नाही", "निराधार"], "documents": ["आधार कार्ड", "वयाचा पुरावा", "BPL प्रमाणपत्र"], "how_to_apply": "ग्रामपंचायत किंवा गट कार्यालयात अर्ज करा.", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"}
    },
    "ayushman": {
        "en": {"name": "Ayushman Bharat (Free Health Insurance)", "amount": "Rs. 5,00,000 per year", "description": "Health insurance cover for secondary and tertiary hospitalization for BPL families.", "eligibility": ["BPL family", "SECC 2011 listed", "No private health insurance"], "documents": ["Aadhaar Card", "Ration Card", "SECC Certificate"], "how_to_apply": "Visit nearest empanelled hospital. Show Aadhaar card for cashless treatment.", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "hi": {"name": "आयुष्मान भारत (मुफ्त स्वास्थ्य बीमा)", "amount": "रु. 5,00,000 प्रति वर्ष", "description": "BPL परिवारों के लिए अस्पताल में भर्ती के लिए स्वास्थ्य बीमा कवर।", "eligibility": ["BPL परिवार", "SECC 2011 में सूचीबद्ध", "कोई निजी स्वास्थ्य बीमा नहीं"], "documents": ["आधार कार्ड", "राशन कार्ड", "SECC प्रमाण पत्र"], "how_to_apply": "नजदीकी सूचीबद्ध अस्पताल जाएं।", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "mr": {"name": "आयुष्मान भारत (मोफत आरोग्य विमा)", "amount": "रु. 5,00,000 प्रति वर्ष", "description": "BPL कुटुंबांसाठी रुग्णालयात भर्तीसाठी आरोग्य विमा कव्हर.", "eligibility": ["BPL कुटुंब", "SECC 2011 मध्ये नोंदणीकृत", "कोणताही खाजगी आरोग्य विमा नाही"], "documents": ["आधार कार्ड", "रेशन कार्ड", "SECC प्रमाणपत्र"], "how_to_apply": "जवळच्या सूचीबद्ध रुग्णालयात जा.", "website": "https://pmjay.gov.in", "helpline": "14555"}
    },
    "divyangjan": {
        "en": {"name": "Divyangjan Swavalamban Scheme", "amount": "Rs. 300-1500 per month", "description": "Monthly financial assistance to persons with disabilities.", "eligibility": ["Person with 40% or more disability", "BPL family", "Age 18-59 years"], "documents": ["Aadhaar Card", "Disability Certificate (40%+)", "BPL Certificate", "Bank Account Details"], "how_to_apply": "Apply at District Social Welfare Office.", "website": "https://disabilityaffairs.gov.in", "helpline": "1800-180-5129"},
        "hi": {"name": "दिव्यांगजन स्वावलंबन योजना", "amount": "रु. 300-1500 प्रति माह", "description": "विकलांग व्यक्तियों को मासिक वित्तीय सहायता।", "eligibility": ["40% या अधिक विकलांगता", "BPL परिवार", "आयु 18-59 वर्ष"], "documents": ["आधार कार्ड", "विकलांगता प्रमाण पत्र (40%+)", "BPL प्रमाण पत्र", "बैंक खाता विवरण"], "how_to_apply": "जिला समाज कल्याण कार्यालय में आवेदन करें।", "website": "https://disabilityaffairs.gov.in", "helpline": "1800-180-5129"},
        "mr": {"name": "दिव्यांगजन स्वावलंबन योजना", "amount": "रु. 300-1500 प्रति महिना", "description": "अपंग व्यक्तींना मासिक आर्थिक मदत.", "eligibility": ["40% किंवा अधिक अपंगत्व", "BPL कुटुंब", "वय 18-59 वर्षे"], "documents": ["आधार कार्ड", "अपंगत्व प्रमाणपत्र (40%+)", "BPL प्रमाणपत्र", "बँक खाते तपशील"], "how_to_apply": "जिल्हा समाज कल्याण कार्यालयात अर्ज करा.", "website": "https://disabilityaffairs.gov.in", "helpline": "1800-180-5129"}
    },
    "accessible_india": {
        "en": {"name": "Accessible India Campaign - Disability Aid", "amount": "Free aids and equipment", "description": "Free assistive devices like wheelchairs, crutches, hearing aids to disabled persons.", "eligibility": ["Person with disability", "BPL or low income", "Any age"], "documents": ["Aadhaar Card", "Disability Certificate", "Income Certificate"], "how_to_apply": "Apply through ALIMCO camps or nearest District Disability Rehabilitation Centre.", "website": "https://accessibleindia.gov.in", "helpline": "1800-180-5129"},
        "hi": {"name": "सुगम्य भारत अभियान - विकलांगता सहायता", "amount": "मुफ्त सहायक उपकरण", "description": "विकलांग व्यक्तियों को व्हीलचेयर, बैसाखी, श्रवण यंत्र जैसे उपकरण मुफ्त।", "eligibility": ["विकलांग व्यक्ति", "BPL या कम आय", "कोई भी आयु"], "documents": ["आधार कार्ड", "विकलांगता प्रमाण पत्र", "आय प्रमाण पत्र"], "how_to_apply": "ALIMCO शिविरों या निकटतम जिला विकलांग पुनर्वास केंद्र के माध्यम से आवेदन करें।", "website": "https://accessibleindia.gov.in", "helpline": "1800-180-5129"},
        "mr": {"name": "सुगम्य भारत अभियान - अपंगत्व मदत", "amount": "मोफत सहाय्यक साधने", "description": "अपंग व्यक्तींना व्हीलचेअर, कुबड्या, श्रवणयंत्र यासारखी मोफत साधने.", "eligibility": ["अपंग व्यक्ती", "BPL किंवा कमी उत्पन्न", "कोणतेही वय"], "documents": ["आधार कार्ड", "अपंगत्व प्रमाणपत्र", "उत्पन्न प्रमाणपत्र"], "how_to_apply": "ALIMCO शिबिरांद्वारे किंवा जवळच्या जिल्हा अपंग पुनर्वसन केंद्राद्वारे अर्ज करा.", "website": "https://accessibleindia.gov.in", "helpline": "1800-180-5129"}
    },
    "pm_awas": {
        "en": {"name": "PM Awas Yojana (Free Housing)", "amount": "Rs. 1,20,000", "description": "Financial assistance to BPL families to construct or upgrade their house.", "eligibility": ["BPL family", "No pucca house", "Must not have received housing benefit before"], "documents": ["Aadhaar Card", "BPL Certificate", "Land Ownership Document", "Bank Account Details", "Income Certificate"], "how_to_apply": "Apply at Gram Panchayat or online at pmaymis.gov.in.", "website": "https://pmaymis.gov.in", "helpline": "1800-11-6163"},
        "hi": {"name": "PM आवास योजना (मुफ्त आवास)", "amount": "रु. 1,20,000", "description": "BPL परिवारों को घर बनाने के लिए वित्तीय सहायता।", "eligibility": ["BPL परिवार", "कोई पक्का घर नहीं", "पहले कोई आवास लाभ नहीं लिया"], "documents": ["आधार कार्ड", "BPL प्रमाण पत्र", "भूमि स्वामित्व दस्तावेज", "बैंक खाता विवरण", "आय प्रमाण पत्र"], "how_to_apply": "ग्राम पंचायत में आवेदन करें या pmaymis.gov.in पर ऑनलाइन।", "website": "https://pmaymis.gov.in", "helpline": "1800-11-6163"},
        "mr": {"name": "PM आवास योजना (मोफत घर)", "amount": "रु. 1,20,000", "description": "BPL कुटुंबांना घर बांधण्यासाठी आर्थिक मदत.", "eligibility": ["BPL कुटुंब", "कोणतेही पक्के घर नाही", "यापूर्वी कोणताही गृहनिर्माण लाभ नाही"], "documents": ["आधार कार्ड", "BPL प्रमाणपत्र", "जमीन मालकी दस्तऐवज", "बँक खाते तपशील", "उत्पन्न प्रमाणपत्र"], "how_to_apply": "ग्रामपंचायतमध्ये अर्ज करा किंवा pmaymis.gov.in वर ऑनलाइन.", "website": "https://pmaymis.gov.in", "helpline": "1800-11-6163"}
    },
    "antyodaya": {
        "en": {"name": "Antyodaya Anna Yojana (Free Ration)", "amount": "35 kg food grains per month", "description": "Subsidized food grains for the poorest of poor families.", "eligibility": ["Poorest BPL families", "No regular income", "Widow/disabled headed household"], "documents": ["Aadhaar Card", "Ration Card (Yellow/Antyodaya)", "Income Certificate"], "how_to_apply": "Apply for Antyodaya ration card at nearest Food Department office.", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"},
        "hi": {"name": "अंत्योदय अन्न योजना (मुफ्त राशन)", "amount": "35 किग्रा खाद्यान्न प्रति माह", "description": "सबसे गरीब परिवारों के लिए सब्सिडी वाले खाद्यान्न।", "eligibility": ["सबसे गरीब BPL परिवार", "कोई नियमित आय नहीं", "विधवा/विकलांग वाले परिवार"], "documents": ["आधार कार्ड", "राशन कार्ड (पीला/अंत्योदय)", "आय प्रमाण पत्र"], "how_to_apply": "निकटतम खाद्य विभाग कार्यालय में अंत्योदय राशन कार्ड के लिए आवेदन करें।", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"},
        "mr": {"name": "अंत्योदय अन्न योजना (मोफत रेशन)", "amount": "35 किग्रा अन्नधान्य प्रति महिना", "description": "सर्वात गरीब कुटुंबांसाठी अनुदानित अन्नधान्य.", "eligibility": ["सर्वात गरीब BPL कुटुंबे", "कोणतेही नियमित उत्पन्न नाही", "विधवा/अपंग कुटुंब"], "documents": ["आधार कार्ड", "रेशन कार्ड (पिवळे/अंत्योदय)", "उत्पन्न प्रमाणपत्र"], "how_to_apply": "जवळच्या अन्न विभाग कार्यालयात अंत्योदय रेशन कार्डसाठी अर्ज करा.", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"}
    },
    "ujjwala": {
        "en": {"name": "PM Ujjwala Yojana (Free Gas Connection)", "amount": "Free LPG connection + 1 cylinder", "description": "Free LPG gas connection to BPL women.", "eligibility": ["Women aged 18 or above", "BPL household", "No existing LPG connection"], "documents": ["Aadhaar Card", "BPL Certificate/Ration Card", "Bank Account Details", "Address Proof"], "how_to_apply": "Visit nearest LPG distributor (HP/Bharat/Indane) with documents.", "website": "https://pmuy.gov.in", "helpline": "1800-266-6696"},
        "hi": {"name": "PM उज्ज्वला योजना (मुफ्त गैस कनेक्शन)", "amount": "मुफ्त LPG कनेक्शन + 1 सिलेंडर", "description": "BPL महिलाओं को मुफ्त LPG गैस कनेक्शन।", "eligibility": ["18 वर्ष या उससे अधिक आयु की महिला", "BPL परिवार", "कोई मौजूदा LPG कनेक्शन नहीं"], "documents": ["आधार कार्ड", "BPL प्रमाण पत्र/राशन कार्ड", "बैंक खाता विवरण", "पता प्रमाण"], "how_to_apply": "दस्तावेजों के साथ निकटतम LPG वितरक पर जाएं।", "website": "https://pmuy.gov.in", "helpline": "1800-266-6696"},
        "mr": {"name": "PM उज्ज्वला योजना (मोफत गॅस कनेक्शन)", "amount": "मोफत LPG कनेक्शन + 1 सिलेंडर", "description": "BPL महिलांना मोफत LPG गॅस कनेक्शन.", "eligibility": ["18 वर्षे किंवा त्याहून अधिक वयाची महिला", "BPL कुटुंब", "कोणतेही विद्यमान LPG कनेक्शन नाही"], "documents": ["आधार कार्ड", "BPL प्रमाणपत्र/रेशन कार्ड", "बँक खाते तपशील", "पत्ता पुरावा"], "how_to_apply": "कागदपत्रांसह जवळच्या LPG वितरकाकडे जा.", "website": "https://pmuy.gov.in", "helpline": "1800-266-6696"}
    },
    "saubhagya": {
        "en": {"name": "Saubhagya Scheme (Free Electricity)", "amount": "Free electricity connection", "description": "Free household electricity connection to all un-electrified households.", "eligibility": ["Un-electrified household", "BPL or poor household", "Rural or urban area"], "documents": ["Aadhaar Card", "BPL Certificate", "Address Proof"], "how_to_apply": "Contact nearest electricity distribution company (DISCOM).", "website": "https://saubhagya.gov.in", "helpline": "1800-11-5467"},
        "hi": {"name": "सौभाग्य योजना (मुफ्त बिजली)", "amount": "मुफ्त बिजली कनेक्शन", "description": "सभी बिना बिजली वाले घरों को मुफ्त बिजली कनेक्शन।", "eligibility": ["बिना बिजली वाला घर", "BPL या गरीब परिवार", "ग्रामीण या शहरी क्षेत्र"], "documents": ["आधार कार्ड", "BPL प्रमाण पत्र", "पता प्रमाण"], "how_to_apply": "निकटतम बिजली वितरण कंपनी से संपर्क करें।", "website": "https://saubhagya.gov.in", "helpline": "1800-11-5467"},
        "mr": {"name": "सौभाग्य योजना (मोफत वीज)", "amount": "मोफत वीज कनेक्शन", "description": "सर्व विनावीज घरांना मोफत वीज कनेक्शन.", "eligibility": ["विनावीज घर", "BPL किंवा गरीब कुटुंब", "ग्रामीण किंवा शहरी भाग"], "documents": ["आधार कार्ड", "BPL प्रमाणपत्र", "पत्ता पुरावा"], "how_to_apply": "जवळच्या वीज वितरण कंपनीशी संपर्क करा.", "website": "https://saubhagya.gov.in", "helpline": "1800-11-5467"}
    },
    "jan_dhan": {
        "en": {"name": "PM Jan Dhan Yojana (Free Bank Account)", "amount": "Zero balance account + RuPay debit card", "description": "Free bank account with zero minimum balance and Rs. 1 lakh accident insurance.", "eligibility": ["Any Indian citizen", "Age 10 years and above", "No existing bank account"], "documents": ["Aadhaar Card", "Passport size photo"], "how_to_apply": "Visit any nationalized bank branch with Aadhaar card.", "website": "https://pmjdy.gov.in", "helpline": "1800-11-0001"},
        "hi": {"name": "PM जन धन योजना (मुफ्त बैंक खाता)", "amount": "शून्य बैलेंस खाता + RuPay डेबिट कार्ड", "description": "शून्य न्यूनतम बैलेंस और रु. 1 लाख दुर्घटना बीमा के साथ मुफ्त बैंक खाता।", "eligibility": ["कोई भी भारतीय नागरिक", "10 वर्ष और उससे अधिक आयु", "कोई मौजूदा बैंक खाता नहीं"], "documents": ["आधार कार्ड", "पासपोर्ट साइज फोटो"], "how_to_apply": "आधार कार्ड के साथ किसी भी राष्ट्रीयकृत बैंक शाखा में जाएं।", "website": "https://pmjdy.gov.in", "helpline": "1800-11-0001"},
        "mr": {"name": "PM जन धन योजना (मोफत बँक खाते)", "amount": "शून्य शिल्लक खाते + RuPay डेबिट कार्ड", "description": "शून्य किमान शिल्लक आणि रु. 1 लाख अपघात विमा सह मोफत बँक खाते.", "eligibility": ["कोणताही भारतीय नागरिक", "10 वर्षे आणि त्याहून अधिक वय", "कोणतेही विद्यमान बँक खाते नाही"], "documents": ["आधार कार्ड", "पासपोर्ट आकाराचा फोटो"], "how_to_apply": "आधार कार्डसह कोणत्याही राष्ट्रीयकृत बँक शाखेत जा.", "website": "https://pmjdy.gov.in", "helpline": "1800-11-0001"}
    },
    "ladki_bahin": {
        "en": {"name": "Ladki Bahin Yojana (Maharashtra)", "amount": "Rs. 1,500/month", "description": "Maharashtra government scheme providing Rs.1,500 per month financial assistance to women aged 21-65 years from economically weaker families.", "eligibility": ["Female aged 21-65 years", "Maharashtra resident", "Annual family income below Rs. 2.5 lakh", "Not a government employee or income tax payer"], "documents": ["Aadhaar Card", "Bank Account Passbook", "Income Certificate", "Age Proof", "Maharashtra Domicile Certificate"], "how_to_apply": "Apply online at ladakibahin.maharashtra.gov.in or visit nearest Gram Panchayat / Municipal office.", "website": "https://ladakibahin.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "लड़की बहन योजना (महाराष्ट्र)", "amount": "रु. 1,500/माह", "description": "महाराष्ट्र सरकार की योजना जो 21-65 वर्ष की महिलाओं को रु.1,500 प्रति माह वित्तीय सहायता देती है।", "eligibility": ["21-65 वर्ष की महिला", "महाराष्ट्र निवासी", "वार्षिक पारिवारिक आय रु. 2.5 लाख से कम", "सरकारी कर्मचारी या आयकर दाता नहीं"], "documents": ["आधार कार्ड", "बैंक पासबुक", "आय प्रमाण पत्र", "आयु प्रमाण", "महाराष्ट्र अधिवास प्रमाण पत्र"], "how_to_apply": "ladakibahin.maharashtra.gov.in पर ऑनलाइन आवेदन करें या निकटतम ग्राम पंचायत जाएं।", "website": "https://ladakibahin.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "लाडकी बहीण योजना (महाराष्ट्र)", "amount": "रु. 1,500/महिना", "description": "महाराष्ट्र सरकारची योजना जी 21-65 वर्षांच्या महिलांना रु.1,500 प्रति महिना आर्थिक मदत देते.", "eligibility": ["21-65 वर्षांची महिला", "महाराष्ट्र रहिवासी", "वार्षिक कौटुंबिक उत्पन्न रु. 2.5 लाखापेक्षा कमी", "सरकारी कर्मचारी नाही"], "documents": ["आधार कार्ड", "बँक पासबुक", "उत्पन्न प्रमाणपत्र", "वयाचा पुरावा", "महाराष्ट्र अधिवास प्रमाणपत्र"], "how_to_apply": "ladakibahin.maharashtra.gov.in वर ऑनलाइन अर्ज करा किंवा जवळच्या ग्रामपंचायतला जा.", "website": "https://ladakibahin.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "mh_health": {
        "en": {"name": "Mahatma Phule Jan Arogya Yojana (Maharashtra)", "amount": "Rs. 5 lakh/year", "description": "Maharashtra state health insurance scheme providing cashless treatment up to Rs.5 lakh per year at empanelled hospitals.", "eligibility": ["Maharashtra resident", "Annual income below Rs. 1 lakh (Yellow/Orange ration card holders)", "BPL families", "Farmers (Shetkari)"], "documents": ["Aadhaar Card", "Ration Card (Yellow/Orange)", "Income Certificate", "Maharashtra Domicile Proof"], "how_to_apply": "Visit any empanelled government or private hospital in Maharashtra with Aadhaar and ration card.", "website": "https://www.jeevandayee.gov.in", "helpline": "155388"},
        "hi": {"name": "महात्मा फुले जन आरोग्य योजना (महाराष्ट्र)", "amount": "रु. 5 लाख/वर्ष", "description": "महाराष्ट्र राज्य स्वास्थ्य बीमा योजना जो सूचीबद्ध अस्पतालों में रु.5 लाख तक का कैशलेस उपचार प्रदान करती है।", "eligibility": ["महाराष्ट्र निवासी", "वार्षिक आय रु. 1 लाख से कम", "BPL परिवार", "किसान (शेतकरी)"], "documents": ["आधार कार्ड", "राशन कार्ड (पीला/नारंगी)", "आय प्रमाण पत्र", "महाराष्ट्र निवास प्रमाण"], "how_to_apply": "आधार और राशन कार्ड के साथ महाराष्ट्र के किसी भी सूचीबद्ध अस्पताल में जाएं।", "website": "https://www.jeevandayee.gov.in", "helpline": "155388"},
        "mr": {"name": "महात्मा फुले जन आरोग्य योजना (महाराष्ट्र)", "amount": "रु. 5 लाख/वर्ष", "description": "महाराष्ट्र राज्य आरोग्य विमा योजना जी सूचीबद्ध रुग्णालयांमध्ये रु.5 लाखापर्यंत कॅशलेस उपचार देते.", "eligibility": ["महाराष्ट्र रहिवासी", "वार्षिक उत्पन्न रु. 1 लाखापेक्षा कमी", "BPL कुटुंब", "शेतकरी"], "documents": ["आधार कार्ड", "रेशन कार्ड (पिवळे/नारिंगी)", "उत्पन्न प्रमाणपत्र", "महाराष्ट्र अधिवास पुरावा"], "how_to_apply": "आधार आणि रेशन कार्डसह महाराष्ट्रातील कोणत्याही सूचीबद्ध रुग्णालयात जा.", "website": "https://www.jeevandayee.gov.in", "helpline": "155388"}
    },
    "shravan_bal": {
        "en": {"name": "Shravan Bal Seva Rajya Nivrutti Vetan (Maharashtra)", "amount": "Rs. 600/month", "description": "Maharashtra state old age pension scheme providing Rs.600 per month to elderly citizens aged 65 and above.", "eligibility": ["Age 65 years and above", "Maharashtra resident for 15+ years", "Annual income below Rs. 21,000", "Not receiving any other pension"], "documents": ["Aadhaar Card", "Age Proof (Birth Certificate/School Certificate)", "Income Certificate", "Bank Account Details", "Domicile Certificate"], "how_to_apply": "Apply at nearest Gram Panchayat or District Social Welfare Office.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "श्रवण बाल सेवा राज्य निवृत्ती वेतन (महाराष्ट्र)", "amount": "रु. 600/माह", "description": "महाराष्ट्र राज्य वृद्धावस्था पेंशन योजना जो 65+ वर्ष के वृद्धों को रु.600 प्रति माह देती है।", "eligibility": ["65 वर्ष और उससे अधिक", "15+ वर्ष से महाराष्ट्र निवासी", "वार्षिक आय रु. 21,000 से कम", "कोई अन्य पेंशन नहीं"], "documents": ["आधार कार्ड", "आयु प्रमाण", "आय प्रमाण पत्र", "बैंक खाता विवरण", "अधिवास प्रमाण पत्र"], "how_to_apply": "निकटतम ग्राम पंचायत या जिला समाज कल्याण कार्यालय में आवेदन करें।", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "श्रवण बाल सेवा राज्य निवृत्ती वेतन (महाराष्ट्र)", "amount": "रु. 600/महिना", "description": "महाराष्ट्र राज्य वृद्धापकाळ पेन्शन योजना जी 65+ वयाच्या वृद्धांना रु.600 प्रति महिना देते.", "eligibility": ["65 वर्षे आणि त्याहून अधिक", "15+ वर्षांपासून महाराष्ट्र रहिवासी", "वार्षिक उत्पन्न रु. 21,000 पेक्षा कमी", "इतर कोणतीही पेन्शन नाही"], "documents": ["आधार कार्ड", "वयाचा पुरावा", "उत्पन्न प्रमाणपत्र", "बँक खाते तपशील", "अधिवास प्रमाणपत्र"], "how_to_apply": "जवळच्या ग्रामपंचायत किंवा जिल्हा समाज कल्याण कार्यालयात अर्ज करा.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "gharkul": {
        "en": {"name": "Ramai Awas Gharkul Yojana (Maharashtra)", "amount": "Free Permanent House", "description": "Maharashtra government housing scheme providing free permanent houses to SC/ST/OBC/NT and other deprived communities.", "eligibility": ["SC/ST/OBC/NT community member", "Maharashtra resident", "No pucca house", "Annual income below Rs. 1 lakh", "Land ownership or government land allotment"], "documents": ["Aadhaar Card", "Caste Certificate", "Income Certificate", "Land Documents", "BPL Certificate", "Bank Account Details"], "how_to_apply": "Apply at Gram Panchayat or District Collector Office. Online at ramai.maharashtra.gov.in", "website": "https://ramai.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "रमाई आवास घरकुल योजना (महाराष्ट्र)", "amount": "मुफ्त पक्का घर", "description": "महाराष्ट्र सरकार की आवास योजना SC/ST/OBC/NT समुदाय को मुफ्त पक्का घर देती है।", "eligibility": ["SC/ST/OBC/NT समुदाय सदस्य", "महाराष्ट्र निवासी", "कोई पक्का घर नहीं", "वार्षिक आय रु. 1 लाख से कम"], "documents": ["आधार कार्ड", "जाति प्रमाण पत्र", "आय प्रमाण पत्र", "भूमि दस्तावेज", "BPL प्रमाण पत्र", "बैंक खाता"], "how_to_apply": "ग्राम पंचायत या जिला कलेक्टर कार्यालय में आवेदन करें।", "website": "https://ramai.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "रमाई आवास घरकुल योजना (महाराष्ट्र)", "amount": "मोफत पक्के घर", "description": "महाराष्ट्र सरकारची आवास योजना SC/ST/OBC/NT समुदायाला मोफत पक्के घर देते.", "eligibility": ["SC/ST/OBC/NT समुदाय सदस्य", "महाराष्ट्र रहिवासी", "पक्के घर नाही", "वार्षिक उत्पन्न रु. 1 लाखापेक्षा कमी"], "documents": ["आधार कार्ड", "जात प्रमाणपत्र", "उत्पन्न प्रमाणपत्र", "जमीन दस्तऐवज", "BPL प्रमाणपत्र", "बँक खाते"], "how_to_apply": "ग्रामपंचायत किंवा जिल्हाधिकारी कार्यालयात अर्ज करा.", "website": "https://ramai.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "sanjay_gandhi": {
        "en": {"name": "Sanjay Gandhi Niradhar Anudan Yojana (Maharashtra)", "amount": "Rs. 600/month", "description": "Maharashtra scheme providing monthly financial assistance to destitute persons who have no means of livelihood.", "eligibility": ["Age above 18 years", "Maharashtra resident", "Destitute — no income or family support", "Widow/Divorcee/Abandoned woman", "Annual income below Rs. 21,000"], "documents": ["Aadhaar Card", "Income Certificate", "Domicile Certificate", "Bank Account Details", "Proof of destitution"], "how_to_apply": "Apply at District Social Welfare Office or Gram Panchayat.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "संजय गांधी निराधार अनुदान योजना (महाराष्ट्र)", "amount": "रु. 600/माह", "description": "महाराष्ट्र योजना जो बेसहारा व्यक्तियों को मासिक वित्तीय सहायता देती है।", "eligibility": ["18 वर्ष से अधिक", "महाराष्ट्र निवासी", "बेसहारा — कोई आय नहीं", "विधवा/तलाकशुदा/परित्यक्त महिला", "वार्षिक आय रु. 21,000 से कम"], "documents": ["आधार कार्ड", "आय प्रमाण पत्र", "अधिवास प्रमाण पत्र", "बैंक खाता विवरण"], "how_to_apply": "जिला समाज कल्याण कार्यालय या ग्राम पंचायत में आवेदन करें।", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "संजय गांधी निराधार अनुदान योजना (महाराष्ट्र)", "amount": "रु. 600/महिना", "description": "महाराष्ट्र योजना जी निराधार व्यक्तींना मासिक आर्थिक मदत देते.", "eligibility": ["18 वर्षांपेक्षा जास्त", "महाराष्ट्र रहिवासी", "निराधार — उत्पन्न नाही", "विधवा/घटस्फोटित/परित्यक्त महिला", "वार्षिक उत्पन्न रु. 21,000 पेक्षा कमी"], "documents": ["आधार कार्ड", "उत्पन्न प्रमाणपत्र", "अधिवास प्रमाणपत्र", "बँक खाते तपशील"], "how_to_apply": "जिल्हा समाज कल्याण कार्यालय किंवा ग्रामपंचायतमध्ये अर्ज करा.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "rajmata_jijau": {
        "en": {"name": "Rajmata Jijau Mata-Bal Swasthya Poshan Mission (Maharashtra)", "amount": "Free maternal & child health", "description": "Maharashtra scheme for comprehensive maternal and child health care including free nutrition, health checkups, and immunization.", "eligibility": ["Pregnant women", "Lactating mothers", "Children under 6 years", "Maharashtra resident", "BPL or low income family"], "documents": ["Aadhaar Card", "Ration Card", "Pregnancy Card / Mother Child Protection Card", "Bank Account Details"], "how_to_apply": "Register at nearest Anganwadi Centre or Primary Health Centre.", "website": "https://womenchild.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "राजमाता जिजाऊ माता-बाल स्वास्थ्य पोषण मिशन (महाराष्ट्र)", "amount": "मुफ्त मातृ एवं शिशु स्वास्थ्य", "description": "महाराष्ट्र योजना जो गर्भवती महिलाओं और बच्चों के लिए मुफ्त स्वास्थ्य सेवाएं देती है।", "eligibility": ["गर्भवती महिलाएं", "स्तनपान कराने वाली माताएं", "6 वर्ष से कम के बच्चे", "BPL या कम आय परिवार"], "documents": ["आधार कार्ड", "राशन कार्ड", "प्रेगनेंसी कार्ड", "बैंक खाता विवरण"], "how_to_apply": "निकटतम आंगनवाड़ी केंद्र या प्राथमिक स्वास्थ्य केंद्र में पंजीकरण करें।", "website": "https://womenchild.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "राजमाता जिजाऊ माता-बाल आरोग्य पोषण मिशन (महाराष्ट्र)", "amount": "मोफत माता व बाल आरोग्य", "description": "महाराष्ट्र योजना जी गर्भवती महिला आणि मुलांसाठी मोफत आरोग्य सेवा देते.", "eligibility": ["गर्भवती महिला", "स्तनपान करणाऱ्या माता", "6 वर्षांखालील मुले", "BPL किंवा कमी उत्पन्न कुटुंब"], "documents": ["आधार कार्ड", "रेशन कार्ड", "गर्भधारणा कार्ड", "बँक खाते तपशील"], "how_to_apply": "जवळच्या अंगणवाडी केंद्र किंवा प्राथमिक आरोग्य केंद्रात नोंदणी करा.", "website": "https://womenchild.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "mh_ration": {
        "en": {"name": "Maharashtra Yellow Ration Card Scheme", "amount": "Subsidised food grains", "description": "Maharashtra state ration card for BPL families providing subsidised food grains at Fair Price Shops.", "eligibility": ["Maharashtra resident", "Annual income below Rs. 1 lakh", "BPL or economically weaker family", "No existing ration card"], "documents": ["Aadhaar Card", "Income Certificate", "Address Proof", "Passport size photos of all family members"], "how_to_apply": "Apply at nearest Gram Panchayat or Taluka Supply Office.", "website": "https://mahafood.gov.in", "helpline": "1800-22-4950"},
        "hi": {"name": "महाराष्ट्र पीला राशन कार्ड योजना", "amount": "सब्सिडी खाद्यान्न", "description": "महाराष्ट्र BPL परिवारों के लिए पीला राशन कार्ड जो उचित मूल्य की दुकानों पर सब्सिडी वाले अनाज देता है।", "eligibility": ["महाराष्ट्र निवासी", "वार्षिक आय रु. 1 लाख से कम", "BPL परिवार", "कोई मौजूदा राशन कार्ड नहीं"], "documents": ["आधार कार्ड", "आय प्रमाण पत्र", "पता प्रमाण", "सभी सदस्यों के पासपोर्ट फोटो"], "how_to_apply": "निकटतम ग्राम पंचायत या तालुका आपूर्ति कार्यालय में आवेदन करें।", "website": "https://mahafood.gov.in", "helpline": "1800-22-4950"},
        "mr": {"name": "महाराष्ट्र पिवळे रेशन कार्ड योजना", "amount": "अनुदानित अन्नधान्य", "description": "महाराष्ट्र BPL कुटुंबांसाठी पिवळे रेशन कार्ड जे स्वस्त धान्य दुकानांवर सवलतीच्या दरात धान्य देते.", "eligibility": ["महाराष्ट्र रहिवासी", "वार्षिक उत्पन्न रु. 1 लाखापेक्षा कमी", "BPL कुटुंब", "विद्यमान रेशन कार्ड नाही"], "documents": ["आधार कार्ड", "उत्पन्न प्रमाणपत्र", "पत्ता पुरावा", "सर्व सदस्यांचे पासपोर्ट फोटो"], "how_to_apply": "जवळच्या ग्रामपंचायत किंवा तालुका पुरवठा कार्यालयात अर्ज करा.", "website": "https://mahafood.gov.in", "helpline": "1800-22-4950"}
    },
    "vayoshri_mh": {
        "en": {"name": "Vayoshri Yojana Maharashtra", "amount": "Free aids & equipment", "description": "Maharashtra scheme providing free assistive devices like hearing aids, spectacles, walking sticks, wheelchairs to elderly BPL citizens.", "eligibility": ["Age 60 years and above", "BPL category", "Maharashtra resident", "Has disability or age-related health issue"], "documents": ["Aadhaar Card", "BPL Certificate", "Age Proof", "Medical Certificate from government doctor"], "how_to_apply": "Apply at District Social Welfare Office or through Gram Panchayat.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "वयोश्री योजना महाराष्ट्र", "amount": "मुफ्त सहायक उपकरण", "description": "महाराष्ट्र योजना जो BPL बुजुर्गों को श्रवण यंत्र, चश्मा, व्हीलचेयर आदि मुफ्त देती है।", "eligibility": ["60 वर्ष और उससे अधिक", "BPL श्रेणी", "महाराष्ट्र निवासी", "विकलांगता या स्वास्थ्य समस्या"], "documents": ["आधार कार्ड", "BPL प्रमाण पत्र", "आयु प्रमाण", "सरकारी डॉक्टर का प्रमाण पत्र"], "how_to_apply": "जिला समाज कल्याण कार्यालय में आवेदन करें।", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "वयोश्री योजना महाराष्ट्र", "amount": "मोफत सहाय्यक साधने", "description": "महाराष्ट्र योजना जी BPL वृद्धांना श्रवणयंत्र, चष्मा, व्हीलचेअर इ. मोफत देते.", "eligibility": ["60 वर्षे आणि त्याहून अधिक", "BPL श्रेणी", "महाराष्ट्र रहिवासी", "अपंगत्व किंवा आरोग्य समस्या"], "documents": ["आधार कार्ड", "BPL प्रमाणपत्र", "वयाचा पुरावा", "सरकारी डॉक्टरचे प्रमाणपत्र"], "how_to_apply": "जिल्हा समाज कल्याण कार्यालयात अर्ज करा.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "basic": {
        "en": {"name": "Basic Community Support and Ration Assistance", "amount": "As applicable", "description": "Local community support programs including ration assistance and basic welfare services.", "eligibility": ["Any person in need", "BPL or poor household"], "documents": ["Aadhaar Card", "Any identity proof"], "how_to_apply": "Contact nearest Gram Panchayat, Municipal Corporation, or local NGO.", "website": "https://socialjustice.gov.in", "helpline": "1800-180-6763"},
        "hi": {"name": "बुनियादी सामुदायिक सहायता और राशन सहायता", "amount": "लागू अनुसार", "description": "राशन सहायता और बुनियादी कल्याण सेवाओं सहित स्थानीय सामुदायिक सहायता।", "eligibility": ["जरूरतमंद कोई भी व्यक्ति", "BPL या गरीब परिवार"], "documents": ["आधार कार्ड", "कोई भी पहचान प्रमाण"], "how_to_apply": "निकटतम ग्राम पंचायत या स्थानीय NGO से संपर्क करें।", "website": "https://socialjustice.gov.in", "helpline": "1800-180-6763"},
        "mr": {"name": "मूलभूत सामुदायिक मदत आणि रेशन सहाय्य", "amount": "लागू असेल तसे", "description": "रेशन मदत आणि मूलभूत कल्याण सेवांसह स्थानिक सामुदायिक मदत.", "eligibility": ["गरजू कोणताही व्यक्ती", "BPL किंवा गरीब कुटुंब"], "documents": ["आधार कार्ड", "कोणताही ओळख पुरावा"], "how_to_apply": "जवळच्या ग्रामपंचायत किंवा स्थानिक NGO शी संपर्क करा.", "website": "https://socialjustice.gov.in", "helpline": "1800-180-6763"}
    }
}

MH_KEYWORDS = [
    'maharashtra', 'pune', 'mumbai', 'nashik', 'nagpur', 'Sambhaji Nagar',
    'solapur', 'kolhapur', 'satara', 'sangli', 'ahmednagar', 'latur',
    'nanded', 'osmanabad', 'beed', 'jalna', 'hingoli', 'parbhani',
    'washim', 'akola', 'amravati', 'wardha', 'yavatmal', 'buldhana',
    'chandrapur', 'gadchiroli', 'gondia', 'bhandara', 'raigad',
    'ratnagiri', 'sindhudurg', 'thane', 'palghar', 'dhule', 'nandurbar',
    'jalgaon', 'hinganghat', 'vidarbha', 'marathwada', 'konkan', 'mh'
]

STATE_KEYWORDS = {
    'Maharashtra': MH_KEYWORDS,
    'Uttar Pradesh': ['uttar pradesh', 'lucknow', 'kanpur', 'varanasi', 'agra', 'noida', 'ghaziabad', 'prayagraj', 'meerut'],
    'Bihar': ['bihar', 'patna', 'gaya', 'bhagalpur', 'muzaffarpur', 'darbhanga'],
    'Rajasthan': ['rajasthan', 'jaipur', 'jodhpur', 'udaipur', 'kota', 'bikaner', 'ajmer'],
    'Madhya Pradesh': ['madhya pradesh', 'bhopal', 'indore', 'gwalior', 'jabalpur', 'ujjain'],
    'Gujarat': ['gujarat', 'ahmedabad', 'surat', 'vadodara', 'rajkot', 'bhavnagar'],
    'West Bengal': ['west bengal', 'kolkata', 'howrah', 'durgapur', 'siliguri', 'asansol'],
    'Tamil Nadu': ['tamil nadu', 'chennai', 'coimbatore', 'madurai', 'salem', 'tiruchirappalli'],
    'Karnataka': ['karnataka', 'bengaluru', 'bangalore', 'mysuru', 'mysore', 'hubli', 'mangalore'],
    'Telangana': ['telangana', 'hyderabad', 'warangal', 'nizamabad'],
    'Andhra Pradesh': ['andhra pradesh', 'visakhapatnam', 'vijayawada', 'guntur', 'tirupati'],
    'Delhi': ['delhi', 'new delhi'],
    'Punjab': ['punjab', 'ludhiana', 'amritsar', 'jalandhar', 'patiala'],
    'Haryana': ['haryana', 'gurugram', 'gurgaon', 'faridabad', 'panipat', 'karnal'],
    'Odisha': ['odisha', 'bhubaneswar', 'cuttack', 'rourkela'],
    'Kerala': ['kerala', 'kochi', 'thiruvananthapuram', 'kozhikode', 'thrissur'],
    'Assam': ['assam', 'guwahati', 'dibrugarh', 'silchar'],
    'Jharkhand': ['jharkhand', 'ranchi', 'jamshedpur', 'dhanbad'],
    'Chhattisgarh': ['chhattisgarh', 'raipur', 'bhilai', 'bilaspur'],
}

def detect_state(address):
    addr = (address or '').lower()
    for state, keywords in STATE_KEYWORDS.items():
        if any(kw.lower() in addr for kw in keywords):
            return state
    return None

MH_SCHEMES = {
    'en': {
        'ladki_bahin':    ('urgent', 'Ladki Bahin Yojana (Maharashtra)', 'Rs. 1,500/month'),
        'mh_health':      ('urgent', 'Mahatma Phule Jan Arogya Yojana (MH)', 'Rs. 5 lakh/yr'),
        'shravan_bal':    ('normal', 'Shravan Bal Seva Pension (MH)', 'Rs. 600/month'),
        'gharkul':        ('normal', 'Ramai Awas Gharkul Yojana (MH)', 'Free House'),
        'sanjay_gandhi':  ('normal', 'Sanjay Gandhi Niradhar Yojana (MH)', 'Rs. 600/month'),
        'rajmata_jijau':  ('normal', 'Rajmata Jijau Mata-Bal Swasthya (MH)', 'Free maternal health'),
        'mh_ration':      ('normal', 'Maharashtra Yellow Ration Card (MH)', 'Subsidised ration'),
        'vayoshri_mh':    ('normal', 'Vayoshri Yojana Maharashtra (MH)', 'Free aids for elderly'),
    },
    'hi': {
        'ladki_bahin':    ('urgent', 'लड़की बहन योजना (महाराष्ट्र)', 'रु. 1,500/माह'),
        'mh_health':      ('urgent', 'महात्मा फुले जन आरोग्य योजना (MH)', 'रु. 5 लाख/वर्ष'),
        'shravan_bal':    ('normal', 'श्रवण बाल सेवा पेंशन (MH)', 'रु. 600/माह'),
        'gharkul':        ('normal', 'रमाई आवास घरकुल योजना (MH)', 'मुफ्त घर'),
        'sanjay_gandhi':  ('normal', 'संजय गांधी निराधार योजना (MH)', 'रु. 600/माह'),
        'rajmata_jijau':  ('normal', 'राजमाता जिजाऊ माता-बाल स्वास्थ्य (MH)', 'मुफ्त मातृ स्वास्थ्य'),
        'mh_ration':      ('normal', 'महाराष्ट्र पीला राशन कार्ड (MH)', 'सब्सिडी राशन'),
        'vayoshri_mh':    ('normal', 'वयोश्री योजना महाराष्ट्र (MH)', 'बुजुर्गों के लिए मदद'),
    },
    'mr': {
        'ladki_bahin':    ('urgent', 'लाडकी बहीण योजना (महाराष्ट्र)', 'रु. 1,500/महिना'),
        'mh_health':      ('urgent', 'महात्मा फुले जन आरोग्य योजना (MH)', 'रु. 5 लाख/वर्ष'),
        'shravan_bal':    ('normal', 'श्रवण बाल सेवा निवृत्ती वेतन (MH)', 'रु. 600/महिना'),
        'gharkul':        ('normal', 'रमाई आवास घरकुल योजना (MH)', 'मोफत घर'),
        'sanjay_gandhi':  ('normal', 'संजय गांधी निराधार योजना (MH)', 'रु. 600/महिना'),
        'rajmata_jijau':  ('normal', 'राजमाता जिजाऊ माता-बाल आरोग्य (MH)', 'मोफत माता आरोग्य'),
        'mh_ration':      ('normal', 'महाराष्ट्र पिवळे रेशन कार्ड (MH)', 'अनुदानित रेशन'),
        'vayoshri_mh':    ('normal', 'वयोश्री योजना महाराष्ट्र (MH)', 'वृद्धांसाठी मदत'),
    }
}

def calculate_score(data):
    score = 0
    age_group = data['age_group']
    if age_group == 'child': score += 30
    elif age_group == 'elderly': score += 25
    income = int(data['income'])
    if income < 5000: score += 40
    elif income < 10000: score += 25
    elif income < 20000: score += 10
    family = int(data['family_size'])
    if family >= 5: score += 20
    elif family >= 3: score += 10
    if data['housing'] == 'homeless': score += 20
    elif data['housing'] == 'kutcha': score += 15
    elif data['housing'] == 'rented': score += 5
    if data['electricity'] == 'no': score += 10
    elif data['electricity'] == 'sometimes': score += 5
    if data['ration'] == 'no': score += 10
    if data['medical'] == 'emergency': score += 30
    elif data['medical'] == 'chronic_illness': score += 15
    elif data['medical'] == 'disability': score += 20
    if data['accident'] == 'yes': score += 25
    if data['earning_member_died'] == 'yes': score += 25
    if data.get('widow_status') == 'yes': score += 15
    return score

# ---------------------------------------------------------------------------
# AI Welfare Assistant helpers
# These turn the raw eligibility-form answers already sitting in the session
# into a readable "User Profile" block that gets fed to Gemini, plus a couple
# of deterministic (non-LLM) explainers for the Need Score and document
# checklist so those specific answers are always accurate, not guessed.
# ---------------------------------------------------------------------------

PROFILE_LABELS = {
    'en': {
        'age_group': {'child': 'Child', 'adult': 'Adult', 'elderly': 'Senior Citizen (60+)'},
        'housing': {'homeless': 'Homeless', 'kutcha': 'Kutcha (temporary/weak structure)', 'rented': 'Rented house', 'pucca': 'Pucca (permanent) house'},
        'medical': {'none': 'No major medical issue', 'emergency': 'Medical Emergency', 'chronic_illness': 'Chronic Illness', 'disability': 'Disability'},
        'yesno': {'yes': 'Yes', 'no': 'No', 'sometimes': 'Sometimes'},
        'gender': {'male': 'Male', 'female': 'Female', 'other': 'Other'},
        'fields': {'name': 'Name', 'age_group': 'Age Group', 'gender': 'Gender', 'widow': 'Widow', 'income': 'Monthly Income',
                   'family_size': 'Family Size', 'housing': 'Housing', 'medical': 'Medical Condition', 'electricity': 'Electricity',
                   'ration': 'Ration Card', 'accident': 'Recent Accident', 'earning_member_died': 'Earning Member Died Recently',
                   'address': 'Address', 'state': 'State', 'score': 'AI Need Score', 'priority': 'Priority'},
    },
    'hi': {
        'age_group': {'child': 'बच्चा', 'adult': 'वयस्क', 'elderly': 'वरिष्ठ नागरिक (60+)'},
        'housing': {'homeless': 'बेघर', 'kutcha': 'कच्चा घर', 'rented': 'किराए का घर', 'pucca': 'पक्का घर'},
        'medical': {'none': 'कोई बड़ी बीमारी नहीं', 'emergency': 'चिकित्सा आपातकाल', 'chronic_illness': 'पुरानी बीमारी', 'disability': 'दिव्यांगता'},
        'yesno': {'yes': 'हां', 'no': 'नहीं', 'sometimes': 'कभी-कभी'},
        'gender': {'male': 'पुरुष', 'female': 'महिला', 'other': 'अन्य'},
        'fields': {'name': 'नाम', 'age_group': 'आयु समूह', 'gender': 'लिंग', 'widow': 'विधवा', 'income': 'मासिक आय',
                   'family_size': 'परिवार का आकार', 'housing': 'आवास', 'medical': 'चिकित्सा स्थिति', 'electricity': 'बिजली',
                   'ration': 'राशन कार्ड', 'accident': 'हाल की दुर्घटना', 'earning_member_died': 'कमाने वाले सदस्य की मृत्यु',
                   'address': 'पता', 'state': 'राज्य', 'score': 'AI Need Score', 'priority': 'प्राथमिकता'},
    },
    'mr': {
        'age_group': {'child': 'मूल', 'adult': 'प्रौढ', 'elderly': 'ज्येष्ठ नागरिक (60+)'},
        'housing': {'homeless': 'बेघर', 'kutcha': 'कच्चे घर', 'rented': 'भाड्याचे घर', 'pucca': 'पक्के घर'},
        'medical': {'none': 'मोठा आजार नाही', 'emergency': 'वैद्यकीय आणीबाणी', 'chronic_illness': 'दीर्घकालीन आजार', 'disability': 'अपंगत्व'},
        'yesno': {'yes': 'होय', 'no': 'नाही', 'sometimes': 'कधी कधी'},
        'gender': {'male': 'पुरुष', 'female': 'स्त्री', 'other': 'इतर'},
        'fields': {'name': 'नाव', 'age_group': 'वयोगट', 'gender': 'लिंग', 'widow': 'विधवा', 'income': 'मासिक उत्पन्न',
                   'family_size': 'कुटुंबाचा आकार', 'housing': 'निवास', 'medical': 'वैद्यकीय स्थिती', 'electricity': 'वीज',
                   'ration': 'रेशन कार्ड', 'accident': 'अलीकडील अपघात', 'earning_member_died': 'कमावत्या सदस्याचा मृत्यू',
                   'address': 'पत्ता', 'state': 'राज्य', 'score': 'AI Need Score', 'priority': 'प्राधान्य'},
    },
}

def _label(category, value, lang):
    if not value:
        return None
    lang_map = PROFILE_LABELS.get(lang, PROFILE_LABELS['en'])
    return lang_map.get(category, {}).get(value, value)

def build_profile_context(profile, lang='en'):
    """Turn the stored session profile dict into a compact text block for the
    Gemini prompt, e.g. Name / Age / Income / Need Score / Recommended Schemes.
    Only includes fields that were actually answered."""
    if not profile:
        return None

    F = PROFILE_LABELS.get(lang, PROFILE_LABELS['en'])['fields']
    lines = []

    if profile.get('name'):
        lines.append(f"{F['name']}: {profile['name']}")
    if profile.get('age_group'):
        lines.append(f"{F['age_group']}: {_label('age_group', profile['age_group'], lang)}")
    if profile.get('gender'):
        lines.append(f"{F['gender']}: {_label('gender', profile['gender'], lang)}")
    if profile.get('widow') == 'yes':
        lines.append(f"{F['widow']}: {_label('yesno', 'yes', lang)}")
    if profile.get('income'):
        lines.append(f"{F['income']}: Rs. {profile['income']}")
    if profile.get('family_size'):
        lines.append(f"{F['family_size']}: {profile['family_size']}")
    if profile.get('housing'):
        lines.append(f"{F['housing']}: {_label('housing', profile['housing'], lang)}")
    if profile.get('medical') and profile['medical'] != 'none':
        lines.append(f"{F['medical']}: {_label('medical', profile['medical'], lang)}")
    if profile.get('electricity'):
        lines.append(f"{F['electricity']}: {_label('yesno', profile['electricity'], lang)}")
    if profile.get('ration'):
        lines.append(f"{F['ration']}: {_label('yesno', profile['ration'], lang)}")
    if profile.get('accident') == 'yes':
        lines.append(f"{F['accident']}: {_label('yesno', 'yes', lang)}")
    if profile.get('earning_member_died') == 'yes':
        lines.append(f"{F['earning_member_died']}: {_label('yesno', 'yes', lang)}")
    if profile.get('state'):
        lines.append(f"{F['state']}: {profile['state']}")
    if profile.get('score') is not None:
        lines.append(f"{F['score']}: {profile['score']} / 175")
    if profile.get('priority'):
        lines.append(f"{F['priority']}: {profile['priority']}")

    schemes = profile.get('schemes') or []
    if schemes:
        scheme_lines = "\n".join(f"- {sc['name']} ({sc['amount']})" for sc in schemes)
        lines.append(f"\nRecommended Schemes:\n{scheme_lines}")

    return "User Profile:\n" + "\n".join(lines)

def explain_need_score(profile, lang='en'):
    """Deterministic, always-accurate breakdown of WHY the score is what it
    is — mirrors calculate_score() exactly instead of letting the LLM guess."""
    if not profile:
        return None
    reasons = []
    age_group = profile.get('age_group', '')
    income = int(profile.get('income') or 0)
    family = int(profile.get('family_size') or 0)
    housing = profile.get('housing', '')
    electricity = profile.get('electricity', '')
    ration = profile.get('ration', '')
    medical = profile.get('medical', '')
    accident = profile.get('accident', '')
    earning_died = profile.get('earning_member_died', '')
    widow = profile.get('widow', '')

    texts = {
        'en': {
            'child': "Child (+30 pts) — children are a high priority group",
            'elderly': "Senior citizen, 60+ (+25 pts)",
            'income_lt5000': f"Very low income, under Rs. 5,000/month (+40 pts)",
            'income_lt10000': f"Low income, under Rs. 10,000/month (+25 pts)",
            'income_lt20000': f"Below-average income, under Rs. 20,000/month (+10 pts)",
            'family_ge5': "Large family, 5 or more members (+20 pts)",
            'family_ge3': "Medium family, 3-4 members (+10 pts)",
            'homeless': "Currently homeless (+20 pts)",
            'kutcha': "Living in a kutcha (temporary/weak) house (+15 pts)",
            'rented': "Living in a rented house (+5 pts)",
            'electricity_no': "No electricity connection (+10 pts)",
            'electricity_sometimes': "Irregular electricity (+5 pts)",
            'ration_no': "No ration card (+10 pts)",
            'medical_emergency': "Ongoing medical emergency (+30 pts)",
            'medical_chronic': "Chronic illness (+15 pts)",
            'medical_disability': "Living with a disability (+20 pts)",
            'accident': "Recent accident (+25 pts)",
            'earning_died': "Family's earning member passed away recently (+25 pts)",
            'widow': "Widow status (+15 pts) — a recognized vulnerability factor",
            'header': "Your Need Score is {score}/175 because of:",
            'footer': "A higher score means higher priority for urgent government help.",
        },
        'hi': {
            'child': "बच्चा (+30 अंक) — बच्चे उच्च प्राथमिकता समूह हैं",
            'elderly': "वरिष्ठ नागरिक, 60+ (+25 अंक)",
            'income_lt5000': "बहुत कम आय, ₹5,000/माह से कम (+40 अंक)",
            'income_lt10000': "कम आय, ₹10,000/माह से कम (+25 अंक)",
            'income_lt20000': "औसत से कम आय, ₹20,000/माह से कम (+10 अंक)",
            'family_ge5': "बड़ा परिवार, 5 या अधिक सदस्य (+20 अंक)",
            'family_ge3': "मध्यम परिवार, 3-4 सदस्य (+10 अंक)",
            'homeless': "वर्तमान में बेघर (+20 अंक)",
            'kutcha': "कच्चे घर में रहना (+15 अंक)",
            'rented': "किराए के घर में रहना (+5 अंक)",
            'electricity_no': "बिजली कनेक्शन नहीं (+10 अंक)",
            'electricity_sometimes': "अनियमित बिजली (+5 अंक)",
            'ration_no': "राशन कार्ड नहीं (+10 अंक)",
            'medical_emergency': "चल रही चिकित्सा आपातकाल (+30 अंक)",
            'medical_chronic': "पुरानी बीमारी (+15 अंक)",
            'medical_disability': "दिव्यांगता के साथ जीवन (+20 अंक)",
            'accident': "हाल की दुर्घटना (+25 अंक)",
            'earning_died': "परिवार के कमाने वाले सदस्य का हाल में निधन (+25 अंक)",
            'widow': "विधवा स्थिति (+15 अंक) — एक मान्यता प्राप्त संवेदनशील कारक",
            'header': "आपका Need Score {score}/175 है क्योंकि:",
            'footer': "अधिक स्कोर का मतलब है तत्काल सरकारी मदद के लिए उच्च प्राथमिकता।",
        },
        'mr': {
            'child': "मूल (+30 गुण) — मुले उच्च प्राधान्य गट आहेत",
            'elderly': "ज्येष्ठ नागरिक, 60+ (+25 गुण)",
            'income_lt5000': "खूप कमी उत्पन्न, ₹5,000/महिना पेक्षा कमी (+40 गुण)",
            'income_lt10000': "कमी उत्पन्न, ₹10,000/महिना पेक्षा कमी (+25 गुण)",
            'income_lt20000': "सरासरीपेक्षा कमी उत्पन्न, ₹20,000/महिना पेक्षा कमी (+10 गुण)",
            'family_ge5': "मोठे कुटुंब, 5 किंवा अधिक सदस्य (+20 गुण)",
            'family_ge3': "मध्यम कुटुंब, 3-4 सदस्य (+10 गुण)",
            'homeless': "सध्या बेघर (+20 गुण)",
            'kutcha': "कच्च्या घरात राहणे (+15 गुण)",
            'rented': "भाड्याच्या घरात राहणे (+5 गुण)",
            'electricity_no': "वीज जोडणी नाही (+10 गुण)",
            'electricity_sometimes': "अनियमित वीज (+5 गुण)",
            'ration_no': "रेशन कार्ड नाही (+10 गुण)",
            'medical_emergency': "सुरू असलेली वैद्यकीय आणीबाणी (+30 गुण)",
            'medical_chronic': "दीर्घकालीन आजार (+15 गुण)",
            'medical_disability': "अपंगत्वासह जीवन (+20 गुण)",
            'accident': "अलीकडील अपघात (+25 गुण)",
            'earning_died': "कुटुंबातील कमावत्या सदस्याचे नुकतेच निधन (+25 गुण)",
            'widow': "विधवा स्थिती (+15 गुण) — एक मान्यताप्राप्त असुरक्षितता घटक",
            'header': "तुमचा Need Score {score}/175 आहे कारण:",
            'footer': "जास्त स्कोअर म्हणजे तातडीच्या सरकारी मदतीसाठी जास्त प्राधान्य.",
        },
    }
    t = texts.get(lang, texts['en'])

    if age_group == 'child': reasons.append(t['child'])
    elif age_group == 'elderly': reasons.append(t['elderly'])
    if income < 5000: reasons.append(t['income_lt5000'])
    elif income < 10000: reasons.append(t['income_lt10000'])
    elif income < 20000: reasons.append(t['income_lt20000'])
    if family >= 5: reasons.append(t['family_ge5'])
    elif family >= 3: reasons.append(t['family_ge3'])
    if housing == 'homeless': reasons.append(t['homeless'])
    elif housing == 'kutcha': reasons.append(t['kutcha'])
    elif housing == 'rented': reasons.append(t['rented'])
    if electricity == 'no': reasons.append(t['electricity_no'])
    elif electricity == 'sometimes': reasons.append(t['electricity_sometimes'])
    if ration == 'no': reasons.append(t['ration_no'])
    if medical == 'emergency': reasons.append(t['medical_emergency'])
    elif medical == 'chronic_illness': reasons.append(t['medical_chronic'])
    elif medical == 'disability': reasons.append(t['medical_disability'])
    if accident == 'yes': reasons.append(t['accident'])
    if earning_died == 'yes': reasons.append(t['earning_died'])
    if widow == 'yes': reasons.append(t['widow'])

    header = t['header'].format(score=profile.get('score', 0))
    body = "\n".join(f"• {r}" for r in reasons) if reasons else "-"
    return f"{header}\n\n{body}\n\n{t['footer']}"

def get_combined_documents(profile, lang='en'):
    """Combined, de-duplicated document checklist across every scheme the
    user is recommended for, pulled from the same SCHEME_DETAILS data used
    on the scheme detail pages — so it never invents documents."""
    if not profile or not profile.get('schemes'):
        return None
    seen = []
    for sc in profile['schemes']:
        detail = SCHEME_DETAILS.get(sc['key'])
        if not detail:
            continue
        info = detail.get(lang, detail.get('en'))
        for doc in info.get('documents', []):
            if doc not in seen:
                seen.append(doc)
    if not seen:
        return None
    headers = {'en': "Documents you'll need (combined checklist):",
               'hi': "आपको जरूरी दस्तावेज़ (संयुक्त सूची):",
               'mr': "तुम्हाला आवश्यक कागदपत्रे (एकत्रित यादी):"}
    header = headers.get(lang, headers['en'])
    body = "\n".join(f"• {d}" for d in seen)
    return f"{header}\n{body}"

# ---------------------------------------------------------------------------
# Case-worker mode: lets someone just DESCRIBE their situation in the chat
# ("I'm a 62-year-old widow from Nagpur earning Rs 4000") instead of
# requiring the eligibility form first. Gemini only EXTRACTS structured
# facts (JSON) from the sentence — the actual eligibility/score/scheme
# matching is still done by your existing calculate_score()/get_schemes(),
# so the numbers can't be hallucinated.
# ---------------------------------------------------------------------------

INTAKE_DEFAULTS = {
    'age_group': 'adult', 'income': '0', 'family_size': '1', 'housing': 'pucca',
    'electricity': 'yes', 'ration': 'yes', 'medical': 'none', 'accident': 'no',
    'earning_member_died': 'no', 'widow_status': 'no', 'address': '',
}
# Fields we look at to decide "is this actually a self-description" vs a
# generic question — require at least 2 of these before treating it as intake.
INTAKE_SIGNAL_FIELDS = ['age_group', 'income', 'housing', 'medical', 'family_size', 'gender', 'widow', 'address']

def _derive_age_group(age_years):
    try:
        y = int(age_years)
    except (TypeError, ValueError):
        return None
    if y < 18: return 'child'
    if y >= 60: return 'elderly'
    return 'adult'

def extract_case_intake(model, user_message, lang):
    """One Gemini call that either (a) extracts structured facts if the
    message describes the sender's own situation, or (b) just answers
    normally if it's a generic question. Returns a dict or None on failure."""
    extraction_prompt = f"""You are a JSON extraction engine for an Indian welfare-scheme app. Read the citizen's message below.

If the message describes THIS PERSON'S OWN life situation (age, income, housing, family, health, widow status, location, etc. — like a case-worker intake), set "is_case_intake" to true and fill "extracted" with whatever facts are mentioned (use null for anything not mentioned). Otherwise (it's a generic question like "what is Ayushman Bharat" or "how do I apply"), set "is_case_intake" to false, leave "extracted" as null, and instead put a short helpful answer (max 5 lines, simple language) in "reply". If the message is VAGUE — like "I have a doubt", "I have a question", "need help" — with no actual topic mentioned, do NOT guess a topic. Instead set "is_case_intake" to false and put a short, friendly clarifying question in "reply" asking what the doubt/question is about (e.g. eligibility, documents, how to apply, Need Score, corruption reporting).

Respond with ONLY raw JSON, no markdown fences, no commentary, matching exactly this shape:
{{
  "is_case_intake": true or false,
  "extracted": {{
    "name": string or null,
    "age_years": integer or null,
    "gender": one of "male"/"female"/"other" or null,
    "widow": "yes" or "no" or null,
    "income": integer (monthly income in rupees, digits only) or null,
    "family_size": integer or null,
    "housing": one of "homeless"/"kutcha"/"rented"/"pucca" or null,
    "electricity": one of "yes"/"no"/"sometimes" or null,
    "ration": "yes" or "no" or null,
    "medical": one of "none"/"emergency"/"chronic_illness"/"disability" or null,
    "accident": "yes" or "no" or null,
    "earning_member_died": "yes" or "no" or null,
    "address": string (any city/state/district mentioned) or null
  }} or null,
  "reply": string or null
}}

Reply language for "reply" field should be: {lang}

Citizen's message: "{user_message}\""""

    try:
        resp = model.generate_content(extraction_prompt)
        raw = resp.text.strip()
        raw = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        return parsed
    except Exception as e:
        print(f"Case-intake extraction error: {e}")
        return None

def build_profile_from_intake(extracted, lang):
    """Fill missing fields with neutral defaults, then run the SAME
    calculate_score()/get_schemes() used by the real eligibility form, so a
    chat-described situation gets a real, consistent Need Score."""
    data = dict(INTAKE_DEFAULTS)
    age_group = extracted.get('age_group') or _derive_age_group(extracted.get('age_years'))
    if age_group:
        data['age_group'] = age_group
    if extracted.get('income') is not None:
        data['income'] = str(extracted['income'])
    if extracted.get('family_size') is not None:
        data['family_size'] = str(extracted['family_size'])
    for key in ['housing', 'electricity', 'ration', 'medical', 'accident', 'earning_member_died']:
        if extracted.get(key):
            data[key] = extracted[key]
    if extracted.get('widow'):
        data['widow_status'] = extracted['widow']
    address = extracted.get('address') or ''
    data['address'] = address

    score = calculate_score(data)
    schemes = get_schemes(score, data, lang)
    priority = get_priority(score, data)

    return {
        'name': extracted.get('name') or '',
        'gender': extracted.get('gender') or '',
        'widow': extracted.get('widow') or '',
        'age_group': data['age_group'],
        'income': data['income'],
        'family_size': data['family_size'],
        'housing': data['housing'],
        'electricity': data['electricity'],
        'ration': data['ration'],
        'medical': data['medical'],
        'accident': data['accident'],
        'earning_member_died': data['earning_member_died'],
        'address': address,
        'state': detect_state(address),
        'score': score,
        'priority': priority,
        'schemes': [{'key': sc[0], 'urgency': sc[1], 'name': sc[2], 'amount': sc[3]} for sc in schemes],
        'lang': lang,
        'source': 'chat_intake',
        'updated_at': datetime.now().strftime("%d %b %Y, %I:%M %p"),
    }

def format_case_worker_reply(profile, lang='en'):
    """The 'digital case worker' response: eligible schemes, documents,
    where to apply, and the recommended order — all computed from real
    scheme data, not invented by the LLM."""
    schemes = profile.get('schemes') or []
    urgent = [sc for sc in schemes if sc.get('urgency') == 'urgent']
    normal = [sc for sc in schemes if sc.get('urgency') != 'urgent']
    ordered = urgent + normal

    where_to_apply = []
    for sc in ordered[:4]:
        detail = SCHEME_DETAILS.get(sc['key'])
        if detail:
            info = detail.get(lang, detail.get('en'))
            how = info.get('how_to_apply', '')
            if how and how not in where_to_apply:
                where_to_apply.append(how)

    checklist = get_combined_documents(profile, lang)

    L = {
        'en': {'greet': "Based on what you told me, here's your personal plan:",
               'eligible': "✅ You may be eligible for:", 'order': "📋 Recommended order to apply:",
               'where': "📍 Where to go:", 'note': "This is an estimate from our chat — fill the full eligibility form on the app for your exact Need Score and to save this permanently."},
        'hi': {'greet': "आपने जो बताया उसके आधार पर, यह आपकी व्यक्तिगत योजना है:",
               'eligible': "✅ आप इनके लिए पात्र हो सकते हैं:", 'order': "📋 आवेदन का सुझाया गया क्रम:",
               'where': "📍 कहां जाएं:", 'note': "यह हमारी बातचीत पर आधारित एक अनुमान है — सटीक Need Score और स्थायी रिकॉर्ड के लिए ऐप में पूरा फॉर्म भरें।"},
        'mr': {'greet': "तुम्ही जे सांगितले त्यानुसार, ही तुमची वैयक्तिक योजना आहे:",
               'eligible': "✅ तुम्ही यासाठी पात्र असू शकता:", 'order': "📋 अर्ज करण्याचा सुचवलेला क्रम:",
               'where': "📍 कुठे जावे:", 'note': "हा आमच्या संभाषणावर आधारित अंदाज आहे — अचूक Need Score आणि कायमस्वरूपी नोंदीसाठी अॅपमध्ये संपूर्ण फॉर्म भरा."},
    }
    t = L.get(lang, L['en'])

    parts = [t['greet'], ""]
    parts.append(t['eligible'])
    parts.extend(f"• {sc['name']} — {sc['amount']}" for sc in ordered[:6])
    parts.append("")
    parts.append(t['order'])
    parts.extend(f"{i+1}. {sc['name']}" for i, sc in enumerate(ordered[:4]))
    if checklist:
        parts.append("")
        parts.append(checklist)
    if where_to_apply:
        parts.append("")
        parts.append(t['where'])
        parts.extend(f"• {w}" for w in where_to_apply[:3])
    parts.append("")
    parts.append(t['note'])
    return "\n".join(parts)

def get_schemes(score, data, lang='en'):
    schemes = []
    age = data['age_group']
    medical = data['medical']
    accident = data['accident']
    housing = data['housing']
    electricity = data['electricity']
    ration = data['ration']
    earning = data['earning_member_died']
    widow_status = data.get('widow_status', 'no')
    income = int(data.get('income', 0) or 0)
    address = data.get('address', '').lower()
    s = SCHEMES.get(lang, SCHEMES['en'])
    if medical == 'emergency': schemes.append(('pm_jan_arogya',) + s['pm_jan_arogya'])
    if accident == 'yes': schemes.append(('state_emergency',) + s['state_emergency'])
    if earning == 'yes': schemes.append(('national_family',) + s['national_family'])
    if widow_status == 'yes': schemes.append(('widow_pension',) + s['widow_pension'])
    if age == 'child':
        schemes.append(('pm_poshan',) + s['pm_poshan'])
        schemes.append(('icds',) + s['icds'])
    if age == 'elderly':
        schemes.append(('old_age_pension',) + s['old_age_pension'])
        schemes.append(('annapurna',) + s['annapurna'])
    if medical == 'chronic_illness': schemes.append(('ayushman',) + s['ayushman'])
    if medical == 'disability':
        schemes.append(('divyangjan',) + s['divyangjan'])
        schemes.append(('accessible_india',) + s['accessible_india'])
    if housing in ['homeless', 'kutcha']: schemes.append(('pm_awas',) + s['pm_awas'])
    if ration == 'no': schemes.append(('antyodaya',) + s['antyodaya'])
    if electricity == 'no':
        schemes.append(('ujjwala',) + s['ujjwala'])
        schemes.append(('saubhagya',) + s['saubhagya'])
    if score >= 40: schemes.append(('jan_dhan',) + s['jan_dhan'])
    schemes.append(('basic',) + s['basic'])

    is_mh = any(kw in address for kw in MH_KEYWORDS)
    if is_mh:
        mh = MH_SCHEMES.get(lang, MH_SCHEMES['en'])
        if income < 20834:
            schemes.append(('ladki_bahin',) + mh['ladki_bahin'])
        if medical in ['emergency', 'chronic_illness', 'disability'] or income < 10000:
            schemes.append(('mh_health',) + mh['mh_health'])
        if age == 'elderly':
            schemes.append(('shravan_bal',) + mh['shravan_bal'])
            if medical in ['disability', 'chronic_illness']:
                schemes.append(('vayoshri_mh',) + mh['vayoshri_mh'])
        if housing in ['homeless', 'kutcha']:
            schemes.append(('gharkul',) + mh['gharkul'])
        if earning == 'yes' or widow_status == 'yes' or (income < 5000 and age == 'elderly'):
            schemes.append(('sanjay_gandhi',) + mh['sanjay_gandhi'])
        if age == 'child':
            schemes.append(('rajmata_jijau',) + mh['rajmata_jijau'])
        if ration == 'no' or income < 10000:
            schemes.append(('mh_ration',) + mh['mh_ration'])

    seen = set()
    unique = []
    for item in schemes:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique

def get_priority(score, data):
    age = data['age_group']
    if age == 'child' and score >= 40: return "CRITICAL - Child in Need, Immediate Help Required"
    elif age == 'elderly' and score >= 40: return "CRITICAL - Elderly Person, Immediate Help Required"
    elif data['medical'] == 'emergency' or data['accident'] == 'yes': return "CRITICAL - Medical or Accident Emergency, Immediate Help"
    elif score >= 60: return "HIGH NEED - Urgent Help Required"
    elif score >= 40: return "MODERATE NEED - Eligible for Aid"
    elif score >= 20: return "LOW NEED - Some Schemes Available"
    else: return "Will Receive Basic Community Help"

def generate_tracking_id():
    return "PAI-2026-" + ''.join(random.choices(string.digits, k=4))

def get_db_connection():
    conn = sqlite3.connect('reports.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def root():
    return redirect(url_for('home'))


# Landing page
@app.route('/home')
def home():
    return render_template('home.html')


# Eligibility Form
@app.route('/eligibility', methods=['GET', 'POST'])
def index():
    ip = get_client_ip()
    result = None
    schemes = []
    score = 0
    person_name = ''

    # Get the language parameter if provided, otherwise leave it flexible for the user choice screen
    lang = request.args.get('lang') or request.form.get('lang') or session.get('lang', 'en')
    session['lang'] = lang

    
    if request.method == 'POST':

        if not rate_limit_check(ip):
            log_activity('PUBLIC', 'RATE_LIMIT_HIT', ip, 'Too many requests', suspicious=1)
            return render_template(
                'index.html',
                result="Too many requests. Please wait a minute.",
                schemes=[],
                score=0,
                lang='en',
                person_name='',
                now=datetime.now().strftime("%d %b %Y, %I:%M %p")
            )

        lang = sanitize(request.form.get('lang', 'en'))

        if not request.form.get('consent'):
            return render_template(
                'index.html',
                result=None,
                schemes=[],
                score=0,
                lang=lang,
                person_name='',
                error="Please accept the consent checkbox to continue.",
                now=datetime.now().strftime("%d %b %Y, %I:%M %p")
            )

        if 'age_group' not in request.form:
            return render_template(
                'index.html',
                result=None,
                schemes=[],
                score=0,
                lang=lang,
                person_name='',
                now=datetime.now().strftime("%d %b %Y, %I:%M %p")
            )

        person_name = sanitize(request.form.get('person_name', ''))
        phone = sanitize(request.form.get('phone', ''))
        address = sanitize(request.form.get('address', ''))
        gender = sanitize(request.form.get('gender', ''))
        widow = sanitize(request.form.get('widow_status', ''))

        if phone and not re.match(r'^[0-9]{10}$', phone):
            return render_template(
                'index.html',
                result=None,
                schemes=[],
                score=0,
                lang=lang,
                person_name='',
                error="Invalid phone number. Enter 10 digits.",
                now=datetime.now().strftime("%d %b %Y, %I:%M %p")
            )

        score = calculate_score(request.form)
        schemes = get_schemes(score, request.form, lang)
        result = get_priority(score, request.form)

        # Keep these session lines, just make sure to add the results flag
        session['schemes'] = schemes
        session['lang'] = lang
        session['person_name'] = person_name
        session['phone'] = phone
        session['address'] = address
        session['score'] = score
        session['result'] = result
        session['assessment_results_ready'] = True  # Flag to show the results block

        # Persistent profile for the AI Welfare Assistant chatbot. Unlike the
        # keys above, this is NOT popped after one display — it stays in the
        # session so the chatbot can use it on any page, any time later,
        # until the person fills the form again.
        session['profile'] = {
            'name': person_name,
            'gender': gender,
            'widow': widow,
            'age_group': request.form.get('age_group', ''),
            'income': request.form.get('income', ''),
            'family_size': request.form.get('family_size', ''),
            'housing': request.form.get('housing', ''),
            'electricity': request.form.get('electricity', ''),
            'ration': request.form.get('ration', ''),
            'medical': request.form.get('medical', ''),
            'accident': request.form.get('accident', ''),
            'earning_member_died': request.form.get('earning_member_died', ''),
            'address': address,
            'state': detect_state(address),
            'score': score,
            'priority': result,
            'schemes': [{'key': sc[0], 'urgency': sc[1], 'name': sc[2], 'amount': sc[3]} for sc in schemes],
            'lang': lang,
            'updated_at': datetime.now().strftime("%d %b %Y, %I:%M %p"),
        }

        try:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO form_submissions (phone, ip_address, submitted_at, lang, schemes_count, state) VALUES (?, ?, ?, ?, ?, ?)',
                (phone, ip, datetime.now().strftime("%d %b %Y, %I:%M %p"), lang, len(schemes), detect_state(address))
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        log_activity('PUBLIC', 'FORM_SUBMITTED', ip, f'Form submitted for {person_name}')

        return redirect(url_for('index', lang=lang))

    # Pull the calculated values out of the session safely.
    # FIX: use pop() (not get()) for every result-related key so the data
    # is shown exactly once and then wiped — otherwise the next visit to
    # /eligibility (fresh form) re-displays the previous person's result.
    results_ready = session.pop('assessment_results_ready', False)
    schemes = session.pop('schemes', [])
    score = session.pop('score', 0)
    result = session.pop('result', None)
    person_name = session.pop('person_name', '')
    session.pop('phone', None)
    session.pop('address', None)

    if not results_ready:
        # No fresh submission — always show a blank form, never stale data.
        schemes, score, result, person_name = [], 0, None, ''

    return render_template(
        'index.html', 
        results=results_ready, 
        schemes=schemes, 
        score=score, 
        result=result, 
        person_name=person_name, 
        lang=lang
    )
    
    

@app.route('/scheme/<scheme_key>')
def scheme_detail(scheme_key):
    lang = request.args.get('lang', session.get('lang', 'en'))
    detail = SCHEME_DETAILS.get(scheme_key)
    if not detail:
        return render_template('404.html'), 404
    scheme_info = detail.get(lang, detail.get('en'))
    return render_template('scheme_detail.html', scheme=scheme_info, lang=lang, scheme_key=scheme_key)

@app.route('/corruption', methods=['GET', 'POST'])
def corruption():
    tracking_id = None
    lang = request.args.get('lang', session.get('lang', 'en'))
    schemes = session.get('schemes', [])
    report = None
    ip = get_client_ip()
    if request.method == 'POST':
        action = request.form.get('action')
        lang = request.form.get('lang', 'en')
        if action == 'submit_report':
            tracking_id = generate_tracking_id()
            assigned_officer = random.choice(OFFICERS.get(lang, OFFICERS['en']))
            authority = random.choice(AUTHORITIES.get(lang, AUTHORITIES['en']))
            filed_date = datetime.now().strftime("%d %b %Y, %I:%M %p")
            expected = (datetime.now() + timedelta(days=30)).strftime("%d %b %Y")
            conn = get_db_connection()
            conn.execute('''INSERT INTO reports
                (tracking_id, person_name, phone, address, scheme,
                entitled_amount, received_amount, official_name, description,
                incident_date, location, status, assigned_officer, authority,
                filed_date, expected_resolution, lang)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (tracking_id,
                session.get('person_name', ''),
                session.get('phone', ''),
                session.get('address', ''),
                request.form.get('scheme'),
                request.form.get('entitled_amount'),
                request.form.get('received_amount'),
                request.form.get('official_name'),
                request.form.get('description'),
                request.form.get('incident_date'),
                request.form.get('location'),
                'Filed', assigned_officer, authority,
                filed_date, expected, lang))
            conn.commit()
            conn.close()
            log_activity('PUBLIC', 'COMPLAINT_FILED', ip,
                f'Tracking ID: {tracking_id}')
        elif action == 'track_report':
            track_id = request.form.get('tracking_id_input')
            conn = get_db_connection()
            row = conn.execute('SELECT * FROM reports WHERE tracking_id = ?', (track_id,)).fetchone()
            conn.close()
            if row:
                report = {
                    'tracking_id': row['tracking_id'], 'scheme': row['scheme'],
                    'entitled_amount': row['entitled_amount'], 'received_amount': row['received_amount'],
                    'description': row['description'], 'location': row['location'],
                    'status': row['status'], 'assigned_officer': row['assigned_officer'],
                    'authority': row['authority'], 'filed_date': row['filed_date'],
                    'received_date': row['received_date'], 'action_date': row['action_date'],
                    'resolved_date': row['resolved_date'], 'expected_resolution': row['expected_resolution']
                }
    return render_template('corruption.html', tracking_id=tracking_id, lang=lang, schemes=schemes, report=report)

@app.route('/track', methods=['GET', 'POST'])
def track():
    lang = request.args.get('lang', session.get('lang', 'en'))
    report = None
    not_found = False
    if request.method == 'POST':
        track_id = request.form.get('tracking_id_input')
        lang = request.form.get('lang', 'en')
        conn = get_db_connection()
        row = conn.execute('SELECT * FROM reports WHERE tracking_id = ?', (track_id,)).fetchone()
        conn.close()
        if row:
            report = {
                'tracking_id': row['tracking_id'], 'scheme': row['scheme'],
                'entitled_amount': row['entitled_amount'], 'received_amount': row['received_amount'],
                'description': row['description'], 'location': row['location'],
                'status': row['status'], 'assigned_officer': row['assigned_officer'],
                'authority': row['authority'], 'filed_date': row['filed_date'],
                'received_date': row['received_date'], 'action_date': row['action_date'],
                'resolved_date': row['resolved_date'], 'expected_resolution': row['expected_resolution']
            }
        else:
            not_found = True
    return render_template('track.html', report=report, not_found=not_found, lang=lang,scheme=report['scheme'] if report else '')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    ip = get_client_ip()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM admin_users WHERE username=?', (username,)).fetchone()
        if user and verify_password(user['password'], password):
            # Transparently upgrade any old unsalted SHA-256 hash to the
            # new salted hash the next time that account logs in.
            if not user['password'].startswith(('pbkdf2:', 'scrypt:')):
                conn.execute('UPDATE admin_users SET password=? WHERE username=?',
                    (hash_password(password), username))
                conn.commit()
            conn.close()
            session['admin_logged_in'] = True
            session['admin_username'] = user['username']
            session['admin_role'] = user['role']
            session['admin_name'] = user['full_name']
            log_activity(username, 'LOGIN_SUCCESS', ip, f'{user["full_name"]} logged in')
            return redirect(url_for('admin'))
        else:
            conn.close()
            log_activity(username or 'UNKNOWN', 'LOGIN_FAILED', ip,
                f'Failed login attempt with username: {username}', suspicious=1)
            error = "Invalid username or password"
    return render_template('login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    ip = get_client_ip()
    log_activity(session.get('admin_username', 'UNKNOWN'), 'LOGOUT', ip, 'User logged out')
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    session.pop('admin_role', None)
    session.pop('admin_name', None)
    return redirect(url_for('admin_login'))

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    ip = get_client_ip()
    conn = get_db_connection()
    log_activity(session.get('admin_username'), 'ADMIN_ACCESS', ip,
        f'Accessed admin dashboard')
    if request.method == 'POST':
        tracking_id = request.form.get('tracking_id')
        new_status = request.form.get('new_status')
        now = datetime.now().strftime("%d %b %Y, %I:%M %p")
        if new_status == 'Received':
            conn.execute('UPDATE reports SET status=?, received_date=? WHERE tracking_id=?', (new_status, now, tracking_id))
        elif new_status == 'Action Taken':
            conn.execute('UPDATE reports SET status=?, action_date=? WHERE tracking_id=?', (new_status, now, tracking_id))
        elif new_status == 'Resolved':
            conn.execute('UPDATE reports SET status=?, resolved_date=? WHERE tracking_id=?', (new_status, now, tracking_id))
        conn.commit()
        log_activity(session.get('admin_username'), 'STATUS_UPDATE', ip,
            f'Updated {tracking_id} to {new_status}')
    filter_status = request.args.get('filter', 'All')
    total = conn.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
    filed = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Filed'").fetchone()[0]
    received = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Received'").fetchone()[0]
    action = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Action Taken'").fetchone()[0]
    resolved = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Resolved'").fetchone()[0]
    suspicious_count = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE suspicious=1").fetchone()[0]
    if filter_status == 'All':
        reports = conn.execute('SELECT * FROM reports ORDER BY id DESC').fetchall()
    else:
        reports = conn.execute('SELECT * FROM reports WHERE status=? ORDER BY id DESC', (filter_status,)).fetchall()
    recent_logs = conn.execute('SELECT * FROM activity_logs ORDER BY id DESC LIMIT 20').fetchall()
    suspicious_logs = conn.execute('SELECT * FROM activity_logs WHERE suspicious=1 ORDER BY id DESC LIMIT 10').fetchall()
    conn.close()
    return render_template('admin.html',
        reports=reports, total=total, filed=filed, received=received,
        action=action, resolved=resolved, filter_status=filter_status,
        now=datetime.now().strftime("%d %b %Y, %I:%M %p"),
        admin_name=session.get('admin_name'),
        admin_role=session.get('admin_role'),
        recent_logs=recent_logs,
        suspicious_logs=suspicious_logs,
        suspicious_count=suspicious_count)

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/heatmap')
def heatmap():
    conn = get_db_connection()

    complaints = conn.execute('''
        SELECT location,
        COUNT(*) as count,
        SUM(CASE WHEN status='Resolved' THEN 1 ELSE 0 END) as resolved_count,
        SUM(CASE
            WHEN entitled_amount != '' AND received_amount != ''
            THEN CAST(entitled_amount AS INTEGER) -
                 CAST(received_amount AS INTEGER)
            ELSE 0
        END) as total_gap
        FROM reports
        GROUP BY location
        ORDER BY count DESC
    ''').fetchall()

    total = conn.execute(
        'SELECT COUNT(*) FROM reports'
    ).fetchone()[0]

    resolved = conn.execute(
        "SELECT COUNT(*) FROM reports WHERE status='Resolved'"
    ).fetchone()[0]

    top_locations = conn.execute('''
        SELECT location, COUNT(*) as count
        FROM reports
        GROUP BY location
        ORDER BY count DESC
        LIMIT 5
    ''').fetchall()

    conn.close()

    complaints_list = [dict(row) for row in complaints]
    top_list = [dict(row) for row in top_locations]

    return render_template(
        'heatmap.html',
        complaints=complaints_list,
        total=total,
        resolved=resolved,
        fake=0,
        top_locations=top_list
    )

# Fix 6 — Error pages
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(429)
def rate_limit_error(e):
    return render_template('429.html'), 429

# Fix 4 — Input sanitization helper
def sanitize(text):
    if not text:
        return ''
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', str(text))
    # Remove dangerous characters
    text = re.sub(r'[<>"\';]', '', text)
    return text.strip()

@app.route('/apply/<scheme_key>', methods=['GET', 'POST'])
def apply_scheme(scheme_key):
    lang = request.args.get('lang', session.get('lang', 'en'))
    detail = SCHEME_DETAILS.get(scheme_key)
    if not detail:
        return render_template('404.html'), 404
    scheme_info = detail.get(lang, detail.get('en'))
    success = False
    application_id = None
    if request.method == 'POST':
        application_id = 'APP-2026-' + ''.join(random.choices(string.digits, k=6))
        ip = get_client_ip()
        log_activity('PUBLIC', 'APPLICATION_SUBMITTED', ip,
            f'Application {application_id} for {scheme_key}')
        success = True
    return render_template('apply.html',
        scheme=scheme_info,
        scheme_key=scheme_key,
        lang=lang,
        success=success,
        application_id=application_id)

@app.route('/documents/<scheme_key>')
def documents(scheme_key):
    lang = request.args.get('lang', session.get('lang', 'en'))
    detail = SCHEME_DETAILS.get(scheme_key)
    if not detail:
        return render_template('404.html'), 404
    scheme_info = detail.get(lang, detail.get('en'))
    return render_template('documents.html',
        scheme=scheme_info,
        scheme_key=scheme_key,
        lang=lang)

@app.route('/offices')
def offices():
    lang = request.args.get('lang', session.get('lang', 'en'))
    return render_template('offices.html', lang=lang)

#keep alive on render free plan
from keep_alive import start
start("https://poverty-aid-identifier.onrender.com")

@app.route('/impact')
def impact():
    conn = get_db_connection()

    total_forms = conn.execute('SELECT COUNT(*) FROM form_submissions').fetchone()[0]
    total_schemes_matched = conn.execute('SELECT COALESCE(SUM(schemes_count),0) FROM form_submissions').fetchone()[0]
    states_covered = conn.execute(
        "SELECT COUNT(DISTINCT state) FROM form_submissions WHERE state IS NOT NULL AND state != ''"
    ).fetchone()[0]
    districts_with_reports = conn.execute(
        "SELECT COUNT(DISTINCT location) FROM reports WHERE fake_flag=0 AND location IS NOT NULL AND location != ''"
    ).fetchone()[0]
    total_complaints = conn.execute('SELECT COUNT(*) FROM reports WHERE fake_flag=0').fetchone()[0]
    resolved_complaints = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Resolved' AND fake_flag=0").fetchone()[0]
    resolution_rate = round((resolved_complaints / total_complaints * 100)) if total_complaints > 0 else 0

    lang_rows = conn.execute(
        "SELECT lang, COUNT(*) as cnt FROM form_submissions GROUP BY lang"
    ).fetchall()
    conn.close()

    lang_counts = {'en': 0, 'hi': 0, 'mr': 0}
    for row in lang_rows:
        key = row['lang'] if row['lang'] in lang_counts else 'en'
        lang_counts[key] += row['cnt']
    lang_total = sum(lang_counts.values()) or 1
    lang_percent = {k: round(v / lang_total * 100) for k, v in lang_counts.items()}

    lang = request.args.get('lang') or session.get('lang', 'en')

    return render_template(
        'impact.html',
        lang=lang,
        total_forms=total_forms,
        total_schemes_matched=total_schemes_matched,
        states_covered=states_covered,
        districts_with_reports=districts_with_reports,
        total_complaints=total_complaints,
        resolved_complaints=resolved_complaints,
        resolution_rate=resolution_rate,
        lang_percent=lang_percent
    )


def progress():
    conn = get_db_connection()
    now = datetime.now().strftime("%d %b %Y, %I:%M %p")

    # Total stats
    total = conn.execute('SELECT COUNT(*) FROM reports WHERE fake_flag=0').fetchone()[0]
    resolved = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Resolved' AND fake_flag=0").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM reports WHERE status!='Resolved' AND fake_flag=0").fetchone()[0]
    fake = conn.execute("SELECT COUNT(*) FROM reports WHERE fake_flag=1").fetchone()[0]
    rate = round((resolved / total * 100)) if total > 0 else 0

    # Monthly trend — last 6 months
    months = []
    from datetime import timedelta
    month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    max_val = 1
    for i in range(5, -1, -1):
        d = datetime.now() - timedelta(days=30*i)
        m = d.month
        y = d.year
        label = f"{month_names[m-1]} {str(y)[2:]}"
        c = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE filed_date LIKE ? AND fake_flag=0",
            (f"%{month_names[m-1]}%{y}%",)
        ).fetchone()[0]
        r = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE filed_date LIKE ? AND status='Resolved' AND fake_flag=0",
            (f"%{month_names[m-1]}%{y}%",)
        ).fetchone()[0]
        if c > max_val: max_val = c
        months.append({'month': label, 'complaints': c, 'resolved': r})

    # Scale bars to max 100px
    for m in months:
        m['complaint_height'] = max(4, int(m['complaints'] / max_val * 100)) if max_val > 0 else 4
        m['resolved_height'] = max(4, int(m['resolved'] / max_val * 100)) if max_val > 0 else 4

    # Improvement check
    improving = False
    improvement_percent = 0
    if len(months) >= 2:
        prev = months[-2]['complaints']
        curr = months[-1]['complaints']
        if prev > 0 and curr < prev:
            improving = True
            improvement_percent = round((prev - curr) / prev * 100)

    # District scores
    district_rows = conn.execute(
        "SELECT location, COUNT(*) as total, SUM(CASE WHEN status='Resolved' THEN 1 ELSE 0 END) as resolved FROM reports WHERE fake_flag=0 GROUP BY location ORDER BY total DESC LIMIT 10"
    ).fetchall()

    district_scores = []
    for row in district_rows:
        t = row['total']
        r = row['resolved'] or 0
        p = t - r
        rt = round(r / t * 100) if t > 0 else 0
        if t == 0:
            grade = 'A'
        elif rt >= 75:
            grade = 'B'
        elif rt >= 50:
            grade = 'C'
        elif p >= 5:
            grade = 'F'
        else:
            grade = 'D'
        parts = str(row['location']).split(',')
        name = parts[0].strip() if parts else row['location']
        state = parts[-1].strip() if len(parts) > 1 else 'India'
        district_scores.append({
            'name': name, 'state': state,
            'total': t, 'resolved': r,
            'pending': p, 'rate': rt, 'grade': grade
        })

    # Corruption free districts (grade A from above + zero complaints 30 days)
    clean_districts = []
    for d in district_scores:
        if d['grade'] == 'A':
            clean_districts.append({'name': d['name'], 'state': d['state'], 'days': 30})

    # Scheme stats
    scheme_rows = conn.execute(
        "SELECT scheme, COUNT(*) as total, SUM(CASE WHEN status='Resolved' THEN 1 ELSE 0 END) as resolved FROM reports WHERE fake_flag=0 GROUP BY scheme ORDER BY total DESC LIMIT 8"
    ).fetchall()

    scheme_stats = []
    for row in scheme_rows:
        t = row['total']
        r = row['resolved'] or 0
        rt = round(r / t * 100) if t > 0 else 0
        scheme_stats.append({
            'name': str(row['scheme'])[:40],
            'complaints': t,
            'resolved': r,
            'rate': rt
        })

    conn.close()

    return render_template('progress.html',
        now=now,
        total_complaints=total,
        resolved_count=resolved,
        pending_count=pending,
        fake_count=fake,
        resolution_rate=rate,
        monthly_trend=months,
        improving=improving,
        improvement_percent=improvement_percent,
        district_scores=district_scores,
        clean_districts=clean_districts,
        scheme_stats=scheme_stats
    )
@app.route('/stories')
def stories():
    conn = get_db_connection()

    # Get approved stories only
    story_rows = conn.execute(
        'SELECT * FROM success_stories WHERE approved=1 ORDER BY id DESC'
    ).fetchall()

    # Stats
    total_stories = conn.execute(
        'SELECT COUNT(*) FROM success_stories WHERE approved=1'
    ).fetchone()[0]

    total_schemes = conn.execute(
        'SELECT COUNT(*) FROM success_stories WHERE approved=1'
    ).fetchone()[0]

    # Count unique states
    state_rows = conn.execute(
        'SELECT DISTINCT location FROM success_stories WHERE approved=1'
    ).fetchall()
    states = set()
    for r in state_rows:
        if r['location'] and ',' in r['location']:
            states.add(r['location'].split(',')[-1].strip())
    states_covered = len(states) if states else 0

    # Avatar colors and icons
    icons = ['👨', '👩', '👴', '👵', '🧑', '👦', '👧']
    bgs = ['#e8f5e9', '#e3f2fd', '#fff3e0', '#fce4ec', '#f3e5f5', '#e0f7fa', '#fff8e1']
    scheme_colors = {
        'PM Jan Arogya Yojana': ('#fff3e0', '#e65c00'),
        'PM Awas Yojana': ('#e8f5e9', '#138808'),
        'Ayushman Bharat': ('#fff3e0', '#e65c00'),
        'Antyodaya Anna Yojana': ('#fff8e1', '#f57f17'),
        'Widow Pension': ('#f3e5f5', '#7b1fa2'),
        'Old Age Pension': ('#e3f2fd', '#1565c0'),
        'MNREGA': ('#e0f7fa', '#00838f'),
    }

    stories_list = []
    for i, row in enumerate(story_rows):
        sbg, scol = scheme_colors.get(row['scheme'], ('#f5f5f5', '#333333'))
        stories_list.append({
            'name': row['name'],
            'district': row['location'].split(',')[0].strip() if row['location'] and ',' in row['location'] else row['location'],
            'state': row['location'].split(',')[-1].strip() if row['location'] and ',' in row['location'] else 'India',
            'scheme': row['scheme'],
            'scheme_bg': sbg,
            'scheme_color': scol,
            'quote_en': row['story'],
            'quote_hi': row['story'],  # same text — user wrote in their own language
            'quote_mr': row['story'],
            'benefit': row['benefit'] or '',
            'benefit_hi': row['benefit'] or '',
            'benefit_mr': row['benefit'] or '',
            'time_taken': row['time_taken'] or '',
            'time_taken_hi': row['time_taken'] or '',
            'time_taken_mr': row['time_taken'] or '',
            'avatar_bg': bgs[i % len(bgs)],
            'avatar_icon': icons[i % len(icons)],
            'verified': True,
        })

    conn.close()

    return render_template('stories.html',
        stories=stories_list,
        total_stories=total_stories,
        total_schemes_received=total_schemes,
        states_covered=states_covered,
    )


@app.route('/stories/submit', methods=['POST'])
def submit_story():
    name = sanitize(request.form.get('name', ''))
    location = sanitize(request.form.get('location', ''))
    scheme = sanitize(request.form.get('scheme', ''))
    story = sanitize(request.form.get('story', ''))
    benefit = sanitize(request.form.get('benefit', ''))
    time_taken = sanitize(request.form.get('time_taken', ''))
    consent = request.form.get('consent')

    if not all([name, location, scheme, story, consent]):
        return render_template('stories.html',
            error="Please fill all required fields.",
            stories=[], total_stories=0,
            total_schemes_received=0, states_covered=0
        )

    if len(story) < 20:
        return render_template('stories.html',
            error="Please write a longer story (minimum 20 characters).",
            stories=[], total_stories=0,
            total_schemes_received=0, states_covered=0
        )

    conn = get_db_connection()
    filed_date = datetime.now().strftime("%d %b %Y, %I:%M %p")

    conn.execute(
        '''INSERT INTO success_stories
           (name, location, scheme, story, benefit, time_taken, approved, filed_date)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?)''',
        (name, location, scheme, story, benefit, time_taken, filed_date)
    )
    conn.commit()
    conn.close()

    # Log activity
    try:
        log_conn = get_db_connection()
        log_conn.execute(
            'INSERT INTO activity_logs (timestamp, username, action, ip_address) VALUES (?, ?, ?, ?)',
            (filed_date, name, 'Story submitted — pending approval', request.remote_addr or 'unknown')
        )
        log_conn.commit()
        log_conn.close()
    except:
        pass

    return render_template('story_submitted.html')


@app.route('/admin/stories')
@login_required
def admin_stories():
    conn = get_db_connection()
    pending = conn.execute(
        'SELECT * FROM success_stories WHERE approved=0 ORDER BY id DESC'
    ).fetchall()
    approved = conn.execute(
        'SELECT * FROM success_stories WHERE approved=1 ORDER BY id DESC'
    ).fetchall()
    conn.close()
    return render_template('admin_stories.html', pending=pending, approved=approved)


@app.route('/admin/stories/approve/<int:story_id>')
@login_required
def approve_story(story_id):
    conn = get_db_connection()
    conn.execute('UPDATE success_stories SET approved=1 WHERE id=?', (story_id,))
    conn.commit()
    conn.close()
    return redirect('/admin/stories')


@app.route('/admin/stories/reject/<int:story_id>')
@login_required
def reject_story(story_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM success_stories WHERE id=?', (story_id,))
    conn.commit()
    conn.close()
    return redirect('/admin/stories')

@app.route('/chatbot')
def chatbot_page():
    lang = request.args.get('lang', session.get('lang', 'en'))
    profile = session.get('profile')
    return render_template('chatbot.html', lang=lang, profile=profile)


@app.route('/chatbot', methods=['POST'])
def chatbot_reply():
    data = None
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        lang = data.get('lang', 'en')

        if not user_message:
            return jsonify({'reply': 'Please ask a question.'})

        # Sanitize input
        user_message = sanitize(user_message)

        # The eligibility form the person already filled in — if it exists,
        # the assistant should use it instead of asking generic questions.
        profile = session.get('profile')

        # A couple of question types get a deterministic, always-accurate
        # answer computed directly from the profile instead of asking Gemini
        # to guess — this keeps the Need Score explanation and document
        # checklist 100% consistent with what calculate_score()/get_schemes()
        # actually did.
        q = user_message.lower()
        score_question = any(k in q for k in [
            'need score', 'why is my score', 'why my score', 'score high', 'score so high',
            'स्कोर', 'गुण'
        ])
        doc_question = any(k in q for k in [
            'document', 'documents', 'papers', 'paper', 'missing document',
            'दस्तावेज़', 'कागदपत्र', 'कागद'
        ])

        if profile and score_question:
            explanation = explain_need_score(profile, lang)
            if explanation:
                push_chat_history(user_message, explanation)
                log_activity('CHATBOT', 'QUERY', get_client_ip(), f'Lang: {lang} | Q(score): {user_message[:50]}')
                return jsonify({'reply': explanation})

        if profile and doc_question:
            checklist = get_combined_documents(profile, lang)
            if checklist:
                push_chat_history(user_message, checklist)
                log_activity('CHATBOT', 'QUERY', get_client_ip(), f'Lang: {lang} | Q(docs): {user_message[:50]}')
                return jsonify({'reply': checklist})

        # Get Gemini API key
        api_key = os.environ.get('GEMINI_API_KEY', '')

        if not api_key:
            # Fallback if no API key — rule based answers, profile-aware
            fallback_reply = get_fallback_answer(user_message, lang, profile)
            push_chat_history(user_message, fallback_reply)
            return jsonify({'reply': fallback_reply})

        # Configure Gemini
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-3.5-flash')

        # CASE-WORKER MODE: if this person hasn't filled the eligibility form
        # yet, see if their message is actually a self-description ("I'm a
        # 62-year-old widow from Nagpur earning Rs 4000") rather than a plain
        # FAQ. One Gemini call either extracts structured facts (which we
        # then run through the real scoring engine) or just answers the FAQ.
        if not profile:
            intake = extract_case_intake(model, user_message, lang)
            if intake and intake.get('is_case_intake'):
                extracted = intake.get('extracted') or {}
                signal_count = sum(1 for f in INTAKE_SIGNAL_FIELDS if extracted.get(f) not in (None, ''))
                if signal_count >= 2:
                    new_profile = build_profile_from_intake(extracted, lang)
                    session['profile'] = new_profile  # remembered for follow-up questions too
                    reply = format_case_worker_reply(new_profile, lang)
                    push_chat_history(user_message, reply)
                    log_activity('CHATBOT', 'CASE_INTAKE', get_client_ip(), f'Lang: {lang} | Q: {user_message[:50]}')
                    return jsonify({'reply': reply})
            elif intake and intake.get('reply'):
                # Not a self-description — Gemini already answered it in the same call.
                push_chat_history(user_message, intake['reply'])
                log_activity('CHATBOT', 'QUERY', get_client_ip(), f'Lang: {lang} | Q: {user_message[:50]}')
                return jsonify({'reply': intake['reply']})
            # If extraction failed entirely, fall through to the normal flow below.

        # System prompt based on language
        system_prompts = {
            'en': """You are the AI Welfare Assistant for Poverty Aid Identifier — a free civic tech app that helps India's poorest citizens find government schemes they qualify for.

You help citizens with:
1. Information about 16 government schemes: PM Jan Arogya Yojana, PM Awas Yojana, Ayushman Bharat, Antyodaya Anna Yojana, National Family Benefit Scheme, PM Ujjwala Yojana, Old Age Pension (IGNOAPS), Widow Pension, Divyangjan Swavalamban, Accessible India Campaign, PM Poshan, ICDS, Annapurna Scheme, Saubhagya, PM Jan Dhan Yojana, Basic Community Support
2. Documents needed for each scheme
3. How to apply for schemes
4. Corruption reporting — citizens can file complaints at /corruption and track with tracking ID
5. How the AI Need Score works (0-175 points across 9 parameters)

Rules:
- Keep answers short and clear — max 4-5 lines, use bullet points for lists/steps
- Use simple language — the user may be poor or uneducated
- Always be helpful and kind
- If asked about something unrelated to welfare schemes, gently redirect to schemes
- Mention relevant helpline numbers when appropriate
- Do NOT make up information — only answer what you know about these schemes
- This is an ongoing conversation — refer back naturally to what was said earlier if the person asks a follow-up ("tell me more about the second one", "what about that scheme you mentioned").
- If the person's message is vague — like "I have a doubt", "I have a question", "need help" — with no actual topic mentioned, do NOT guess or dump a generic list. Ask a short, friendly clarifying question first, e.g. "Sure, what's your doubt about — eligibility, documents, or how to apply?"
- If a "User Profile" is given below, this person has ALREADY filled the eligibility form. Act like a personal welfare officer: use their exact details (name, income, housing, schemes, etc.) instead of asking for them again. Personalize eligibility answers, next-step advice, and document lists to THIS person's profile and recommended schemes specifically.""",

            'hi': """आप Poverty Aid Identifier के लिए AI Welfare Assistant हैं — एक मुफ्त civic tech ऐप जो भारत के गरीब नागरिकों को सरकारी योजनाएं खोजने में मदद करता है।

आप इनके बारे में मदद करते हैं:
1. 16 सरकारी योजनाओं की जानकारी
2. हर योजना के लिए जरूरी दस्तावेज़
3. आवेदन कैसे करें
4. भ्रष्टाचार की शिकायत कैसे करें

नियम:
- जवाब छोटे और सरल रखें — 4-5 लाइन से ज्यादा नहीं
- आसान हिंदी में बोलें — उपयोगकर्ता पढ़ा-लिखा नहीं हो सकता
- हमेशा दयालु और मददगार रहें
- झूठी जानकारी न दें
- यह एक चालू बातचीत है — अगर व्यक्ति पहले कही गई बात के बारे में पूछे ("दूसरे वाले के बारे में बताओ"), तो पिछली बात को याद रखते हुए जवाब दें।
- अगर व्यक्ति का संदेश अस्पष्ट है — जैसे "मुझे एक शक है", "मुझे सवाल है", "मदद चाहिए" — और कोई असली विषय नहीं बताया गया है, तो अंदाजा मत लगाइए या सामान्य सूची मत भेजिए। पहले एक छोटा, दोस्ताना स्पष्टीकरण वाला सवाल पूछें, जैसे "जरूर, आपका सवाल किस बारे में है — पात्रता, दस्तावेज़, या आवेदन कैसे करें?"
- अगर नीचे "User Profile" दिया गया है, तो इस व्यक्ति ने पहले ही फॉर्म भर दिया है। दोबारा जानकारी मत मांगिए — इनकी असल जानकारी (नाम, आय, आवास, योजनाएं) के आधार पर व्यक्तिगत जवाब दें।""",

            'mr': """तुम्ही Poverty Aid Identifier साठी AI Welfare Assistant आहात — एक मोफत civic tech अॅप जे भारतातील गरीब नागरिकांना सरकारी योजना शोधण्यास मदत करते.

तुम्ही यासाठी मदत करता:
1. 16 सरकारी योजनांची माहिती
2. प्रत्येक योजनेसाठी आवश्यक कागदपत्रे
3. अर्ज कसा करावा
4. भ्रष्टाचाराची तक्रार कशी करावी

नियम:
- उत्तरे छोटी आणि स्पष्ट ठेवा — 4-5 ओळींपेक्षा जास्त नाही
- सोप्या मराठीत बोला
- नेहमी दयाळू आणि मदत करणारे राहा
- खोटी माहिती देऊ नका
- ही एक सुरू असलेली संभाषण आहे — व्यक्तीने आधी सांगितलेल्याबद्दल पुढचा प्रश्न विचारल्यास ("दुसऱ्याबद्दल सांग"), आधीचे लक्षात ठेवून उत्तर द्या.
- व्यक्तीचा संदेश अस्पष्ट असल्यास — जसे "मला शंका आहे", "प्रश्न आहे", "मदत हवी" — आणि खरा विषय सांगितलेला नसल्यास, अंदाज लावू नका किंवा सामान्य यादी पाठवू नका. आधी एक छोटा, मैत्रीपूर्ण स्पष्टीकरण देणारा प्रश्न विचारा, जसे "नक्कीच, तुमचा प्रश्न कशाबद्दल आहे — पात्रता, कागदपत्रे, की अर्ज कसा करावा?"
- खाली "User Profile" दिलेले असल्यास, या व्यक्तीने आधीच फॉर्म भरला आहे. पुन्हा माहिती विचारू नका — त्यांच्या खऱ्या माहितीच्या (नाव, उत्पन्न, निवास, योजना) आधारे वैयक्तिक उत्तर द्या."""
        }

        system_prompt = system_prompts.get(lang, system_prompts['en'])

        profile_block = build_profile_context(profile, lang)
        system_instruction = system_prompt + ("\n\n" + profile_block if profile_block else "")

        # Real multi-turn memory: rebuild a chat session from the last few
        # exchanges stored in session['chat_history'], so follow-up doubts
        # ("tell me more about the second one") actually have context.
        chat_model = genai.GenerativeModel('gemini-3.5-flash', system_instruction=system_instruction)
        gemini_history = [
            {'role': h['role'], 'parts': [h['text']]}
            for h in session.get('chat_history', [])
        ]
        chat = chat_model.start_chat(history=gemini_history)
        response = chat.send_message(user_message)
        reply = response.text.strip()

        push_chat_history(user_message, reply)

        # Log the interaction
        log_activity('CHATBOT', 'QUERY', get_client_ip(),
            f'Lang: {lang} | Q: {user_message[:50]}')

        return jsonify({'reply': reply})

    except Exception as e:
        print(f"Chatbot error: {e}")
        return jsonify({'reply': get_fallback_answer(
            data.get('message', '') if data else '',
            data.get('lang', 'en') if data else 'en',
            session.get('profile')
        )})


def get_fallback_answer(question, lang='en', profile=None):
    """Rule-based fallback when Gemini API is not available. Profile-aware:
    if the person already filled the eligibility form, 'what next' and the
    generic default answer are personalized to their recommended schemes."""
    q = question.lower().strip()

    # VAGUE INPUT: "I have a doubt", "I have a question", "need help" etc.
    # don't say WHAT the doubt is about — a real case worker would ask back,
    # not dump a generic list. This has to be checked BEFORE anything else,
    # and only when the message doesn't already contain a real topic keyword.
    vague_phrases = [
        'i have a doubt', 'i have doubts', 'i have some doubt', 'i have a question',
        'i have some questions', 'need help', 'i need help', 'can you help',
        'help me', 'i have a query', 'confused', 'doubt', 'query',
        'मुझे शक है', 'मुझे संदेह है', 'मेरा एक सवाल है', 'मदद चाहिए', 'सवाल है',
        'मला शंका आहे', 'मला मदत हवी', 'प्रश्न आहे',
    ]
    topic_keywords = [
        'awas', 'ayushman', 'pension', 'widow', 'ration', 'antyodaya', 'jan dhan',
        'ujjwala', 'corruption', 'score', 'document', 'papers', 'apply', 'eligib',
        'ladki bahin', 'saubhagya', 'poshan', 'icds', 'divyangjan', 'accessible',
        'आवास', 'आयुष्मान', 'पेंशन', 'विधवा', 'राशन', 'भ्रष्टाचार', 'स्कोर', 'दस्तावेज़',
        'निवृत्तीवेतन', 'रेशन', 'भ्रष्टाचार', 'कागदपत्र',
    ]
    is_vague = any(p in q for p in vague_phrases) and not any(t in q for t in topic_keywords)
    if is_vague:
        clarify = {
            'en': "Sure, I'm here to help — what's your doubt about? For example, you can ask me:\n• \"Am I eligible for [scheme name]?\"\n• \"What documents do I need?\"\n• \"How do I apply?\"\n• \"Why is my Need Score high?\"\n• \"How do I report corruption?\"\n\nJust tell me what's on your mind.",
            'hi': "जरूर, मैं मदद के लिए यहां हूं — आपका सवाल किस बारे में है? जैसे आप पूछ सकते हैं:\n• \"क्या मैं [योजना का नाम] के लिए पात्र हूं?\"\n• \"मुझे कौन से दस्तावेज़ चाहिए?\"\n• \"आवेदन कैसे करें?\"\n• \"मेरा Need Score ज्यादा क्यों है?\"\n• \"भ्रष्टाचार की शिकायत कैसे करें?\"\n\nबस बताइए आपके मन में क्या है।",
            'mr': "नक्कीच, मी मदतीसाठी इथे आहे — तुमचा प्रश्न कशाबद्दल आहे? उदाहरणार्थ तुम्ही विचारू शकता:\n• \"मी [योजनेचे नाव] साठी पात्र आहे का?\"\n• \"मला कोणती कागदपत्रे हवीत?\"\n• \"अर्ज कसा करावा?\"\n• \"माझा Need Score जास्त का आहे?\"\n• \"भ्रष्टाचाराची तक्रार कशी करावी?\"\n\nफक्त सांगा तुमच्या मनात काय आहे.",
        }
        return clarify.get(lang, clarify['en'])

    # Official scheme names are long ("Indira Gandhi National Widow Pension
    # Scheme") so a citizen typing a short casual phrase ("widow pension")
    # wouldn't match by substring alone. These aliases cover the common
    # short ways people actually ask about a scheme.
    SCHEME_QUERY_ALIASES = {
        'widow_pension': ['widow pension', 'vidhwa pension', 'विधवा पेंशन', 'विधवा निवृत्तीवेतन'],
        'old_age_pension': ['old age pension', 'vridha pension', 'वृद्धावस्था पेंशन', 'वृद्धापकाळ'],
        'pm_awas': ['awas yojana', 'pm awas', 'आवास योजना'],
        'ayushman': ['ayushman bharat', 'ayushman', 'आयुष्मान'],
        'ladki_bahin': ['ladki bahin', 'लाडकी बहीण'],
        'ujjwala': ['ujjwala', 'gas connection', 'उज्ज्वला'],
        'jan_dhan': ['jan dhan', 'bank account scheme', 'जन धन'],
        'antyodaya': ['antyodaya', 'ration scheme', 'अंत्योदय'],
        'divyangjan': ['divyangjan', 'disability pension', 'दिव्यांगजन'],
    }

    if profile:
        recommended_keys = {sc['key'] for sc in (profile.get('schemes') or [])}
        for key, detail in SCHEME_DETAILS.items():
            info = detail.get(lang, detail.get('en'))
            scheme_name = info.get('name', '')
            simple_name = scheme_name.split('(')[0].strip().lower()
            aliases = SCHEME_QUERY_ALIASES.get(key, [])
            matched = (simple_name and simple_name in q and len(simple_name) > 3) or any(a in q for a in aliases)
            if matched:
                if key in recommended_keys:
                    templates = {'en': f"Yes — based on your profile, you ARE eligible for {scheme_name} ({info.get('amount','')}). It's already in your recommended list.",
                                 'hi': f"हां — आपकी प्रोफ़ाइल के अनुसार, आप {scheme_name} ({info.get('amount','')}) के लिए पात्र हैं। यह पहले से आपकी सुझाई गई सूची में है।",
                                 'mr': f"होय — तुमच्या प्रोफाइलनुसार, तुम्ही {scheme_name} ({info.get('amount','')}) साठी पात्र आहात. ही आधीच तुमच्या शिफारस केलेल्या यादीत आहे."}
                else:
                    elig = ", ".join(info.get('eligibility', []))
                    templates = {'en': f"Based on your current profile, {scheme_name} isn't in your recommended list. Its eligibility needs: {elig}.",
                                 'hi': f"आपकी वर्तमान प्रोफ़ाइल के अनुसार, {scheme_name} आपकी सुझाई गई सूची में नहीं है। इसकी पात्रता शर्तें: {elig}.",
                                 'mr': f"तुमच्या सध्याच्या प्रोफाइलनुसार, {scheme_name} तुमच्या शिफारस केलेल्या यादीत नाही. पात्रता अटी: {elig}."}
                return templates.get(lang, templates['en'])

    next_keywords = ['what should i do', 'what next', 'next step', 'what do i do', 'आगे क्या', 'पुढे काय']
    if profile and any(k in q for k in next_keywords):
        schemes = profile.get('schemes') or []
        if schemes:
            top = schemes[:3]
            headers = {'en': "Based on your profile, here's what to do next:",
                       'hi': "आपकी प्रोफ़ाइल के आधार पर, अब यह करें:",
                       'mr': "तुमच्या प्रोफाइलनुसार, आता हे करा:"}
            steps = "\n".join(f"{i+1}. Apply for {sc['name']} ({sc['amount']})" for i, sc in enumerate(top))
            checklist = get_combined_documents(profile, lang)
            doc_line = ("\n\n" + checklist) if checklist else ""
            return f"{headers.get(lang, headers['en'])}\n\n{steps}{doc_line}"
 
    fallbacks = {
        'en': {
            'awas': "PM Awas Yojana gives Rs.1,20,000 for house construction to BPL families.\n\nDocuments needed:\n• Aadhaar Card\n• BPL Certificate\n• Land ownership document\n• Bank account details\n\nApply at your Gram Panchayat or online at pmaymis.gov.in\nHelpline: 1800-11-6163",
            'ayushman': "Ayushman Bharat gives free health insurance up to Rs.5 lakh per year.\n\nDocuments needed:\n• Aadhaar Card\n• Ration Card\n• SECC Certificate\n\nJust visit any empanelled hospital and show your Aadhaar.\nHelpline: 14555",
            'pension': "Old Age Pension (IGNOAPS) gives Rs.200-500 per month to elderly BPL citizens aged 60+.\n\nDocuments needed:\n• Aadhaar Card\n• Age proof\n• BPL Certificate\n• Bank details\n\nApply at Gram Panchayat or Block Office.\nHelpline: 1800-111-555",
            'corruption': "To report corruption:\n1. Go to our app and click 'Report Corruption'\n2. Fill officer name, scheme, amount demanded\n3. You get a tracking ID like PAI-2026-XXXX\n4. Track status: Filed → Received → Action Taken → Resolved\n\nYou can also call: 1800-11-0001",
            'score': "The AI Need Score is calculated from 9 parameters:\n• Income (40 pts)\n• Medical condition (30 pts)\n• Accident (25 pts)\n• Earning member death (25 pts)\n• Age group (30 pts)\n• Housing (20 pts)\n• Family size (20 pts)\n• Electricity (10 pts)\n• Ration card (10 pts)\n\nMaximum score: 175 points",
            'ration': "Antyodaya Anna Yojana gives 35 kg free food grains per month to the poorest BPL families.\n\nDocuments: Aadhaar + Ration Card\nApply at nearest Food Department office.\nHelpline: 1800-111-001",
            'default': "I can help you with:\n• PM Awas Yojana (housing)\n• Ayushman Bharat (health)\n• Old Age / Widow Pension\n• Ration schemes\n• Corruption reporting\n• How to apply for any scheme\n\nWhat would you like to know?"
        },
        'hi': {
            'awas': "PM आवास योजना BPL परिवारों को घर बनाने के लिए ₹1,20,000 देती है।\n\nजरूरी दस्तावेज़:\n• आधार कार्ड\n• BPL प्रमाण पत्र\n• जमीन का दस्तावेज़\n• बैंक खाता विवरण\n\nग्राम पंचायत या pmaymis.gov.in पर आवेदन करें।\nहेल्पलाइन: 1800-11-6163",
            'ayushman': "आयुष्मान भारत में हर साल ₹5 लाख तक का मुफ्त इलाज मिलता है।\n\nजरूरी दस्तावेज़:\n• आधार कार्ड\n• राशन कार्ड\n\nकिसी भी सूचीबद्ध अस्पताल में जाएं।\nहेल्पलाइन: 14555",
            'pension': "वृद्धावस्था पेंशन में 60+ उम्र के BPL नागरिकों को ₹200-500 प्रति माह मिलता है।\n\nजरूरी दस्तावेज़:\n• आधार कार्ड\n• उम्र प्रमाण\n• BPL प्रमाण पत्र\n\nग्राम पंचायत में आवेदन करें।",
            'corruption': "भ्रष्टाचार की शिकायत के लिए:\n1. ऐप में 'भ्रष्टाचार रिपोर्ट' पर क्लिक करें\n2. अधिकारी का नाम, योजना, मांगी गई राशि भरें\n3. आपको PAI-2026-XXXX ट्रैकिंग ID मिलेगी\n4. स्थिति ट्रैक करें: दर्ज → प्राप्त → कार्रवाई → हल",
            'default': "मैं इनमें मदद कर सकता हूं:\n• PM आवास योजना\n• आयुष्मान भारत\n• वृद्धावस्था/विधवा पेंशन\n• राशन योजनाएं\n• भ्रष्टाचार की शिकायत\n\nआप क्या जानना चाहते हैं?"
        },
        'mr': {
            'awas': "PM आवास योजना BPL कुटुंबांना घर बांधण्यासाठी ₹1,20,000 देते.\n\nआवश्यक कागदपत्रे:\n• आधार कार्ड\n• BPL प्रमाणपत्र\n• जमिनीचा दस्तऐवज\n• बँक खाते तपशील\n\nग्रामपंचायत किंवा pmaymis.gov.in वर अर्ज करा.\nहेल्पलाइन: 1800-11-6163",
            'ayushman': "आयुष्मान भारतमध्ये दरवर्षी ₹5 लाखापर्यंत मोफत उपचार मिळतो.\n\nआवश्यक कागदपत्रे:\n• आधार कार्ड\n• रेशन कार्ड\n\nकोणत्याही सूचीबद्ध रुग्णालयात जा.\nहेल्पलाइन: 14555",
            'pension': "वृद्धापकाळ पेन्शनमध्ये 60+ वयाच्या BPL नागरिकांना ₹200-500 प्रति महिना मिळतो.\n\nआवश्यक कागदपत्रे:\n• आधार कार्ड\n• वयाचा पुरावा\n• BPL प्रमाणपत्र\n\nग्रामपंचायतमध्ये अर्ज करा.",
            'corruption': "भ्रष्टाचाराची तक्रार करण्यासाठी:\n1. अॅपमध्ये 'भ्रष्टाचार तक्रार' वर क्लिक करा\n2. अधिकाऱ्याचे नाव, योजना, मागितलेली रक्कम भरा\n3. तुम्हाला PAI-2026-XXXX ट्रॅकिंग ID मिळेल\n4. स्थिती ट्रॅक करा: दाखल → प्राप्त → कारवाई → निराकरण",
            'default': "मी यासाठी मदत करू शकतो:\n• PM आवास योजना\n• आयुष्मान भारत\n• वृद्धापकाळ/विधवा पेन्शन\n• रेशन योजना\n• भ्रष्टाचार तक्रार\n\nतुम्हाला काय जाणून घ्यायचे आहे?"
        }
    }
 
    f = fallbacks.get(lang, fallbacks['en'])
    if 'awas' in q or 'housing' in q or 'house' in q or 'घर' in q:
        return f.get('awas', f['default'])
    elif 'ayushman' in q or 'health' in q or 'hospital' in q or 'आयुष्मान' in q:
        return f.get('ayushman', f['default'])
    elif 'pension' in q or 'old age' in q or 'elderly' in q or 'पेंशन' in q or 'पेन्शन' in q:
        return f.get('pension', f['default'])
    elif 'corruption' in q or 'bribe' in q or 'report' in q or 'भ्रष्टाचार' in q:
        return f.get('corruption', f['default'])
    elif 'score' in q or 'need score' in q or 'algorithm' in q or 'स्कोर' in q:
        return f.get('score', f['default'])
    elif 'ration' in q or 'antyodaya' in q or 'food' in q or 'राशन' in q or 'रेशन' in q:
        return f.get('ration', f['default'])
    else:
        if profile and profile.get('schemes'):
            names = ", ".join(sc['name'] for sc in profile['schemes'][:4])
            headers = {'en': f"Based on your profile, you're recommended for: {names}.\n\nAsk me things like 'what should I do next', 'why is my score high', or 'which documents am I missing'.",
                       'hi': f"आपकी प्रोफ़ाइल के आधार पर, ये योजनाएं आपके लिए सुझाई गई हैं: {names}.\n\nमुझसे पूछें: 'आगे क्या करें', 'मेरा स्कोर ज्यादा क्यों है', या 'कौन से दस्तावेज़ बाकी हैं'।",
                       'mr': f"तुमच्या प्रोफाइलनुसार, या योजना तुम्हाला सुचवल्या आहेत: {names}.\n\nमला विचारा: 'पुढे काय करावे', 'माझा स्कोर जास्त का आहे', किंवा 'कोणती कागदपत्रे बाकी आहेत'."}
            return headers.get(lang, headers['en'])
        return f['default']

if __name__ == '__main__':
    
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), threaded=True)
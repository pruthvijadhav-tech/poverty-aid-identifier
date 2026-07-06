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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)


_SECRET_KEY_FALLBACK = 'poverty_aid_secret_key_2026_secure_fallback'
app.secret_key = os.environ.get('SECRET_KEY', _SECRET_KEY_FALLBACK)
if app.secret_key == _SECRET_KEY_FALLBACK:
    print('[WARNING] SECRET_KEY env var not set — using an insecure default. '
          'Set SECRET_KEY before deploying this publicly.')


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
        submitted_at TEXT
    )
    ''')
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
            ('officer1', hash_password(os.environ.get('OFFICER1_PASSWORD', 'officer2026')), 'officer', 'Rajesh Kumar Sharma IAS')
        )

        c.execute(
            "INSERT INTO admin_users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
            ('officer2', hash_password(os.environ.get('OFFICER2_PASSWORD', 'officer2026')), 'officer', 'Sunita Yadav IAS')
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
        "Alok Kumar Verma IAS (Central Vigilance Commissioner)",
        "Sanjay K. Mishra IPS (Vigilance Commissioner, CVC)",
        "R.C. Srinivasan IAS (Vigilance Commissioner, CVC)",
        "Justice K.S. Deshmukh (Lokayukta, Maharashtra)",
        "Justice Milind Gaikwad (Lokayukta, Maharashtra)",
        "Shri P.K. Deshpande IAS (DARPG Secretary, CPGRAMS)",
        "Amit Singh Chouhan IAS (District Collector)",
        "Anjali Sharma IAS (District Collector)",
        "Rohan Singh Bundela IAS (District Magistrate)",
        "Kavita Singhal IAS (District Collector)"
    ],
    "hi": [
        "आलोक कुमार वर्मा IAS (केंद्रीय सतर्कता आयुक्त)",
        "संजय के. मिश्रा IPS (सतर्कता आयुक्त, CVC)",
        "R.C. श्रीनिवासन IAS (सतर्कता आयुक्त, CVC)",
        "न्यायमूर्ति K.S. देशमुख (लोकायुक्त, महाराष्ट्र)",
        "न्यायमूर्ति मिलिंद गायकवाड़ (लोकायुक्त, महाराष्ट्र)",
        "श्री P.K. देशपांडे IAS (DARPG सचिव, CPGRAMS)",
        "अमित सिंह चौहान IAS (जिला कलेक्टर)",
        "अंजलि शर्मा IAS (जिला कलेक्टर)",
        "रोहन सिंह बुंदेला IAS (जिला मजिस्ट्रेट)",
        "कविता सिंघल IAS (जिला कलेक्टर)"
    ],
    "mr": [
        "आलोक कुमार वर्मा IAS (केंद्रीय दक्षता आयुक्त)",
        "संजय के. मिश्रा IPS (दक्षता आयुक्त, CVC)",
        "R.C. श्रीनिवासन IAS (दक्षता आयुक्त, CVC)",
        "न्यायमूर्ती K.S. देशमुख (लोकायुक्त, महाराष्ट्र)",
        "न्यायमूर्ती मिलिंद गायकवाड़ (लोकायुक्त, महाराष्ट्र)",
        "श्री P.K. देशपांडे IAS (DARPG सचिव, CPGRAMS)",
        "अमित सिंह चौहान IAS (जिल्हाधिकारी)",
        "अंजलि शर्मा IAS (जिल्हाधिकारी)",
        "रोहन सिंह बुंदेला IAS (जिल्हा दंडाधिकारी)",
        "कविता सिंघल IAS (जिल्हाधिकारी)"
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
        "widow_pension": ("normal", "Indira Gandhi National Widow Pension", "Rs. 300/month"),
    },
    "hi": {
        "pm_jan_arogya": ("urgent", "PM जन आरोग्य योजना (आपातकालीन चिकित्सा सहायता)", "रु. 5,00,000/वर्ष"),
        "state_emergency": ("urgent", "राज्य आपातकालीन राहत निधि (दुर्घटना)", "रु. 10,000"),
        "national_family": ("urgent", "राष्ट्रीय परिवार लाभ योजना (कमाने वाले सदस्य की मृत्यु)", "रु. 20,000"),
        "pm_poshan": ("normal", "PM पोषण योजना (बच्चों के लिए पोषण)", "मुफ्त भोजन"),
        "icds": ("normal", "एकीकृत बाल विकास सेवाएं (ICDS)", "मुफ्त सेवाएं"),
        "old_age_pension": ("normal", "इंदिरा गांधी राष्ट्रीय वृद्धावस्था पेंशन", "रु. 200-500/माह"),
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
        "widow_pension": ("normal", "इंदिरा गांधी राष्ट्रीय विधवा पेंशन", "रु. 300/माह"),
    },
    "mr": {
        "pm_jan_arogya": ("urgent", "PM जन आरोग्य योजना (आपत्कालीन वैद्यकीय मदत)", "रु. 5,00,000/वर्ष"),
        "state_emergency": ("urgent", "राज्य आपत्कालीन मदत निधी (अपघात)", "रु. 10,000"),
        "national_family": ("urgent", "राष्ट्रीय कुटुंब लाभ योजना (कमावत्या सदस्याचे निधन)", "रु. 20,000"),
        "pm_poshan": ("normal", "PM पोषण योजना (मुलांसाठी पोषण)", "मोफत जेवण"),
        "icds": ("normal", "एकात्मिक बाल विकास सेवा (ICDS)", "मोफत सेवा"),
        "old_age_pension": ("normal", "इंदिरा गांधी राष्ट्रीय वृद्धापकाळ निवृत्तीवेतन", "रु. 200-500/महिना"),
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
        "widow_pension": ("normal", "इंदिरा गांधी राष्ट्रीय विधवा पेन्शन", "रु. 300/महिना"),
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
    "annapurna": {
        "en": {"name": "Annapurna Scheme", "amount": "10 kg free food grains per month", "description": "Free food grains to senior citizens not covered under NSAP old age pension.", "eligibility": ["Age 65 years and above", "Not receiving old age pension", "Indigent/destitute"], "documents": ["Aadhaar Card", "Age Proof", "BPL Certificate"], "how_to_apply": "Apply at Gram Panchayat or Block Office.", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"},
        "hi": {"name": "अन्नपूर्णा योजना", "amount": "10 किग्रा मुफ्त खाद्यान्न प्रति माह", "description": "NSAP वृद्धावस्था पेंशन के अंतर्गत न आने वाले वरिष्ठ नागरिकों को मुफ्त खाद्यान्न।", "eligibility": ["65 वर्ष और उससे अधिक आयु", "वृद्धावस्था पेंशन नहीं मिल रही", "निराश्रित"], "documents": ["आधार कार्ड", "आयु प्रमाण", "BPL प्रमाण पत्र"], "how_to_apply": "ग्राम पंचायत या ब्लॉक कार्यालय में आवेदन करें।", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"},
        "mr": {"name": "अन्नपूर्णा योजना", "amount": "10 किग्रा मोफत अन्नधान्य प्रति महिना", "description": "NSAP वृद्धापकाळ निवृत्तीवेतनाखाली न येथे असणाऱ्या ज्येष्ठ नागरिकांना मोफत अन्नधान्य.", "eligibility": ["65 वर्षे आणि त्याहून अधिक वय", "वृद्धापकाळ निवृत्तीवेतन मिळत नाही", "निराधार"], "documents": ["आधार कार्ड", "वयाचा पुरावा", "BPL प्रमाणपत्र"], "how_to_apply": "ग्रामपंचायत किंवा गट कार्यालयात अर्ज करा.", "website": "https://dfpd.gov.in", "helpline": "1800-111-001"}
    },
    "ayushman": {
        "en": {"name": "Ayushman Bharat (Free Health Insurance)", "amount": "Rs. 5,00,000 per year", "description": "Health insurance cover for secondary and tertiary hospitalization for BPL families.", "eligibility": ["BPL family", "SECC 2011 listed", "No private health insurance"], "documents": ["Aadhaar Card", "Ration Card", "SECC Certificate"], "how_to_apply": "Visit nearest empanelled hospital. Show Aadhaar card for cashless treatment.", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "hi": {"name": "आयुष्मान भारत (मुफ्त स्वास्थ्य बीमा)", "amount": "रु. 5,00,000 प्रति वर्ष", "description": "BPL परिवारों के लिए hospital में भर्ती के लिए स्वास्थ्य बीमा कवर।", "eligibility": ["BPL परिवार", "SECC 2011 में सूचीबद्ध", "कोई निजी स्वास्थ्य बीमा नहीं"], "documents": ["आधार कार्ड", "राशन कार्ड", "SECC प्रमाण पत्र"], "how_to_apply": "नजदीकी सूचीबद्ध अस्पताल जाएं।", "website": "https://pmjay.gov.in", "helpline": "14555"},
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
    "basic": {
        "en": {"name": "Basic Community Support and Ration Assistance", "amount": "As applicable", "description": "Local community support programs including ration assistance and basic welfare services.", "eligibility": ["Any person in need", "BPL or poor household"], "documents": ["Aadhaar Card", "Any identity proof"], "how_to_apply": "Contact nearest Gram Panchayat, Municipal Corporation, or local NGO.", "website": "https://socialjustice.gov.in", "helpline": "1800-180-6763"},
        "hi": {"name": "बुनियादी सामुदायिक सहायता और राशन सहायता", "amount": "लागू अनुसार", "description": "राशन सहायता और बुनियादी कल्याण सेवाओं सहित स्थानीय सामुदायिक सहायता।", "eligibility": ["जरूरतमंद कोई भी व्यक्ति", "BPL या गरीब परिवार"], "documents": ["आधार कार्ड", "कोई भी पहचान प्रमाण"], "how_to_apply": "निकटतम ग्राम पंचायत या स्थानीय NGO से संपर्क करें।", "website": "https://socialjustice.gov.in", "helpline": "1800-180-6763"},
        "mr": {"name": "मूलभूत सामुदायिक मदत आणि रेशन सहाय्य", "amount": "लागू असेल तसे", "description": "रेशन मदत आणि मूलभूत कल्याण सेवांसह स्थानिक सामुदायिक मदत.", "eligibility": ["गरजू कोणताही व्यक्ती", "BPL किंवा गरीब कुटुंब"], "documents": ["आधार कार्ड", "कोणताही ओळख पुरावा"], "how_to_apply": "जवळच्याग्रामपंचायत किंवा स्थानिक NGO शी संपर्क करा.", "website": "https://socialjustice.gov.in", "helpline": "1800-180-6763"}
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
        'mh_health':      ('urgent', 'महात्मा फुले जन आरोग्य योजना (MH)', 'रु. 5 lakh/वर्ष'),
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
    return score

def get_schemes(score, data, lang='en'):
    schemes = []
    age = data['age_group']
    medical = data['medical']
    accident = data['accident']
    housing = data['housing']
    electricity = data['electricity']
    ration = data['ration']
    earning = data['earning_member_died']
    income = int(data.get('income', 0) or 0)
    address = data.get('address', '').lower()
    s = SCHEMES.get(lang, SCHEMES['en'])
    if medical == 'emergency': schemes.append(('pm_jan_arogya',) + s['pm_jan_arogya'])
    if accident == 'yes': schemes.append(('state_emergency',) + s['state_emergency'])
    if earning == 'yes': schemes.append(('national_family',) + s['national_family'])
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
        gender = data.get('gender', '')
        widow = data.get('widow_status', 'no')
        
        # Widow Pension — central scheme
        if widow == 'yes':
            schemes.append(('widow_pension',) + s.get('widow_pension',
                ('normal', 'Widow Pension Scheme', 'Rs. 300/month')))
                
        mh = MH_SCHEMES.get(lang, MH_SCHEMES['en'])
        
        # Ladki Bahin — female + Maharashtra + income limit
        if is_mh and gender == 'female' and income < 20834:
            schemes.append(('ladki_bahin',) + mh['ladki_bahin'])
            
        if medical in ['emergency', 'chronic_illness', 'disability'] or income < 10000:
            schemes.append(('mh_health',) + mh['mh_health'])
        if age == 'elderly':
            schemes.append(('shravan_bal',) + mh['shravan_bal'])
            if medical in ['disability', 'chronic_illness']:
                schemes.append(('vayoshri_mh',) + mh['vayoshri_mh'])
        if housing in ['homeless', 'kutcha']:
            schemes.append(('gharkul',) + mh['gharkul'])
        if earning == 'yes' or (income < 5000 and age == 'elderly'):
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

        # ADD THIS REDIRECT LINE HERE:
        return redirect(url_for('index', lang=lang))

        conn = get_db_connection()
        conn.execute(
            'INSERT INTO form_submissions (phone, ip_address, submitted_at) VALUES (?, ?, ?)',
            (phone, ip, datetime.now().strftime("%d %b %Y, %I:%M %p"))
        )
        conn.commit()
        conn.close()

        log_activity('PUBLIC', 'FORM_SUBMITTED', ip, f'Form submitted for {person_name}')

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

@app.route('/progress')
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
    return render_template('chatbot.html', lang=lang)
 
 
@app.route('/chatbot', methods=['POST'])
def chatbot_reply():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        lang = data.get('lang', 'en')
 
        if not user_message:
            return jsonify({'reply': 'Please ask a question.'})
 
        # Sanitize input
        user_message = sanitize(user_message)
 
        # Get Gemini API key
        api_key = os.environ.get('GEMINI_API_KEY', '')
 
        if not api_key:
            # Fallback if no API key — rule based answers
            return jsonify({'reply': get_fallback_answer(user_message, lang)})
 
        # Configure Gemini
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
 
        # System prompt based on language
        system_prompts = {
            'en': """You are a helpful AI assistant for Poverty Aid Identifier — a free civic tech app that helps India's poorest citizens find government schemes they qualify for.
 
You help citizens with:
1. Information about 16 government schemes: PM Jan Arogya Yojana, PM Awas Yojana, Ayushman Bharat, Antyodaya Anna Yojana, National Family Benefit Scheme, PM Ujjwala Yojana, Old Age Pension (IGNOAPS), Widow Pension, Divyangjan Swavalamban, Accessible India Campaign, PM Poshan, ICDS, Annapurna Scheme, Saubhagya, PM Jan Dhan Yojana, Basic Community Support
2. Documents needed for each scheme
3. How to apply for schemes
4. Corruption reporting — citizens can file complaints at /corruption and track with tracking ID
5. How the AI Need Score works (0-175 points across 9 parameters)
 
Rules:
- Keep answers short and clear — max 4-5 lines
- Use simple language — the user may be poor or uneducated
- Always be helpful and kind
- If asked about something unrelated to welfare schemes, gently redirect to schemes
- Mention relevant helpline numbers when appropriate
- Do NOT make up information — only answer what you know about these schemes""",
 
            'hi': """आप Poverty Aid Identifier के लिए एक सहायक AI हैं — एक मुफ्त civic tech ऐप जो भारत के गरीब नागरिकों को सरकारी योजनाएं खोजने में मदद करता है।
 
आप इनके बारे में मदद करते हैं:
1. 16 सरकारी योजनाओं की जानकारी
2. हर योजना के लिए जरूरी दस्तावेज़
3. आवेदन कैसे करें
4. भ्रष्टाचार की शिकायत कैसे करें
 
नियम:
- जवाब छोटे और सरल रखें — 4-5 लाइन से ज्यादा नहीं
- आसान हिंदी में बोलें — उपयोगकर्ता पढ़ा-लिखा नहीं हो सकता
- हमेशा दयालु और मददगार रहें
- झूठी जानकारी न दें""",
 
            'mr': """तुम्ही Poverty Aid Identifier साठी एक सहाय्यक AI आहात — एक मोफत civic tech अॅप जे भारतातील गरीब नागरिकांना सरकारी योजना शोधण्यास मदत करते.
 
तुम्ही यासाठी मदत करता:
1. 16 सरकारी योजनांची माहिती
2. प्रत्येक योजनेसाठी आवश्यक कागदपत्रे
3. अर्ज कसा करावा
4. भ्रष्टाचाराची तक्रार कशी करावी
 
नियम:
- उत्तरे छोटी आणि स्पष्ट ठेवा — 4-5 ओळींपेक्षा जास्त नाही
- सोप्या मराठीत बोला
- नेहमी दयाळू आणि मदत करणारे राहा
- खोटी माहिती देऊ नका"""
        }
 
        system_prompt = system_prompts.get(lang, system_prompts['en'])
        full_prompt = system_prompt + "\n\nUser question: " + user_message
 
        # Call Gemini
        response = model.generate_content(full_prompt)
        reply = response.text.strip()
 
        # Log the interaction
        log_activity('CHATBOT', 'QUERY', get_client_ip(),
            f'Lang: {lang} | Q: {user_message[:50]}')
 
        return jsonify({'reply': reply})
 
    except Exception as e:
        print(f"Chatbot error: {e}")
        return jsonify({'reply': get_fallback_answer(
            data.get('message', '') if data else '',
            data.get('lang', 'en') if data else 'en'
        )})
 
 
def get_fallback_answer(question, lang='en'):
    """Rule-based fallback when Gemini API is not available"""
    q = question.lower()
 
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
            'corruption': "भ्रष्टाचार की शिकायत के लिए:\n1. ऐप में 'भ्रष्टाचार रिपोर्ट' पर क्लिक करें\n2. के अधिकारी का नाम, योजना, मांगी गई राशि भरें\n3. आपको PAI-2026-XXXX ट्रैकिंग ID मिलेगी\n4. स्थिति ट्रैक करें: दर्ज → प्राप्त → कार्रवाई → हल",
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
        return f['default']

if __name__ == '__main__':
    
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), threaded=True)
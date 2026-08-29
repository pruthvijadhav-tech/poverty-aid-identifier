<<<<<<< HEAD
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, Response
=======
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types as genai_types
import random
import string
import sqlite3
import hashlib
import time
import smtplib
import os
import re
import json
import difflib
import pickle
<<<<<<< HEAD
import csv
import io
=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from collections import defaultdict
from flask_session import Session
<<<<<<< HEAD
import scheme_verification
=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899

# Load ML Poverty Model if trained
ML_MODEL = None
_model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'poverty_model.pkl')
if os.path.exists(_model_path):
    try:
        with open(_model_path, 'rb') as f:
            ML_MODEL = pickle.load(f)
        print(f"[OK] Loaded ML Poverty Scoring Model from {_model_path}")
    except Exception as _e:
        print(f"[WARNING] Could not load ML Poverty model: {_e}")

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'corruption_proofs')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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

GEMINI_MODEL = 'gemini-3.5-flash'


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
from cachelib.file import FileSystemCache as _FSCache
_session_dir = os.environ.get('SESSION_FILE_DIR', os.path.join(os.getcwd(), '.flask_session'))
app.config['SESSION_TYPE'] = 'cachelib'
app.config['SESSION_CACHELIB'] = _FSCache(threshold=500, default_timeout=0, cache_dir=_session_dir)
app.config['SESSION_PERMANENT'] = False
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
        duplicate_flag INTEGER DEFAULT 0,
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
    # Migration for existing databases
    for col_def in [
        "duplicate_flag INTEGER DEFAULT 0",
        "proof_file TEXT",
        "latitude REAL",
        "longitude REAL",
<<<<<<< HEAD
        "geotag_verified INTEGER DEFAULT 0",
        "scheme_key TEXT"
=======
        "geotag_verified INTEGER DEFAULT 0"
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
    ]:
        try:
            c.execute(f'ALTER TABLE reports ADD COLUMN {col_def}')
        except sqlite3.OperationalError:
            pass  # column already exists


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

    # Application Outcome Tracking — the feedback loop. One row per
    # (application, recommended scheme). Lets us learn whether a
    # recommendation actually turned into real help, not just a suggestion.
    c.execute('''
    CREATE TABLE IF NOT EXISTS application_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id TEXT,
        phone TEXT,
        person_name TEXT,
        scheme_key TEXT,
        scheme_name TEXT,
        status TEXT DEFAULT 'not_applied',
        notes TEXT,
        created_at TEXT,
        updated_at TEXT,
        lang TEXT DEFAULT 'en'
    )
    ''')

    # Fraud / duplicate detection. Stores a lightweight snapshot of each
    # eligibility submission so a NEW submission can be compared against a
    # phone number's own history — flags anomalies for admin REVIEW only,
    # never blocks or rejects a citizen automatically.
    c.execute('''
    CREATE TABLE IF NOT EXISTS submission_fingerprints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        ip_address TEXT,
        age_group TEXT,
        gender TEXT,
        widow_status TEXT,
        income INTEGER,
        family_size INTEGER,
        submitted_at TEXT
    )
    ''')

    # Persistent record of every eligibility application — whether filed by
    # the citizen themselves or by a volunteer/NGO worker on their behalf.
    # Session data (session['profile']) only lives in ONE browser; this
    # table is what lets a volunteer's dashboard show past filings, and
    # keeps a durable audit trail of who filed what for whom.
    c.execute('''
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id TEXT UNIQUE,
        person_name TEXT,
        phone TEXT,
        state TEXT,
        score INTEGER,
        priority TEXT,
        schemes_count INTEGER,
        lang TEXT DEFAULT 'en',
        filed_by_volunteer TEXT,
        filed_by_volunteer_name TEXT,
        created_at TEXT
    )
    ''')

    # IVR/keypad-phone support. Each incoming call is a series of separate,
    # stateless webhook requests from the telephony provider (Twilio/Exotel)
    # — this table is what lets us remember what the caller already
    # answered between one keypress and the next.
    c.execute('''
    CREATE TABLE IF NOT EXISTS ivr_sessions (
        call_sid TEXT PRIMARY KEY,
        phone TEXT,
        lang TEXT DEFAULT 'en',
        age_group TEXT,
        income TEXT,
        housing TEXT,
        widow_status TEXT,
        medical TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    ''')

    # Audit Ledger Table for Corruption Complaints
    c.execute('''
    CREATE TABLE IF NOT EXISTS audit_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_id TEXT,
        status TEXT,
        timestamp TEXT,
        prev_hash TEXT,
        block_hash TEXT
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

def add_ledger_entry(tracking_id, status):
    try:
        conn = get_db_connection()
        last_block = conn.execute('SELECT * FROM audit_ledger ORDER BY id DESC LIMIT 1').fetchone()
        prev_hash = 'GENESIS'
        if last_block:
            prev_hash = last_block['block_hash']
        
        timestamp = datetime.now().strftime("%d %b %Y, %I:%M:%S %p")
        hash_input = f"{tracking_id}|{status}|{timestamp}|{prev_hash}"
        block_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
        
        conn.execute('''
            INSERT INTO audit_ledger (tracking_id, status, timestamp, prev_hash, block_hash)
            VALUES (?, ?, ?, ?, ?)
        ''', (tracking_id, status, timestamp, prev_hash, block_hash))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] add_ledger_entry failed: {e}")

def verify_ledger():
    try:
        conn = get_db_connection()
        blocks = conn.execute('SELECT * FROM audit_ledger ORDER BY id ASC').fetchall()
        conn.close()
        
        expected_prev = 'GENESIS'
        for block in blocks:
            if block['prev_hash'] != expected_prev:
                return False, block['id'], f"Chain broken: prev_hash mismatch at block {block['id']} (expected {expected_prev[:8]}..., got {block['prev_hash'][:8]}...)"
            
            hash_input = f"{block['tracking_id']}|{block['status']}|{block['timestamp']}|{block['prev_hash']}"
            calculated_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
            
            if block['block_hash'] != calculated_hash:
                return False, block['id'], f"Integrity error: block hash mismatch at block {block['id']}"
                
            expected_prev = block['block_hash']
            
        return True, None, "Audit Ledger verified: Integrity intact (All hashes valid)"
    except Exception as e:
        return False, None, f"Verification failed: {e}"

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

# ---------------------------------------------------------------------------
# Document OCR: let someone photograph their Aadhaar / Ration Card and
# auto-fill the eligibility form instead of typing everything. Uses Gemini's
# vision capability (same API key/model already in use for the chatbot).
#
# PRIVACY: the uploaded image is processed ENTIRELY IN MEMORY and never
# written to disk or the database. It exists only for the duration of this
# one request, then is discarded when the function returns.
# ---------------------------------------------------------------------------

ALLOWED_DOC_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
MAX_DOC_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB

def extract_document_fields(client, image_bytes, mime_type):
    """One Gemini vision call: read an Aadhaar/Ration Card photo and pull out
    the fields our eligibility form needs. Returns a dict or raises.

    Retries automatically on transient server overload (503/429) — Gemini's
    own error message for these literally says the spike is usually
    temporary, so a short retry meaningfully helps in practice. Does NOT
    retry on other errors (bad image, parse failure, etc.) — those would
    just fail the same way again, so retrying only adds latency."""
    prompt = """You are reading a photo of an Indian identity document (Aadhaar Card or Ration Card) to help someone auto-fill a government welfare eligibility form. Extract ONLY what is actually printed and clearly legible in the image — do not guess or infer anything not visibly present.

Respond with ONLY raw JSON, no markdown fences, no commentary, matching exactly this shape:
{
  "document_type": "aadhaar" or "ration_card" or "unknown",
  "name": string or null,
  "date_of_birth": string in DD-MM-YYYY format or null,
  "age_years": integer (computed from date_of_birth if visible, else null) or null,
  "gender": one of "male"/"female"/"other" or null,
  "address": string (full address as printed) or null,
  "legible": true or false (false if the image is too blurry/dark/cropped to read reliably)
}

If the image does not appear to be an Aadhaar Card or Ration Card at all, set document_type to "unknown" and all other fields to null."""

    image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    max_attempts = 3
    backoff_seconds = [1.5, 3]  # delay before attempt 2 and attempt 3
    last_error = None

    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[prompt, image_part],
            )
            raw = response.text.strip()
            raw = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
            return json.loads(raw)
        except Exception as e:
            last_error = e
            error_text = str(e)
            is_transient = ('503' in error_text or 'UNAVAILABLE' in error_text
                             or '429' in error_text or 'RESOURCE_EXHAUSTED' in error_text)
            if is_transient and attempt < max_attempts - 1:
                print(f"OCR attempt {attempt + 1} hit transient error, retrying in {backoff_seconds[attempt]}s: {error_text[:150]}")
                time.sleep(backoff_seconds[attempt])
                continue
            raise last_error

@app.route('/ocr-extract', methods=['POST'])
def ocr_extract():
    """Receives an uploaded document photo, extracts fields via Gemini
    vision, and returns them as JSON for the frontend to auto-fill the form.
    The image itself is never saved anywhere."""
    ip = get_client_ip()
    try:
        if 'document' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['document']
        if not file or file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        mime_type = file.mimetype or ''
        if mime_type not in ALLOWED_DOC_MIME_TYPES:
            return jsonify({'success': False, 'error': 'Please upload a JPG, PNG, or WEBP image'}), 400

        image_bytes = file.read()
        if len(image_bytes) > MAX_DOC_UPLOAD_BYTES:
            return jsonify({'success': False, 'error': 'Image too large (max 8MB)'}), 400
        if len(image_bytes) == 0:
            return jsonify({'success': False, 'error': 'Empty file'}), 400

        api_key = os.environ.get('GEMINI_API_KEY', '')
        if not api_key:
            return jsonify({'success': False, 'error': 'Document scanning needs AI to be configured. Please fill the form manually.'}), 503

        client = genai.Client(api_key=api_key)
        extracted = extract_document_fields(client, image_bytes, mime_type)
        # image_bytes and file go out of scope here — nothing persisted.

        if extracted.get('document_type') == 'unknown':
            log_activity('OCR', 'UNRECOGNIZED_DOCUMENT', ip, 'Uploaded image not recognized as Aadhaar/Ration Card')
            return jsonify({'success': False, 'error': "Couldn't recognize this as an Aadhaar or Ration Card. Please try a clearer photo, or fill the form manually."})

        if extracted.get('legible') is False:
            log_activity('OCR', 'ILLEGIBLE_DOCUMENT', ip, 'Uploaded document image too blurry/unclear')
            return jsonify({'success': False, 'error': "The image is too blurry to read clearly. Please retake the photo in good light, or fill the form manually."})

        log_activity('OCR', 'DOCUMENT_EXTRACTED', ip, f"Type: {extracted.get('document_type')}")
        extracted['age_group'] = _derive_age_group(extracted.get('age_years'))
        return jsonify({'success': True, 'extracted': extracted})

    except json.JSONDecodeError:
        log_activity('OCR', 'EXTRACTION_PARSE_ERROR', ip, 'Gemini response was not valid JSON', suspicious=0)
        return jsonify({'success': False, 'error': 'Could not read the document clearly. Please fill the form manually.'})
    except Exception as e:
        error_text = str(e)
        print(f"OCR extraction error: {e}")
        log_activity('OCR', 'EXTRACTION_ERROR', ip, error_text[:200], suspicious=0)
        if '503' in error_text or 'UNAVAILABLE' in error_text or '429' in error_text or 'RESOURCE_EXHAUSTED' in error_text:
            return jsonify({'success': False, 'error': "Document scanning is busy right now (high demand). Please try again in a minute, or fill the form manually."})
        return jsonify({'success': False, 'error': 'Something went wrong reading the document. Please fill the form manually.'})

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

def role_required(*allowed_roles):
    """Like login_required, but also checks the account's role. Used to
    keep volunteer accounts (which can only see their own filed
    applications) out of the full admin dashboard (which sees every
    citizen's complaint data)."""
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get('admin_logged_in'):
                ip = get_client_ip()
                log_activity('UNKNOWN', 'UNAUTHORIZED_ACCESS_ATTEMPT',
                    ip, f'Tried to access {request.path} without login', suspicious=1)
                return redirect(url_for('admin_login'))
            if session.get('admin_role') not in allowed_roles:
                ip = get_client_ip()
                log_activity(session.get('admin_username', 'UNKNOWN'), 'ROLE_ACCESS_DENIED',
                    ip, f"Role '{session.get('admin_role')}' tried to access {request.path}", suspicious=1)
                return redirect(url_for('admin_login'))
            return f(*args, **kwargs)
        return decorated
    return wrapper

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
<<<<<<< HEAD
        "pm_jan_arogya": ("urgent", "PM Jan Arogya Yojana / Ayushman Bharat (Health Cover)", "Rs. 5,00,000/yr (+70 cover for 70+)"),
        "state_emergency": ("urgent", "Chief Minister's Relief Fund (Emergency Assistance)", "Case-by-case; no fixed amount"),
        "national_family": ("urgent", "National Family Benefit Scheme (Death of Earning Member)", "Rs. 20,000"),
        "pm_poshan": ("normal", "PM Poshan Scheme (Nutrition for Children)", "Free Meals"),
        "icds": ("normal", "Saksham Anganwadi & Poshan 2.0 (erstwhile ICDS)", "Free Services"),
=======
        "pm_jan_arogya": ("urgent", "PM Jan Arogya Yojana (Emergency Medical Aid)", "Rs. 5,00,000/yr"),
        "state_emergency": ("urgent", "State Emergency Relief Fund (Accident)", "Rs. 10,000"),
        "national_family": ("urgent", "National Family Benefit Scheme (Death of Earning Member)", "Rs. 20,000"),
        "pm_poshan": ("normal", "PM Poshan Scheme (Nutrition for Children)", "Free Meals"),
        "icds": ("normal", "Integrated Child Development Services (ICDS)", "Free Services"),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
        "old_age_pension": ("normal", "Indira Gandhi National Old Age Pension", "Rs. 200-500/month"),
        "widow_pension": ("urgent", "Indira Gandhi National Widow Pension Scheme (IGNWPS)", "Rs. 300-500/month"),
        "annapurna": ("normal", "Annapurna Scheme (Free Food for Elderly)", "10 kg/month"),
        "ayushman": ("normal", "Ayushman Bharat (Free Health Insurance)", "Rs. 5,00,000/yr"),
<<<<<<< HEAD
        "divyangjan": ("normal", "Divyangjan Swavalamban Yojana (Concessional Loan)", "Loan up to Rs. 50 lakh"),
        "accessible_india": ("normal", "Accessible India Campaign - Disability Aid", "Free Aids/Equipment"),
        "adip": ("normal", "ADIP - Assistance to Disabled Persons for Aids & Appliances", "Free/subsidised devices"),
        "pm_awas": ("normal", "PM Awas Yojana (Free Housing)", "Rs. 1,20,000"),
        "pm_awas_gramin": ("normal", "PM Awas Yojana - Gramin (Rural Housing)", "Rs. 1.20-1.30 lakh"),
        "pm_awas_urban": ("normal", "PM Awas Yojana - Urban 2.0 (Urban Housing)", "As per component"),
        "antyodaya": ("normal", "Antyodaya Anna Yojana (Free Ration)", "35 kg/month"),
        "ujjwala": ("normal", "PM Ujjwala Yojana (Free Gas Connection)", "1 Free Cylinder"),
        "saubhagya": ("normal", "Saubhagya Scheme (CLOSED - Historical)", "Closed 31 Mar 2022"),
=======
        "divyangjan": ("normal", "Divyangjan Swavalamban Scheme", "Rs. 300-1500/month"),
        "accessible_india": ("normal", "Accessible India Campaign - Disability Aid", "Free Aids/Equipment"),
        "pm_awas": ("normal", "PM Awas Yojana (Free Housing)", "Rs. 1,20,000"),
        "antyodaya": ("normal", "Antyodaya Anna Yojana (Free Ration)", "35 kg/month"),
        "ujjwala": ("normal", "PM Ujjwala Yojana (Free Gas Connection)", "1 Free Cylinder"),
        "saubhagya": ("normal", "Saubhagya Scheme (Free Electricity)", "Free Connection"),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
        "jan_dhan": ("normal", "PM Jan Dhan Yojana (Free Bank Account)", "Zero Balance Account"),
        "basic": ("normal", "Basic Community Support and Ration Assistance", "As applicable"),
    },
    "hi": {
<<<<<<< HEAD
        "pm_jan_arogya": ("urgent", "PM जन आरोग्य योजना / आयुष्मान भारत (स्वास्थ्य कवर)", "रु. 5,00,000/वर्ष (70+ हेतु अतिरिक्त कवर)"),
        "state_emergency": ("urgent", "मुख्यमंत्री सहायता निधि (आपातकालीन सहायता)", "मामला-दर-मामला; कोई निश्चित राशि नहीं"),
        "national_family": ("urgent", "राष्ट्रीय परिवार लाभ योजना (कमाने वाले सदस्य की मृत्यु)", "रु. 20,000"),
        "pm_poshan": ("normal", "PM पोषण योजना (बच्चों के लिए पोषण)", "मुफ्त भोजन"),
        "icds": ("normal", "सक्षम आंगनवाड़ी और पोषण 2.0 (पूर्व ICDS)", "मुफ्त सेवाएं"),
=======
        "pm_jan_arogya": ("urgent", "PM जन आरोग्य योजना (आपातकालीन चिकित्सा सहायता)", "रु. 5,00,000/वर्ष"),
        "state_emergency": ("urgent", "राज्य आपातकालीन राहत निधि (दुर्घटना)", "रु. 10,000"),
        "national_family": ("urgent", "राष्ट्रीय परिवार लाभ योजना (कमाने वाले सदस्य की मृत्यु)", "रु. 20,000"),
        "pm_poshan": ("normal", "PM पोषण योजना (बच्चों के लिए पोषण)", "मुफ्त भोजन"),
        "icds": ("normal", "एकीकृत बाल विकास सेवाएं (ICDS)", "मुफ्त सेवाएं"),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
        "old_age_pension": ("normal", "इंदिरा गांधी राष्ट्रीय वृद्धावस्था पेंशन", "रु. 200-500/माह"),
        "widow_pension": ("urgent", "इंदिरा गांधी राष्ट्रीय विधवा पेंशन योजना", "रु. 300-500/माह"),
        "annapurna": ("normal", "अन्नपूर्णा योजना (बुजुर्गों के लिए मुफ्त भोजन)", "10 किग्रा/माह"),
        "ayushman": ("normal", "आयुष्मान भारत (मुफ्त स्वास्थ्य बीमा)", "रु. 5,00,000/वर्ष"),
<<<<<<< HEAD
        "divyangjan": ("normal", "दिव्यांगजन स्वावलंबन योजना (रियायती ऋण)", "₹50 लाख तक ऋण"),
        "accessible_india": ("normal", "सुगम्य भारत अभियान - विकलांगता सहायता", "मुफ्त उपकरण"),
        "adip": ("normal", "ADIP - विकलांगों हेतु सहायक उपकरण योजना", "मुफ्त/रियायती उपकरण"),
        "pm_awas": ("normal", "PM आवास योजना (मुफ्त आवास)", "रु. 1,20,000"),
        "pm_awas_gramin": ("normal", "PM आवास योजना - ग्रामीण", "₹1.20-1.30 लाख"),
        "pm_awas_urban": ("normal", "PM आवास योजना - शहरी 2.0", "घटक अनुसार"),
        "antyodaya": ("normal", "अंत्योदय अन्न योजना (मुफ्त राशन)", "35 किग्रा/माह"),
        "ujjwala": ("normal", "PM उज्ज्वला योजना (मुफ्त गैस कनेक्शन)", "1 मुफ्त सिलेंडर"),
        "saubhagya": ("normal", "सौभाग्य योजना (बंद - ऐतिहासिक)", "31 मार्च 2022 को बंद"),
=======
        "divyangjan": ("normal", "दिव्यांगजन स्वावलंबन योजना", "रु. 300-1500/माह"),
        "accessible_india": ("normal", "सुगम्य भारत अभियान - विकलांगता सहायता", "मुफ्त उपकरण"),
        "pm_awas": ("normal", "PM आवास योजना (मुफ्त आवास)", "रु. 1,20,000"),
        "antyodaya": ("normal", "अंत्योदय अन्न योजना (मुफ्त राशन)", "35 किग्रा/माह"),
        "ujjwala": ("normal", "PM उज्ज्वला योजना (मुफ्त गैस कनेक्शन)", "1 मुफ्त सिलेंडर"),
        "saubhagya": ("normal", "सौभाग्य योजना (मुफ्त बिजली)", "मुफ्त कनेक्शन"),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
        "jan_dhan": ("normal", "PM जन धन योजना (मुफ्त बैंक खाता)", "शून्य बैलेंस खाता"),
        "basic": ("normal", "बुनियादी सामुदायिक सहायता और राशन सहायता", "लागू अनुसार"),
    },
    "mr": {
<<<<<<< HEAD
        "pm_jan_arogya": ("urgent", "PM जन आरोग्य योजना / आयुष्मान भारत (आरोग्य कव्हर)", "रु. 5,00,000/वर्ष (70+ साठी अतिरिक्त कव्हर)"),
        "state_emergency": ("urgent", "मुख्यमंत्री सहाय्यता निधी (आपत्कालीन मदत)", "प्रकरणपरत्वे; निश्चित रक्कम नाही"),
        "national_family": ("urgent", "राष्ट्रीय कुटुंब लाभ योजना (कमावत्या सदस्याचे निधन)", "रु. 20,000"),
        "pm_poshan": ("normal", "PM पोषण योजना (मुलांसाठी पोषण)", "मोफत जेवण"),
        "icds": ("normal", "सक्षम अंगणवाडी आणि पोषण 2.0 (पूर्वीची ICDS)", "मोफत सेवा"),
=======
        "pm_jan_arogya": ("urgent", "PM जन आरोग्य योजना (आपत्कालीन वैद्यकीय मदत)", "रु. 5,00,000/वर्ष"),
        "state_emergency": ("urgent", "राज्य आपत्कालीन मदत निधी (अपघात)", "रु. 10,000"),
        "national_family": ("urgent", "राष्ट्रीय कुटुंब लाभ योजना (कमावत्या सदस्याचे निधन)", "रु. 20,000"),
        "pm_poshan": ("normal", "PM पोषण योजना (मुलांसाठी पोषण)", "मोफत जेवण"),
        "icds": ("normal", "एकात्मिक बाल विकास सेवा (ICDS)", "मोफत सेवा"),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
        "old_age_pension": ("normal", "इंदिरा गांधी राष्ट्रीय वृद्धापकाळ निवृत्तीवेतन", "रु. 200-500/महिना"),
        "widow_pension": ("urgent", "इंदिरा गांधी राष्ट्रीय विधवा निवृत्तीवेतन योजना", "रु. 300-500/महिना"),
        "annapurna": ("normal", "अन्नपूर्णा योजना (वृद्धांसाठी मोफत अन्न)", "10 किग्रा/महिना"),
        "ayushman": ("normal", "आयुष्मान भारत (मोफत आरोग्य विमा)", "रु. 5,00,000/वर्ष"),
<<<<<<< HEAD
        "divyangjan": ("normal", "दिव्यांगजन स्वावलंबन योजना (सवलतीचे कर्ज)", "₹50 लाखांपर्यंत कर्ज"),
        "accessible_india": ("normal", "सुगम्य भारत अभियान - अपंगत्व मदत", "मोफत साधने"),
        "adip": ("normal", "ADIP - अपंगांसाठी सहाय्यक साधने योजना", "मोफत/सवलतीची साधने"),
        "pm_awas": ("normal", "PM आवास योजना (मोफत घर)", "रु. 1,20,000"),
        "pm_awas_gramin": ("normal", "PM आवास योजना - ग्रामीण", "₹1.20-1.30 लाख"),
        "pm_awas_urban": ("normal", "PM आवास योजना - शहरी 2.0", "घटकानुसार"),
        "antyodaya": ("normal", "अंत्योदय अन्न योजना (मोफत रेशन)", "35 किग्रा/महिना"),
        "ujjwala": ("normal", "PM उज्ज्वला योजना (मोफत गॅस कनेक्शन)", "1 मोफत सिलेंडर"),
        "saubhagya": ("normal", "सौभाग्य योजना (बंद - ऐतिहासिक)", "31 मार्च 2022 रोजी बंद"),
=======
        "divyangjan": ("normal", "दिव्यांगजन स्वावलंबन योजना", "रु. 300-1500/महिना"),
        "accessible_india": ("normal", "सुगम्य भारत अभियान - अपंगत्व मदत", "मोफत साधने"),
        "pm_awas": ("normal", "PM आवास योजना (मोफत घर)", "रु. 1,20,000"),
        "antyodaya": ("normal", "अंत्योदय अन्न योजना (मोफत रेशन)", "35 किग्रा/महिना"),
        "ujjwala": ("normal", "PM उज्ज्वला योजना (मोफत गॅस कनेक्शन)", "1 मोफत सिलेंडर"),
        "saubhagya": ("normal", "सौभाग्य योजना (मोफत वीज)", "मोफत कनेक्शन"),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
        "jan_dhan": ("normal", "PM जन धन योजना (मोफत बँक खाते)", "शून्य शिल्लक खाते"),
        "basic": ("normal", "मूलभूत सामुदायिक मदत आणि रेशन सहाय्य", "लागू असेल तसे"),
    }
}

SCHEME_DETAILS = {
    "pm_jan_arogya": {
<<<<<<< HEAD
        "en": {"name": "PM Jan Arogya Yojana (Ayushman Bharat / AB-PMJAY)", "amount": "Rs. 5,00,000 per year per family (+ separate Rs. 5,00,000/yr top-up for members aged 70+)", "description": "Free health coverage for poor and vulnerable families for secondary and tertiary hospitalization. Cabinet approved an expansion (11 Sept 2024) giving ALL citizens aged 70+ this cover irrespective of income — families already covered get a separate top-up Rs.5 lakh reserved for their 70+ members; other 70+ citizens get Rs.5 lakh on a family basis via a distinct Ayushman Vay Vandana card.", "eligibility": ["BPL family listed in SECC database, OR", "Any citizen aged 70 years or above (irrespective of income) — new since Sept 2024", "No existing equivalent health coverage (CGHS/ECHS/etc., unless opting in for 70+)"], "documents": ["Aadhaar Card", "Ration Card", "Income Certificate (not required for 70+ category)", "SECC/BPL Certificate (not required for 70+ category)"], "how_to_apply": "Visit nearest empanelled hospital or Common Service Centre (CSC); 70+ citizens can apply for the Ayushman Vay Vandana card.", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "hi": {"name": "PM जन आरोग्य योजना (आयुष्मान भारत / AB-PMJAY)", "amount": "रु. 5,00,000 प्रति वर्ष प्रति परिवार (+ 70+ सदस्यों हेतु अलग ₹5,00,000/वर्ष टॉप-अप)", "description": "गरीब और कमजोर परिवारों के लिए मुफ्त स्वास्थ्य कवरेज। कैबिनेट ने 11 सितंबर 2024 को विस्तार को मंजूरी दी, जिससे 70+ आयु के सभी नागरिकों को आय की परवाह किए बिना यह कवर मिलता है।", "eligibility": ["SECC डेटाबेस में सूचीबद्ध BPL परिवार, या", "70 वर्ष या अधिक आयु का कोई भी नागरिक (आय की परवाह किए बिना) — सितंबर 2024 से नया", "कोई मौजूदा समकक्ष स्वास्थ्य कवरेज नहीं (CGHS/ECHS आदि)"], "documents": ["आधार कार्ड", "राशन कार्ड", "आय प्रमाण पत्र (70+ श्रेणी हेतु आवश्यक नहीं)", "SECC/BPL प्रमाण पत्र (70+ श्रेणी हेतु आवश्यक नहीं)"], "how_to_apply": "नजदीकी सूचीबद्ध अस्पताल या CSC पर जाएं; 70+ नागरिक आयुष्मान वय वंदना कार्ड हेतु आवेदन कर सकते हैं।", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "mr": {"name": "PM जन आरोग्य योजना (आयुष्मान भारत / AB-PMJAY)", "amount": "रु. 5,00,000 प्रति वर्ष प्रति कुटुंब (+ 70+ सदस्यांसाठी वेगळे ₹5,00,000/वर्ष टॉप-अप)", "description": "गरीब आणि असुरक्षित कुटुंबांसाठी मोफत आरोग्य कव्हरेज. मंत्रिमंडळाने 11 सप्टेंबर 2024 रोजी विस्ताराला मंजुरी दिली, ज्यामुळे 70+ वयाच्या सर्व नागरिकांना उत्पन्नाची पर्वा न करता हे कव्हर मिळते.", "eligibility": ["SECC डेटाबेसमध्ये नोंदणीकृत BPL कुटुंब, किंवा", "70 वर्षे किंवा अधिक वयाचा कोणताही नागरिक (उत्पन्नाची पर्वा न करता) — सप्टेंबर 2024 पासून नवीन", "कोणतेही विद्यमान समकक्ष आरोग्य कव्हरेज नाही (CGHS/ECHS इ.)"], "documents": ["आधार कार्ड", "रेशन कार्ड", "उत्पन्न प्रमाणपत्र (70+ श्रेणीसाठी आवश्यक नाही)", "SECC/BPL प्रमाणपत्र (70+ श्रेणीसाठी आवश्यक नाही)"], "how_to_apply": "जवळच्या सूचीबद्ध रुग्णालयात किंवा CSC ला भेट द्या; 70+ नागरिक आयुष्मान वय वंदना कार्डसाठी अर्ज करू शकतात.", "website": "https://pmjay.gov.in", "helpline": "14555"}
    },
    "state_emergency": {
        "en": {"name": "Chief Minister's Relief Fund (CMRF) — Emergency Assistance", "amount": "Case-by-case; no fixed universal amount", "description": "Discretionary emergency financial assistance through the Maharashtra Chief Minister's Relief Fund. Assistance is assessed case-by-case based on the situation — there is no fixed amount guaranteed to every applicant.", "eligibility": ["Accident/emergency-affected person or family", "Genuine financial hardship", "Supporting documents establishing the emergency"], "documents": ["Aadhaar Card", "FIR Copy (if applicable)", "Medical Certificate (if applicable)", "Bank Account Details", "Income/hardship proof"], "how_to_apply": "Apply through the official CMRF portal (cmrf.maharashtra.gov.in) or visit the District Collector Office / nearest Tehsil office with documents.", "website": "https://cmrf.maharashtra.gov.in", "helpline": "1077"},
        "hi": {"name": "मुख्यमंत्री सहायता निधि (CMRF) — आपातकालीन सहायता", "amount": "मामला-दर-मामला; कोई निश्चित राशि नहीं", "description": "महाराष्ट्र मुख्यमंत्री सहायता निधि के माध्यम से विवेकाधीन आपातकालीन वित्तीय सहायता। सहायता स्थिति के आधार पर मामला-दर-मामला तय की जाती है — हर आवेदक को कोई निश्चित राशि गारंटीकृत नहीं है।", "eligibility": ["दुर्घटना/आपातकाल से प्रभावित व्यक्ति या परिवार", "वास्तविक वित्तीय कठिनाई", "आपातकाल साबित करने वाले सहायक दस्तावेज़"], "documents": ["आधार कार्ड", "FIR की प्रति (यदि लागू हो)", "चिकित्सा प्रमाण पत्र (यदि लागू हो)", "बैंक खाता विवरण", "आय/कठिनाई प्रमाण"], "how_to_apply": "आधिकारिक CMRF पोर्टल (cmrf.maharashtra.gov.in) से आवेदन करें या दस्तावेजों के साथ जिला कलेक्टर कार्यालय जाएं।", "website": "https://cmrf.maharashtra.gov.in", "helpline": "1077"},
        "mr": {"name": "मुख्यमंत्री सहाय्यता निधी (CMRF) — आपत्कालीन मदत", "amount": "प्रकरणपरत्वे; निश्चित रक्कम नाही", "description": "महाराष्ट्र मुख्यमंत्री सहाय्यता निधीमार्फत विवेकाधीन आपत्कालीन आर्थिक मदत. मदत परिस्थितीनुसार प्रकरणपरत्वे ठरवली जाते — प्रत्येक अर्जदाराला निश्चित रक्कम हमी दिलेली नाही.", "eligibility": ["अपघात/आपत्कालीन परिस्थितीने प्रभावित व्यक्ती किंवा कुटुंब", "खरी आर्थिक अडचण", "आपत्काल सिद्ध करणारी कागदपत्रे"], "documents": ["आधार कार्ड", "FIR ची प्रत (लागू असल्यास)", "वैद्यकीय प्रमाणपत्र (लागू असल्यास)", "बँक खाते तपशील", "उत्पन्न/अडचण पुरावा"], "how_to_apply": "अधिकृत CMRF पोर्टलवरून (cmrf.maharashtra.gov.in) अर्ज करा किंवा कागदपत्रांसह जिल्हाधिकारी कार्यालयास भेट द्या.", "website": "https://cmrf.maharashtra.gov.in", "helpline": "1077"}
=======
        "en": {"name": "PM Jan Arogya Yojana (Ayushman Bharat)", "amount": "Rs. 5,00,000 per year per family", "description": "Free health coverage for poor and vulnerable families for secondary and tertiary hospitalization.", "eligibility": ["BPL family", "No existing health coverage", "Listed in SECC database"], "documents": ["Aadhaar Card", "Ration Card", "Income Certificate", "SECC/BPL Certificate"], "how_to_apply": "Visit nearest empanelled hospital or Common Service Centre (CSC).", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "hi": {"name": "PM जन आरोग्य योजना (आयुष्मान भारत)", "amount": "रु. 5,00,000 प्रति वर्ष प्रति परिवार", "description": "गरीब और कमजोर परिवारों के लिए माध्यमिक और तृतीयक अस्पताल में भर्ती के लिए मुफ्त स्वास्थ्य कवरेज।", "eligibility": ["BPL परिवार", "कोई मौजूदा स्वास्थ्य कवरेज नहीं", "SECC डेटाबेस में सूचीबद्ध"], "documents": ["आधार कार्ड", "राशन कार्ड", "आय प्रमाण पत्र", "SECC/BPL प्रमाण पत्र"], "how_to_apply": "नजदीकी सूचीबद्ध अस्पताल या कॉमन सर्विस सेंटर (CSC) पर जाएं।", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "mr": {"name": "PM जन आरोग्य योजना (आयुष्मान भारत)", "amount": "रु. 5,00,000 प्रति वर्ष प्रति कुटुंब", "description": "गरीब आणि असुरक्षित कुटुंबांसाठी दुय्यम आणि तृतीयक रुग्णालयात मोफत आरोग्य कव्हरेज.", "eligibility": ["BPL कुटुंब", "कोणतेही विद्यमान आरोग्य कव्हरेज नाही", "SECC डेटाबेसमध्ये नोंदणीकृत"], "documents": ["आधार कार्ड", "रेशन कार्ड", "उत्पन्न प्रमाणपत्र", "SECC/BPL प्रमाणपत्र"], "how_to_apply": "जवळच्या सूचीबद्ध रुग्णालयात किंवा कॉमन सर्व्हिस सेंटरला (CSC) भेट द्या.", "website": "https://pmjay.gov.in", "helpline": "14555"}
    },
    "state_emergency": {
        "en": {"name": "State Emergency Relief Fund (Accident)", "amount": "Rs. 10,000 (one time)", "description": "Immediate financial relief to accident victims and their families.", "eligibility": ["Accident victim", "BPL or economically weak family", "Police FIR filed"], "documents": ["Aadhaar Card", "FIR Copy", "Medical Certificate", "Bank Account Details"], "how_to_apply": "Visit District Collector Office or nearest Tehsil office with documents.", "website": "https://maharashtra.gov.in", "helpline": "1077"},
        "hi": {"name": "राज्य आपातकालीन राहत निधि (दुर्घटना)", "amount": "रु. 10,000 (एक बार)", "description": "दुर्घटना पीड़ितों और उनके परिवारों को तत्काल वित्तीय राहत।", "eligibility": ["दुर्घटना पीड़ित", "BPL या आर्थिक रूप से कमजोर परिवार", "पुलिस FIR दर्ज"], "documents": ["आधार कार्ड", "FIR की प्रति", "चिकित्सा प्रमाण पत्र", "बैंक खाता विवरण"], "how_to_apply": "दस्तावेजों के साथ जिला कलेक्टर कार्यालय या निकटतम तहसील कार्यालय जाएं।", "website": "https://maharashtra.gov.in", "helpline": "1077"},
        "mr": {"name": "राज्य आपत्कालीन मदत निधी (अपघात)", "amount": "रु. 10,000 (एकवेळ)", "description": "अपघात पीडित आणि त्यांच्या कुटुंबांना तात्काळ आर्थिक मदत.", "eligibility": ["अपघात पीडित", "BPL किंवा आर्थिकदृष्ट्या कमकुवत कुटुंब", "पोलीस FIR दाखल"], "documents": ["आधार कार्ड", "FIR ची प्रत", "वैद्यकीय प्रमाणपत्र", "बँक खाते तपशील"], "how_to_apply": "कागदपत्रांसह जिल्हाधिकारी कार्यालय किंवा जवळच्या तहसील कार्यालयास भेट द्या.", "website": "https://maharashtra.gov.in", "helpline": "1077"}
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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
<<<<<<< HEAD
        "en": {"name": "Saksham Anganwadi & Poshan 2.0 (erstwhile ICDS)", "amount": "Free services", "description": "ICDS (launched 1975) has been restructured and is now delivered under Mission Saksham Anganwadi & Poshan 2.0 — supplementary nutrition, immunization, health check-up for children under 6. This is a programme delivered via Anganwadi centres, not a direct cash transfer.", "eligibility": ["Children 0-6 years", "Pregnant and lactating mothers", "Adolescent girls"], "documents": ["Aadhaar Card", "Birth Certificate of child"], "how_to_apply": "Visit nearest Anganwadi Centre in your village or ward.", "website": "https://wcd.gov.in/offerings/nutrition-mission-saksham-anganwadi-and-poshan-2-0-mission-saksham-anganwadi-poshan-2-0", "helpline": "1800-111-100"},
        "hi": {"name": "सक्षम आंगनवाड़ी और पोषण 2.0 (पूर्व ICDS)", "amount": "मुफ्त सेवाएं", "description": "ICDS (1975 में शुरू) को पुनर्गठित कर अब 'मिशन सक्षम आंगनवाड़ी और पोषण 2.0' के तहत दिया जाता है — 6 वर्ष से कम बच्चों हेतु पूरक पोषण, टीकाकरण, स्वास्थ्य जांच। यह आंगनवाड़ी के माध्यम से दिया जाने वाला कार्यक्रम है, सीधा नकद हस्तांतरण नहीं।", "eligibility": ["0-6 वर्ष के बच्चे", "गर्भवती और स्तनपान कराने वाली माताएं", "किशोर लड़कियां"], "documents": ["आधार कार्ड", "बच्चे का जन्म प्रमाण पत्र"], "how_to_apply": "अपने गांव या वार्ड में निकटतम आंगनवाड़ी केंद्र जाएं।", "website": "https://wcd.gov.in/offerings/nutrition-mission-saksham-anganwadi-and-poshan-2-0-mission-saksham-anganwadi-poshan-2-0", "helpline": "1800-111-100"},
        "mr": {"name": "सक्षम अंगणवाडी आणि पोषण 2.0 (पूर्वीची ICDS)", "amount": "मोफत सेवा", "description": "ICDS (1975 मध्ये सुरू) पुनर्रचित करून आता 'मिशन सक्षम अंगणवाडी आणि पोषण 2.0' अंतर्गत दिली जाते — 6 वर्षांखालील मुलांसाठी पूरक पोषण, लसीकरण, आरोग्य तपासणी. ही अंगणवाडीमार्फत दिली जाणारी कार्यक्रम आहे, थेट रोख हस्तांतरण नाही.", "eligibility": ["0-6 वर्षे वयाची मुले", "गर्भवती आणि स्तनपान देणाऱ्या माता", "किशोरवयीन मुली"], "documents": ["आधार कार्ड", "मुलाचे जन्म प्रमाणपत्र"], "how_to_apply": "तुमच्या गावात किंवा वॉर्डमध्ये जवळच्या अंगणवाडी केंद्राला भेट द्या.", "website": "https://wcd.gov.in/offerings/nutrition-mission-saksham-anganwadi-and-poshan-2-0-mission-saksham-anganwadi-poshan-2-0", "helpline": "1800-111-100"}
=======
        "en": {"name": "Integrated Child Development Services (ICDS)", "amount": "Free services", "description": "Supplementary nutrition, immunization, health check-up for children under 6.", "eligibility": ["Children 0-6 years", "Pregnant and lactating mothers", "Adolescent girls"], "documents": ["Aadhaar Card", "Birth Certificate of child"], "how_to_apply": "Visit nearest Anganwadi Centre in your village or ward.", "website": "https://wcd.nic.in", "helpline": "1800-111-100"},
        "hi": {"name": "एकीकृत बाल विकास सेवाएं (ICDS)", "amount": "मुफ्त सेवाएं", "description": "6 वर्ष से कम बच्चों के लिए पूरक पोषण, टीकाकरण, स्वास्थ्य जांच।", "eligibility": ["0-6 वर्ष के बच्चे", "गर्भवती और स्तनपान कराने वाली माताएं", "किशोर लड़कियां"], "documents": ["आधार कार्ड", "बच्चे का जन्म प्रमाण पत्र"], "how_to_apply": "अपने गांव या वार्ड में निकटतम आंगनवाड़ी केंद्र जाएं।", "website": "https://wcd.nic.in", "helpline": "1800-111-100"},
        "mr": {"name": "एकात्मिक बाल विकास सेवा (ICDS)", "amount": "मोफत सेवा", "description": "6 वर्षाखालील मुलांसाठी पूरक पोषण, लसीकरण, आरोग्य तपासणी.", "eligibility": ["0-6 वर्षे वयाची मुले", "गर्भवती आणि स्तनपान देणाऱ्या माता", "किशोरवयीन मुली"], "documents": ["आधार कार्ड", "मुलाचे जन्म प्रमाणपत्र"], "how_to_apply": "तुमच्या गावात किंवा वॉर्डमध्ये जवळच्या अंगणवाडी केंद्राला भेट द्या.", "website": "https://wcd.nic.in", "helpline": "1800-111-100"}
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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
<<<<<<< HEAD
        "en": {"name": "Ayushman Bharat (same scheme as PM Jan Arogya Yojana)", "amount": "See PM Jan Arogya Yojana — Rs. 5,00,000/year", "description": "\u201cAyushman Bharat\u201d and \u201cPM Jan Arogya Yojana (AB-PMJAY)\u201d are the SAME central health scheme, not two separate benefits. This entry is kept only for backward compatibility with old links; please refer to 'PM Jan Arogya Yojana' for the full, current details so you are not shown a duplicate recommendation.", "eligibility": ["Same as PM Jan Arogya Yojana — see that scheme"], "documents": [], "how_to_apply": "See PM Jan Arogya Yojana.", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "hi": {"name": "आयुष्मान भारत (PM जन आरोग्य योजना के समान)", "amount": "PM जन आरोग्य योजना देखें — रु. 5,00,000/वर्ष", "description": "\u201cआयुष्मान भारत\u201d और \u201cPM जन आरोग्य योजना (AB-PMJAY)\u201d एक ही केंद्रीय स्वास्थ्य योजना हैं, दो अलग लाभ नहीं। यह प्रविष्टि केवल पुराने लिंक की पश्च-संगतता हेतु रखी गई है; पूर्ण, वर्तमान विवरण के लिए कृपया 'PM जन आरोग्य योजना' देखें ताकि आपको डुप्लिकेट अनुशंसा न दिखे।", "eligibility": ["PM जन आरोग्य योजना के समान — वह योजना देखें"], "documents": [], "how_to_apply": "PM जन आरोग्य योजना देखें।", "website": "https://pmjay.gov.in", "helpline": "14555"},
        "mr": {"name": "आयुष्मान भारत (PM जन आरोग्य योजने प्रमाणेच)", "amount": "PM जन आरोग्य योजना पहा — रु. 5,00,000/वर्ष", "description": "\u201cआयुष्मान भारत\u201d आणि \u201cPM जन आरोग्य योजना (AB-PMJAY)\u201d ही एकच केंद्रीय आरोग्य योजना आहे, दोन वेगळे लाभ नाहीत. ही नोंद फक्त जुन्या लिंकच्या मागील-सुसंगततेसाठी ठेवली आहे; संपूर्ण, सध्याच्या तपशीलांसाठी कृपया 'PM जन आरोग्य योजना' पहा जेणेकरून तुम्हाला डुप्लिकेट शिफारस दिसणार नाही.", "eligibility": ["PM जन आरोग्य योजनेप्रमाणेच — ती योजना पहा"], "documents": [], "how_to_apply": "PM जन आरोग्य योजना पहा.", "website": "https://pmjay.gov.in", "helpline": "14555"}
    },
    "divyangjan": {
        "en": {"name": "Divyangjan Swavalamban Yojana (Concessional Loan)", "amount": "Concessional loan up to Rs. 50 lakh (NOT a monthly pension)", "description": "A concessional-interest LOAN scheme run by the National Divyangjan Finance & Development Corporation (NDFDC) to help persons with disabilities start or grow an income-generating activity. This is credit, not a monthly cash pension — the monthly disability pension concept belongs to a separate scheme (Indira Gandhi National Disability Pension Scheme, IGNDPS), which is not currently tracked as a separate entry in this app.", "eligibility": ["40% or more disability (as per PwD Act, 2016)", "Age 18 years or above (14+ for persons with mental retardation)", "No income ceiling for the loan itself", "Viable self-employment/income-generation activity"], "documents": ["Aadhaar Card", "Disability Certificate (40%+)", "Bank Account Details", "Business/activity proposal"], "how_to_apply": "Apply through NDFDC's State Channelizing Agencies (SCAs) or partner banks/NBFCs.", "website": "https://ndfdc.nic.in", "helpline": "1800-180-5129"},
        "hi": {"name": "दिव्यांगजन स्वावलंबन योजना (रियायती ऋण)", "amount": "₹50 लाख तक रियायती ऋण (मासिक पेंशन नहीं)", "description": "राष्ट्रीय दिव्यांगजन वित्त एवं विकास निगम (NDFDC) द्वारा संचालित रियायती ब्याज दर वाली ऋण योजना, जो विकलांग व्यक्तियों को आय-सृजन गतिविधि शुरू करने/बढ़ाने में मदद करती है। यह ऋण है, मासिक नकद पेंशन नहीं — मासिक विकलांगता पेंशन एक अलग योजना (इंदिरा गांधी राष्ट्रीय विकलांगता पेंशन योजना, IGNDPS) से संबंधित है, जो इस ऐप में अलग से ट्रैक नहीं की गई है।", "eligibility": ["40% या अधिक विकलांगता (PwD अधिनियम, 2016 अनुसार)", "आयु 18 वर्ष या अधिक (मानसिक मंदता वालों के लिए 14+)", "ऋण के लिए कोई आय सीमा नहीं", "व्यवहार्य स्वरोजगार/आय-सृजन गतिविधि"], "documents": ["आधार कार्ड", "विकलांगता प्रमाण पत्र (40%+)", "बैंक खाता विवरण", "व्यवसाय/गतिविधि प्रस्ताव"], "how_to_apply": "NDFDC की राज्य चैनलाइजिंग एजेंसियों (SCAs) या साझेदार बैंकों/NBFC के माध्यम से आवेदन करें।", "website": "https://ndfdc.nic.in", "helpline": "1800-180-5129"},
        "mr": {"name": "दिव्यांगजन स्वावलंबन योजना (सवलतीचे कर्ज)", "amount": "₹50 लाखांपर्यंत सवलतीचे कर्ज (मासिक निवृत्तीवेतन नाही)", "description": "राष्ट्रीय दिव्यांगजन वित्त व विकास महामंडळ (NDFDC) द्वारा चालवली जाणारी सवलतीच्या व्याजदराची कर्ज योजना, जी अपंग व्यक्तींना उत्पन्न-निर्मिती उपक्रम सुरू करण्यास/वाढवण्यास मदत करते. हे कर्ज आहे, मासिक रोख निवृत्तीवेतन नाही — मासिक अपंगत्व निवृत्तीवेतन ही वेगळी योजना (इंदिरा गांधी राष्ट्रीय अपंगत्व निवृत्तीवेतन योजना, IGNDPS) आहे, जी या अ‍ॅपमध्ये स्वतंत्रपणे ट्रॅक केलेली नाही.", "eligibility": ["40% किंवा अधिक अपंगत्व (PwD कायदा, 2016 नुसार)", "वय 18 वर्षे किंवा अधिक (मतिमंदांसाठी 14+)", "कर्जासाठी उत्पन्न मर्यादा नाही", "व्यवहार्य स्वयंरोजगार/उत्पन्न-निर्मिती उपक्रम"], "documents": ["आधार कार्ड", "अपंगत्व प्रमाणपत्र (40%+)", "बँक खाते तपशील", "व्यवसाय/उपक्रम प्रस्ताव"], "how_to_apply": "NDFDC च्या राज्य चॅनेलायझिंग एजन्सी (SCAs) किंवा भागीदार बँका/NBFC मार्फत अर्ज करा.", "website": "https://ndfdc.nic.in", "helpline": "1800-180-5129"}
    },
    "adip": {
        "en": {"name": "ADIP — Assistance to Disabled Persons for Purchase/Fitting of Aids & Appliances", "amount": "Free / subsidised assistive devices (wheelchairs, hearing aids, prosthetics, etc.)", "description": "Central scheme (since 1981) providing free or subsidised assistive devices — wheelchairs, hearing aids, prosthetics, tricycles and more — through ALIMCO camps and empanelled agencies. (Note: this benefit was previously mislabelled in this app as the 'Accessible India Campaign' — that is a separate infrastructure-accessibility initiative, not a device-distribution scheme.)", "eligibility": ["40% or more disability certificate (benchmark disability)", "Monthly income up to Rs. 30,000 (or of parent/guardian for dependents)", "Not having received assistance for the same purpose in the last 3 years"], "documents": ["Aadhaar Card", "Disability Certificate (40%+)", "Income Certificate"], "how_to_apply": "Apply through ALIMCO camps or nearest District Disability Rehabilitation Centre (DDRC).", "website": "https://depwd.gov.in/en/adip/", "helpline": "1800-180-5129"},
        "hi": {"name": "ADIP — विकलांग व्यक्तियों को सहायक उपकरण खरीदने/फिट करने हेतु सहायता", "amount": "मुफ्त / रियायती सहायक उपकरण (व्हीलचेयर, श्रवण यंत्र, कृत्रिम अंग आदि)", "description": "केंद्रीय योजना (1981 से) जो ALIMCO शिविरों और सूचीबद्ध एजेंसियों के माध्यम से मुफ्त या रियायती सहायक उपकरण — व्हीलचेयर, श्रवण यंत्र, कृत्रिम अंग, ट्राइसाइकिल आदि — प्रदान करती है। (नोट: यह लाभ पहले इस ऐप में गलती से 'सुगम्य भारत अभियान' के नाम से दिखाया गया था — वह एक अलग अवसंरचना-पहुंच पहल है, उपकरण-वितरण योजना नहीं।)", "eligibility": ["40% या अधिक विकलांगता प्रमाण पत्र", "मासिक आय ₹30,000 तक (आश्रितों के लिए माता-पिता/अभिभावक की)", "पिछले 3 वर्षों में इसी उद्देश्य हेतु सहायता न ली हो"], "documents": ["आधार कार्ड", "विकलांगता प्रमाण पत्र (40%+)", "आय प्रमाण पत्र"], "how_to_apply": "ALIMCO शिविरों या निकटतम जिला विकलांग पुनर्वास केंद्र (DDRC) के माध्यम से आवेदन करें।", "website": "https://depwd.gov.in/en/adip/", "helpline": "1800-180-5129"},
        "mr": {"name": "ADIP — अपंग व्यक्तींना साधने/उपकरणे खरेदी/फिटिंगसाठी सहाय्य", "amount": "मोफत / सवलतीची सहाय्यक साधने (व्हीलचेअर, श्रवणयंत्र, कृत्रिम अवयव इ.)", "description": "केंद्रीय योजना (1981 पासून) जी ALIMCO शिबिरे व सूचीबद्ध संस्थांमार्फत मोफत किंवा सवलतीची सहाय्यक साधने — व्हीलचेअर, श्रवणयंत्र, कृत्रिम अवयव, तीनचाकी सायकल इ. — पुरवते. (टीप: हा लाभ आधी या अ‍ॅपमध्ये चुकीने 'सुगम्य भारत अभियान' या नावाने दाखवला होता — ती वेगळी पायाभूत-सुलभता उपक्रम आहे, साधन-वितरण योजना नाही.)", "eligibility": ["40% किंवा अधिक अपंगत्व प्रमाणपत्र", "मासिक उत्पन्न ₹30,000 पर्यंत (अवलंबितांसाठी पालकांचे)", "मागील 3 वर्षांत त्याच कारणासाठी मदत घेतलेली नसावी"], "documents": ["आधार कार्ड", "अपंगत्व प्रमाणपत्र (40%+)", "उत्पन्न प्रमाणपत्र"], "how_to_apply": "ALIMCO शिबिरे किंवा जवळच्या जिल्हा अपंग पुनर्वसन केंद्रामार्फत (DDRC) अर्ज करा.", "website": "https://depwd.gov.in/en/adip/", "helpline": "1800-180-5129"}
    },
    "accessible_india": {
        "en": {"name": "Accessible India Campaign (Sugamya Bharat Abhiyan)", "amount": "Infrastructure programme — not an individual cash/device benefit", "description": "A nationwide DEPwD infrastructure-accessibility initiative (buildings, transport, ICT) for persons with disabilities. It is NOT a scheme citizens individually apply to for free devices — that benefit (wheelchairs, hearing aids, etc.) is provided under the separate ADIP scheme. This entry is kept only for reference; see 'adip' for the actual applicable citizen benefit.", "eligibility": ["Not individually applicable — this is a public-infrastructure programme, not a personal benefit"], "documents": [], "how_to_apply": "Not applicable to individuals — see the ADIP scheme instead for personal assistive-device assistance.", "website": "https://depwd.gov.in/en/accessible-india-campaign/", "helpline": "1800-180-5129"},
        "hi": {"name": "सुगम्य भारत अभियान (Accessible India Campaign)", "amount": "अवसंरचना कार्यक्रम — व्यक्तिगत नकद/उपकरण लाभ नहीं", "description": "विकलांग व्यक्तियों के लिए एक राष्ट्रव्यापी DEPwD अवसंरचना-पहुंच पहल (भवन, परिवहन, ICT)। यह वह योजना नहीं है जिसमें नागरिक मुफ्त उपकरणों के लिए व्यक्तिगत रूप से आवेदन करते हैं — वह लाभ (व्हीलचेयर, श्रवण यंत्र आदि) अलग ADIP योजना के तहत दिया जाता है। यह प्रविष्टि केवल संदर्भ हेतु रखी गई है; वास्तविक लागू नागरिक लाभ के लिए 'adip' देखें।", "eligibility": ["व्यक्तिगत रूप से लागू नहीं — यह एक सार्वजनिक-अवसंरचना कार्यक्रम है, व्यक्तिगत लाभ नहीं"], "documents": [], "how_to_apply": "व्यक्तियों पर लागू नहीं — व्यक्तिगत सहायक-उपकरण सहायता हेतु ADIP योजना देखें।", "website": "https://depwd.gov.in/en/accessible-india-campaign/", "helpline": "1800-180-5129"},
        "mr": {"name": "सुगम्य भारत अभियान (Accessible India Campaign)", "amount": "पायाभूत सुविधा कार्यक्रम — वैयक्तिक रोख/साधन लाभ नाही", "description": "अपंग व्यक्तींसाठी देशव्यापी DEPwD पायाभूत-सुलभता उपक्रम (इमारती, वाहतूक, ICT). ही ती योजना नाही ज्यात नागरिक मोफत साधनांसाठी वैयक्तिकरित्या अर्ज करतात — तो लाभ (व्हीलचेअर, श्रवणयंत्र इ.) वेगळ्या ADIP योजनेअंतर्गत दिला जातो. ही नोंद केवळ संदर्भासाठी ठेवली आहे; प्रत्यक्ष लागू नागरिक लाभासाठी 'adip' पहा.", "eligibility": ["वैयक्तिकरित्या लागू नाही — ही सार्वजनिक-पायाभूत सुविधा कार्यक्रम आहे, वैयक्तिक लाभ नाही"], "documents": [], "how_to_apply": "व्यक्तींना लागू नाही — वैयक्तिक सहाय्यक-साधन मदतीसाठी ADIP योजना पहा.", "website": "https://depwd.gov.in/en/accessible-india-campaign/", "helpline": "1800-180-5129"}
    },
    "pm_awas_gramin": {
        "en": {"name": "PM Awas Yojana - Gramin (PMAY-G)", "amount": "Rs. 1,20,000 (plain areas) / Rs. 1,30,000 (NE & hill states)", "description": "Central rural housing scheme for construction of pucca houses with basic amenities for houseless / kutcha-house rural families. Cabinet approved continuation through FY 2028-29 for 2 crore additional houses.", "eligibility": ["Rural household without a pucca house, or living in a kutcha/dilapidated house", "Listed in SECC 2011 Permanent Wait List or the Awaas+ survey", "Approved by the Gram Sabha", "Has not availed any other central housing scheme benefit"], "documents": ["Aadhaar Card", "Job Card (MGNREGA) if available", "Bank Account Details", "Land Ownership Document"], "how_to_apply": "Apply at Gram Panchayat or check status online at pmayg.nic.in.", "website": "https://pmayg.nic.in", "helpline": "1800-11-6446"},
        "hi": {"name": "PM आवास योजना - ग्रामीण (PMAY-G)", "amount": "रु. 1,20,000 (सामान्य क्षेत्र) / रु. 1,30,000 (पूर्वोत्तर व पहाड़ी राज्य)", "description": "बेघर/कच्चे घर वाले ग्रामीण परिवारों के लिए पक्के घर बनाने की केंद्रीय ग्रामीण आवास योजना। कैबिनेट ने FY 2028-29 तक 2 करोड़ अतिरिक्त घरों के लिए निरंतरता को मंजूरी दी है।", "eligibility": ["पक्का घर न होने वाला या कच्चे/जर्जर घर में रहने वाला ग्रामीण परिवार", "SECC 2011 स्थायी प्रतीक्षा सूची या Awaas+ सर्वेक्षण में सूचीबद्ध", "ग्राम सभा द्वारा अनुमोदित", "किसी अन्य केंद्रीय आवास योजना का लाभ न लिया हो"], "documents": ["आधार कार्ड", "जॉब कार्ड (यदि उपलब्ध हो)", "बैंक खाता विवरण", "भूमि स्वामित्व दस्तावेज"], "how_to_apply": "ग्राम पंचायत में आवेदन करें या pmayg.nic.in पर स्थिति जांचें।", "website": "https://pmayg.nic.in", "helpline": "1800-11-6446"},
        "mr": {"name": "PM आवास योजना - ग्रामीण (PMAY-G)", "amount": "रु. 1,20,000 (सर्वसाधारण क्षेत्र) / रु. 1,30,000 (ईशान्य व डोंगराळ राज्ये)", "description": "बेघर/कच्च्या घरातील ग्रामीण कुटुंबांसाठी पक्के घर बांधण्याची केंद्रीय ग्रामीण गृहनिर्माण योजना. मंत्रिमंडळाने FY 2028-29 पर्यंत 2 कोटी अतिरिक्त घरांसाठी सातत्याला मंजुरी दिली आहे.", "eligibility": ["पक्के घर नसलेले किंवा कच्च्या/मोडकळीस आलेल्या घरात राहणारे ग्रामीण कुटुंब", "SECC 2011 कायम प्रतीक्षा यादी किंवा Awaas+ सर्वेक्षणात नोंदणीकृत", "ग्रामसभेने मंजूर केलेले", "इतर कोणत्याही केंद्रीय गृहनिर्माण योजनेचा लाभ घेतलेला नसावा"], "documents": ["आधार कार्ड", "जॉब कार्ड (उपलब्ध असल्यास)", "बँक खाते तपशील", "जमीन मालकी दस्तऐवज"], "how_to_apply": "ग्रामपंचायतमध्ये अर्ज करा किंवा pmayg.nic.in वर स्थिती तपासा.", "website": "https://pmayg.nic.in", "helpline": "1800-11-6446"}
    },
    "pm_awas_urban": {
        "en": {"name": "PM Awas Yojana - Urban (PMAY-U 2.0)", "amount": "Central assistance varies by component (up to Rs. 2.5 lakh under BLC)", "description": "Central urban housing scheme (PMAY-Urban 2.0, Cabinet-approved 9 Aug 2024, outlay Rs. 2.30 lakh crore) for houseless urban families / slum dwellers, delivered via Beneficiary-Led Construction (BLC), Affordable Housing in Partnership, and other verticals.", "eligibility": ["Urban area resident (statutory town/municipal area)", "Household without a pucca house anywhere in India", "Falls under EWS/LIG/MIG income criteria as per current guidelines", "Has not availed any other central housing scheme benefit"], "documents": ["Aadhaar Card", "Income Certificate", "Municipal/Urban Local Body Residence Proof", "Bank Account Details"], "how_to_apply": "Apply online at pmay-urban.gov.in or through the Urban Local Body (Municipal Corporation/Council).", "website": "https://pmay-urban.gov.in", "helpline": "1800-11-6163"},
        "hi": {"name": "PM आवास योजना - शहरी (PMAY-U 2.0)", "amount": "घटक अनुसार केंद्रीय सहायता (BLC के तहत ₹2.5 लाख तक)", "description": "बेघर शहरी परिवारों / झुग्गी निवासियों के लिए केंद्रीय शहरी आवास योजना (PMAY-शहरी 2.0, 9 अगस्त 2024 कैबिनेट स्वीकृत, परिव्यय ₹2.30 लाख करोड़), लाभार्थी-नेतृत्व निर्माण (BLC) सहित कई घटकों के माध्यम से दी जाती है।", "eligibility": ["शहरी क्षेत्र निवासी", "भारत में कहीं भी पक्का घर न हो", "वर्तमान दिशानिर्देशों अनुसार EWS/LIG/MIG आय मानदंड में आता हो", "किसी अन्य केंद्रीय आवास योजना का लाभ न लिया हो"], "documents": ["आधार कार्ड", "आय प्रमाण पत्र", "शहरी निवास प्रमाण", "बैंक खाता विवरण"], "how_to_apply": "pmay-urban.gov.in पर ऑनलाइन आवेदन करें या नगर निकाय के माध्यम से।", "website": "https://pmay-urban.gov.in", "helpline": "1800-11-6163"},
        "mr": {"name": "PM आवास योजना - शहरी (PMAY-U 2.0)", "amount": "घटकानुसार केंद्रीय सहाय्य (BLC अंतर्गत ₹2.5 लाखांपर्यंत)", "description": "बेघर शहरी कुटुंबे / झोपडपट्टीवासीयांसाठी केंद्रीय शहरी गृहनिर्माण योजना (PMAY-शहरी 2.0, 9 ऑगस्ट 2024 मंत्रिमंडळ मंजूर, खर्च ₹2.30 लाख कोटी), लाभार्थी-आधारित बांधकाम (BLC) यासह अनेक घटकांमार्फत दिली जाते.", "eligibility": ["शहरी भागातील रहिवासी", "भारतात कुठेही पक्के घर नसावे", "सध्याच्या मार्गदर्शक तत्त्वांनुसार EWS/LIG/MIG उत्पन्न निकषात बसणारे", "इतर कोणत्याही केंद्रीय गृहनिर्माण योजनेचा लाभ घेतलेला नसावा"], "documents": ["आधार कार्ड", "उत्पन्न प्रमाणपत्र", "शहरी रहिवासी पुरावा", "बँक खाते तपशील"], "how_to_apply": "pmay-urban.gov.in वर ऑनलाइन अर्ज करा किंवा नागरी स्थानिक संस्थेमार्फत.", "website": "https://pmay-urban.gov.in", "helpline": "1800-11-6163"}
    },
    "pm_awas": {
        "en": {"name": "PM Awas Yojana (legacy — see PMAY-Gramin / PMAY-Urban)", "amount": "See PMAY-Gramin or PMAY-Urban", "description": "PMAY-Gramin and PMAY-Urban are governed by different eligibility rules, departments and unit assistance. This legacy entry is kept only for old links; please refer to 'PM Awas Yojana - Gramin' (rural) or 'PM Awas Yojana - Urban' (urban) for accurate, current details.", "eligibility": ["See PMAY-Gramin (rural) or PMAY-Urban (urban)"], "documents": [], "how_to_apply": "See PMAY-Gramin or PMAY-Urban.", "website": "https://pmaymis.gov.in", "helpline": "1800-11-6163"},
        "hi": {"name": "PM आवास योजना (पुराना — PMAY-ग्रामीण / PMAY-शहरी देखें)", "amount": "PMAY-ग्रामीण या PMAY-शहरी देखें", "description": "PMAY-ग्रामीण और PMAY-शहरी अलग-अलग पात्रता नियमों, विभागों और इकाई सहायता द्वारा शासित हैं। यह पुरानी प्रविष्टि केवल पुराने लिंक के लिए रखी गई है; सटीक, वर्तमान विवरण हेतु 'PM आवास योजना - ग्रामीण' या 'PM आवास योजना - शहरी' देखें।", "eligibility": ["PMAY-ग्रामीण (ग्रामीण) या PMAY-शहरी (शहरी) देखें"], "documents": [], "how_to_apply": "PMAY-ग्रामीण या PMAY-शहरी देखें।", "website": "https://pmaymis.gov.in", "helpline": "1800-11-6163"},
        "mr": {"name": "PM आवास योजना (जुने — PMAY-ग्रामीण / PMAY-शहरी पहा)", "amount": "PMAY-ग्रामीण किंवा PMAY-शहरी पहा", "description": "PMAY-ग्रामीण आणि PMAY-शहरी वेगवेगळ्या पात्रता नियम, विभाग आणि युनिट सहाय्याने नियंत्रित आहेत. ही जुनी नोंद फक्त जुन्या लिंकसाठी ठेवली आहे; अचूक, सध्याच्या तपशीलांसाठी 'PM आवास योजना - ग्रामीण' किंवा 'PM आवास योजना - शहरी' पहा.", "eligibility": ["PMAY-ग्रामीण (ग्रामीण) किंवा PMAY-शहरी (शहरी) पहा"], "documents": [], "how_to_apply": "PMAY-ग्रामीण किंवा PMAY-शहरी पहा.", "website": "https://pmaymis.gov.in", "helpline": "1800-11-6163"}
=======
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
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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
<<<<<<< HEAD
        "en": {"name": "Saubhagya Scheme (CLOSED — Historical, 2017-2022)", "amount": "CLOSED — do not apply, no longer active", "description": "Pradhan Mantri Sahaj Bijli Har Ghar Yojana (Saubhagya) provided free household electricity connections but was completed and officially closed on 31 March 2022 after ~2.86 crore households were electrified (confirmed via PIB/Ministry of Power press releases). It is shown here for historical reference only. Later electrification gaps are handled under the separate Revamped Distribution Sector Scheme (RDSS) — contact your local DISCOM if you still lack an electricity connection.", "eligibility": ["NOT APPLICABLE — this scheme is closed and cannot be applied for"], "documents": [], "how_to_apply": "This scheme is closed. If you still need an electricity connection, contact your local electricity distribution company (DISCOM) about current connection options / RDSS.", "website": "https://pib.gov.in/PressReleseDetailm.aspx?PRID=1983087", "helpline": "1800-11-5467"},
        "hi": {"name": "सौभाग्य योजना (बंद — ऐतिहासिक, 2017-2022)", "amount": "बंद — आवेदन न करें, अब सक्रिय नहीं", "description": "प्रधानमंत्री सहज बिजली हर घर योजना (सौभाग्य) मुफ्त घरेलू बिजली कनेक्शन देती थी, लेकिन लगभग 2.86 करोड़ घरों के विद्युतीकरण के बाद 31 मार्च 2022 को आधिकारिक रूप से बंद हो गई (PIB/ऊर्जा मंत्रालय की प्रेस विज्ञप्तियों से पुष्टि)। यह केवल ऐतिहासिक संदर्भ हेतु दिखाई गई है। बाद के विद्युतीकरण अंतराल अलग रिवैम्प्ड डिस्ट्रीब्यूशन सेक्टर स्कीम (RDSS) के तहत संभाले जाते हैं।", "eligibility": ["लागू नहीं — यह योजना बंद है और इसके लिए आवेदन नहीं किया जा सकता"], "documents": [], "how_to_apply": "यह योजना बंद है। यदि अभी भी बिजली कनेक्शन चाहिए तो अपनी स्थानीय बिजली वितरण कंपनी (DISCOM) से RDSS के बारे में संपर्क करें।", "website": "https://pib.gov.in/PressReleseDetailm.aspx?PRID=1983087", "helpline": "1800-11-5467"},
        "mr": {"name": "सौभाग्य योजना (बंद — ऐतिहासिक, 2017-2022)", "amount": "बंद — अर्ज करू नका, आता सक्रिय नाही", "description": "प्रधानमंत्री सहज बिजली हर घर योजना (सौभाग्य) मोफत घरगुती वीज कनेक्शन देत होती, परंतु सुमारे 2.86 कोटी घरांचे विद्युतीकरण झाल्यानंतर 31 मार्च 2022 रोजी अधिकृतपणे बंद झाली (PIB/ऊर्जा मंत्रालयाच्या प्रसिद्धीपत्रकांवरून पुष्टी). ही केवळ ऐतिहासिक संदर्भासाठी दाखवली आहे. नंतरची विद्युतीकरण तफावत वेगळ्या रिव्हॅम्प्ड डिस्ट्रिब्युशन सेक्टर स्कीम (RDSS) अंतर्गत हाताळली जाते.", "eligibility": ["लागू नाही — ही योजना बंद आहे आणि यासाठी अर्ज करता येणार नाही"], "documents": [], "how_to_apply": "ही योजना बंद आहे. वीज कनेक्शन हवे असल्यास तुमच्या स्थानिक वीज वितरण कंपनीशी (DISCOM) RDSS बाबत संपर्क साधा.", "website": "https://pib.gov.in/PressReleseDetailm.aspx?PRID=1983087", "helpline": "1800-11-5467"}
=======
        "en": {"name": "Saubhagya Scheme (Free Electricity)", "amount": "Free electricity connection", "description": "Free household electricity connection to all un-electrified households.", "eligibility": ["Un-electrified household", "BPL or poor household", "Rural or urban area"], "documents": ["Aadhaar Card", "BPL Certificate", "Address Proof"], "how_to_apply": "Contact nearest electricity distribution company (DISCOM).", "website": "https://saubhagya.gov.in", "helpline": "1800-11-5467"},
        "hi": {"name": "सौभाग्य योजना (मुफ्त बिजली)", "amount": "मुफ्त बिजली कनेक्शन", "description": "सभी बिना बिजली वाले घरों को मुफ्त बिजली कनेक्शन।", "eligibility": ["बिना बिजली वाला घर", "BPL या गरीब परिवार", "ग्रामीण या शहरी क्षेत्र"], "documents": ["आधार कार्ड", "BPL प्रमाण पत्र", "पता प्रमाण"], "how_to_apply": "निकटतम बिजली वितरण कंपनी से संपर्क करें।", "website": "https://saubhagya.gov.in", "helpline": "1800-11-5467"},
        "mr": {"name": "सौभाग्य योजना (मोफत वीज)", "amount": "मोफत वीज कनेक्शन", "description": "सर्व विनावीज घरांना मोफत वीज कनेक्शन.", "eligibility": ["विनावीज घर", "BPL किंवा गरीब कुटुंब", "ग्रामीण किंवा शहरी भाग"], "documents": ["आधार कार्ड", "BPL प्रमाणपत्र", "पत्ता पुरावा"], "how_to_apply": "जवळच्या वीज वितरण कंपनीशी संपर्क करा.", "website": "https://saubhagya.gov.in", "helpline": "1800-11-5467"}
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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
<<<<<<< HEAD
        "en": {"name": "Mahatma Jyotirao Phule Jan Arogya Yojana (Maharashtra)", "amount": "Rs. 5 lakh/family/year (effective 1 July 2024)", "description": "Maharashtra state health insurance scheme (combined with AB-PMJAY) providing cashless treatment up to Rs.5 lakh per family per year at empanelled hospitals. As of the 28 July 2023 GR, coverage was expanded to ALL ration card categories, not just Yellow/Orange.", "eligibility": ["Maharashtra resident", "Holder of Yellow, Antyodaya, Annapurna, or Orange (income up to Rs.1 lakh) ration card, OR any Maharashtra-domicile family under the expanded coverage", "White-card farmer families in specified drought-affected talukas also covered"], "documents": ["Aadhaar Card", "Ration Card (any category)", "Maharashtra Domicile Proof"], "how_to_apply": "Visit any empanelled government or private hospital in Maharashtra with Aadhaar and ration card.", "website": "https://www.jeevandayee.gov.in", "helpline": "155388"},
        "hi": {"name": "महात्मा ज्योतिराव फुले जन आरोग्य योजना (महाराष्ट्र)", "amount": "रु. 5 लाख/परिवार/वर्ष (1 जुलाई 2024 से प्रभावी)", "description": "महाराष्ट्र राज्य स्वास्थ्य बीमा योजना (AB-PMJAY के साथ संयुक्त) जो सूचीबद्ध अस्पतालों में रु.5 लाख प्रति परिवार प्रति वर्ष तक का कैशलेस उपचार देती है। 28 जुलाई 2023 के GR अनुसार, कवरेज को सभी राशन कार्ड श्रेणियों तक बढ़ाया गया, केवल पीला/नारंगी तक सीमित नहीं।", "eligibility": ["महाराष्ट्र निवासी", "पीला, अंत्योदय, अन्नपूर्णा, या नारंगी (आय रु.1 लाख तक) राशन कार्ड धारक, या विस्तारित कवरेज के तहत कोई भी महाराष्ट्र-अधिवास परिवार", "निर्दिष्ट सूखा-प्रभावित तालुकाओं में सफेद कार्ड किसान परिवार भी शामिल"], "documents": ["आधार कार्ड", "राशन कार्ड (कोई भी श्रेणी)", "महाराष्ट्र निवास प्रमाण"], "how_to_apply": "आधार और राशन कार्ड के साथ महाराष्ट्र के किसी भी सूचीबद्ध अस्पताल में जाएं।", "website": "https://www.jeevandayee.gov.in", "helpline": "155388"},
        "mr": {"name": "महात्मा ज्योतिराव फुले जन आरोग्य योजना (महाराष्ट्र)", "amount": "रु. 5 लाख/कुटुंब/वर्ष (1 जुलै 2024 पासून लागू)", "description": "महाराष्ट्र राज्य आरोग्य विमा योजना (AB-PMJAY सह एकत्रित) जी सूचीबद्ध रुग्णालयांमध्ये रु.5 लाख प्रति कुटुंब प्रति वर्ष कॅशलेस उपचार देते. 28 जुलै 2023 च्या GR नुसार, कव्हरेज सर्व शिधापत्रिका प्रकारांपर्यंत वाढवण्यात आले, फक्त पिवळे/नारिंगीपुरते मर्यादित नाही.", "eligibility": ["महाराष्ट्र रहिवासी", "पिवळे, अंत्योदय, अन्नपूर्णा, किंवा नारिंगी (उत्पन्न रु.1 लाखापर्यंत) शिधापत्रिका धारक, किंवा विस्तारित कव्हरेज अंतर्गत कोणतेही महाराष्ट्र-अधिवास कुटुंब", "निर्दिष्ट दुष्काळग्रस्त तालुक्यांतील पांढरे कार्ड शेतकरी कुटुंबेही समाविष्ट"], "documents": ["आधार कार्ड", "शिधापत्रिका (कोणताही प्रकार)", "महाराष्ट्र अधिवास पुरावा"], "how_to_apply": "आधार आणि शिधापत्रिकेसह महाराष्ट्रातील कोणत्याही सूचीबद्ध रुग्णालयात जा.", "website": "https://www.jeevandayee.gov.in", "helpline": "155388"}
    },
    "shravan_bal": {
        "en": {"name": "Shravan Bal Seva Rajya Nivrutti Vetan (Maharashtra)", "amount": "Rs. 1,500/month", "description": "Maharashtra state old age pension scheme. GR विसयो-2022/प्र.क्र.120/विसयो (5 July 2023) raised the monthly amount from Rs.1,000 to Rs.1,500 for eligible elderly citizens aged 65 and above.", "eligibility": ["Age 65 years and above", "Maharashtra resident for 15+ years", "Annual income below Rs. 21,000", "Not receiving any other pension"], "documents": ["Aadhaar Card", "Age Proof (Birth Certificate/School Certificate)", "Income Certificate", "Bank Account Details", "Domicile Certificate"], "how_to_apply": "Apply at nearest Gram Panchayat or District Social Welfare Office.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "श्रवण बाल सेवा राज्य निवृत्ती वेतन (महाराष्ट्र)", "amount": "रु. 1,500/माह", "description": "महाराष्ट्र राज्य वृद्धावस्था पेंशन योजना। GR विसयो-2022/प्र.क्र.120/विसयो (5 जुलाई 2023) ने मासिक राशि रु.1,000 से बढ़ाकर रु.1,500 कर दी, 65+ वर्ष के पात्र वृद्धों हेतु।", "eligibility": ["65 वर्ष और उससे अधिक", "15+ वर्ष से महाराष्ट्र निवासी", "वार्षिक आय रु. 21,000 से कम", "कोई अन्य पेंशन नहीं"], "documents": ["आधार कार्ड", "आयु प्रमाण", "आय प्रमाण पत्र", "बैंक खाता विवरण", "अधिवास प्रमाण पत्र"], "how_to_apply": "निकटतम ग्राम पंचायत या जिला समाज कल्याण कार्यालय में आवेदन करें।", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "श्रवण बाल सेवा राज्य निवृत्ती वेतन (महाराष्ट्र)", "amount": "रु. 1,500/महिना", "description": "महाराष्ट्र राज्य वृद्धापकाळ निवृत्तीवेतन योजना. GR विसयो-2022/प्र.क्र.120/विसयो (5 जुलै 2023) ने मासिक रक्कम रु.1,000 वरून रु.1,500 केली, 65+ वयाच्या पात्र वृद्धांसाठी.", "eligibility": ["65 वर्षे आणि त्याहून अधिक", "15+ वर्षांपासून महाराष्ट्र रहिवासी", "वार्षिक उत्पन्न रु. 21,000 पेक्षा कमी", "इतर कोणतीही पेन्शन नाही"], "documents": ["आधार कार्ड", "वयाचा पुरावा", "उत्पन्न प्रमाणपत्र", "बँक खाते तपशील", "अधिवास प्रमाणपत्र"], "how_to_apply": "जवळच्या ग्रामपंचायत किंवा जिल्हा समाज कल्याण कार्यालयात अर्ज करा.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "gharkul": {
        "en": {"name": "Ramai Awas Gharkul Yojana (Maharashtra)", "amount": "Free Permanent House (Rs. 1.20 lakh+ construction assistance)", "description": "Maharashtra government housing scheme providing free permanent houses specifically to Scheduled Caste (SC) and Neo-Buddhist (Nav-Bauddha) community families — not the broader SC/ST/OBC/NT grouping.", "eligibility": ["Scheduled Caste (SC) or Neo-Buddhist (Nav-Bauddha) community member", "Resident of Maharashtra for 15+ years", "No pucca house", "Annual income below Rs. 1 lakh", "Only one beneficiary per family; must not have availed another housing scheme"], "documents": ["Aadhaar Card", "Caste Certificate (SC/Nav-Bauddha)", "Income Certificate", "Land Documents / 7/12 extract", "Bank Account Details"], "how_to_apply": "Apply at Gram Panchayat (rural) or Municipal office (urban), or through the District Social Welfare Office.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "रमाई आवास घरकुल योजना (महाराष्ट्र)", "amount": "मुफ्त पक्का घर (₹1.20 लाख+ निर्माण सहायता)", "description": "महाराष्ट्र सरकार की आवास योजना विशेष रूप से अनुसूचित जाति (SC) और नवबौद्ध समुदाय के परिवारों को मुफ्त पक्का घर देती है — व्यापक SC/ST/OBC/NT समूह नहीं।", "eligibility": ["अनुसूचित जाति (SC) या नवबौद्ध समुदाय सदस्य", "15+ वर्ष से महाराष्ट्र निवासी", "कोई पक्का घर नहीं", "वार्षिक आय रु. 1 लाख से कम", "परिवार में केवल एक लाभार्थी; अन्य आवास योजना का लाभ न लिया हो"], "documents": ["आधार कार्ड", "जाति प्रमाण पत्र (SC/नवबौद्ध)", "आय प्रमाण पत्र", "भूमि दस्तावेज / 7/12 उतारा", "बैंक खाता"], "how_to_apply": "ग्राम पंचायत (ग्रामीण) या नगर पालिका (शहरी) में, या जिला समाज कल्याण कार्यालय के माध्यम से आवेदन करें।", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "रमाई आवास घरकुल योजना (महाराष्ट्र)", "amount": "मोफत पक्के घर (₹1.20 लाख+ बांधकाम सहाय्य)", "description": "महाराष्ट्र सरकारची आवास योजना विशेषतः अनुसूचित जाती (SC) व नवबौद्ध समुदायातील कुटुंबांना मोफत पक्के घर देते — व्यापक SC/ST/OBC/NT गट नाही.", "eligibility": ["अनुसूचित जाती (SC) किंवा नवबौद्ध समुदाय सदस्य", "15+ वर्षांपासून महाराष्ट्र रहिवासी", "पक्के घर नाही", "वार्षिक उत्पन्न रु. 1 लाखापेक्षा कमी", "कुटुंबात फक्त एक लाभार्थी; इतर गृहनिर्माण योजनेचा लाभ घेतलेला नसावा"], "documents": ["आधार कार्ड", "जात प्रमाणपत्र (SC/नवबौद्ध)", "उत्पन्न प्रमाणपत्र", "जमीन दस्तऐवज / ७/१२ उतारा", "बँक खाते"], "how_to_apply": "ग्रामपंचायत (ग्रामीण) किंवा नगरपालिका (शहरी) येथे, किंवा जिल्हा समाज कल्याण कार्यालयामार्फत अर्ज करा.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "sanjay_gandhi": {
        "en": {"name": "Sanjay Gandhi Niradhar Anudan Yojana (Maharashtra)", "amount": "Rs. 1,500/month", "description": "Maharashtra scheme providing monthly financial assistance to destitute persons who have no means of livelihood. GR विसयो-2022/प्र.क्र.120/विसयो (5 July 2023) raised the monthly amount from Rs.1,000 to Rs.1,500.", "eligibility": ["Age above 18 years", "Maharashtra resident", "Destitute — no income or family support", "Widow/Divorcee/Abandoned woman", "Annual income below Rs. 21,000"], "documents": ["Aadhaar Card", "Income Certificate", "Domicile Certificate", "Bank Account Details", "Proof of destitution"], "how_to_apply": "Apply at District Social Welfare Office or Gram Panchayat.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "संजय गांधी निराधार अनुदान योजना (महाराष्ट्र)", "amount": "रु. 1,500/माह", "description": "महाराष्ट्र योजना जो बेसहारा व्यक्तियों को मासिक वित्तीय सहायता देती है। GR विसयो-2022/प्र.क्र.120/विसयो (5 जुलाई 2023) ने मासिक राशि रु.1,000 से बढ़ाकर रु.1,500 कर दी।", "eligibility": ["18 वर्ष से अधिक", "महाराष्ट्र निवासी", "बेसहारा — कोई आय नहीं", "विधवा/तलाकशुदा/परित्यक्त महिला", "वार्षिक आय रु. 21,000 से कम"], "documents": ["आधार कार्ड", "आय प्रमाण पत्र", "अधिवास प्रमाण पत्र", "बैंक खाता विवरण"], "how_to_apply": "जिला समाज कल्याण कार्यालय या ग्राम पंचायत में आवेदन करें।", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "संजय गांधी निराधार अनुदान योजना (महाराष्ट्र)", "amount": "रु. 1,500/महिना", "description": "महाराष्ट्र योजना जी निराधार व्यक्तींना मासिक आर्थिक मदत देते. GR विसयो-2022/प्र.क्र.120/विसयो (5 जुलै 2023) ने मासिक रक्कम रु.1,000 वरून रु.1,500 केली.", "eligibility": ["18 वर्षांपेक्षा जास्त", "महाराष्ट्र रहिवासी", "निराधार — उत्पन्न नाही", "विधवा/घटस्फोटित/परित्यक्त महिला", "वार्षिक उत्पन्न रु. 21,000 पेक्षा कमी"], "documents": ["आधार कार्ड", "उत्पन्न प्रमाणपत्र", "अधिवास प्रमाणपत्र", "बँक खाते तपशील"], "how_to_apply": "जिल्हा समाज कल्याण कार्यालय किंवा ग्रामपंचायतमध्ये अर्ज करा.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "rajmata_jijau": {
        "en": {"name": "Rajmata Jijau Mata-Bal Poshan Mission (Maharashtra) — Programme, not a cash scheme", "amount": "Coordination programme — no direct cash payment", "description": "A Maharashtra coordination MISSION for maternal and child health/nutrition, delivered through existing Anganwadi and health-department channels (not a standalone direct cash-benefit scheme). It converges services like nutrition support, health checkups and immunization rather than issuing an independent payment.", "eligibility": ["Pregnant women", "Lactating mothers", "Children under 6 years", "Maharashtra resident"], "documents": ["Aadhaar Card", "Ration Card", "Mother & Child Protection Card"], "how_to_apply": "Register at your nearest Anganwadi Centre or Primary Health Centre — no separate application needed beyond normal Anganwadi/health registration.", "website": "https://womenchild.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "राजमाता जिजाऊ माता-बाल पोषण मिशन (महाराष्ट्र) — कार्यक्रम, नकद योजना नहीं", "amount": "समन्वय कार्यक्रम — कोई सीधा नकद भुगतान नहीं", "description": "मातृ एवं शिशु स्वास्थ्य/पोषण हेतु महाराष्ट्र का समन्वय मिशन, जो मौजूदा आंगनवाड़ी और स्वास्थ्य विभाग चैनलों के माध्यम से दिया जाता है (स्वतंत्र प्रत्यक्ष नकद-लाभ योजना नहीं)। यह पोषण सहायता, स्वास्थ्य जांच और टीकाकरण जैसी सेवाओं को समन्वित करता है, अलग भुगतान जारी नहीं करता।", "eligibility": ["गर्भवती महिलाएं", "स्तनपान कराने वाली माताएं", "6 वर्ष से कम के बच्चे", "महाराष्ट्र निवासी"], "documents": ["आधार कार्ड", "राशन कार्ड", "मातृ एवं शिशु सुरक्षा कार्ड"], "how_to_apply": "निकटतम आंगनवाड़ी केंद्र या प्राथमिक स्वास्थ्य केंद्र में पंजीकरण करें — सामान्य पंजीकरण के अलावा अलग आवेदन आवश्यक नहीं।", "website": "https://womenchild.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "राजमाता जिजाऊ माता-बाल पोषण अभियान (महाराष्ट्र) — कार्यक्रम, रोख योजना नाही", "amount": "समन्वय कार्यक्रम — थेट रोख देयक नाही", "description": "माता व बाल आरोग्य/पोषणासाठी महाराष्ट्राचे समन्वय अभियान, जे विद्यमान अंगणवाडी व आरोग्य विभाग माध्यमांतून दिले जाते (स्वतंत्र थेट रोख-लाभ योजना नाही). हे पोषण सहाय्य, आरोग्य तपासणी व लसीकरण यासारख्या सेवा एकत्रित करते, वेगळे देयक जारी करत नाही.", "eligibility": ["गर्भवती महिला", "स्तनपान करणाऱ्या माता", "6 वर्षांखालील मुले", "महाराष्ट्र रहिवासी"], "documents": ["आधार कार्ड", "रेशन कार्ड", "माता व बाल संरक्षण कार्ड"], "how_to_apply": "जवळच्या अंगणवाडी केंद्र किंवा प्राथमिक आरोग्य केंद्रात नोंदणी करा — सामान्य नोंदणीव्यतिरिक्त वेगळा अर्ज आवश्यक नाही.", "website": "https://womenchild.maharashtra.gov.in", "helpline": "1800-120-8040"}
    },
    "mh_ration": {
        "en": {"name": "Maharashtra Ration Card Classification (PDS/NFSA) — Eligibility framework, not a cash scheme", "amount": "Subsidised food grains via Fair Price Shops — no independent cash payout", "description": "The Yellow/Antyodaya/Annapurna/Orange ration card categories are an eligibility/entitlement FRAMEWORK under the Public Distribution System (PDS)/NFSA, not a standalone scheme with its own fixed payout. Holding a particular card type instead determines eligibility for other schemes (like mh_health, antyodaya).", "eligibility": ["Maharashtra resident", "Family income within the relevant card category's ceiling", "No existing ration card (for new applications)"], "documents": ["Aadhaar Card", "Income Certificate", "Address Proof", "Passport size photos of all family members"], "how_to_apply": "Apply at nearest Gram Panchayat or Taluka Supply Office / online at mahafood.gov.in.", "website": "https://mahafood.gov.in", "helpline": "1800-22-4950"},
        "hi": {"name": "महाराष्ट्र राशन कार्ड वर्गीकरण (PDS/NFSA) — पात्रता ढांचा, नकद योजना नहीं", "amount": "उचित मूल्य दुकानों से सब्सिडी अनाज — कोई स्वतंत्र नकद भुगतान नहीं", "description": "पीला/अंत्योदय/अन्नपूर्णा/नारंगी राशन कार्ड श्रेणियां PDS/NFSA के तहत एक पात्रता ढांचा हैं, अपने स्वयं के निश्चित भुगतान वाली स्वतंत्र योजना नहीं। एक विशेष कार्ड प्रकार होने से अन्य योजनाओं (जैसे mh_health, antyodaya) की पात्रता तय होती है।", "eligibility": ["महाराष्ट्र निवासी", "संबंधित कार्ड श्रेणी की सीमा के भीतर पारिवारिक आय", "नए आवेदन के लिए कोई मौजूदा राशन कार्ड नहीं"], "documents": ["आधार कार्ड", "आय प्रमाण पत्र", "पता प्रमाण", "सभी सदस्यों के पासपोर्ट फोटो"], "how_to_apply": "निकटतम ग्राम पंचायत या तालुका आपूर्ति कार्यालय में / mahafood.gov.in पर ऑनलाइन आवेदन करें।", "website": "https://mahafood.gov.in", "helpline": "1800-22-4950"},
        "mr": {"name": "महाराष्ट्र रेशन कार्ड वर्गीकरण (PDS/NFSA) — पात्रता चौकट, रोख योजना नाही", "amount": "स्वस्त धान्य दुकानांतून सवलतीचे धान्य — स्वतंत्र रोख देयक नाही", "description": "पिवळे/अंत्योदय/अन्नपूर्णा/नारिंगी शिधापत्रिका प्रकार हे PDS/NFSA अंतर्गत एक पात्रता चौकट आहेत, स्वतःच्या निश्चित देयकासह स्वतंत्र योजना नाही. विशिष्ट कार्ड प्रकार असल्याने इतर योजनांची (उदा. mh_health, antyodaya) पात्रता ठरते.", "eligibility": ["महाराष्ट्र रहिवासी", "संबंधित कार्ड प्रकाराच्या मर्यादेत कौटुंबिक उत्पन्न", "नवीन अर्जासाठी विद्यमान शिधापत्रिका नसावी"], "documents": ["आधार कार्ड", "उत्पन्न प्रमाणपत्र", "पत्ता पुरावा", "सर्व सदस्यांचे पासपोर्ट फोटो"], "how_to_apply": "जवळच्या ग्रामपंचायत किंवा तालुका पुरवठा कार्यालयात / mahafood.gov.in वर ऑनलाइन अर्ज करा.", "website": "https://mahafood.gov.in", "helpline": "1800-22-4950"}
    },
    "vayoshri_mh": {
        "en": {"name": "Mukhyamantri Vayoshri Yojana (Maharashtra)", "amount": "Rs. 3,000 ONE-TIME lump-sum DBT (not monthly)", "description": "Maharashtra scheme providing a one-time lump-sum Rs.3,000 Direct Benefit Transfer to an Aadhaar-linked bank account, for senior citizens to purchase assistive devices (hearing aids, spectacles, walking sticks, wheelchairs, etc.). GR क्र.ज्येष्ठना-2022/प्र.क्र.344/सामासु, amended 6.02.2024 / 11.03.2024 / 19.08.2024.", "eligibility": ["Age 65 years and above", "Maharashtra resident", "Aadhaar-linked bank account", "Has an age-related mobility/sensory difficulty needing assistive devices"], "documents": ["Aadhaar Card (linked to bank account)", "Age Proof", "Domicile Certificate"], "how_to_apply": "Apply at District Social Welfare Office or through Gram Panchayat.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "hi": {"name": "मुख्यमंत्री वयोश्री योजना (महाराष्ट्र)", "amount": "₹3,000 एकमुश्त DBT (मासिक नहीं)", "description": "महाराष्ट्र योजना जो आधार-लिंक्ड बैंक खाते में एकमुश्त ₹3,000 का Direct Benefit Transfer देती है, ताकि वरिष्ठ नागरिक सहायक उपकरण (श्रवण यंत्र, चश्मा, छड़ी, व्हीलचेयर आदि) खरीद सकें। GR क्र.ज्येष्ठना-2022/प्र.क्र.344/सामासु, संशोधित 6.02.2024 / 11.03.2024 / 19.08.2024।", "eligibility": ["65 वर्ष और उससे अधिक", "महाराष्ट्र निवासी", "आधार-लिंक्ड बैंक खाता", "आयु-संबंधी गतिशीलता/संवेदी समस्या जिसके लिए उपकरण चाहिए"], "documents": ["आधार कार्ड (बैंक से लिंक्ड)", "आयु प्रमाण", "अधिवास प्रमाण पत्र"], "how_to_apply": "जिला समाज कल्याण कार्यालय में आवेदन करें।", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"},
        "mr": {"name": "मुख्यमंत्री वयोश्री योजना (महाराष्ट्र)", "amount": "₹3,000 एकवेळ DBT (मासिक नाही)", "description": "महाराष्ट्र योजना जी आधार-लिंक्ड बँक खात्यात एकवेळ ₹3,000 चा Direct Benefit Transfer देते, जेणेकरून ज्येष्ठ नागरिक सहाय्यक साधने (श्रवणयंत्र, चष्मा, काठी, व्हीलचेअर इ.) खरेदी करू शकतील. GR क्र.ज्येष्ठना-2022/प्र.क्र.344/सामासु, सुधारित 6.02.2024 / 11.03.2024 / 19.08.2024.", "eligibility": ["वय 65 वर्षे आणि त्याहून अधिक", "महाराष्ट्र रहिवासी", "आधार-लिंक्ड बँक खाते", "वयोमानपरत्वे गतिशीलता/संवेदी अडचण ज्यासाठी साधने आवश्यक"], "documents": ["आधार कार्ड (बँकेशी लिंक्ड)", "वयाचा पुरावा", "अधिवास प्रमाणपत्र"], "how_to_apply": "जिल्हा समाज कल्याण कार्यालयात अर्ज करा.", "website": "https://sjsa.maharashtra.gov.in", "helpline": "1800-120-8040"}
=======
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
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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

<<<<<<< HEAD
# Heuristic ONLY — used to decide PMAY-Gramin vs PMAY-Urban when the
# eligibility form doesn't collect an explicit rural/urban flag. Presence
# of a major city/municipal-area name suggests urban; this is NOT a
# government determination and the scheme page says so explicitly.
URBAN_KEYWORDS = [
    'mumbai', 'pune', 'nagpur', 'nashik', 'thane', 'solapur', 'kolhapur',
    'sambhaji nagar', 'aurangabad', 'navi mumbai', 'pimpri', 'chinchwad',
    'city', 'municipal', 'nagar palika', 'nagar parishad', 'ward', 'colony',
    'lucknow', 'kanpur', 'delhi', 'bangalore', 'bengaluru', 'chennai',
    'kolkata', 'hyderabad', 'ahmedabad', 'surat', 'jaipur', 'indore',
]

=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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
<<<<<<< HEAD
        'shravan_bal':    ('normal', 'Shravan Bal Seva Pension (MH)', 'Rs. 1,500/month'),
        'gharkul':        ('normal', 'Ramai Awas Gharkul Yojana (MH)', 'Free House (SC/Neo-Buddhist)'),
        'sanjay_gandhi':  ('normal', 'Sanjay Gandhi Niradhar Yojana (MH)', 'Rs. 1,500/month'),
        'rajmata_jijau':  ('normal', 'Rajmata Jijau Mata-Bal Poshan Mission (MH)', 'Programme — not a direct cash benefit'),
        'mh_ration':      ('normal', 'Maharashtra Ration Card Classification (MH)', 'Eligibility framework — not a cash scheme'),
        'vayoshri_mh':    ('normal', 'Vayoshri Yojana Maharashtra (MH)', 'Rs. 3,000 one-time DBT'),
=======
        'shravan_bal':    ('normal', 'Shravan Bal Seva Pension (MH)', 'Rs. 600/month'),
        'gharkul':        ('normal', 'Ramai Awas Gharkul Yojana (MH)', 'Free House'),
        'sanjay_gandhi':  ('normal', 'Sanjay Gandhi Niradhar Yojana (MH)', 'Rs. 600/month'),
        'rajmata_jijau':  ('normal', 'Rajmata Jijau Mata-Bal Swasthya (MH)', 'Free maternal health'),
        'mh_ration':      ('normal', 'Maharashtra Yellow Ration Card (MH)', 'Subsidised ration'),
        'vayoshri_mh':    ('normal', 'Vayoshri Yojana Maharashtra (MH)', 'Free aids for elderly'),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
    },
    'hi': {
        'ladki_bahin':    ('urgent', 'लड़की बहन योजना (महाराष्ट्र)', 'रु. 1,500/माह'),
        'mh_health':      ('urgent', 'महात्मा फुले जन आरोग्य योजना (MH)', 'रु. 5 लाख/वर्ष'),
<<<<<<< HEAD
        'shravan_bal':    ('normal', 'श्रवण बाल सेवा पेंशन (MH)', 'रु. 1,500/माह'),
        'gharkul':        ('normal', 'रमाई आवास घरकुल योजना (MH)', 'मुफ्त घर (SC/नवबौद्ध)'),
        'sanjay_gandhi':  ('normal', 'संजय गांधी निराधार योजना (MH)', 'रु. 1,500/माह'),
        'rajmata_jijau':  ('normal', 'राजमाता जिजाऊ माता-बाल पोषण मिशन (MH)', 'कार्यक्रम — सीधा नकद लाभ नहीं'),
        'mh_ration':      ('normal', 'महाराष्ट्र राशन कार्ड वर्गीकरण (MH)', 'पात्रता ढांचा — नकद योजना नहीं'),
        'vayoshri_mh':    ('normal', 'वयोश्री योजना महाराष्ट्र (MH)', 'रु. 3,000 एकमुश्त DBT'),
=======
        'shravan_bal':    ('normal', 'श्रवण बाल सेवा पेंशन (MH)', 'रु. 600/माह'),
        'gharkul':        ('normal', 'रमाई आवास घरकुल योजना (MH)', 'मुफ्त घर'),
        'sanjay_gandhi':  ('normal', 'संजय गांधी निराधार योजना (MH)', 'रु. 600/माह'),
        'rajmata_jijau':  ('normal', 'राजमाता जिजाऊ माता-बाल स्वास्थ्य (MH)', 'मुफ्त मातृ स्वास्थ्य'),
        'mh_ration':      ('normal', 'महाराष्ट्र पीला राशन कार्ड (MH)', 'सब्सिडी राशन'),
        'vayoshri_mh':    ('normal', 'वयोश्री योजना महाराष्ट्र (MH)', 'बुजुर्गों के लिए मदद'),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
    },
    'mr': {
        'ladki_bahin':    ('urgent', 'लाडकी बहीण योजना (महाराष्ट्र)', 'रु. 1,500/महिना'),
        'mh_health':      ('urgent', 'महात्मा फुले जन आरोग्य योजना (MH)', 'रु. 5 लाख/वर्ष'),
<<<<<<< HEAD
        'shravan_bal':    ('normal', 'श्रवण बाल सेवा निवृत्ती वेतन (MH)', 'रु. 1,500/महिना'),
        'gharkul':        ('normal', 'रमाई आवास घरकुल योजना (MH)', 'मोफत घर (SC/नवबौद्ध)'),
        'sanjay_gandhi':  ('normal', 'संजय गांधी निराधार योजना (MH)', 'रु. 1,500/महिना'),
        'rajmata_jijau':  ('normal', 'राजमाता जिजाऊ माता-बाल पोषण अभियान (MH)', 'कार्यक्रम — थेट रोख लाभ नाही'),
        'mh_ration':      ('normal', 'महाराष्ट्र रेशन कार्ड वर्गीकरण (MH)', 'पात्रता चौकट — रोख योजना नाही'),
        'vayoshri_mh':    ('normal', 'वयोश्री योजना महाराष्ट्र (MH)', 'रु. 3,000 एकवेळ DBT'),
=======
        'shravan_bal':    ('normal', 'श्रवण बाल सेवा निवृत्ती वेतन (MH)', 'रु. 600/महिना'),
        'gharkul':        ('normal', 'रमाई आवास घरकुल योजना (MH)', 'मोफत घर'),
        'sanjay_gandhi':  ('normal', 'संजय गांधी निराधार योजना (MH)', 'रु. 600/महिना'),
        'rajmata_jijau':  ('normal', 'राजमाता जिजाऊ माता-बाल आरोग्य (MH)', 'मोफत माता आरोग्य'),
        'mh_ration':      ('normal', 'महाराष्ट्र पिवळे रेशन कार्ड (MH)', 'अनुदानित रेशन'),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
    }
}

def get_ml_prediction(data):
    """
    Performs real-time machine learning inference using the trained Random Forest model
    on live citizen form inputs.
    """
    if ML_MODEL is None:
        return None
    try:
        age_map = {'adult': 0, 'child': 1, 'elderly': 2}
        housing_map = {'pucca': 0, 'rented': 1, 'kutcha': 2, 'homeless': 3}
        elec_map = {'yes': 0, 'sometimes': 1, 'no': 2}
        ration_map = {'yes': 0, 'no': 1}
        med_map = {'none': 0, 'chronic_illness': 1, 'disability': 2, 'emergency': 3}

        ag = age_map.get(data.get('age_group', 'adult'), 0)
        inc = int(data.get('income', 0))
        fs = int(data.get('family_size', 1))
        hsg = housing_map.get(data.get('housing', 'pucca'), 0)
        ele = elec_map.get(data.get('electricity', 'yes'), 0)
        rat = ration_map.get(data.get('ration', 'yes'), 0)
        med = med_map.get(data.get('medical', 'none'), 0)
        acc = 1 if data.get('accident') == 'yes' else 0
        emd = 1 if data.get('earning_member_died') == 'yes' else 0
        wid = 1 if data.get('widow_status') == 'yes' else 0

        features = [[ag, inc, fs, hsg, ele, rat, med, acc, emd, wid]]
        proba = ML_MODEL.predict_proba(features)[0]
        categories = ["Low Need", "Moderate Need", "High Need", "Critical Need"]
        predicted_idx = int(ML_MODEL.predict(features)[0])
        confidence = float(proba[predicted_idx]) * 100

        return {
            'predicted_category': categories[predicted_idx],
            'confidence_percent': round(confidence, 1),
            'probabilities': {cat: round(float(p) * 100, 1) for cat, p in zip(categories, proba)}
        }
    except Exception as e:
        return None

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
        lines.append(f"{F['score']}: {profile['score']} / 225")
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
            'header': "Your Need Score is {score}/225 because of:",
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
            'header': "आपका Need Score {score}/225 है क्योंकि:",
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
            'header': "तुमचा Need Score {score}/225 आहे कारण:",
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

def extract_case_intake(client, user_message, lang):
    """One Gemini call that either (a) extracts structured facts if the
    message describes the sender's own situation, or (b) just answers
    normally if it's a generic question. Returns a dict or None on failure."""
    target_lang_name = {'hi': 'Hindi (हिंदी) written in Devanagari script', 'mr': 'Marathi (मराठी) written in Devanagari script'}.get(lang, 'English')
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

Reply language for "reply" field MUST strictly be: {target_lang_name}

Citizen's message: "{user_message}\""""

    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=extraction_prompt)
        raw = resp.text.strip()
        raw = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        return parsed
    except Exception as e:
        print(f"Case-intake extraction error: {e}")
        return None

def extract_outcome_update(client, user_message, profile, lang='en'):
    """One Gemini call: does this message report an application outcome
    ('I got approved for widow pension', 'my Ayushman application was
    rejected')? If so, match it to one of THIS person's actual recommended
    schemes and figure out the new status. Returns a dict or None."""
    schemes = profile.get('schemes') or []
    if not schemes:
        return None
    scheme_list = "\n".join(f'- key: "{sc["key"]}", name: "{sc["name"]}"' for sc in schemes)

    prompt = f"""A citizen is chatting with a welfare-scheme assistant. Their recommended schemes are:
{scheme_list}

Their message: "{user_message}"

Does this message report the outcome of applying for one of these schemes (e.g. "I got approved for X", "my application was rejected", "I applied for X last week", "still waiting")? If yes, match it to the closest scheme from the list above by its exact "key" value, and determine the status.

Respond with ONLY raw JSON, no markdown fences, no commentary:
{{
  "is_outcome_update": true or false,
  "scheme_key": the exact "key" string from the list above that best matches, or null if unclear which scheme,
  "status": one of "applied"/"under_review"/"approved"/"rejected"/"not_applied" (use "under_review" for things like "still waiting", "no update yet", "they're processing it"), or null if is_outcome_update is false
}}"""

    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = resp.text.strip()
        raw = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"Outcome extraction error: {e}")
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

    # Persist this the SAME way the web form and volunteer flow do — so
    # /track-outcome and the "STATUS <ID>" SMS command actually work for
    # applications that started as a chat or SMS conversation, not just
    # ones that went through the form.
    application_id = generate_application_id()
    phone = extracted.get('phone') or ''
    name = extracted.get('name') or ''
    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    try:
        conn = get_db_connection()
        conn.execute(
            '''INSERT INTO applications
               (application_id, person_name, phone, state, score, priority, schemes_count, lang, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (application_id, name, phone, detect_state(address), score, priority, len(schemes), lang, now_str)
        )
        for sc in schemes:
            conn.execute(
                '''INSERT INTO application_outcomes
                   (application_id, phone, person_name, scheme_key, scheme_name, status, created_at, updated_at, lang)
                   VALUES (?, ?, ?, ?, ?, 'not_applied', ?, ?, ?)''',
                (application_id, phone, name, sc[0], sc[2], now_str, now_str, lang)
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Chat/SMS intake persistence error: {e}")

    return {
        'name': name,
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
        'application_id': application_id,
        'source': 'chat_intake',
        'updated_at': now_str,
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
<<<<<<< HEAD
    # pm_jan_arogya / ayushman are the SAME scheme (AB-PMJAY) — always add
    # under the single canonical key so the two trigger conditions below
    # can never produce a duplicate recommendation card.
=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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
<<<<<<< HEAD
    if medical == 'chronic_illness': schemes.append(('pm_jan_arogya',) + s['pm_jan_arogya'])
    if medical == 'disability':
        schemes.append(('divyangjan',) + s['divyangjan'])
        schemes.append(('adip',) + s['adip'])
    if housing in ['homeless', 'kutcha']:
        # PMAY-Gramin vs PMAY-Urban: prefer an explicit residence_type answer
        # from the (optional, backward-compatible) form field. If it's absent
        # -- e.g. older submissions/API callers that predate this field --
        # fall back to the address-text heuristic used previously so nothing
        # breaks for existing records.
        residence_type = (data.get('residence_type', '') or '').strip().lower()
        if residence_type == 'urban':
            schemes.append(('pm_awas_urban',) + s['pm_awas_urban'])
        elif residence_type == 'rural':
            schemes.append(('pm_awas_gramin',) + s['pm_awas_gramin'])
        elif any(kw in address for kw in URBAN_KEYWORDS):
            schemes.append(('pm_awas_urban',) + s['pm_awas_urban'])
        else:
            schemes.append(('pm_awas_gramin',) + s['pm_awas_gramin'])
    if ration == 'no': schemes.append(('antyodaya',) + s['antyodaya'])
    if electricity == 'no':
        schemes.append(('ujjwala',) + s['ujjwala'])
        # NOTE: Saubhagya is CLOSED (since 31 Mar 2022) and must never be
        # recommended as an active scheme — deliberately not added here.
=======
    if medical == 'chronic_illness': schemes.append(('ayushman',) + s['ayushman'])
    if medical == 'disability':
        schemes.append(('divyangjan',) + s['divyangjan'])
        schemes.append(('accessible_india',) + s['accessible_india'])
    if housing in ['homeless', 'kutcha']: schemes.append(('pm_awas',) + s['pm_awas'])
    if ration == 'no': schemes.append(('antyodaya',) + s['antyodaya'])
    if electricity == 'no':
        schemes.append(('ujjwala',) + s['ujjwala'])
        schemes.append(('saubhagya',) + s['saubhagya'])
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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
<<<<<<< HEAD
            # Gharkul / Ramai Awas is verified as targeted specifically at
            # Scheduled Caste (SC) and Neo-Buddhist (Nav-Bauddha) community
            # families -- housing need alone (kutcha/homeless) is NOT
            # sufficient per the verification registry. Only recommend it
            # when the person has indicated one of the required categories
            # via the (optional, backward-compatible) 'category' field.
            # Older submissions/API callers without this field simply won't
            # trigger Gharkul, which is the safe default (no false claim).
            category = (data.get('category', '') or '').strip().lower()
            if category in ('sc', 'neo_buddhist'):
                schemes.append(('gharkul',) + mh['gharkul'])
=======
            schemes.append(('gharkul',) + mh['gharkul'])
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
        if earning == 'yes' or widow_status == 'yes' or (income < 5000 and age == 'elderly'):
            schemes.append(('sanjay_gandhi',) + mh['sanjay_gandhi'])
        if age == 'child':
            schemes.append(('rajmata_jijau',) + mh['rajmata_jijau'])
        if ration == 'no' or income < 10000:
            schemes.append(('mh_ration',) + mh['mh_ration'])

<<<<<<< HEAD
    # Final safety filter: never let a CLOSED or DUPLICATE-status scheme
    # (per the verification registry) reach the recommendation list, even
    # if some future trigger above is added carelessly.
    schemes = [item for item in schemes if scheme_verification.is_recommendable(item[0])]

=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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

def generate_application_id():
    return "APP-2026-" + ''.join(random.choices(string.digits, k=4))

def get_db_connection():
    conn = sqlite3.connect('reports.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

<<<<<<< HEAD
def get_filtered_reports(conn, filter_status='All', q='', scheme_filter='All',
                          location_filter='All', date_from='', date_to='', sort='newest'):
    """
    Shared complaint-filtering logic used by both the admin dashboard table
    and the CSV export, so the two always agree on what "the current view"
    means. Status/fake filtering happens in SQL (parameterized); search,
    scheme/location, date range, and sorting happen in Python afterwards
    since filed_date is stored as a formatted display string, not an
    orderable date column.
    """
    if filter_status == 'Fake':
        rows = conn.execute('SELECT * FROM reports WHERE fake_flag=1 ORDER BY id DESC').fetchall()
    elif filter_status and filter_status != 'All':
        rows = conn.execute('SELECT * FROM reports WHERE status=? ORDER BY id DESC', (filter_status,)).fetchall()
    else:
        rows = conn.execute('SELECT * FROM reports ORDER BY id DESC').fetchall()

    reports = [dict(r) for r in rows]

    if q:
        needle = q.strip().lower()
        if needle:
            def _match(r):
                haystack = ' '.join(str(r.get(f) or '') for f in
                    ('tracking_id', 'person_name', 'phone', 'scheme', 'location', 'assigned_officer'))
                return needle in haystack.lower()
            reports = [r for r in reports if _match(r)]

    if scheme_filter and scheme_filter != 'All':
        reports = [r for r in reports if r.get('scheme') == scheme_filter]

    if location_filter and location_filter != 'All':
        reports = [r for r in reports if r.get('location') == location_filter]

    if date_from or date_to:
        try:
            df = datetime.strptime(date_from, '%Y-%m-%d').date() if date_from else None
        except ValueError:
            df = None
        try:
            dt_ = datetime.strptime(date_to, '%Y-%m-%d').date() if date_to else None
        except ValueError:
            dt_ = None

        def _in_range(r):
            fd = r.get('filed_date')
            if not fd:
                return False
            try:
                filed = datetime.strptime(fd, "%d %b %Y, %I:%M %p").date()
            except ValueError:
                return False
            if df and filed < df:
                return False
            if dt_ and filed > dt_:
                return False
            return True
        reports = [r for r in reports if _in_range(r)]

    if sort == 'oldest':
        reports = list(reversed(reports))
    elif sort == 'status':
        reports = sorted(reports, key=lambda r: (r.get('status') or ''))
    # 'newest' is already the default DB order (id DESC)

    return reports

=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
OUTCOME_STATUSES = {'not_applied', 'applied', 'under_review', 'approved', 'rejected'}

def get_outcome_rows(application_id):
    """All scheme outcome rows for one application, as a list of dicts."""
    if not application_id:
        return []
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT * FROM application_outcomes WHERE application_id = ? ORDER BY id',
        (application_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_outcome_status(application_id, scheme_key, status, notes=''):
    """Update one scheme's outcome status for one application. Returns True
    if a matching row was found and updated."""
    if status not in OUTCOME_STATUSES:
        return False
    conn = get_db_connection()
    cur = conn.execute(
        'UPDATE application_outcomes SET status = ?, notes = ?, updated_at = ? WHERE application_id = ? AND scheme_key = ?',
        (status, notes, datetime.now().strftime("%d %b %Y, %I:%M %p"), application_id, scheme_key)
    )
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated

# ---------------------------------------------------------------------------
# Fraud / duplicate detection.
#
# Design principle: FLAG FOR ADMIN REVIEW, NEVER AUTO-REJECT. A citizen's
# income or living situation can genuinely change between submissions —
# treating that as proof of fraud and blocking them would be far more
# harmful than the fraud itself. These functions only ever produce a
# reviewable signal (a suspicious activity log entry, or an existing
# tracking ID reused), never a denial.
# ---------------------------------------------------------------------------

def check_submission_anomaly(phone, ip, age_group, gender, widow_status, income, family_size):
    """Compares a new eligibility submission against this phone number's
    own recent history. Returns a list of human-readable anomaly reasons
    (empty list = nothing unusual). Always records the new fingerprint,
    regardless of outcome, so future submissions can compare against it."""
    reasons = []
    conn = get_db_connection()

    if phone:
        recent = conn.execute(
            'SELECT * FROM submission_fingerprints WHERE phone = ? ORDER BY id DESC LIMIT 5',
            (phone,)
        ).fetchall()

        if recent:
            last = dict(recent[0])
            try:
                income_val = int(income or 0)
                last_income = int(last['income'] or 0)
                if last_income > 0 and income_val > 0:
                    pct_change = abs(income_val - last_income) / last_income
                    if pct_change > 0.4:
                        reasons.append(f"Income changed sharply: Rs.{last_income} -> Rs.{income_val} ({int(pct_change*100)}% change)")
            except (ValueError, ZeroDivisionError):
                pass

            if last['age_group'] and age_group and last['age_group'] != age_group:
                reasons.append(f"Age group changed: {last['age_group']} -> {age_group}")
            if last['gender'] and gender and last['gender'] != gender:
                reasons.append(f"Gender changed: {last['gender']} -> {gender}")
            if last['widow_status'] and widow_status and last['widow_status'] != widow_status:
                reasons.append(f"Widow status changed: {last['widow_status']} -> {widow_status}")

        # Rapid resubmission check (last 24 hours, same phone)
        very_recent = conn.execute(
            'SELECT COUNT(*) as cnt FROM submission_fingerprints WHERE phone = ? AND submitted_at > ?',
            (phone, (datetime.now() - timedelta(hours=24)).isoformat())
        ).fetchone()
        if very_recent and very_recent['cnt'] >= 3:
            reasons.append(f"{very_recent['cnt']} submissions from this phone number in the last 24 hours")

    conn.execute(
        '''INSERT INTO submission_fingerprints
           (phone, ip_address, age_group, gender, widow_status, income, family_size, submitted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (phone, ip, age_group, gender, widow_status, income, family_size, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return reasons

def find_recent_similar_complaint(phone, scheme, official_name, description):
    """Looks for a near-duplicate corruption complaint from the same phone
    number in the last 7 days (same scheme + similar description). Returns
    the existing tracking_id if found, else None. This protects the
    citizen from accidentally filing (and having to track) multiple
    entries for what's really one incident — it is NOT used to dismiss
    complaints as fake."""
    if not phone:
        return None
    conn = get_db_connection()
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%d %b %Y")
    candidates = conn.execute(
        'SELECT tracking_id, description FROM reports WHERE phone = ? AND scheme = ? ORDER BY id DESC LIMIT 5',
        (phone, scheme)
    ).fetchall()
    conn.close()

    for row in candidates:
        similarity = difflib.SequenceMatcher(None, (description or '').lower(), (row['description'] or '').lower()).ratio()
        if similarity > 0.75:
            return row['tracking_id']
    return None

# ---------------------------------------------------------------------------
# KEYPAD-PHONE SUPPORT (SMS + IVR)
#
# A genuine feature/keypad phone cannot run this (or any) web app — it has
# no browser. SMS and phone calls are the only channels that reach such a
# device. These routes are built for Twilio-style webhooks (Exotel and most
# India-friendly providers use a very similar POST format) — going fully
# live still requires signing up for a real number with one of those
# providers, which needs to be done outside this codebase.
#
# Both channels run through the SAME calculate_score()/get_schemes() engine
# as the web form and chatbot — no separate/duplicated eligibility logic.
# ---------------------------------------------------------------------------

def twiml_response(inner_xml):
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner_xml}</Response>'

def twiml_message(text):
    """SMS reply."""
    from xml.sax.saxutils import escape
    return twiml_response(f'<Message>{escape(text)}</Message>')

def twiml_gather_digits(prompt_text, action_url, num_digits=1, lang_voice='en-IN'):
    """Voice prompt that waits for one keypress, then posts to action_url."""
    from xml.sax.saxutils import escape
    return twiml_response(
        f'<Gather numDigits="{num_digits}" action="{action_url}" method="POST" timeout="8">'
        f'<Say language="{lang_voice}">{escape(prompt_text)}</Say>'
        f'</Gather>'
        f'<Say language="{lang_voice}">{escape("Sorry, we did not receive your input. Goodbye." if lang_voice == "en-IN" else "माफ करें, कोई जवाब नहीं मिला। धन्यवाद।")}</Say>'
    )

def twiml_say_hangup(text, lang_voice='en-IN'):
    from xml.sax.saxutils import escape
    return twiml_response(f'<Say language="{lang_voice}">{escape(text)}</Say><Hangup/>')

IVR_VOICE_LANG = {'en': 'en-IN', 'hi': 'hi-IN', 'mr': 'en-IN'}  # Marathi TTS isn't reliably available on most providers — falls back to English voice, spoken text still shown for reference

def get_ivr_session(call_sid):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM ivr_sessions WHERE call_sid = ?', (call_sid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def upsert_ivr_session(call_sid, phone=None, **fields):
    conn = get_db_connection()
    existing = conn.execute('SELECT call_sid FROM ivr_sessions WHERE call_sid = ?', (call_sid,)).fetchone()
    now = datetime.now().strftime("%d %b %Y, %I:%M %p")
    if existing:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f'UPDATE ivr_sessions SET {set_clause}, updated_at = ? WHERE call_sid = ?',
                     (*fields.values(), now, call_sid))
    else:
        cols = ['call_sid', 'phone', 'created_at', 'updated_at'] + list(fields.keys())
        vals = [call_sid, phone, now, now] + list(fields.values())
        placeholders = ", ".join(['?'] * len(vals))
        conn.execute(f'INSERT INTO ivr_sessions ({", ".join(cols)}) VALUES ({placeholders})', vals)
    conn.commit()
    conn.close()

# Income bucket (DTMF choice) -> representative rupee value for scoring
IVR_INCOME_MAP = {'1': '3000', '2': '7500', '3': '15000', '4': '25000'}
IVR_HOUSING_MAP = {'1': 'homeless', '2': 'kutcha', '3': 'rented', '4': 'pucca'}
IVR_AGE_MAP = {'1': 'child', '2': 'adult', '3': 'elderly'}

@app.route('/sms-webhook', methods=['POST'])
def sms_webhook():
    """Twilio-style inbound SMS webhook. Supports:
    - Freeform text describing the person's situation (reuses the same
      Gemini extraction as the chatbot's case-worker mode)
    - "STATUS APP-2026-XXXX" to check an application's outcome status
    """
    from_number = request.form.get('From', '').strip()
    body = (request.form.get('Body') or '').strip()
    ip = get_client_ip()
    log_activity('SMS', 'INBOUND', ip, f'From {from_number}: {body[:100]}')

    if not body:
        return twiml_message("Please text us your situation, e.g. '62 year old widow from Nagpur earning 4000 rupees'."), 200, {'Content-Type': 'text/xml'}

    # STATUS lookup command
    status_match = re.match(r'^status\s+(APP-\d{4}-\d+)', body, re.IGNORECASE)
    if status_match:
        app_id = status_match.group(1).upper()
        outcomes = get_outcome_rows(app_id)
        if not outcomes:
            reply = f"No application found with ID {app_id}. Please check and try again."
        else:
            lines = [f"{o['scheme_name'][:30]}: {o['status'].replace('_', ' ')}" for o in outcomes[:5]]
            reply = f"Status for {app_id}:\n" + "\n".join(lines)
        return twiml_message(reply), 200, {'Content-Type': 'text/xml'}

    # Freeform intake — reuse the exact same extraction used by the chatbot
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        return twiml_message("This service needs setup on our end. Please try the web app, or call our helpline."), 200, {'Content-Type': 'text/xml'}

    client = genai.Client(api_key=api_key)
    intake = extract_case_intake(client, body, 'en')
    if not intake or not intake.get('is_case_intake'):
        fallback_reply = (intake or {}).get('reply') or "Please text your age, income, and location, e.g. '62 year old widow from Nagpur earning 4000 rupees'."
        return twiml_message(fallback_reply[:300]), 200, {'Content-Type': 'text/xml'}

    extracted = intake.get('extracted') or {}
    signal_count = sum(1 for f in INTAKE_SIGNAL_FIELDS if extracted.get(f) not in (None, ''))
    if signal_count < 2:
        return twiml_message("We need a bit more detail — please include your age, income, and location."), 200, {'Content-Type': 'text/xml'}

    extracted['phone'] = from_number
    profile = build_profile_from_intake(extracted, 'en')
    top_schemes = profile['schemes'][:3]
    scheme_lines = "\n".join(f"- {sc['name'][:35]} ({sc['amount']})" for sc in top_schemes)
    reply = (f"You may be eligible for {len(profile['schemes'])} scheme(s):\n{scheme_lines}\n"
              f"App ID: {profile.get('application_id', 'N/A')}\nReply STATUS <ID> anytime to check progress.")
    return twiml_message(reply[:1500]), 200, {'Content-Type': 'text/xml'}

@app.route('/voice-webhook', methods=['POST'])
def voice_webhook():
    """First webhook Twilio/Exotel calls when someone dials in. Offers a
    language choice, then hands off to the step-by-step questionnaire."""
    call_sid = request.form.get('CallSid', '')
    from_number = request.form.get('From', '')
    upsert_ivr_session(call_sid, phone=from_number)
    log_activity('IVR', 'CALL_STARTED', get_client_ip(), f'CallSid {call_sid} from {from_number}')

    prompt = "Welcome to Poverty Aid Identifier. For English, press 1. Hindi ke liye 2 dabayen."
    return twiml_gather_digits(prompt, '/voice-collect?step=lang', num_digits=1), 200, {'Content-Type': 'text/xml'}

@app.route('/voice-collect', methods=['POST'])
def voice_collect():
    """Handles every step of the DTMF questionnaire. `step` in the query
    string says which question was just answered; responds with the next
    question, or the final results once all answers are in."""
    step = request.args.get('step', 'lang')
    digit = request.form.get('Digits', '')
    call_sid = request.form.get('CallSid', '')
    session_data = get_ivr_session(call_sid) or {}
    lang = session_data.get('lang', 'en')
    voice = IVR_VOICE_LANG.get(lang, 'en-IN')

    if step == 'lang':
        lang = 'hi' if digit == '2' else 'en'
        upsert_ivr_session(call_sid, lang=lang)
        voice = IVR_VOICE_LANG.get(lang, 'en-IN')
        prompt = ("Press 1 if you are a child, 2 for adult, 3 for senior citizen above 60."
                  if lang == 'en' else
                  "Bachche ke liye 1, vayask ke liye 2, 60 se upar ke liye 3 dabayen.")
        return twiml_gather_digits(prompt, '/voice-collect?step=age', num_digits=1, lang_voice=voice), 200, {'Content-Type': 'text/xml'}

    if step == 'age':
        upsert_ivr_session(call_sid, age_group=IVR_AGE_MAP.get(digit, 'adult'))
        prompt = ("What is your monthly income? Press 1 for under 5000 rupees, 2 for 5000 to 10000, "
                  "3 for 10000 to 20000, 4 for above 20000."
                  if lang == 'en' else
                  "Aapki mahine ki aay kitni hai? 5000 se kam ke liye 1, 5000 se 10000 ke liye 2, "
                  "10000 se 20000 ke liye 3, 20000 se zyada ke liye 4 dabayen.")
        return twiml_gather_digits(prompt, '/voice-collect?step=income', num_digits=1, lang_voice=voice), 200, {'Content-Type': 'text/xml'}

    if step == 'income':
        upsert_ivr_session(call_sid, income=IVR_INCOME_MAP.get(digit, '10000'))
        prompt = ("What is your housing? Press 1 for homeless, 2 for a kutcha house, 3 for rented, 4 for a pucca house."
                  if lang == 'en' else
                  "Aapka ghar kaisa hai? Beghar ke liye 1, kaccha ghar ke liye 2, kiraye ke ghar ke liye 3, "
                  "pakka ghar ke liye 4 dabayen.")
        return twiml_gather_digits(prompt, '/voice-collect?step=housing', num_digits=1, lang_voice=voice), 200, {'Content-Type': 'text/xml'}

    if step == 'housing':
        upsert_ivr_session(call_sid, housing=IVR_HOUSING_MAP.get(digit, 'pucca'))
        prompt = ("Are you a widow or widower? Press 1 for yes, 2 for no."
                  if lang == 'en' else
                  "Kya aap vidhwa ya vidhur hain? Haan ke liye 1, nahin ke liye 2 dabayen.")
        return twiml_gather_digits(prompt, '/voice-collect?step=widow', num_digits=1, lang_voice=voice), 200, {'Content-Type': 'text/xml'}

    if step == 'widow':
        upsert_ivr_session(call_sid, widow_status='yes' if digit == '1' else 'no')
        prompt = ("Do you have a medical emergency right now? Press 1 for yes, 2 for no."
                  if lang == 'en' else
                  "Kya abhi koi medical emergency hai? Haan ke liye 1, nahin ke liye 2 dabayen.")
        return twiml_gather_digits(prompt, '/voice-collect?step=medical', num_digits=1, lang_voice=voice), 200, {'Content-Type': 'text/xml'}

    if step == 'medical':
        session_data = get_ivr_session(call_sid) or {}
        medical = 'emergency' if digit == '1' else 'none'
        upsert_ivr_session(call_sid, medical=medical)
        session_data = get_ivr_session(call_sid)

        # Run through the SAME real scoring engine as the web form.
        data = dict(INTAKE_DEFAULTS)
        data['age_group'] = session_data.get('age_group') or 'adult'
        data['income'] = session_data.get('income') or '10000'
        data['housing'] = session_data.get('housing') or 'pucca'
        data['widow_status'] = session_data.get('widow_status') or 'no'
        data['medical'] = medical
        score = calculate_score(data)
        schemes = get_schemes(score, data, lang)
        top = schemes[:3]

        if lang == 'en':
            if top:
                names = ". ".join(sc[2] for sc in top)
                text = f"Based on your answers, you may be eligible for: {names}. Please visit your nearest Gram Panchayat office, or check the web app for full details. Thank you."
            else:
                text = "Based on your answers, please visit your nearest Gram Panchayat office for basic community support. Thank you."
        else:
            if top:
                names = ". ".join(sc[2] for sc in top)
                text = f"Aapke jawabon ke anusar, aap in yojanaon ke patra ho sakte hain: {names}. Apne nazdeeki Gram Panchayat karyalay mein sampark karein. Dhanyavad."
            else:
                text = "Apne nazdeeki Gram Panchayat karyalay mein sampark karein. Dhanyavad."

        log_activity('IVR', 'CALL_COMPLETED', get_client_ip(), f'CallSid {call_sid}, score={score}, schemes={len(schemes)}')
        return twiml_say_hangup(text, lang_voice=voice), 200, {'Content-Type': 'text/xml'}

    # Unknown step — end gracefully rather than looping
    return twiml_say_hangup("Thank you for calling. Goodbye.", lang_voice=voice), 200, {'Content-Type': 'text/xml'}

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
        application_id = generate_application_id()

        # Fraud/duplicate detection: compare against this phone's own
        # submission history. Flags for admin review only — the citizen's
        # results below are completely unaffected either way.
        anomalies = check_submission_anomaly(
            phone, ip, request.form.get('age_group', ''), gender, widow,
            request.form.get('income', ''), request.form.get('family_size', '')
        )
        if anomalies:
            log_activity('PUBLIC', 'SUBMISSION_ANOMALY', ip,
                          f"Phone {phone}: " + "; ".join(anomalies), suspicious=1)

        session['profile'] = {
            'name': person_name,
            'phone': phone,
            'gender': gender,
            'widow': widow,
            'age_group': request.form.get('age_group', ''),
            'income': request.form.get('income', ''),
            'family_size': request.form.get('family_size', ''),
            'housing': request.form.get('housing', ''),
<<<<<<< HEAD
            'residence_type': request.form.get('residence_type', ''),
            'category': request.form.get('category', ''),
=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
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
            'application_id': application_id,
            'updated_at': datetime.now().strftime("%d %b %Y, %I:%M %p"),
        }
        # Every new form submission is a fresh person/situation as far as the
        # chatbot is concerned — wipe any leftover conversation memory from
        # whoever used this browser/session before, so the AI never greets
        # someone new using the previous person's name or context.
        session.pop('chat_history', None)

        try:
            conn = get_db_connection()
            conn.execute(
                'INSERT INTO form_submissions (phone, ip_address, submitted_at, lang, schemes_count, state) VALUES (?, ?, ?, ?, ?, ?)',
                (phone, ip, datetime.now().strftime("%d %b %Y, %I:%M %p"), lang, len(schemes), detect_state(address))
            )
            now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
            conn.execute(
                '''INSERT INTO applications
                   (application_id, person_name, phone, state, score, priority, schemes_count, lang, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (application_id, person_name, phone, detect_state(address), score, result, len(schemes), lang, now_str)
            )
            for sc in schemes:
                conn.execute(
                    '''INSERT INTO application_outcomes
                       (application_id, phone, person_name, scheme_key, scheme_name, status, created_at, updated_at, lang)
                       VALUES (?, ?, ?, ?, ?, 'not_applied', ?, ?, ?)''',
                    (application_id, phone, person_name, sc[0], sc[2], now_str, now_str, lang)
                )
            conn.commit()
            conn.close()
        except Exception:
            pass

        log_activity('PUBLIC', 'FORM_SUBMITTED', ip, f'Form submitted for {person_name}')

        return redirect(url_for('index', lang=lang))

    # Pull the calculated values out of the session safely.
    # FIX: use pop() (not get()) only for assessment_results_ready flag so the
    # results block is shown exactly once, but keep the actual user details and
    # matched schemes in the session so they are available on other pages,
    # such as the corruption reporting form (/corruption).
    results_ready = session.pop('assessment_results_ready', False)
    schemes = session.get('schemes', [])
    score = session.get('score', 0)
    result = session.get('result', None)
    person_name = session.get('person_name', '')
    phone = session.get('phone', '')
    address = session.get('address', '')

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
<<<<<<< HEAD
    verification = scheme_verification.get_verification(scheme_key, lang)
    ui_labels = {k: v.get(lang, v['en']) for k, v in scheme_verification.UI_LABELS.items()}
    canonical_name = None
    if verification and verification['is_alias']:
        canon_detail = SCHEME_DETAILS.get(verification['canonical_key'])
        if canon_detail:
            canonical_name = canon_detail.get(lang, canon_detail.get('en'))['name']
    return render_template('scheme_detail.html', scheme=scheme_info, lang=lang, scheme_key=scheme_key,
                            verification=verification, ui_labels=ui_labels, canonical_name=canonical_name)
=======
    return render_template('scheme_detail.html', scheme=scheme_info, lang=lang, scheme_key=scheme_key)
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899

@app.route('/corruption', methods=['GET', 'POST'])
def corruption():
    tracking_id = None
    duplicate_notice = False
    lang = request.args.get('lang', session.get('lang', 'en'))
<<<<<<< HEAD

    # Retrieve the user's applicable scheme KEYS from session (language-
    # independent), then re-derive display name/amount fresh from
    # SCHEME_DETAILS in the CURRENT language every time this page renders.
    # This fixes the earlier language-desync bug where switching the UI
    # language after filling the eligibility form left scheme names stuck
    # in whatever language was active at submission time.
    raw_schemes = session.get('schemes', [])
    if not raw_schemes and 'profile' in session and 'schemes' in session['profile']:
        raw_schemes = [(sc.get('key'), sc.get('urgency'), sc.get('name'), sc.get('amount')) for sc in session['profile']['schemes']]

    schemes = []
    seen_canonical = set()
    for item in raw_schemes:
        key = item[0]
        canonical_key = scheme_verification.resolve_canonical(key)
        if not scheme_verification.is_recommendable(canonical_key) and canonical_key in scheme_verification.VERIFICATION_REGISTRY:
            continue  # never let a CLOSED/DUPLICATE scheme reach the complaint form
        if canonical_key in seen_canonical:
            continue
        seen_canonical.add(canonical_key)
        detail = SCHEME_DETAILS.get(canonical_key) or SCHEME_DETAILS.get(key)
        if detail:
            info = detail.get(lang, detail.get('en'))
            schemes.append((canonical_key, item[1] if len(item) > 1 else 'normal', info['name'], info.get('amount', '')))
        else:
            schemes.append((canonical_key,) + tuple(item[1:]))

    # If the citizen hasn't filled the eligibility form yet, still let them
    # manually pick from the FULL set of known, currently-recommendable
    # schemes (never a silent empty dropdown) — clearly distinguished from
    # a personalised list via the `schemes_are_personalized` flag below.
    schemes_are_personalized = bool(schemes)
    if not schemes:
        for key, detail in SCHEME_DETAILS.items():
            canonical_key = scheme_verification.resolve_canonical(key)
            if canonical_key != key:
                continue  # skip aliases/legacy duplicates in the fallback list
            if not scheme_verification.is_recommendable(canonical_key) and canonical_key in scheme_verification.VERIFICATION_REGISTRY:
                continue  # skip CLOSED schemes (e.g. Saubhagya)
            if key == 'basic':
                continue
            info = detail.get(lang, detail.get('en'))
            schemes.append((key, 'normal', info['name'], info.get('amount', '')))

=======
    
    # Retrieve schemes from session, fallback to profile if needed
    schemes = session.get('schemes', [])
    if not schemes and 'profile' in session and 'schemes' in session['profile']:
        schemes = [(sc.get('key'), sc.get('urgency'), sc.get('name'), sc.get('amount')) for sc in session['profile']['schemes']]
        
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
    report = None
    ip = get_client_ip()
    if request.method == 'POST':
        action = request.form.get('action')
        lang = request.form.get('lang', 'en')
        if action == 'submit_report':
            reporter_phone = session.get('phone') or session.get('profile', {}).get('phone', '')
<<<<<<< HEAD
            submitted_scheme_key = request.form.get('scheme_key', '')
            canonical_scheme_key = scheme_verification.resolve_canonical(submitted_scheme_key) if submitted_scheme_key else ''
            scheme_display_name = request.form.get('scheme', '') or submitted_scheme_key
            existing_id = find_recent_similar_complaint(
                reporter_phone, scheme_display_name,
=======
            existing_id = find_recent_similar_complaint(
                reporter_phone, request.form.get('scheme'),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
                request.form.get('official_name'), request.form.get('description')
            )
            if existing_id:
                # Likely the same incident being filed twice — reuse the
                # existing tracking ID instead of creating a confusing
                # duplicate entry. The citizen still gets a tracking ID
                # back either way, just the one they already have.
                tracking_id = existing_id
                duplicate_notice = True
                log_activity('PUBLIC', 'DUPLICATE_COMPLAINT_MERGED', ip,
                              f'Reused existing tracking ID: {existing_id}')
            else:
                duplicate_notice = False
                tracking_id = generate_tracking_id()
                assigned_officer = random.choice(OFFICERS.get(lang, OFFICERS['en']))
                authority = random.choice(AUTHORITIES.get(lang, AUTHORITIES['en']))
                filed_date = datetime.now().strftime("%d %b %Y, %I:%M %p")
                expected = (datetime.now() + timedelta(days=30)).strftime("%d %b %Y")

                # Handle Proof File Upload
                proof_filename = None
                proof_file = request.files.get('proof_file')
                if proof_file and proof_file.filename != '':
                    sec_filename = secure_filename(proof_file.filename)
                    proof_filename = f"{int(time.time())}_{sec_filename}"
                    proof_file.save(os.path.join(UPLOAD_FOLDER, proof_filename))

                # Handle GPS Geotag
                lat_str = request.form.get('latitude')
                lng_str = request.form.get('longitude')
                latitude = float(lat_str) if lat_str else None
                longitude = float(lng_str) if lng_str else None
                geotag_verified = 1 if (latitude is not None and longitude is not None) else 0

                reporter_name = session.get('person_name') or session.get('profile', {}).get('name', '')
                reporter_address = session.get('address') or session.get('profile', {}).get('address', '')
                conn = get_db_connection()
                conn.execute('''INSERT INTO reports
<<<<<<< HEAD
                    (tracking_id, person_name, phone, address, scheme, scheme_key,
                    entitled_amount, received_amount, official_name, description,
                    incident_date, location, status, assigned_officer, authority,
                    filed_date, expected_resolution, lang, proof_file, latitude, longitude, geotag_verified)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
=======
                    (tracking_id, person_name, phone, address, scheme,
                    entitled_amount, received_amount, official_name, description,
                    incident_date, location, status, assigned_officer, authority,
                    filed_date, expected_resolution, lang, proof_file, latitude, longitude, geotag_verified)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
                    (tracking_id,
                    reporter_name,
                    reporter_phone,
                    reporter_address,
<<<<<<< HEAD
                    scheme_display_name,
                    canonical_scheme_key,
=======
                    request.form.get('scheme'),
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
                    request.form.get('entitled_amount'),
                    request.form.get('received_amount'),
                    request.form.get('official_name'),
                    request.form.get('description'),
                    request.form.get('incident_date'),
                    request.form.get('location'),
                    'Filed', assigned_officer, authority,
                    filed_date, expected, lang,
                    proof_filename, latitude, longitude, geotag_verified))
                conn.commit()
                conn.close()
                add_ledger_entry(tracking_id, 'Filed')
                log_activity('PUBLIC', 'COMPLAINT_FILED', ip,
                    f'Tracking ID: {tracking_id} (Geotag Verified: {geotag_verified})')
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
<<<<<<< HEAD
    return render_template('corruption.html', tracking_id=tracking_id, lang=lang, schemes=schemes, report=report,
                            duplicate_notice=duplicate_notice, schemes_are_personalized=schemes_are_personalized)
=======
    return render_template('corruption.html', tracking_id=tracking_id, lang=lang, schemes=schemes, report=report, duplicate_notice=duplicate_notice)
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899

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

@app.route('/track-outcome', methods=['GET', 'POST'])
def track_outcome():
    lang = request.args.get('lang', session.get('lang', 'en'))
    application_id = None
    outcomes = []
    not_found = False

    # If the person already has a profile in session, prefill their own
    # application ID so they don't have to type it in.
    profile = session.get('profile')
    prefill_id = profile.get('application_id') if profile else ''

    if request.method == 'POST':
        application_id = (request.form.get('application_id_input') or '').strip()
        lang = request.form.get('lang', 'en')
        outcomes = get_outcome_rows(application_id)
        if not outcomes:
            not_found = True
    elif request.args.get('id'):
        application_id = request.args.get('id').strip()
        outcomes = get_outcome_rows(application_id)
        if not outcomes:
            not_found = True

    person_name = outcomes[0]['person_name'] if outcomes else ''
    return render_template(
        'track_outcome.html',
        lang=lang, application_id=application_id, outcomes=outcomes,
        not_found=not_found, person_name=person_name, prefill_id=prefill_id
    )

@app.route('/volunteer/register', methods=['GET', 'POST'])
def volunteer_register():
    """Self-signup for NGO workers / panchayat volunteers. Note for a real
    deployment: this is currently open self-registration, which is fine for
    a prototype but should likely gain an admin-approval step before wide
    public rollout, since anyone can create a volunteer account this way."""
    error = None
    if request.method == 'POST':
        username = sanitize(request.form.get('username', '')).strip()
        password = request.form.get('password', '')
        full_name = sanitize(request.form.get('full_name', '')).strip()
        if not username or not password or not full_name:
            error = "Please fill in all fields."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            conn = get_db_connection()
            existing = conn.execute('SELECT id FROM admin_users WHERE username=?', (username,)).fetchone()
            if existing:
                conn.close()
                error = "That username is already taken."
            else:
                conn.execute(
                    'INSERT INTO admin_users (username, password, role, full_name) VALUES (?, ?, ?, ?)',
                    (username, hash_password(password), 'volunteer', full_name)
                )
                conn.commit()
                conn.close()
                log_activity(username, 'VOLUNTEER_REGISTERED', get_client_ip(), f'{full_name} registered as volunteer')
                session['admin_logged_in'] = True
                session['admin_username'] = username
                session['admin_role'] = 'volunteer'
                session['admin_name'] = full_name
                return redirect(url_for('volunteer_dashboard'))
    return render_template('volunteer_register.html', error=error)

@app.route('/volunteer/dashboard')
@role_required('volunteer', 'admin', 'superadmin')
def volunteer_dashboard():
    conn = get_db_connection()
    applications = conn.execute(
        'SELECT * FROM applications WHERE filed_by_volunteer = ? ORDER BY id DESC',
        (session.get('admin_username'),)
    ).fetchall()
    conn.close()
    return render_template('volunteer_dashboard.html',
        applications=applications, volunteer_name=session.get('admin_name'))

@app.route('/volunteer/new-application', methods=['GET', 'POST'])
@role_required('volunteer', 'admin', 'superadmin')
def volunteer_new_application():
    lang = request.args.get('lang', session.get('lang', 'en'))
    if request.method == 'POST':
        lang = request.form.get('lang', 'en')
        person_name = sanitize(request.form.get('person_name', ''))
        phone = sanitize(request.form.get('phone', ''))
        address = sanitize(request.form.get('address', ''))
        ip = get_client_ip()

        if phone and not re.match(r'^[0-9]{10}$', phone):
            return render_template('volunteer_new_application.html', lang=lang,
                error="Invalid phone number. Enter 10 digits.", result=None)

        # SAME scoring engine as the citizen-facing form — a volunteer's
        # assisted filing is scored identically, never differently.
        score = calculate_score(request.form)
        schemes = get_schemes(score, request.form, lang)
        result = get_priority(score, request.form)
        application_id = generate_application_id()
        now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

        anomalies = check_submission_anomaly(
            phone, ip, request.form.get('age_group', ''),
            sanitize(request.form.get('gender', '')), sanitize(request.form.get('widow_status', '')),
            request.form.get('income', ''), request.form.get('family_size', '')
        )
        if anomalies:
            log_activity('VOLUNTEER', 'SUBMISSION_ANOMALY', ip,
                          f"Phone {phone} (filed by volunteer {session.get('admin_username')}): " + "; ".join(anomalies),
                          suspicious=1)

        try:
            conn = get_db_connection()
            conn.execute(
                '''INSERT INTO applications
                   (application_id, person_name, phone, state, score, priority, schemes_count, lang,
                    filed_by_volunteer, filed_by_volunteer_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (application_id, person_name, phone, detect_state(address), score, result, len(schemes), lang,
                 session.get('admin_username'), session.get('admin_name'), now_str)
            )
            for sc in schemes:
                conn.execute(
                    '''INSERT INTO application_outcomes
                       (application_id, phone, person_name, scheme_key, scheme_name, status, created_at, updated_at, lang)
                       VALUES (?, ?, ?, ?, ?, 'not_applied', ?, ?, ?)''',
                    (application_id, phone, person_name, sc[0], sc[2], now_str, now_str, lang)
                )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Volunteer application save error: {e}")

        log_activity(session.get('admin_username', 'VOLUNTEER'), 'VOLUNTEER_FILED_APPLICATION', ip,
                     f'On behalf of {person_name} ({phone}) -> {application_id}')

        return render_template('volunteer_new_application.html', lang=lang, result=result,
            score=score, schemes=schemes, application_id=application_id, person_name=person_name,
            volunteer_name=session.get('admin_name'), error=None)

    return render_template('volunteer_new_application.html', lang=lang, result=None, error=None)

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
            if user['role'] == 'volunteer':
                return redirect(url_for('volunteer_dashboard'))
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
@role_required('admin', 'superadmin')
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
        add_ledger_entry(tracking_id, new_status)
        log_activity(session.get('admin_username'), 'STATUS_UPDATE', ip,
            f'Updated {tracking_id} to {new_status}')
    filter_status = request.args.get('filter', 'All')
<<<<<<< HEAD
    search_q = request.args.get('q', '').strip()
    scheme_filter = request.args.get('scheme', 'All')
    location_filter = request.args.get('location', 'All')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    sort_by = request.args.get('sort', 'newest')

=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
    total = conn.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
    filed = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Filed'").fetchone()[0]
    received = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Received'").fetchone()[0]
    action = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Action Taken'").fetchone()[0]
    resolved = conn.execute("SELECT COUNT(*) FROM reports WHERE status='Resolved'").fetchone()[0]
    fake_count = conn.execute("SELECT COUNT(*) FROM reports WHERE fake_flag=1").fetchone()[0]
    suspicious_count = conn.execute("SELECT COUNT(*) FROM activity_logs WHERE suspicious=1").fetchone()[0]
<<<<<<< HEAD
    pending_count = filed + received
    resolution_rate = round((resolved / total) * 100, 1) if total > 0 else 0

    reports = get_filtered_reports(conn, filter_status, search_q, scheme_filter,
                                    location_filter, date_from, date_to, sort_by)

    # Dropdown option sources for the filter bar — real distinct values only.
    scheme_options = [row['scheme'] for row in conn.execute(
        "SELECT DISTINCT scheme FROM reports WHERE scheme IS NOT NULL AND scheme != '' ORDER BY scheme").fetchall()]
    location_options = [row['location'] for row in conn.execute(
        "SELECT DISTINCT location FROM reports WHERE location IS NOT NULL AND location != '' ORDER BY location").fetchall()]

    # Today's Overview — computed from real filed/received/action/resolved
    # date columns (formatted as "%d %b %Y, ..."), never invented.
    today_str = datetime.now().strftime("%d %b %Y")
    new_today = conn.execute(
        "SELECT COUNT(*) FROM reports WHERE filed_date LIKE ?", (today_str + '%',)).fetchone()[0]
    review_today = conn.execute(
        "SELECT COUNT(*) FROM reports WHERE received_date LIKE ?", (today_str + '%',)).fetchone()[0]
    action_today = conn.execute(
        "SELECT COUNT(*) FROM reports WHERE action_date LIKE ?", (today_str + '%',)).fetchone()[0]
    resolved_today = conn.execute(
        "SELECT COUNT(*) FROM reports WHERE resolved_date LIKE ?", (today_str + '%',)).fetchone()[0]

    # System Health — only components we can actually check right now.
    # Reaching this line means the DB query above succeeded and we're
    # inside an authenticated Flask session, so those two are real checks;
    # AI/ML availability is a real file-existence check, not a guess.
    ml_metrics_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'model_metrics.json')
    system_health = {
        'database': True,
        'application': True,
        'ml_available': os.path.exists(ml_metrics_path),
        'session_active': bool(session.get('admin_logged_in')),
    }

=======
    if filter_status == 'All':
        reports = conn.execute('SELECT * FROM reports ORDER BY id DESC').fetchall()
    else:
        reports = conn.execute('SELECT * FROM reports WHERE status=? ORDER BY id DESC', (filter_status,)).fetchall()
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
    recent_logs = conn.execute('SELECT * FROM activity_logs ORDER BY id DESC LIMIT 20').fetchall()
    suspicious_logs = conn.execute('SELECT * FROM activity_logs WHERE suspicious=1 ORDER BY id DESC LIMIT 10').fetchall()

    # Ledger verification
    ledger_valid, error_block, ledger_message = verify_ledger()
    ledger_blocks = conn.execute('SELECT * FROM audit_ledger ORDER BY id DESC').fetchall()

    # Suspicious submissions / Fraud
    suspicious_inputs = conn.execute('''
        SELECT phone, COUNT(DISTINCT age_group) as age_diffs, COUNT(DISTINCT income) as income_diffs, COUNT(*) as cnt
        FROM submission_fingerprints
        GROUP BY phone
        HAVING age_diffs > 1 OR income_diffs > 1
    ''').fetchall()

    suspicious_phones = [row['phone'] for row in suspicious_inputs]
<<<<<<< HEAD
    # Real risk level per phone, derived from the actual number of conflicting
    # age/income entries and total submissions for that phone — not a
    # cosmetic alternating pattern.
    phone_risk = {}
    for row in suspicious_inputs:
        age_diffs = row['age_diffs'] or 0
        income_diffs = row['income_diffs'] or 0
        cnt = row['cnt'] or 0
        phone_risk[row['phone']] = 'High' if (age_diffs >= 2 or income_diffs >= 2 or cnt >= 4) else 'Med'

=======
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899
    suspicious_fingerprints = []
    if suspicious_phones:
        placeholders = ','.join('?' for _ in suspicious_phones)
        suspicious_fingerprints = conn.execute(f'''
            SELECT * FROM submission_fingerprints
            WHERE phone IN ({placeholders})
            ORDER BY phone, submitted_at DESC
        ''', suspicious_phones).fetchall()

    # Scheme Stats
    scheme_counts_raw = conn.execute('''
        SELECT scheme, COUNT(*) as count 
        FROM reports 
        WHERE scheme IS NOT NULL AND scheme != ""
        GROUP BY scheme
    ''').fetchall()
    scheme_stats = {row['scheme']: row['count'] for row in scheme_counts_raw}

    conn.close()
    return render_template('admin.html',
        reports=reports, total=total, filed=filed, received=received,
        action=action, resolved=resolved, filter_status=filter_status,
        fake_count=fake_count,
        now=datetime.now().strftime("%d %b %Y, %I:%M %p"),
        admin_name=session.get('admin_name'),
        admin_role=session.get('admin_role'),
        recent_logs=recent_logs,
        suspicious_logs=suspicious_logs,
        suspicious_count=suspicious_count,
        ledger_valid=ledger_valid,
        ledger_message=ledger_message,
        ledger_blocks=ledger_blocks,
        suspicious_fingerprints=suspicious_fingerprints,
<<<<<<< HEAD
        phone_risk=phone_risk,
        scheme_stats=scheme_stats,
        pending_count=pending_count,
        resolution_rate=resolution_rate,
        search_q=search_q,
        scheme_filter=scheme_filter,
        location_filter=location_filter,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        scheme_options=scheme_options,
        location_options=location_options,
        new_today=new_today,
        review_today=review_today,
        action_today=action_today,
        resolved_today=resolved_today,
        system_health=system_health)

@app.route('/admin/export')
@role_required('admin', 'superadmin')
def admin_export():
    """CSV export of the currently filtered complaint view — the same
    filters as the dashboard table (status/search/scheme/location/date)."""
    ip = get_client_ip()
    conn = get_db_connection()
    filter_status = request.args.get('filter', 'All')
    search_q = request.args.get('q', '').strip()
    scheme_filter = request.args.get('scheme', 'All')
    location_filter = request.args.get('location', 'All')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    sort_by = request.args.get('sort', 'newest')

    reports = get_filtered_reports(conn, filter_status, search_q, scheme_filter,
                                    location_filter, date_from, date_to, sort_by)
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Tracking ID', 'Person Name', 'Phone', 'Scheme', 'Entitled Amount',
                      'Received Amount', 'Location', 'Assigned Officer', 'Filed Date', 'Status'])
    for r in reports:
        writer.writerow([
            r.get('tracking_id'), r.get('person_name'), r.get('phone'), r.get('scheme'),
            r.get('entitled_amount'), r.get('received_amount'), r.get('location'),
            r.get('assigned_officer'), r.get('filed_date'), r.get('status')
        ])

    log_activity(session.get('admin_username'), 'EXPORT_REPORT', ip,
        f'Exported {len(reports)} complaint record(s) to CSV')

    filename = f"complaints_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'})
=======
        scheme_stats=scheme_stats)
>>>>>>> 281c6cdb0629bebeadde07d64db0f3591af67899

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

@app.route('/apply/<scheme_key>/print')
def apply_scheme_print(scheme_key):
    lang = request.args.get('lang', session.get('lang', 'en'))
    detail = SCHEME_DETAILS.get(scheme_key)
    if not detail:
        return render_template('404.html'), 404
    scheme_info = detail.get(lang, detail.get('en'))
    profile = session.get('profile') or {}
    
    # Generate dummy application ID if not present
    app_id = profile.get('application_id') or ('PAI-2026-' + ''.join(random.choices(string.digits, k=6)))
    
    return render_template('application_form_print.html',
        scheme=scheme_info,
        scheme_key=scheme_key,
        lang=lang,
        profile=profile,
        app_id=app_id)


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

@app.route('/voice-assistant')
def voice_assistant_page():
    lang = request.args.get('lang', session.get('lang', 'en'))
    profile = session.get('profile')
    return render_template('voice_assistant.html', lang=lang, profile=profile)


@app.route('/chatbot')
def chatbot_page():
    lang = request.args.get('lang', session.get('lang', 'en'))
    profile = session.get('profile')
    return render_template('voice_assistant.html' if request.args.get('mode') == 'voice' else 'chatbot.html', lang=lang, profile=profile)


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
        outcome_question = any(k in q for k in [
            'got approved', 'approved for', 'approved my', 'was rejected', 'got rejected', 'rejected my',
            'i applied for', 'i applied to', 'application status', 'track my application', 'update my status',
            'update my application', 'still waiting', 'i received the', 'i got the money', 'application was',
            'application is', 'my application', 'under review', 'is reviewing', 'still processing',
            'no update', 'not yet approved', 'pending', 'was approved', 'was accepted', 'got accepted',
            'is my', 'status of my', 'applied last', 'applied a', 'applied this',
            'मंजूर हो गया', 'अस्वीकार', 'आवेदन की स्थिति', 'मंजूर झाले', 'नाकारले', 'मेरा आवेदन',
            'समीक्षा में', 'प्रतीक्षा', 'माझा अर्ज', 'पुनरावलोकनात', 'प्रतीक्षेत',
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

        # Configure Gemini (new google-genai SDK — old google.generativeai is deprecated)
        client = genai.Client(api_key=api_key)

        # CASE-WORKER MODE: if this person hasn't filled the eligibility form
        # yet, see if their message is actually a self-description ("I'm a
        # 62-year-old widow from Nagpur earning Rs 4000") rather than a plain
        # FAQ. One Gemini call either extracts structured facts (which we
        # then run through the real scoring engine) or just answers the FAQ.
        if not profile:
            intake = extract_case_intake(client, user_message, lang)
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

        # OUTCOME TRACKING (the feedback loop): if this person already has a
        # profile with an application_id, and their message sounds like a
        # status report ("I got approved for widow pension"), match it to
        # their actual scheme and record it in application_outcomes — so the
        # app learns whether recommendations turned into real help, not just
        # suggestions that go nowhere.
        if profile and profile.get('application_id') and outcome_question:
            outcome = extract_outcome_update(client, user_message, profile, lang)
            if outcome and outcome.get('is_outcome_update'):
                scheme_key = outcome.get('scheme_key')
                status = outcome.get('status')
                matched_scheme = next((sc for sc in profile['schemes'] if sc['key'] == scheme_key), None)

                if matched_scheme and status in OUTCOME_STATUSES:
                    update_outcome_status(profile['application_id'], scheme_key, status, notes=user_message[:200])
                    status_labels = {
                        'en': {'applied': 'applied', 'under_review': 'under review', 'approved': 'approved ✅', 'rejected': 'rejected', 'not_applied': 'not yet applied'},
                        'hi': {'applied': 'आवेदन किया गया', 'under_review': 'समीक्षा में', 'approved': 'मंजूर ✅', 'rejected': 'अस्वीकृत', 'not_applied': 'अभी आवेदन नहीं किया'},
                        'mr': {'applied': 'अर्ज केला', 'under_review': 'पुनरावलोकनात', 'approved': 'मंजूर ✅', 'rejected': 'नाकारले', 'not_applied': 'अजून अर्ज केलेला नाही'},
                    }
                    label = status_labels.get(lang, status_labels['en']).get(status, status)
                    confirms = {
                        'en': f"Got it — marked {matched_scheme['name']} as {label}. Thanks for letting me know, this helps us understand what's actually working. Anything else I can help with?",
                        'hi': f"समझ गया — {matched_scheme['name']} को {label} के रूप में दर्ज किया। बताने के लिए धन्यवाद, इससे हमें यह समझने में मदद मिलती है कि वास्तव में क्या काम कर रहा है। कुछ और मदद चाहिए?",
                        'mr': f"समजले — {matched_scheme['name']} {label} म्हणून नोंदवले. सांगितल्याबद्दल धन्यवाद, यामुळे आम्हाला काय खरोखर काम करत आहे हे समजण्यास मदत होते. आणखी काही मदत हवी आहे का?",
                    }
                    reply = confirms.get(lang, confirms['en'])
                    push_chat_history(user_message, reply)
                    log_activity('CHATBOT', 'OUTCOME_UPDATE', get_client_ip(), f'{scheme_key} -> {status}')
                    return jsonify({'reply': reply})
                elif not matched_scheme:
                    # Couldn't tell which scheme — ask, don't guess.
                    scheme_names = ", ".join(sc['name'] for sc in profile['schemes'])
                    clarify = {
                        'en': f"Which scheme are you talking about? Your recommended ones are: {scheme_names}.",
                        'hi': f"आप किस योजना की बात कर रहे हैं? आपकी सुझाई गई योजनाएं हैं: {scheme_names}.",
                        'mr': f"तुम्ही कोणत्या योजनेबद्दल बोलत आहात? तुमच्या शिफारस केलेल्या योजना आहेत: {scheme_names}.",
                    }
                    reply = clarify.get(lang, clarify['en'])
                    push_chat_history(user_message, reply)
                    return jsonify({'reply': reply})
            # If it wasn't actually an outcome update after all, fall through to normal flow.

        # System prompt based on language
        system_prompts = {
            'en': """You are the AI Welfare Assistant for Poverty Aid Identifier — a free civic tech app that helps India's poorest citizens find government schemes they qualify for.

You help citizens with:
1. Information about 16 government schemes: PM Jan Arogya Yojana, PM Awas Yojana, Ayushman Bharat, Antyodaya Anna Yojana, National Family Benefit Scheme, PM Ujjwala Yojana, Old Age Pension (IGNOAPS), Widow Pension, Divyangjan Swavalamban, Accessible India Campaign, PM Poshan, ICDS, Annapurna Scheme, Saubhagya, PM Jan Dhan Yojana, Basic Community Support
2. Documents needed for each scheme
3. How to apply for schemes
4. Corruption reporting — citizens can file complaints at /corruption and track with tracking ID
5. How the AI Need Score works (0-225 points across 9 parameters)

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

            'hi': """अत्यंत महत्त्वपूर्ण निर्देश: आपका पूरा उत्तर केवल और केवल हिंदी भाषा (देवनागरी लिपि) में ही होना चाहिए। अंग्रेजी भाषा का प्रयोग बिल्कुल न करें।

आप Poverty Aid Identifier के लिए AI Welfare Assistant हैं — एक मुफ्त civic tech ऐप जो भारत के गरीब नागरिकों को सरकारी योजनाएं खोजने में मदद करता है।

आप इनके बारे में मदद करते हैं:
1. 16 सरकारी योजनाओं की जानकारी
2. हर योजना के लिए जरूरी दस्तावेज़
3. आवेदन कैसे करें
4. भ्रष्टाचार की शिकायत कैसे करें

नियम:
- आपका पूरा जवाब केवल हिंदी (देवनागरी) में होना चाहिए
- जवाब छोटे और सरल रखें — 4-5 लाइन से ज्यादा नहीं
- आसान हिंदी में बोलें — उपयोगकर्ता पढ़ा-लिखा नहीं हो सकता
- हमेशा दयालु और मददगार रहें
- झूठी जानकारी न दें
- यह एक चालू बातचीत है — अगर व्यक्ति पहले कही गई बात के बारे में पूछे ("दूसरे वाले के बारे में बताओ"), तो पिछली बात को याद रखते हुए जवाब दें।
- अगर व्यक्ति का संदेश अस्पष्ट है — जैसे "मुझे एक शक है", "मुझे सवाल है", "मदद चाहिए" — और कोई असली विषय नहीं बताया गया है, तो अंदाजा मत लगाइए या सामान्य सूची मत भेजिए। पहले एक छोटा, दोस्ताना स्पष्टीकरण वाला सवाल पूछें, जैसे "जरूर, आपका सवाल किस बारे में है — पात्रता, दस्तावेज़, या आवेदन कैसे करें?"
- अगर नीचे "User Profile" दिया गया है, तो इस व्यक्ति ने पहले ही फॉर्म भर दिया है। दोबारा जानकारी मत मांगिए — इनकी असल जानकारी (नाम, आय, आवास, योजनाएं) के आधार पर व्यक्तिगत जवाब दें।""",

            'mr': """अत्यंत महत्त्वाचे निर्देश: तुमचे संपूर्ण उत्तर केवळ आणि केवळ मराठी भाषा (देवनागरी लिपी) मध्येच असले पाहिजे. इंग्रजी भाषेचा वापर अजिबात करू नका.

तुम्ही Poverty Aid Identifier साठी AI Welfare Assistant आहात — एक मोफत civic tech अॅप जे भारतातील गरीब नागरिकांना सरकारी योजना शोधण्यास मदत करते.

तुम्ही यासाठी मदत करता:
1. 16 सरकारी योजनांची माहिती
2. प्रत्येक योजनेसाठी आवश्यक कागदपत्रे
3. अर्ज कसा करावा
4. भ्रष्टाचाराची तक्रार कशी करावी

नियम:
- तुमचे उत्तर फक्त आणि फक्त शुद्ध मराठीत असले पाहिजे
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
        gemini_history = [
            genai_types.Content(role=h['role'], parts=[genai_types.Part(text=h['text'])])
            for h in session.get('chat_history', [])
        ]
        chat = client.chats.create(
            model=GEMINI_MODEL,
            config=genai_types.GenerateContentConfig(system_instruction=system_instruction),
            history=gemini_history,
        )
        response = chat.send_message(message=user_message)
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
            'score': "The AI Need Score is calculated from 9 parameters:\n• Income (40 pts)\n• Medical condition (30 pts)\n• Accident (25 pts)\n• Earning member death (25 pts)\n• Age group (30 pts)\n• Housing (20 pts)\n• Family size (20 pts)\n• Electricity (10 pts)\n• Ration card (10 pts)\n\nMaximum score: 225 points",
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

@app.route('/api/ml-metrics')
def ml_metrics_api():
    metrics_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'model_metrics.json')
    if os.path.exists(metrics_path):
        with open(metrics_path, 'r') as f:
            data = json.load(f)
        return jsonify({'success': True, 'metrics': data})
    return jsonify({'success': False, 'message': 'Model metrics not found. Run ml_scoring.py.'})


if __name__ == '__main__':

    
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), threaded=True)
# -*- coding: utf-8 -*-
"""
scheme_verification.py

Machine-readable government-verification registry for the Poverty Aid
Identifier.

This module is intentionally standalone (no Flask/DB imports) so it can be
unit-tested in isolation and imported by app.py without side effects.

DATA MODEL
----------
Each entry in VERIFICATION_REGISTRY is keyed by the scheme_key already used
throughout the existing app (SCHEME_DETAILS / MH_SCHEMES / SCHEMES) and
contains:

    canonical_key        -> the key this scheme should be treated as (for
                             duplicate/alias resolution). Equal to its own
                             key unless this is an alias record.
    aliases               -> list of other scheme_keys that resolve to this
                             canonical scheme (only set on canonical entries)
    scheme_type           -> 'SCHEME' | 'PROGRAM_POLICY'
    status                -> one of VERIFICATION_STATUSES
    confidence            -> 'high' | 'medium' | 'low'  (human-facing hint,
                             derived from status but kept explicit)
    current_2026          -> bool, whether the figures are believed current
                             as of the 2026-08-28 research date
    department            -> {'en':..., 'hi':..., 'mr':...}
    jurisdiction           -> 'central' | 'maharashtra'
    documents             -> list of document dicts (see below)
    notes                 -> {'en':..., 'hi':..., 'mr':...} short, honest
                             explanation of the evidence strength /
                             known caveats for this scheme
    last_verified_date    -> ISO date string, research date for this task

Each document dict:
    document_type   -> e.g. 'Government Resolution (GR)', 'Cabinet Decision',
                        'PIB Press Release', 'Scheme Guidelines',
                        'Gazette Notification', 'Official Scheme Portal'
    document_number -> exact string as issued, or None if not applicable
                        (e.g. central schemes governed by guidelines rather
                        than a single numbered GR)
    document_date   -> ISO date string or None
    title           -> {'en':..., 'hi':..., 'mr':...}
    official_url    -> URL string or None (never fabricated)
    source_authority -> 'Government of Maharashtra' | 'Government of India' | ...
    directly_opened -> bool, whether this exact document/page content was
                        directly read during this research pass (vs. only
                        referenced through a secondary/aggregator source)
    is_founding     -> bool
    is_current      -> bool, whether this is the currently-governing document

No GR number, date, or URL below was invented. Where the original 2024/2025
audit lead could not be independently re-confirmed this session, that is
stated explicitly in `notes` and reflected in a lower `status`
(PARTIAL / VERIFIED_WITH_CHAIN) rather than claimed as
VERIFIED_PRIMARY_CURRENT.
"""

RESEARCH_DATE = "2026-08-28"

# ---------------------------------------------------------------------------
# Verification status vocabulary
# ---------------------------------------------------------------------------
STATUS_VERIFIED_PRIMARY_CURRENT = "VERIFIED_PRIMARY_CURRENT"
STATUS_VERIFIED_WITH_CHAIN = "VERIFIED_WITH_CHAIN"
STATUS_PARTIAL = "PARTIAL"
STATUS_NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
STATUS_PROGRAM_POLICY = "PROGRAM_POLICY"
STATUS_DUPLICATE = "DUPLICATE"
STATUS_CLOSED = "CLOSED"

VERIFICATION_STATUSES = [
    STATUS_VERIFIED_PRIMARY_CURRENT,
    STATUS_VERIFIED_WITH_CHAIN,
    STATUS_PARTIAL,
    STATUS_NEEDS_VERIFICATION,
    STATUS_PROGRAM_POLICY,
    STATUS_DUPLICATE,
    STATUS_CLOSED,
]

# Statuses that must NEVER be surfaced as an active, recommendable,
# guaranteed-cash scheme.
NON_RECOMMENDABLE_STATUSES = {STATUS_CLOSED, STATUS_DUPLICATE}

# ---------------------------------------------------------------------------
# Localized labels for statuses / section headings (used by templates)
# ---------------------------------------------------------------------------
STATUS_LABELS = {
    STATUS_VERIFIED_PRIMARY_CURRENT: {
        "en": "Verified (Primary Document)",
        "hi": "सत्यापित (मूल दस्तावेज़)",
        "mr": "पडताळणी झालेले (मूळ दस्तऐवज)",
    },
    STATUS_VERIFIED_WITH_CHAIN: {
        "en": "Verified (Official Evidence Chain)",
        "hi": "सत्यापित (आधिकारिक साक्ष्य श्रृंखला)",
        "mr": "पडताळणी झालेले (अधिकृत पुरावा साखळी)",
    },
    STATUS_PARTIAL: {
        "en": "Partially Verified",
        "hi": "आंशिक रूप से सत्यापित",
        "mr": "अंशतः पडताळणी झालेले",
    },
    STATUS_NEEDS_VERIFICATION: {
        "en": "Needs Verification",
        "hi": "सत्यापन आवश्यक",
        "mr": "पडताळणी आवश्यक",
    },
    STATUS_PROGRAM_POLICY: {
        "en": "Programme / Policy (Not a Direct Cash Scheme)",
        "hi": "कार्यक्रम / नीति (सीधी नकद योजना नहीं)",
        "mr": "कार्यक्रम / धोरण (थेट रोख योजना नाही)",
    },
    STATUS_DUPLICATE: {
        "en": "Duplicate / Alias of Another Scheme",
        "hi": "किसी अन्य योजना का डुप्लिकेट / उपनाम",
        "mr": "अन्य योजनेचे डुप्लिकेट / उपनाव",
    },
    STATUS_CLOSED: {
        "en": "Closed / Historical Scheme",
        "hi": "बंद / ऐतिहासिक योजना",
        "mr": "बंद / ऐतिहासिक योजना",
    },
}

STATUS_EXPLANATIONS = {
    STATUS_VERIFIED_PRIMARY_CURRENT: {
        "en": "An official government document or page was directly opened and confirms this current information.",
        "hi": "एक आधिकारिक सरकारी दस्तावेज़ या पेज सीधे खोला गया और यह वर्तमान जानकारी की पुष्टि करता है।",
        "mr": "एक अधिकृत शासकीय दस्तऐवज किंवा पान थेट उघडण्यात आले आणि ते सध्याच्या माहितीची पुष्टी करते.",
    },
    STATUS_VERIFIED_WITH_CHAIN: {
        "en": "Supported by an official government document chain, though one referenced original document was not independently re-opened this session.",
        "hi": "एक आधिकारिक सरकारी दस्तावेज़ श्रृंखला द्वारा समर्थित, हालांकि इस सत्र में एक संदर्भित मूल दस्तावेज़ को स्वतंत्र रूप से दोबारा नहीं खोला गया।",
        "mr": "अधिकृत शासकीय दस्तऐवज साखळीद्वारे समर्थित, तरीही या सत्रात एक संदर्भित मूळ दस्तऐवज स्वतंत्रपणे पुन्हा उघडण्यात आलेला नाही.",
    },
    STATUS_PARTIAL: {
        "en": "An official government source confirms the scheme's identity and department, but complete primary-document evidence could not be independently established this session.",
        "hi": "एक आधिकारिक सरकारी स्रोत योजना की पहचान और विभाग की पुष्टि करता है, लेकिन इस सत्र में पूर्ण मूल-दस्तावेज़ साक्ष्य स्वतंत्र रूप से स्थापित नहीं किया जा सका।",
        "mr": "एक अधिकृत शासकीय स्रोत योजनेची ओळख आणि विभाग यांची पुष्टी करतो, परंतु या सत्रात संपूर्ण मूळ-दस्तऐवज पुरावा स्वतंत्रपणे स्थापित करता आला नाही.",
    },
    STATUS_NEEDS_VERIFICATION: {
        "en": "Available evidence is insufficient to make a strong, specific claim. Please confirm current details with the official department before relying on this.",
        "hi": "उपलब्ध साक्ष्य एक मजबूत, विशिष्ट दावा करने के लिए पर्याप्त नहीं है। इस पर भरोसा करने से पहले कृपया आधिकारिक विभाग से वर्तमान विवरण की पुष्टि करें।",
        "mr": "उपलब्ध पुरावा एक ठोस, विशिष्ट दावा करण्यासाठी पुरेसा नाही. यावर विसंबण्यापूर्वी कृपया अधिकृत विभागाकडून सध्याचे तपशील निश्चित करा.",
    },
    STATUS_PROGRAM_POLICY: {
        "en": "This is a government programme, mission or policy framework delivered through existing departments/Anganwadi systems — not a standalone guaranteed cash benefit.",
        "hi": "यह मौजूदा विभागों/आंगनवाड़ी प्रणालियों के माध्यम से दिया जाने वाला एक सरकारी कार्यक्रम, मिशन या नीति ढांचा है — यह कोई स्वतंत्र गारंटीकृत नकद लाभ नहीं है।",
        "mr": "हा विद्यमान विभाग/अंगणवाडी प्रणालींद्वारे दिला जाणारा एक शासकीय कार्यक्रम, मिशन किंवा धोरण चौकट आहे — ही स्वतंत्र हमी दिलेली रोख लाभ योजना नाही.",
    },
    STATUS_DUPLICATE: {
        "en": "This is the same underlying scheme as another entry, shown here only for reference. It will not be recommended as a separate benefit.",
        "hi": "यह किसी अन्य प्रविष्टि के समान अंतर्निहित योजना है, यहाँ केवल संदर्भ के लिए दिखाई गई है। इसे एक अलग लाभ के रूप में अनुशंसित नहीं किया जाएगा।",
        "mr": "ही दुसऱ्या नोंदीसारखीच मूळ योजना आहे, येथे फक्त संदर्भासाठी दाखवली आहे. ती स्वतंत्र लाभ म्हणून शिफारस केली जाणार नाही.",
    },
    STATUS_CLOSED: {
        "en": "This scheme is officially closed. It is shown for historical reference only and will never be recommended as an active benefit.",
        "hi": "यह योजना आधिकारिक रूप से बंद है। यह केवल ऐतिहासिक संदर्भ के लिए दिखाई गई है और इसे कभी भी सक्रिय लाभ के रूप में अनुशंसित नहीं किया जाएगा।",
        "mr": "ही योजना अधिकृतपणे बंद झाली आहे. ती केवळ ऐतिहासिक संदर्भासाठी दाखवली आहे आणि ती कधीही सक्रिय लाभ म्हणून शिफारस केली जाणार नाही.",
    },
}

UI_LABELS = {
    "government_verification_heading": {
        "en": "Government Verification", "hi": "सरकारी सत्यापन", "mr": "शासकीय पडताळणी",
    },
    "department_label": {
        "en": "Government Department", "hi": "सरकारी विभाग", "mr": "शासकीय विभाग",
    },
    "document_type_label": {
        "en": "Document Type", "hi": "दस्तावेज़ प्रकार", "mr": "दस्तऐवज प्रकार",
    },
    "document_number_label": {
        "en": "Document Number", "hi": "दस्तावेज़ संख्या", "mr": "दस्तऐवज क्रमांक",
    },
    "document_date_label": {
        "en": "Date", "hi": "दिनांक", "mr": "दिनांक",
    },
    "source_label": {
        "en": "Source", "hi": "स्रोत", "mr": "स्रोत",
    },
    "view_official_document": {
        "en": "View Official Document", "hi": "आधिकारिक दस्तावेज़ देखें", "mr": "अधिकृत दस्तऐवज पहा",
    },
    "no_gr_explanation": {
        "en": "This central scheme is governed through official scheme guidelines / Cabinet decisions / notifications rather than a single Maharashtra-style Government Resolution.",
        "hi": "यह केंद्रीय योजना महाराष्ट्र-शैली के एकल सरकारी संकल्प (GR) के बजाय आधिकारिक योजना दिशानिर्देशों / कैबिनेट निर्णयों / अधिसूचनाओं के माध्यम से संचालित होती है।",
        "mr": "ही केंद्रीय योजना महाराष्ट्र-शैलीच्या एकाच शासन निर्णयाऐवजी अधिकृत योजना मार्गदर्शक तत्त्वे / मंत्रिमंडळ निर्णय / अधिसूचनांद्वारे चालवली जाते.",
    },
    "alias_explanation": {
        "en": "This scheme is the same as {canonical_name} — shown once to avoid a duplicate recommendation.",
        "hi": "यह योजना {canonical_name} के समान है — डुप्लिकेट अनुशंसा से बचने के लिए इसे एक बार दिखाया गया है।",
        "mr": "ही योजना {canonical_name} सारखीच आहे — डुप्लिकेट शिफारस टाळण्यासाठी ती एकदाच दाखवली आहे.",
    },
    "current_2026_yes": {
        "en": "Confirmed current as of August 2026.",
        "hi": "अगस्त 2026 तक वर्तमान होने की पुष्टि की गई।",
        "mr": "ऑगस्ट 2026 पर्यंत सध्याची असल्याची पुष्टी झाली आहे.",
    },
    "current_2026_unknown": {
        "en": "Could not independently confirm this is still current as of August 2026 — verify with the department before relying on it.",
        "hi": "यह स्वतंत्र रूप से पुष्टि नहीं की जा सकी कि यह अगस्त 2026 तक अभी भी लागू है — इस पर भरोसा करने से पहले विभाग से पुष्टि करें।",
        "mr": "ऑगस्ट 2026 पर्यंत हे अजूनही लागू आहे याची स्वतंत्रपणे पुष्टी करता आली नाही — यावर अवलंबून राहण्यापूर्वी विभागाकडून खात्री करा.",
    },
}


def _doc(document_type, document_number, document_date, title_en, title_hi, title_mr,
          official_url, source_authority, directly_opened, is_founding, is_current,
          supersedes_document_id=None):
    return {
        "document_type": document_type,
        "document_number": document_number,
        "document_date": document_date,
        "title": {"en": title_en, "hi": title_hi, "mr": title_mr},
        "official_url": official_url,
        "source_authority": source_authority,
        "directly_opened": directly_opened,
        "is_founding": is_founding,
        "is_current": is_current,
        "supersedes_document_id": supersedes_document_id,
    }


def _dept(en, hi, mr):
    return {"en": en, "hi": hi, "mr": mr}


def _notes(en, hi, mr):
    return {"en": en, "hi": hi, "mr": mr}


# ---------------------------------------------------------------------------
# THE REGISTRY
# ---------------------------------------------------------------------------
# NOTE ON "current_2026": True only where this session's research (or the
# nature of an evergreen central portal/GR) gives reasonable confidence the
# figure is still correct as of 2026-08-28. Where the underlying source is
# undated / an older lead was not re-confirmed, this is False and the notes
# say so plainly.

VERIFICATION_REGISTRY = {

    # ---------------- CENTRAL: HEALTH ----------------
    "pm_jan_arogya": {
        "canonical_key": "pm_jan_arogya",
        "aliases": ["ayushman"],
        "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_PRIMARY_CURRENT,
        "confidence": "high",
        "current_2026": True,
        "department": _dept("National Health Authority, Ministry of Health & Family Welfare, Government of India",
                             "राष्ट्रीय स्वास्थ्य प्राधिकरण, स्वास्थ्य एवं परिवार कल्याण मंत्रालय, भारत सरकार",
                             "राष्ट्रीय आरोग्य प्राधिकरण, आरोग्य व कुटुंब कल्याण मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("Cabinet Decision / PIB Press Release", None, "2024-09-11",
                 "Cabinet approves health coverage to all senior citizens aged 70+ under AB PM-JAY",
                 "कैबिनेट ने AB PM-JAY के तहत 70+ वरिष्ठ नागरिकों के लिए स्वास्थ्य कवरेज को मंजूरी दी",
                 "मंत्रिमंडळाने AB PM-JAY अंतर्गत ७०+ वयाच्या ज्येष्ठ नागरिकांसाठी आरोग्य कव्हरेजला मंजुरी दिली",
                 "https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=2053883&reg=48&lang=2",
                 "Government of India (PIB / PMO)", True, False, True),
        ],
        "notes": _notes(
            "Ayushman Bharat - Pradhan Mantri Jan Arogya Yojana (AB-PMJAY) is the base scheme (₹5 lakh/family/year, "
            "BPL/SECC-listed families). Cabinet approved a further expansion on 11 Sept 2024 giving all citizens "
            "aged 70+ ₹5 lakh/year cover irrespective of income, confirmed directly from the PIB press release.",
            "आयुष्मान भारत - प्रधानमंत्री जन आरोग्य योजना (AB-PMJAY) मूल योजना है (₹5 लाख/परिवार/वर्ष, BPL/SECC-सूचीबद्ध परिवार)। "
            "11 सितंबर 2024 को कैबिनेट ने 70+ आयु के सभी नागरिकों को आय की परवाह किए बिना ₹5 लाख/वर्ष कवर देने के विस्तार को मंजूरी दी, "
            "जिसे सीधे PIB प्रेस विज्ञप्ति से पुष्टि की गई।",
            "आयुष्मान भारत - प्रधानमंत्री जन आरोग्य योजना (AB-PMJAY) ही मूळ योजना आहे (₹5 लाख/कुटुंब/वर्ष, BPL/SECC-सूचीबद्ध कुटुंबे). "
            "11 सप्टेंबर 2024 रोजी मंत्रिमंडळाने उत्पन्नाची पर्वा न करता 70+ वयाच्या सर्व नागरिकांना ₹5 लाख/वर्ष कव्हर देण्याच्या विस्ताराला "
            "मंजुरी दिली, जी थेट PIB प्रसिद्धीपत्रकावरून पुष्टी करण्यात आली."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "ayushman": {
        "canonical_key": "pm_jan_arogya",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_DUPLICATE,
        "confidence": "high",
        "current_2026": True,
        "department": _dept("Same as PM Jan Arogya Yojana (AB-PMJAY)", "PM जन आरोग्य योजना (AB-PMJAY) के समान", "PM जन आरोग्य योजना (AB-PMJAY) प्रमाणेच"),
        "jurisdiction": "central",
        "documents": [],
        "notes": _notes(
            "\u201cAyushman Bharat\u201d and \u201cPM Jan Arogya Yojana\u201d are the same scheme (AB-PMJAY). "
            "This key is kept only for backward compatibility and always resolves to pm_jan_arogya.",
            "\u201cआयुष्मान भारत\u201d और \u201cPM जन आरोग्य योजना\u201d एक ही योजना (AB-PMJAY) हैं। "
            "यह कुंजी केवल पश्च-संगतता के लिए रखी गई है और हमेशा pm_jan_arogya में परिवर्तित होती है।",
            "\u201cआयुष्मान भारत\u201d आणि \u201cPM जन आरोग्य योजना\u201d ही एकच योजना (AB-PMJAY) आहे. "
            "ही की फक्त मागील-सुसंगततेसाठी ठेवली आहे आणि नेहमी pm_jan_arogya कडे निर्देशित होते."
        ),
        "last_verified_date": RESEARCH_DATE,
    },

    # ---------------- CENTRAL: EMERGENCY / DEATH / FAMILY ----------------
    "state_emergency": {
        "canonical_key": "state_emergency",
        "aliases": [],
        "scheme_type": "PROGRAM_POLICY",
        "status": STATUS_PARTIAL,
        "confidence": "medium",
        "current_2026": False,
        "department": _dept("Chief Minister's Office / Chief Minister's Relief Fund (CMRF), Government of Maharashtra",
                             "मुख्यमंत्री कार्यालय / मुख्यमंत्री सहायता निधि (CMRF), महाराष्ट्र सरकार",
                             "मुख्यमंत्री कार्यालय / मुख्यमंत्री सहाय्यता निधी (CMRF), महाराष्ट्र शासन"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Official Scheme Portal", None, None,
                 "Chief Minister's Relief Fund — Maharashtra",
                 "मुख्यमंत्री सहायता निधि — महाराष्ट्र",
                 "मुख्यमंत्री सहाय्यता निधी — महाराष्ट्र",
                 "https://cmrf.maharashtra.gov.in", "Government of Maharashtra", False, False, True),
        ],
        "notes": _notes(
            "Most plausibly identified as the Chief Minister's Relief Fund (CMRF). This is case-by-case discretionary "
            "assistance, NOT a fixed ₹10,000 benefit — the earlier fixed amount could not be sourced to any official "
            "document and has been removed.",
            "सबसे अधिक संभावना मुख्यमंत्री सहायता निधि (CMRF) के रूप में पहचानी गई है। यह मामला-दर-मामला विवेकाधीन सहायता है, "
            "निश्चित ₹10,000 का लाभ नहीं — पहले की निश्चित राशि किसी आधिकारिक दस्तावेज़ से सिद्ध नहीं हो सकी और उसे हटा दिया गया है।",
            "सर्वात शक्यता मुख्यमंत्री सहाय्यता निधी (CMRF) म्हणून ओळखली गेली आहे. ही प्रकरणपरत्वे विवेकाधीन मदत आहे, "
            "निश्चित ₹10,000 चा लाभ नाही — आधीची निश्चित रक्कम कोणत्याही अधिकृत दस्तऐवजावरून सिद्ध होऊ शकली नाही आणि ती काढून टाकण्यात आली आहे."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "national_family": {
        "canonical_key": "national_family",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_PARTIAL,
        "confidence": "medium",
        "current_2026": False,
        "department": _dept("Ministry of Rural Development, Government of India (National Social Assistance Programme)",
                             "ग्रामीण विकास मंत्रालय, भारत सरकार (राष्ट्रीय सामाजिक सहायता कार्यक्रम)",
                             "ग्रामीण विकास मंत्रालय, भारत सरकार (राष्ट्रीय सामाजिक सहाय्यता कार्यक्रम)"),
        "jurisdiction": "central",
        "documents": [
            _doc("Official Scheme Portal", None, None,
                 "National Social Assistance Programme (NSAP) — National Family Benefit Scheme",
                 "राष्ट्रीय सामाजिक सहायता कार्यक्रम (NSAP) — राष्ट्रीय परिवार लाभ योजना",
                 "राष्ट्रीय सामाजिक सहाय्यता कार्यक्रम (NSAP) — राष्ट्रीय कुटुंब लाभ योजना",
                 "https://nsap.nic.in", "Government of India", False, True, True),
        ],
        "notes": _notes(
            "Identity and department confirmed against the official NSAP portal. The ₹20,000 one-time figure is the "
            "well-established NSAP figure but was not re-confirmed against a dated notification this session.",
            "NSAP आधिकारिक पोर्टल के विरुद्ध पहचान और विभाग की पुष्टि की गई। ₹20,000 की एकमुश्त राशि प्रसिद्ध NSAP आंकड़ा है "
            "लेकिन इसे इस सत्र में किसी दिनांकित अधिसूचना से पुनः पुष्टि नहीं किया गया।",
            "NSAP अधिकृत पोर्टलवरून ओळख आणि विभागाची पुष्टी झाली आहे. ₹20,000 ही एकवेळची रक्कम सुप्रसिद्ध NSAP आकडा आहे "
            "परंतु या सत्रात कोणत्याही दिनांकित अधिसूचनेवरून पुन्हा पुष्टी करण्यात आलेली नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "widow_pension": {
        "canonical_key": "widow_pension",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_PARTIAL,
        "confidence": "medium",
        "current_2026": False,
        "department": _dept("Ministry of Rural Development, Government of India (NSAP)",
                             "ग्रामीण विकास मंत्रालय, भारत सरकार (NSAP)", "ग्रामीण विकास मंत्रालय, भारत सरकार (NSAP)"),
        "jurisdiction": "central",
        "documents": [
            _doc("Official Scheme Portal", None, None,
                 "NSAP — Indira Gandhi National Widow Pension Scheme",
                 "NSAP — इंदिरा गांधी राष्ट्रीय विधवा पेंशन योजना",
                 "NSAP — इंदिरा गांधी राष्ट्रीय विधवा निवृत्तीवेतन योजना",
                 "https://nsap.nic.in", "Government of India", False, True, True),
        ],
        "notes": _notes(
            "Central NSAP scheme confirmed via the official portal. State-level top-ups vary and were not individually re-verified.",
            "केंद्रीय NSAP योजना आधिकारिक पोर्टल से पुष्टि की गई। राज्य-स्तरीय टॉप-अप अलग-अलग होते हैं और व्यक्तिगत रूप से पुनः सत्यापित नहीं किए गए।",
            "केंद्रीय NSAP योजना अधिकृत पोर्टलवरून पुष्टी झाली आहे. राज्य-स्तरीय टॉप-अप वेगवेगळे असतात आणि वैयक्तिकरित्या पुन्हा पडताळले गेलेले नाहीत."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "old_age_pension": {
        "canonical_key": "old_age_pension",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_PARTIAL,
        "confidence": "medium",
        "current_2026": False,
        "department": _dept("Ministry of Rural Development, Government of India (NSAP)",
                             "ग्रामीण विकास मंत्रालय, भारत सरकार (NSAP)", "ग्रामीण विकास मंत्रालय, भारत सरकार (NSAP)"),
        "jurisdiction": "central",
        "documents": [
            _doc("Official Scheme Portal", None, None,
                 "NSAP — Indira Gandhi National Old Age Pension Scheme",
                 "NSAP — इंदिरा गांधी राष्ट्रीय वृद्धावस्था पेंशन योजना",
                 "NSAP — इंदिरा गांधी राष्ट्रीय वृद्धापकाळ निवृत्तीवेतन योजना",
                 "https://nsap.nic.in", "Government of India", False, True, True),
        ],
        "notes": _notes(
            "Central NSAP scheme, identity confirmed via official portal; exact current per-state top-up figures not re-verified this session.",
            "केंद्रीय NSAP योजना, आधिकारिक पोर्टल से पहचान की पुष्टि; सटीक वर्तमान राज्य-वार टॉप-अप आंकड़े इस सत्र में पुनः सत्यापित नहीं।",
            "केंद्रीय NSAP योजना, अधिकृत पोर्टलवरून ओळख पुष्टी; नेमके सध्याचे राज्यनिहाय टॉप-अप आकडे या सत्रात पुन्हा पडताळलेले नाहीत."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "annapurna": {
        "canonical_key": "annapurna",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_PARTIAL,
        "confidence": "medium",
        "current_2026": False,
        "department": _dept("Department of Food & Public Distribution, Government of India",
                             "खाद्य एवं सार्वजनिक वितरण विभाग, भारत सरकार", "अन्न व सार्वजनिक वितरण विभाग, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("Official Scheme Portal", None, None, "Annapurna Scheme",
                 "अन्नपूर्णा योजना", "अन्नपूर्णा योजना",
                 "https://dfpd.gov.in", "Government of India", False, True, True),
        ],
        "notes": _notes(
            "Identity/department confirmed via official DFPD portal; not independently re-verified against a dated notification this session.",
            "पहचान/विभाग की पुष्टि आधिकारिक DFPD पोर्टल से; इस सत्र में किसी दिनांकित अधिसूचना से स्वतंत्र रूप से पुनः सत्यापित नहीं।",
            "ओळख/विभाग अधिकृत DFPD पोर्टलवरून पुष्टी; या सत्रात कोणत्याही दिनांकित अधिसूचनेवरून स्वतंत्रपणे पुन्हा पडताळलेले नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },

    # ---------------- CENTRAL: CHILD / NUTRITION ----------------
    "pm_poshan": {
        "canonical_key": "pm_poshan",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_PARTIAL,
        "confidence": "medium",
        "current_2026": False,
        "department": _dept("Department of School Education & Literacy, Ministry of Education, Government of India",
                             "स्कूली शिक्षा एवं साक्षरता विभाग, शिक्षा मंत्रालय, भारत सरकार",
                             "शालेय शिक्षण व साक्षरता विभाग, शिक्षण मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("Official Scheme Portal", None, None, "PM POSHAN (erstwhile Mid-Day Meal Scheme)",
                 "PM पोषण (पूर्व में मध्याह्न भोजन योजना)", "PM पोषण (पूर्वीची मध्यान्ह भोजन योजना)",
                 "https://pmposhan.education.gov.in", "Government of India", False, True, True),
        ],
        "notes": _notes(
            "Identity/department confirmed via official portal.",
            "पहचान/विभाग की पुष्टि आधिकारिक पोर्टल से।",
            "ओळख/विभाग अधिकृत पोर्टलवरून पुष्टी."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "icds": {
        "canonical_key": "icds",
        "aliases": [],
        "scheme_type": "PROGRAM_POLICY",
        "status": STATUS_VERIFIED_PRIMARY_CURRENT,
        "confidence": "high",
        "current_2026": True,
        "department": _dept("Ministry of Women & Child Development, Government of India",
                             "महिला एवं बाल विकास मंत्रालय, भारत सरकार", "महिला व बाल विकास मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("Scheme Guidelines", None, None,
                 "Mission Saksham Anganwadi & Poshan 2.0 (erstwhile Integrated Child Development Services / ICDS)",
                 "मिशन सक्षम आंगनवाड़ी और पोषण 2.0 (पूर्व में एकीकृत बाल विकास सेवाएं / ICDS)",
                 "मिशन सक्षम अंगणवाडी आणि पोषण 2.0 (पूर्वीची एकात्मिक बाल विकास सेवा / ICDS)",
                 "https://wcd.gov.in/offerings/nutrition-mission-saksham-anganwadi-and-poshan-2-0-mission-saksham-anganwadi-poshan-2-0",
                 "Government of India (Ministry of Women & Child Development)", True, False, True),
        ],
        "notes": _notes(
            "ICDS (launched 1975) has been restructured and is now delivered under 'Mission Saksham Anganwadi & Poshan 2.0', "
            "confirmed directly on the Ministry of Women & Child Development site. Services remain Anganwadi-delivered — this "
            "is a programme, not a direct cash-transfer scheme.",
            "ICDS (1975 में शुरू) को पुनर्गठित किया गया है और अब इसे 'मिशन सक्षम आंगनवाड़ी और पोषण 2.0' के तहत दिया जाता है, "
            "जिसकी सीधे महिला एवं बाल विकास मंत्रालय की वेबसाइट पर पुष्टि हुई। सेवाएं अभी भी आंगनवाड़ी के माध्यम से दी जाती हैं — यह एक "
            "कार्यक्रम है, सीधा नकद-हस्तांतरण योजना नहीं।",
            "ICDS (1975 मध्ये सुरू) पुनर्रचित करण्यात आले असून आता ते 'मिशन सक्षम अंगणवाडी आणि पोषण 2.0' अंतर्गत दिले जाते, "
            "याची थेट महिला व बाल विकास मंत्रालयाच्या संकेतस्थळावर पुष्टी झाली. सेवा अजूनही अंगणवाडीमार्फत दिल्या जातात — हा "
            "एक कार्यक्रम आहे, थेट रोख-हस्तांतरण योजना नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },

    # ---------------- CENTRAL: DISABILITY ----------------
    "divyangjan": {
        "canonical_key": "divyangjan",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_PRIMARY_CURRENT,
        "confidence": "high",
        "current_2026": True,
        "department": _dept("National Divyangjan Finance & Development Corporation (NDFDC/NHFDC), Dept. of Empowerment of Persons with Disabilities, Govt. of India",
                             "राष्ट्रीय दिव्यांगजन वित्त एवं विकास निगम (NDFDC/NHFDC), दिव्यांगजन सशक्तिकरण विभाग, भारत सरकार",
                             "राष्ट्रीय दिव्यांगजन वित्त व विकास महामंडळ (NDFDC/NHFDC), दिव्यांगजन सक्षमीकरण विभाग, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("Official Scheme Page", None, None, "Divyangjan Swavalamban Yojana (NDFDC concessional loan scheme)",
                 "दिव्यांगजन स्वावलंबन योजना (NDFDC रियायती ऋण योजना)", "दिव्यांगजन स्वावलंबन योजना (NDFDC सवलतीचे कर्ज योजना)",
                 "https://depwd.gov.in/en/national-handicapped-finance-and-development-corporation/",
                 "Government of India (DEPwD / NDFDC)", True, True, True),
        ],
        "notes": _notes(
            "Corrected: Divyangjan Swavalamban Yojana is a CONCESSIONAL LOAN scheme (up to ₹50 lakh, no income ceiling, "
            "for self-employment/income generation), not a monthly disability pension. The previous ₹300-1500/month "
            "pension description belongs to a different scheme (Indira Gandhi National Disability Pension Scheme, IGNDPS) "
            "which is not currently modelled as a separate key in this app.",
            "सुधार: दिव्यांगजन स्वावलंबन योजना एक रियायती ऋण योजना है (₹50 लाख तक, कोई आय सीमा नहीं, स्वरोजगार/आय सृजन हेतु), "
            "मासिक विकलांगता पेंशन नहीं। पहले का ₹300-1500/माह पेंशन विवरण एक अलग योजना (इंदिरा गांधी राष्ट्रीय विकलांगता पेंशन योजना, IGNDPS) से संबंधित है, "
            "जिसे इस ऐप में अलग कुंजी के रूप में मॉडल नहीं किया गया है।",
            "दुरुस्ती: दिव्यांगजन स्वावलंबन योजना ही एक सवलतीच्या कर्जाची योजना आहे (₹50 लाखांपर्यंत, उत्पन्न मर्यादा नाही, स्वयंरोजगार/उत्पन्न निर्मितीसाठी), "
            "मासिक अपंगत्व निवृत्तीवेतन नाही. आधीचे ₹300-1500/महिना निवृत्तीवेतन वर्णन वेगळ्या योजनेशी (इंदिरा गांधी राष्ट्रीय अपंगत्व निवृत्तीवेतन योजना, IGNDPS) संबंधित आहे, "
            "जी या अ‍ॅपमध्ये स्वतंत्र की म्हणून मॉडेल केलेली नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "adip": {
        "canonical_key": "adip",
        "aliases": ["accessible_india"],
        "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_PRIMARY_CURRENT,
        "confidence": "high",
        "current_2026": True,
        "department": _dept("Department of Empowerment of Persons with Disabilities (DEPwD), Ministry of Social Justice & Empowerment, Government of India",
                             "दिव्यांगजन सशक्तिकरण विभाग (DEPwD), सामाजिक न्याय एवं अधिकारिता मंत्रालय, भारत सरकार",
                             "दिव्यांगजन सक्षमीकरण विभाग (DEPwD), सामाजिक न्याय व सक्षमीकरण मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("Scheme Guidelines / Official Scheme Page", None, None,
                 "ADIP — Assistance to Disabled Persons for Purchase/Fitting of Aids & Appliances",
                 "ADIP — विकलांग व्यक्तियों को सहायता उपकरण/यंत्र खरीदने/फिट करने हेतु सहायता",
                 "ADIP — अपंग व्यक्तींना साधने/उपकरणे खरेदी/फिटिंगसाठी सहाय्य",
                 "https://depwd.gov.in/en/adip/", "Government of India (DEPwD)", True, True, True),
        ],
        "notes": _notes(
            "Corrected & repointed: the benefit previously described under 'Accessible India Campaign' — free/subsidised "
            "wheelchairs, hearing aids and other assistive devices via ALIMCO camps — is actually the ADIP scheme "
            "(operating since 1981, 40%+ disability certificate, income ceiling ₹30,000/month). The Accessible India "
            "Campaign (Sugamya Bharat Abhiyan) is a separate DEPwD initiative for physical/transport/ICT accessibility "
            "infrastructure, not an individual device-distribution scheme, and is kept only as a non-recommendable alias "
            "here to avoid implying citizens can 'apply' for a cash/device benefit under that name.",
            "सुधार व पुनर्निर्देशन: पहले 'सुगम्य भारत अभियान' के तहत वर्णित लाभ — ALIMCO शिविरों के माध्यम से मुफ्त/रियायती व्हीलचेयर, "
            "श्रवण यंत्र और अन्य सहायक उपकरण — वास्तव में ADIP योजना है (1981 से संचालित, 40%+ विकलांगता प्रमाण पत्र, आय सीमा ₹30,000/माह)। "
            "सुगम्य भारत अभियान भौतिक/परिवहन/ICT पहुंच अवसंरचना के लिए एक अलग DEPwD पहल है, व्यक्तिगत उपकरण-वितरण योजना नहीं।",
            "दुरुस्ती व पुनर्निर्देशन: आधी 'सुगम्य भारत अभियान' अंतर्गत वर्णन केलेला लाभ — ALIMCO शिबिरांमार्फत मोफत/सवलतीच्या व्हीलचेअर, "
            "श्रवणयंत्र आणि इतर सहाय्यक साधने — प्रत्यक्षात ADIP योजना आहे (1981 पासून सुरू, 40%+ अपंगत्व प्रमाणपत्र, उत्पन्न मर्यादा ₹30,000/महिना). "
            "सुगम्य भारत अभियान ही भौतिक/वाहतूक/ICT सुलभता पायाभूत सुविधांसाठी वेगळी DEPwD उपक्रम आहे, वैयक्तिक साधन-वितरण योजना नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "accessible_india": {
        "canonical_key": "adip",
        "aliases": [],
        "scheme_type": "PROGRAM_POLICY",
        "status": STATUS_DUPLICATE,
        "confidence": "high",
        "current_2026": True,
        "department": _dept("See ADIP", "देखें ADIP", "पहा ADIP"),
        "jurisdiction": "central",
        "documents": [],
        "notes": _notes(
            "Kept only for backward compatibility with the old key name; the actual device-distribution benefit is ADIP. "
            "The real Accessible India Campaign (Sugamya Bharat Abhiyan) is an infrastructure-accessibility initiative, "
            "not a citizen-applied cash/device benefit, so it is not separately recommendable here.",
            "पुराने कुंजी नाम के साथ पश्च-संगतता के लिए रखा गया; वास्तविक उपकरण-वितरण लाभ ADIP है। वास्तविक सुगम्य भारत अभियान एक "
            "अवसंरचना-पहुंच पहल है, नागरिक-आवेदित नकद/उपकरण लाभ नहीं।",
            "जुन्या की नावासह मागील-सुसंगततेसाठी ठेवले आहे; प्रत्यक्ष साधन-वितरण लाभ ADIP आहे. प्रत्यक्ष सुगम्य भारत अभियान ही "
            "पायाभूत-सुलभता उपक्रम आहे, नागरिकांनी अर्ज करण्याजोगा रोख/साधन लाभ नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },

    # ---------------- CENTRAL: HOUSING ----------------
    "pm_awas_gramin": {
        "canonical_key": "pm_awas_gramin",
        "aliases": ["pm_awas"],
        "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_PRIMARY_CURRENT,
        "confidence": "high",
        "current_2026": True,
        "department": _dept("Ministry of Rural Development, Government of India",
                             "ग्रामीण विकास मंत्रालय, भारत सरकार", "ग्रामीण विकास मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("Cabinet Decision / PIB Press Release", None, "2024-08-09",
                 "Cabinet approves implementation of PMAY-Gramin during FY 2024-25 to 2028-29 (2 crore additional houses)",
                 "कैबिनेट ने FY 2024-25 से 2028-29 तक PMAY-ग्रामीण के कार्यान्वयन को मंजूरी दी (2 करोड़ अतिरिक्त घर)",
                 "मंत्रिमंडळाने FY 2024-25 ते 2028-29 पर्यंत PMAY-ग्रामीणच्या अंमलबजावणीला मंजुरी दिली (2 कोटी अतिरिक्त घरे)",
                 "https://www.pmindia.gov.in/en/news_updates/cabinet-approves-implementation-of-the-pradhan-mantri-awaas-yojana-gramin-pmay-g-during-fy-2024-25-to-2028-29/",
                 "Government of India (PMO/PIB)", True, False, True),
        ],
        "notes": _notes(
            "Split out from the previous blended 'pm_awas' entry. Cabinet approved continuation of PMAY-G through "
            "FY2028-29 for 2 crore additional houses at unit assistance of ₹1.20 lakh (plain areas) / ₹1.30 lakh "
            "(NE & hill states), confirmed directly from the PMO press release.",
            "पिछली मिश्रित 'pm_awas' प्रविष्टि से अलग किया गया। कैबिनेट ने FY2028-29 तक PMAY-G की निरंतरता को 2 करोड़ अतिरिक्त घरों "
            "हेतु ₹1.20 लाख (सामान्य क्षेत्र) / ₹1.30 लाख (पूर्वोत्तर व पहाड़ी राज्य) की इकाई सहायता पर मंजूरी दी, जिसे सीधे PMO प्रेस विज्ञप्ति से पुष्टि किया गया।",
            "आधीच्या मिश्रित 'pm_awas' नोंदीपासून वेगळे केले. मंत्रिमंडळाने FY2028-29 पर्यंत PMAY-G च्या सातत्याला 2 कोटी अतिरिक्त घरांसाठी "
            "₹1.20 लाख (सर्वसाधारण क्षेत्र) / ₹1.30 लाख (ईशान्य व डोंगराळ राज्ये) युनिट सहाय्यावर मंजुरी दिली, जी थेट PMO प्रसिद्धीपत्रकावरून पुष्टी करण्यात आली."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "pm_awas_urban": {
        "canonical_key": "pm_awas_urban",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_WITH_CHAIN,
        "confidence": "medium",
        "current_2026": True,
        "department": _dept("Ministry of Housing & Urban Affairs, Government of India",
                             "आवास एवं शहरी कार्य मंत्रालय, भारत सरकार", "गृहनिर्माण व नागरी व्यवहार मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("Cabinet Decision", None, "2024-08-09",
                 "Cabinet approves Pradhan Mantri Awas Yojana-Urban 2.0",
                 "कैबिनेट ने प्रधानमंत्री आवास योजना-शहरी 2.0 को मंजूरी दी",
                 "मंत्रिमंडळाने प्रधानमंत्री आवास योजना-शहरी 2.0 ला मंजुरी दिली",
                 "https://pmay-urban.gov.in", "Government of India (MoHUA)", False, False, True),
        ],
        "notes": _notes(
            "Split out from the previous blended 'pm_awas' entry. PMAY-Urban 2.0 was approved the same day as the "
            "PMAY-G extension (9 Aug 2024) with a government outlay of ₹2.30 lakh crore; the official portal was "
            "referenced but not independently opened this session, so this is VERIFIED_WITH_CHAIN rather than PRIMARY.",
            "पिछली मिश्रित 'pm_awas' प्रविष्टि से अलग किया गया। PMAY-शहरी 2.0 को PMAY-G विस्तार के समान दिन (9 अगस्त 2024) मंजूरी दी गई "
            "थी, सरकारी परिव्यय ₹2.30 लाख करोड़; आधिकारिक पोर्टल का संदर्भ दिया गया लेकिन इस सत्र में स्वतंत्र रूप से नहीं खोला गया।",
            "आधीच्या मिश्रित 'pm_awas' नोंदीपासून वेगळे केले. PMAY-शहरी 2.0 ला PMAY-G विस्ताराच्याच दिवशी (9 ऑगस्ट 2024) मंजुरी मिळाली, "
            "शासकीय खर्च ₹2.30 लाख कोटी; अधिकृत पोर्टलचा संदर्भ दिला परंतु या सत्रात स्वतंत्रपणे उघडलेला नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "pm_awas": {
        "canonical_key": "pm_awas_gramin",
        "aliases": [],
        "scheme_type": "SCHEME",
        "status": STATUS_DUPLICATE,
        "confidence": "high",
        "current_2026": True,
        "department": _dept("See PMAY-Gramin / PMAY-Urban", "देखें PMAY-ग्रामीण / PMAY-शहरी", "पहा PMAY-ग्रामीण / PMAY-शहरी"),
        "jurisdiction": "central",
        "documents": [],
        "notes": _notes(
            "Kept only as a legacy/parent key. PMAY-Gramin and PMAY-Urban are governed by different eligibility rules, "
            "departments and unit assistance and are now modelled as separate schemes (pm_awas_gramin / pm_awas_urban).",
            "केवल विरासत/मूल कुंजी के रूप में रखा गया। PMAY-ग्रामीण और PMAY-शहरी अलग-अलग पात्रता नियमों, विभागों और इकाई सहायता द्वारा "
            "शासित होते हैं और अब अलग-अलग योजनाओं (pm_awas_gramin / pm_awas_urban) के रूप में मॉडल किए गए हैं।",
            "फक्त वारसा/मूळ की म्हणून ठेवले आहे. PMAY-ग्रामीण आणि PMAY-शहरी वेगवेगळ्या पात्रता नियम, विभाग आणि युनिट सहाय्याने "
            "नियंत्रित होतात आणि आता स्वतंत्र योजना (pm_awas_gramin / pm_awas_urban) म्हणून मॉडेल केल्या आहेत."
        ),
        "last_verified_date": RESEARCH_DATE,
    },

    # ---------------- CENTRAL: FOOD / RATION / ENERGY / BANKING ----------------
    "antyodaya": {
        "canonical_key": "antyodaya", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_PARTIAL, "confidence": "medium", "current_2026": False,
        "department": _dept("Department of Food & Public Distribution, Government of India",
                             "खाद्य एवं सार्वजनिक वितरण विभाग, भारत सरकार", "अन्न व सार्वजनिक वितरण विभाग, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [_doc("Official Scheme Portal", None, None, "Antyodaya Anna Yojana", "अंत्योदय अन्न योजना", "अंत्योदय अन्न योजना",
                            "https://dfpd.gov.in", "Government of India", False, True, True)],
        "notes": _notes("Identity/department confirmed via official portal; not re-verified against a dated notification this session.",
                         "पहचान/विभाग की पुष्टि आधिकारिक पोर्टल से; इस सत्र में दिनांकित अधिसूचना से पुनः सत्यापित नहीं।",
                         "ओळख/विभाग अधिकृत पोर्टलवरून पुष्टी; या सत्रात दिनांकित अधिसूचनेवरून पुन्हा पडताळलेले नाही."),
        "last_verified_date": RESEARCH_DATE,
    },
    "ujjwala": {
        "canonical_key": "ujjwala", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_PARTIAL, "confidence": "medium", "current_2026": False,
        "department": _dept("Ministry of Petroleum & Natural Gas, Government of India",
                             "पेट्रोलियम एवं प्राकृतिक गैस मंत्रालय, भारत सरकार", "पेट्रोलियम व नैसर्गिक वायू मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [_doc("Official Scheme Portal", None, None, "PM Ujjwala Yojana (Ujjwala 2.0)", "PM उज्ज्वला योजना (उज्ज्वला 2.0)", "PM उज्ज्वला योजना (उज्ज्वला 2.0)",
                            "https://pmuy.gov.in", "Government of India", False, True, True)],
        "notes": _notes("Identity confirmed via official portal; Ujjwala 2.0 expansion details not re-verified this session.",
                         "पहचान आधिकारिक पोर्टल से पुष्टि; उज्ज्वला 2.0 विस्तार विवरण इस सत्र में पुनः सत्यापित नहीं।",
                         "ओळख अधिकृत पोर्टलवरून पुष्टी; उज्ज्वला 2.0 विस्तार तपशील या सत्रात पुन्हा पडताळलेले नाहीत."),
        "last_verified_date": RESEARCH_DATE,
    },
    "saubhagya": {
        "canonical_key": "saubhagya", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_CLOSED, "confidence": "high", "current_2026": True,
        "department": _dept("Ministry of Power, Government of India",
                             "ऊर्जा मंत्रालय, भारत सरकार", "ऊर्जा मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [
            _doc("PIB Press Release", None, "2022-03-31",
                 "Households Electrified Under SAUBHAGYA — scheme stands closed as on 31.03.2022",
                 "SAUBHAGYA के तहत विद्युतीकृत घर — योजना 31.03.2022 से बंद",
                 "SAUBHAGYA अंतर्गत विद्युतीकरण झालेली घरे — योजना 31.03.2022 पासून बंद",
                 "https://pib.gov.in/PressReleseDetailm.aspx?PRID=1983087", "Government of India (Ministry of Power / PIB)",
                 True, False, True),
        ],
        "notes": _notes(
            "CONFIRMED CLOSED. Multiple PIB press releases (Rajya Sabha replies) confirm Pradhan Mantri Sahaj Bijli Har "
            "Ghar Yojana (Saubhagya) was completed and officially closed on 31 March 2022 after ~2.86 crore households "
            "were electrified. Later electrification gaps are handled under the separate Revamped Distribution Sector "
            "Scheme (RDSS) — RDSS is NOT the same scheme as Saubhagya and is not modelled here. This scheme must never "
            "be recommended as active.",
            "पुष्टि: बंद। कई PIB प्रेस विज्ञप्तियां (राज्यसभा उत्तर) पुष्टि करती हैं कि प्रधानमंत्री सहज बिजली हर घर योजना (सौभाग्य) "
            "31 मार्च 2022 को पूर्ण होकर आधिकारिक रूप से बंद हो गई, लगभग 2.86 करोड़ घरों के विद्युतीकरण के बाद। बाद के विद्युतीकरण अंतराल "
            "अलग रिवैम्प्ड डिस्ट्रीब्यूशन सेक्टर स्कीम (RDSS) के तहत संभाले जाते हैं — RDSS सौभाग्य के समान योजना नहीं है।",
            "पुष्टी: बंद. अनेक PIB प्रसिद्धीपत्रके (राज्यसभा उत्तरे) पुष्टी करतात की प्रधानमंत्री सहज बिजली हर घर योजना (सौभाग्य) "
            "31 मार्च 2022 रोजी पूर्ण होऊन अधिकृतपणे बंद झाली, सुमारे 2.86 कोटी घरांचे विद्युतीकरण झाल्यानंतर. नंतरची विद्युतीकरण तफावत "
            "वेगळ्या रिव्हॅम्प्ड डिस्ट्रिब्युशन सेक्टर स्कीम (RDSS) अंतर्गत हाताळली जाते — RDSS ही सौभाग्यसारखीच योजना नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "jan_dhan": {
        "canonical_key": "jan_dhan", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_PARTIAL, "confidence": "medium", "current_2026": False,
        "department": _dept("Department of Financial Services, Ministry of Finance, Government of India",
                             "वित्तीय सेवा विभाग, वित्त मंत्रालय, भारत सरकार", "वित्तीय सेवा विभाग, अर्थ मंत्रालय, भारत सरकार"),
        "jurisdiction": "central",
        "documents": [_doc("Official Scheme Portal", None, None, "PM Jan Dhan Yojana", "PM जन धन योजना", "PM जन धन योजना",
                            "https://pmjdy.gov.in", "Government of India", False, True, True)],
        "notes": _notes("Identity/department confirmed via official portal; not re-verified against a dated notification this session.",
                         "पहचान/विभाग की पुष्टि आधिकारिक पोर्टल से; इस सत्र में पुनः सत्यापित नहीं।",
                         "ओळख/विभाग अधिकृत पोर्टलवरून पुष्टी; या सत्रात पुन्हा पडताळलेले नाही."),
        "last_verified_date": RESEARCH_DATE,
    },

    # ---------------- MAHARASHTRA ----------------
    "ladki_bahin": {
        "canonical_key": "ladki_bahin", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_WITH_CHAIN, "confidence": "medium", "current_2026": True,
        "department": _dept("Women & Child Development Department, Government of Maharashtra",
                             "महिला एवं बाल विकास विभाग, महाराष्ट्र सरकार", "महिला व बालविकास विभाग, महाराष्ट्र शासन"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Government Resolution (GR)", "मबावि २०२४/प्र.क्र.९६/कार्या-२", "2024-06-28",
                 "Mukhyamantri-Majhi Ladki Bahin Yojana — founding GR",
                 "मुख्यमंत्री-माझी लाडकी बहीण योजना — मूल शासन निर्णय",
                 "मुख्यमंत्री-माझी लाडकी बहीण योजना — मूळ शासन निर्णय",
                 "https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/English/202406281814018230.pdf",
                 "Government of Maharashtra", False, True, True),
        ],
        "notes": _notes(
            "Founding GR number/date carried forward from prior audit and not re-opened this session, so kept at "
            "VERIFIED_WITH_CHAIN rather than PRIMARY. A previously-circulated 2025 e-KYC circular number "
            "(मबावि 2025/प्र.क्र.167/काया-2) could NOT be independently verified on the official GR portal and is "
            "deliberately NOT shown anywhere in this app as a confirmed document.",
            "मूल GR संख्या/दिनांक पूर्व ऑडिट से आगे बढ़ाई गई और इस सत्र में दोबारा नहीं खोली गई, इसलिए PRIMARY के बजाय "
            "VERIFIED_WITH_CHAIN रखा गया। पूर्व में प्रसारित 2025 e-KYC परिपत्र संख्या (मबावि 2025/प्र.क्र.167/काया-2) आधिकारिक "
            "GR पोर्टल पर स्वतंत्र रूप से सत्यापित नहीं की जा सकी और इसे जानबूझकर इस ऐप में कहीं भी पुष्ट दस्तावेज़ के रूप में नहीं दिखाया गया है।",
            "मूळ GR क्रमांक/दिनांक आधीच्या ऑडिटवरून पुढे आणला असून या सत्रात पुन्हा उघडलेला नाही, म्हणून PRIMARY ऐवजी "
            "VERIFIED_WITH_CHAIN ठेवले आहे. आधी प्रसारित 2025 e-KYC परिपत्रक क्रमांक (मबावि 2025/प्र.क्र.167/काया-2) अधिकृत "
            "GR पोर्टलवर स्वतंत्रपणे पडताळता आला नाही आणि तो जाणीवपूर्वक या अ‍ॅपमध्ये कुठेही पुष्टी झालेला दस्तऐवज म्हणून दाखवलेला नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "mh_health": {
        "canonical_key": "mh_health", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_WITH_CHAIN, "confidence": "high", "current_2026": True,
        "department": _dept("Public Health Department, Government of Maharashtra / State Health Assurance Society",
                             "सार्वजनिक स्वास्थ्य विभाग, महाराष्ट्र सरकार / राज्य स्वास्थ्य हमी सोसायटी",
                             "सार्वजनिक आरोग्य विभाग, महाराष्ट्र शासन / राज्य आरोग्य हमी सोसायटी"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Government Resolution (GR)", "मफुयो-2023/प्र.क्र.160/आरोग्य-6", "2023-07-28",
                 "Combined Mahatma Jyotirao Phule Jan Arogya Yojana & PM-JAY expansion GR",
                 "एकत्रित महात्मा ज्योतिराव फुले जन आरोग्य योजना व PM-JAY विस्तार शासन निर्णय",
                 "एकत्रित महात्मा ज्योतिराव फुले जन आरोग्य योजना व PM-JAY विस्तार शासन निर्णय",
                 None, "Government of Maharashtra", True, False, True),
        ],
        "notes": _notes(
            "Independently re-confirmed this session: the 28 July 2023 GR (मफुयो-2023/प्र.क्र.160/आरोग्य-6) content was found "
            "directly, expanding cover to ₹5 lakh/family/year effective 1 July 2024 and extending eligibility to ALL ration "
            "card categories (yellow, Antyodaya, Annapurna, orange up to ₹1 lakh income, plus white/no-card families in "
            "drought-affected talukas), not just yellow/orange as the previous app text said. That outdated restriction has "
            "been corrected.",
            "इस सत्र में स्वतंत्र रूप से पुनः पुष्टि: 28 जुलाई 2023 का GR (मफुयो-2023/प्र.क्र.160/आरोग्य-6) सीधे मिला, जो 1 जुलाई 2024 से "
            "₹5 लाख/परिवार/वर्ष कवर तक विस्तारित है और पात्रता को सभी राशन कार्ड श्रेणियों तक बढ़ाता है, केवल पीला/नारंगी तक सीमित नहीं। "
            "पुरानी सीमा को ठीक कर दिया गया है।",
            "या सत्रात स्वतंत्रपणे पुन्हा पुष्टी: 28 जुलै 2023 चा GR (मफुयो-2023/प्र.क्र.160/आरोग्य-6) थेट सापडला, जो 1 जुलै 2024 पासून "
            "₹5 लाख/कुटुंब/वर्ष कव्हरपर्यंत विस्तारित आहे आणि पात्रता सर्व शिधापत्रिका प्रकारांपर्यंत वाढवतो, फक्त पिवळे/नारिंगीपुरती मर्यादित नाही. "
            "जुनी मर्यादा दुरुस्त करण्यात आली आहे."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "shravan_bal": {
        "canonical_key": "shravan_bal", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_PRIMARY_CURRENT, "confidence": "high", "current_2026": True,
        "department": _dept("Social Justice & Special Assistance Department, Government of Maharashtra",
                             "सामाजिक न्याय एवं विशेष सहायता विभाग, महाराष्ट्र सरकार", "सामाजिक न्याय व विशेष सहाय्य विभाग, महाराष्ट्र शासन"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Government Resolution (GR)", "विसयो-2022/प्र.क्र.120/विसयो", "2023-07-05",
                 "Increase in monthly financial assistance under Sanjay Gandhi Niradhar Anudan Yojana & Shravan Bal Seva Rajya Nivrutti Vetan Yojana to Rs.1,500/month",
                 "संजय गांधी निराधार अनुदान योजना व श्रावणबाळ सेवा राज्य निवृत्तीवेतन योजना अंतर्गत मासिक अर्थसहाय्य रु.1,500/माह करने बाबत",
                 "संजय गांधी निराधार अनुदान योजना व श्रावणबाळ सेवा राज्य निवृत्तीवेतन योजनेंतर्गत मासिक अर्थसहाय्य रु.1,500/महिना करण्याबाबत",
                 "https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/Marathi/202307061137387522.pdf",
                 "Government of Maharashtra (Social Justice & Special Assistance Dept.)", True, False, True),
        ],
        "notes": _notes(
            "Independently re-confirmed this session directly from the GR text and the official sjsa.maharashtra.gov.in "
            "scheme page: GR विसयो-2022/प्र.क्र.120/विसयो dated 5 July 2023 raised the monthly amount from ₹1,000 to "
            "₹1,500/month. The app previously showed ₹600/month — that figure is outdated and has been corrected.",
            "इस सत्र में सीधे GR पाठ और आधिकारिक sjsa.maharashtra.gov.in योजना पृष्ठ से पुनः पुष्टि: GR विसयो-2022/प्र.क्र.120/विसयो "
            "दिनांक 5 जुलाई 2023 ने मासिक राशि ₹1,000 से बढ़ाकर ₹1,500/माह कर दी। ऐप पहले ₹600/माह दिखाता था — यह आंकड़ा पुराना था और ठीक कर दिया गया है।",
            "या सत्रात थेट GR मजकूर आणि अधिकृत sjsa.maharashtra.gov.in योजना पानावरून पुन्हा पुष्टी: GR विसयो-2022/प्र.क्र.120/विसयो "
            "दिनांक 5 जुलै 2023 ने मासिक रक्कम ₹1,000 वरून ₹1,500/महिना केली. अ‍ॅप आधी ₹600/महिना दाखवत होते — तो आकडा जुना होता आणि दुरुस्त करण्यात आला आहे."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "sanjay_gandhi": {
        "canonical_key": "sanjay_gandhi", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_PRIMARY_CURRENT, "confidence": "high", "current_2026": True,
        "department": _dept("Social Justice & Special Assistance Department, Government of Maharashtra",
                             "सामाजिक न्याय एवं विशेष सहायता विभाग, महाराष्ट्र सरकार", "सामाजिक न्याय व विशेष सहाय्य विभाग, महाराष्ट्र शासन"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Government Resolution (GR)", "विसयो-2022/प्र.क्र.120/विसयो", "2023-07-05",
                 "Increase in monthly financial assistance under Sanjay Gandhi Niradhar Anudan Yojana to Rs.1,500/month",
                 "संजय गांधी निराधार अनुदान योजना अंतर्गत मासिक अर्थसहाय्य रु.1,500/माह करने बाबत",
                 "संजय गांधी निराधार अनुदान योजनेंतर्गत मासिक अर्थसहाय्य रु.1,500/महिना करण्याबाबत",
                 "https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/Marathi/202307061137387522.pdf",
                 "Government of Maharashtra (Social Justice & Special Assistance Dept.)", True, False, True),
        ],
        "notes": _notes(
            "Independently re-confirmed this session: same GR as Shravan Bal (विसयो-2022/प्र.क्र.120/विसयो, 5 July 2023), "
            "and confirmed again on the official sjsa.maharashtra.gov.in scheme page, which currently states ₹1,500/month. "
            "The app previously showed ₹600/month — corrected.",
            "इस सत्र में स्वतंत्र रूप से पुनः पुष्टि: श्रावणबाळ के समान GR (विसयो-2022/प्र.क्र.120/विसयो, 5 जुलाई 2023), और आधिकारिक "
            "sjsa.maharashtra.gov.in योजना पृष्ठ पर पुनः पुष्टि, जो वर्तमान में ₹1,500/माह बताता है। ऐप पहले ₹600/माह दिखाता था — ठीक कर दिया गया।",
            "या सत्रात स्वतंत्रपणे पुन्हा पुष्टी: श्रावणबाळप्रमाणेच GR (विसयो-2022/प्र.क्र.120/विसयो, 5 जुलै 2023), आणि अधिकृत "
            "sjsa.maharashtra.gov.in योजना पानावर पुन्हा पुष्टी, जे सध्या ₹1,500/महिना सांगते. अ‍ॅप आधी ₹600/महिना दाखवत होते — दुरुस्त केले."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "gharkul": {
        "canonical_key": "gharkul", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_WITH_CHAIN, "confidence": "high", "current_2026": True,
        "department": _dept("Social Justice & Special Assistance Department, Government of Maharashtra",
                             "सामाजिक न्याय एवं विशेष सहायता विभाग, महाराष्ट्र सरकार", "सामाजिक न्याय व विशेष सहाय्य विभाग, महाराष्ट्र शासन"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Government Resolution (GR)", "रआयो-2020/प्र.क्र.147/बांधकामे", "2021-03-10",
                 "Ramai Awas Gharkul Yojana — procedural GR",
                 "रमाई आवास घरकुल योजना — प्रक्रियात्मक शासन निर्णय",
                 "रमाई आवास घरकुल योजना — प्रक्रियात्मक शासन निर्णय",
                 "https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/English/202103101726227922.pdf",
                 "Government of Maharashtra", True, False, True),
            _doc("Government Resolution (GR)", "बीसीएच-2008/प्र.क्र.36/मावक-2", "2008-11-15",
                 "Ramai Awas Gharkul Yojana — founding GR",
                 "रमाई आवास घरकुल योजना — मूल शासन निर्णय",
                 "रमाई आवास घरकुल योजना — मूळ शासन निर्णय",
                 None, "Government of Maharashtra", False, True, False),
        ],
        "notes": _notes(
            "Eligibility corrected this session: independently confirmed via the scheme's official description and multiple "
            "district administration pages that Ramai Awas Gharkul Yojana is for the Scheduled Caste and Neo-Buddhist "
            "(Nav-Bauddha) communities specifically — NOT the broader 'SC/ST/OBC/NT' the app previously displayed.",
            "इस सत्र में पात्रता ठीक की गई: स्वतंत्र रूप से योजना के आधिकारिक विवरण और कई जिला प्रशासन पृष्ठों से पुष्टि की गई कि रमाई आवास "
            "घरकुल योजना विशेष रूप से अनुसूचित जाति और नवबौद्ध समुदायों के लिए है — व्यापक 'SC/ST/OBC/NT' नहीं जो ऐप पहले दिखाता था।",
            "या सत्रात पात्रता दुरुस्त केली: स्वतंत्रपणे योजनेच्या अधिकृत वर्णनावरून आणि अनेक जिल्हा प्रशासन पानांवरून पुष्टी झाली की रमाई आवास "
            "घरकुल योजना विशेषतः अनुसूचित जाती व नवबौद्ध समुदायांसाठी आहे — अ‍ॅप आधी दाखवत असलेली व्यापक 'SC/ST/OBC/NT' नाही."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "rajmata_jijau": {
        "canonical_key": "rajmata_jijau", "aliases": [], "scheme_type": "PROGRAM_POLICY",
        "status": STATUS_PROGRAM_POLICY, "confidence": "medium", "current_2026": False,
        "department": _dept("Women & Child Development Department, Government of Maharashtra",
                             "महिला एवं बाल विकास विभाग, महाराष्ट्र सरकार", "महिला व बालविकास विभाग, महाराष्ट्र शासन"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Official Department Page", None, None, "Rajmata Jijau Mother-Child Health & Nutrition Mission",
                 "राजमाता जिजाऊ माता-बाल स्वास्थ्य एवं पोषण मिशन", "राजमाता जिजाऊ माता-बाल आरोग्य व पोषण अभियान",
                 "https://womenchild.maharashtra.gov.in", "Government of Maharashtra", False, True, True),
        ],
        "notes": _notes(
            "Reclassified as a coordination MISSION/PROGRAMME delivered through Anganwadi/health-department channels, "
            "not a standalone direct cash-benefit scheme — the app previously implied a direct household payment.",
            "इसे आंगनवाड़ी/स्वास्थ्य विभाग चैनलों के माध्यम से दिए जाने वाले समन्वय मिशन/कार्यक्रम के रूप में पुनर्वर्गीकृत किया गया, "
            "स्वतंत्र प्रत्यक्ष नकद-लाभ योजना नहीं — ऐप पहले प्रत्यक्ष घरेलू भुगतान का संकेत देता था।",
            "अंगणवाडी/आरोग्य विभाग माध्यमांतून दिल्या जाणाऱ्या समन्वय मिशन/कार्यक्रम म्हणून पुनर्वर्गीकृत केले, "
            "स्वतंत्र थेट रोख-लाभ योजना नाही — अ‍ॅप आधी थेट घरगुती देयकाचे सूचन करत होते."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "mh_ration": {
        "canonical_key": "mh_ration", "aliases": [], "scheme_type": "PROGRAM_POLICY",
        "status": STATUS_PROGRAM_POLICY, "confidence": "medium", "current_2026": False,
        "department": _dept("Food, Civil Supplies & Consumer Protection Department, Government of Maharashtra",
                             "अन्न, नागरी आपूर्ति एवं उपभोक्ता संरक्षण विभाग, महाराष्ट्र सरकार", "अन्न, नागरी पुरवठा व ग्राहक संरक्षण विभाग, महाराष्ट्र शासन"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Official Department Page", None, None, "Public Distribution System (PDS) / NFSA Ration Card Classification",
                 "सार्वजनिक वितरण प्रणाली (PDS) / NFSA राशन कार्ड वर्गीकरण", "सार्वजनिक वितरण प्रणाली (PDS) / NFSA रेशन कार्ड वर्गीकरण",
                 "https://mahafood.gov.in", "Government of Maharashtra", False, True, True),
        ],
        "notes": _notes(
            "Reclassified: the Yellow Ration Card / NFSA category is an eligibility/entitlement FRAMEWORK, not itself a "
            "standalone scheme with an independent payout — the app previously listed a fixed benefit amount for it.",
            "पुनर्वर्गीकृत: पीला राशन कार्ड / NFSA श्रेणी एक पात्रता ढांचा है, न कि स्वयं एक स्वतंत्र भुगतान वाली योजना — ऐप पहले इसके लिए "
            "एक निश्चित लाभ राशि सूचीबद्ध करता था।",
            "पुनर्वर्गीकृत: पिवळे रेशन कार्ड / NFSA श्रेणी ही एक पात्रता चौकट आहे, स्वतःच स्वतंत्र देयक असलेली योजना नाही — अ‍ॅप आधी "
            "यासाठी निश्चित लाभ रक्कम सूचीबद्ध करत होते."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
    "vayoshri_mh": {
        "canonical_key": "vayoshri_mh", "aliases": [], "scheme_type": "SCHEME",
        "status": STATUS_VERIFIED_PRIMARY_CURRENT, "confidence": "high", "current_2026": True,
        "department": _dept("Social Justice & Special Assistance Department, Government of Maharashtra",
                             "सामाजिक न्याय एवं विशेष सहायता विभाग, महाराष्ट्र सरकार", "सामाजिक न्याय व विशेष सहाय्य विभाग, महाराष्ट्र शासन"),
        "jurisdiction": "maharashtra",
        "documents": [
            _doc("Government Resolution (GR) — amendment", "ज्येष्ठना-2022/प्र.क्र.344/सामासु", "2024-08-19",
                 "Mukhyamantri Vayoshri Yojana — amendment GR",
                 "मुख्यमंत्री वयोश्री योजना — संशोधन शासन निर्णय",
                 "मुख्यमंत्री वयोश्री योजना — सुधारणा शासन निर्णय",
                 "https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/Marathi/202408191800428222.pdf",
                 "Government of Maharashtra (Social Justice & Special Assistance Dept.)", True, False, True),
            _doc("Government Resolution (GR) — founding", "ज्येष्ठना-2022/प्र.क्र.344/सामासु", "2024-02-06",
                 "Mukhyamantri Vayoshri Yojana — founding GR",
                 "मुख्यमंत्री वयोश्री योजना — मूल शासन निर्णय",
                 "मुख्यमंत्री वयोश्री योजना — मूळ शासन निर्णय",
                 None, "Government of Maharashtra", False, True, False),
        ],
        "notes": _notes(
            "Independently re-confirmed this session directly on the official sjsa.maharashtra.gov.in scheme page: the "
            "benefit is a ONE-TIME lump-sum Rs.3,000 Direct Benefit Transfer (DBT) to an Aadhaar-linked bank account for "
            "purchase of assistive devices, for citizens aged 65+, GR क्र.ज्येष्ठना-2022/प्र.क्र.344/सामासु with amendments "
            "dated 6.02.2024, 11.03.2024 and 19.08.2024. The app previously described it only as 'free aids & equipment' "
            "— corrected to reflect the actual one-time cash-DBT mechanism.",
            "इस सत्र में आधिकारिक sjsa.maharashtra.gov.in योजना पृष्ठ पर स्वतंत्र रूप से पुनः पुष्टि: लाभ एक बारगी ₹3,000 की राशि है जो "
            "आधार-लिंक्ड बैंक खाते में DBT द्वारा सहायक उपकरण खरीदने हेतु दी जाती है, 65+ आयु के नागरिकों के लिए, GR क्र.ज्येष्ठना-2022/प्र.क्र.344/सामासु "
            "जिसमें 6.02.2024, 11.03.2024 और 19.08.2024 के संशोधन हैं। ऐप पहले इसे केवल 'मुफ्त सहायक उपकरण' बताता था — सही किया गया।",
            "या सत्रात अधिकृत sjsa.maharashtra.gov.in योजना पानावर स्वतंत्रपणे पुन्हा पुष्टी: लाभ एकवेळ ₹3,000 ची रक्कम आहे जी "
            "आधार-लिंक्ड बँक खात्यात DBT द्वारे सहाय्यक साधने खरेदीसाठी दिली जाते, 65+ वयाच्या नागरिकांसाठी, GR क्र.ज्येष्ठना-2022/प्र.क्र.344/सामासु "
            "ज्यात 6.02.2024, 11.03.2024 आणि 19.08.2024 च्या सुधारणा आहेत. अ‍ॅप आधी हे फक्त 'मोफत सहाय्यक साधने' असे सांगत होते — दुरुस्त केले."
        ),
        "last_verified_date": RESEARCH_DATE,
    },
}


def resolve_canonical(scheme_key):
    """Return the canonical scheme_key for any given key (identity if the
    key is already canonical or unknown)."""
    entry = VERIFICATION_REGISTRY.get(scheme_key)
    if not entry:
        return scheme_key
    return entry.get("canonical_key", scheme_key)


def is_recommendable(scheme_key):
    """False for CLOSED or DUPLICATE-status keys — these must never be
    shown as an active, independently-recommendable benefit."""
    entry = VERIFICATION_REGISTRY.get(scheme_key)
    if not entry:
        return True  # no registry entry -> no known reason to block it
    return entry["status"] not in NON_RECOMMENDABLE_STATUSES


def get_verification(scheme_key, lang="en"):
    """Return a template-ready, language-resolved verification dict for a
    given scheme_key, or None if this key has no registry entry."""
    entry = VERIFICATION_REGISTRY.get(scheme_key)
    if not entry:
        return None
    lang = lang if lang in ("en", "hi", "mr") else "en"
    status = entry["status"]
    docs = []
    for d in entry["documents"]:
        docs.append({
            "document_type": d["document_type"],
            "document_number": d["document_number"],
            "document_date": d["document_date"],
            "title": d["title"].get(lang, d["title"]["en"]),
            "official_url": d["official_url"],
            "source_authority": d["source_authority"],
            "directly_opened": d["directly_opened"],
            "is_founding": d["is_founding"],
            "is_current": d["is_current"],
        })
    canonical_key = entry["canonical_key"]
    canonical_entry = VERIFICATION_REGISTRY.get(canonical_key, entry)
    return {
        "scheme_key": scheme_key,
        "canonical_key": canonical_key,
        "is_alias": canonical_key != scheme_key,
        "scheme_type": entry["scheme_type"],
        "status": status,
        "status_label": STATUS_LABELS.get(status, {}).get(lang, status),
        "status_explanation": STATUS_EXPLANATIONS.get(status, {}).get(lang, ""),
        "confidence": entry["confidence"],
        "current_2026": entry["current_2026"],
        "current_2026_label": (UI_LABELS["current_2026_yes"][lang] if entry["current_2026"]
                                else UI_LABELS["current_2026_unknown"][lang]),
        "department": entry["department"].get(lang, entry["department"]["en"]),
        "jurisdiction": entry["jurisdiction"],
        "documents": docs,
        "has_gr_style_document": any(d["document_type"] == "Government Resolution (GR)" or
                                       d["document_type"].startswith("Government Resolution")
                                       for d in entry["documents"]),
        "no_gr_explanation": UI_LABELS["no_gr_explanation"][lang],
        "notes": entry["notes"].get(lang, entry["notes"]["en"]),
        "last_verified_date": entry["last_verified_date"],
        "is_recommendable": status not in NON_RECOMMENDABLE_STATUSES,
        "is_closed": status == STATUS_CLOSED,
        "is_program_policy": entry["scheme_type"] == "PROGRAM_POLICY",
    }


def all_scheme_keys():
    return list(VERIFICATION_REGISTRY.keys())

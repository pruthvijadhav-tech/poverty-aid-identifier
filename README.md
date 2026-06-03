# Poverty Aid Identifier 🇮🇳

A multilingual civic-tech web app that helps identify poor/needy persons and recommends applicable government schemes, with anti-corruption complaint tracking and real-time heatmap.

## Features

- **Multilingual** — English, Hindi, Marathi
- **Need Score Calculator** — AI-based poverty scoring (0-175)
- **16 Government Schemes** — PM Jan Arogya, PM Awas, Ayushman Bharat and more
- **Corruption Complaint System** — Amazon-style tracking with unique IDs
- **Real-Time Heatmap** — Live corruption complaint map of India
- **Admin Dashboard** — Secure login, activity logs, security alerts
- **PWA Support** — Installable on phone, works offline
- **Fake Complaint Detection** — Auto-flags suspicious submissions
- **Rate Limiting** — Prevents spam and abuse
- **Security Logging** — All access logged with IP, browser, device

## Tech Stack

- **Backend:** Python Flask
- **Database:** SQLite
- **Frontend:** HTML, CSS, JavaScript
- **Map:** Leaflet.js + OpenStreetMap
- **Security:** SHA256 password hashing, session management

## Setup

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/poverty-aid-identifier.git
cd poverty-aid-identifier

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py

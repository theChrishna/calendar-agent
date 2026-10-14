# 🗓️ Calendar Automation Agent

An intelligent, interactive calendar assistant built with **Chainlit** and **Google Gemini** that parses plain-text requests, photos, and document notices (PDFs) into Google Calendar events.

## ✨ Features

- **Natural Language Scheduling:** Create, view, and update events with simple sentences (*"Schedule a team sync tomorrow at 3 PM"*).
- **Document & Image Parsing:** Upload photos or PDF notices; the assistant automatically extracts event titles, dates, and times.
- **Conflict Checking & Draft Confirmation:** Checks your Google Calendar for duplicates and conflicts, provides a clean draft, and only creates the event once you confirm.
- **Live Streaming & Fast Response:** Powered by `gemini-3.1-flash-lite` with real-time token streaming and cached Google Calendar service.
- **Persistent Chat History:** Seamlessly saves all past chats and event threads in a local SQLite database (`chainlit.db`), allowing you to review or resume any conversation from the sidebar.

---

## 🚀 Getting Started

### 1. Prerequisites

- Python 3.10+
- A Google Cloud Project with the **Google Calendar API** enabled
- A Google Gemini API key

### 2. Installation

Clone the repository and set up a virtual environment:

```bash
git clone https://github.com/theChrishna/calendar-agent.git
cd calendar-agent

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Google Calendar API Setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Google Calendar API**.
3. Configure the **OAuth Consent Screen** (set user type to *External*, add your Google account as a *Test User*).
4. Create **OAuth 2.0 Client IDs** (Application type: *Desktop App*).
5. Download the client credentials JSON and save it in the project root as `credentials.json`.

### 4. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Fill in your configuration:

```env
GEMINI_API_KEY=your_gemini_api_key_here
TIMEZONE=Asia/Kolkata
GEMINI_MODEL=gemini-3.1-flash-lite
CHAINLIT_AUTH_SECRET=your_chainlit_auth_secret_here
CHAINLIT_CUSTOM_AUTH=true
```

*(You can generate a random auth secret with `python -c "import secrets; print(secrets.token_hex(32))"`).*

### 5. Run the Application

Start the Chainlit server:

```bash
chainlit run app.py -w
# or simply
python app.py
```

On your first run, a browser tab will open asking you to authorize access to your Google Calendar. Once authorized, `token.json` is saved locally, and your agent is ready at [http://localhost:8000](http://localhost:8000)!

---

## 🛠️ Tech Stack

- **Framework:** [Chainlit](https://github.com/Chainlit/chainlit)
- **AI Model:** Google Gemini (`gemini-3.1-flash-lite`) via `google-genai` SDK
- **Calendar Integration:** Google Calendar API (`google-api-python-client`)
- **Data Persistence:** SQLAlchemy + SQLite (`aiosqlite`)

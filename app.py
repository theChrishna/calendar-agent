import datetime as dt
import os
import sqlite3
from typing import Optional
from zoneinfo import ZoneInfo


import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from dotenv import load_dotenv
from google import genai
from google.auth.transport.requests import Request
from google.genai import types
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()


# ---------- Database & Chat History Persistence ----------
def init_db():
    con = sqlite3.connect("chainlit.db")
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        identifier TEXT NOT NULL UNIQUE,
        metadata TEXT NOT NULL,
        createdAt TEXT
    );

    CREATE TABLE IF NOT EXISTS threads (
        id TEXT PRIMARY KEY,
        createdAt TEXT,
        name TEXT,
        userId TEXT,
        userIdentifier TEXT,
        tags TEXT,
        metadata TEXT,
        FOREIGN KEY (userId) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS steps (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        threadId TEXT NOT NULL,
        parentId TEXT,
        streaming INTEGER NOT NULL,
        waitForAnswer INTEGER,
        isError INTEGER,
        metadata TEXT,
        tags TEXT,
        input TEXT,
        output TEXT,
        createdAt TEXT,
        command TEXT,
        start TEXT,
        end TEXT,
        generation TEXT,
        showInput TEXT,
        language TEXT,
        indent INTEGER,
        defaultOpen INTEGER,
        autoCollapse INTEGER,
        icon TEXT,
        modes TEXT,
        feedback TEXT,
        forId TEXT,
        FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS elements (
        id TEXT PRIMARY KEY,
        threadId TEXT,
        type TEXT,
        url TEXT,
        chainlitKey TEXT,
        name TEXT NOT NULL,
        display TEXT,
        objectKey TEXT,
        size TEXT,
        page INTEGER,
        language TEXT,
        forId TEXT,
        mime TEXT,
        props TEXT,
        path TEXT,
        autoPlay INTEGER,
        playerConfig TEXT,
        FOREIGN KEY (threadId) REFERENCES threads(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS feedbacks (
        id TEXT PRIMARY KEY,
        forId TEXT NOT NULL,
        threadId TEXT,
        value INTEGER NOT NULL,
        comment TEXT,
        strategy TEXT
    );
    """)

    # Ensure columns exist if table was already created
    for col, col_type in [("autoCollapse", "INTEGER"), ("icon", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE steps ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    for col, col_type in [("path", "TEXT"), ("autoPlay", "INTEGER"), ("playerConfig", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE elements ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    con.commit()
    con.close()



init_db()


@cl.data_layer
def get_data_layer():
    return SQLAlchemyDataLayer(conninfo="sqlite+aiosqlite:///chainlit.db")


@cl.oauth_callback
def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: dict,
    default_user: cl.User,
) -> Optional[cl.User]:
    return default_user


@cl.password_auth_callback
def password_auth_callback(username: str, password: str) -> Optional[cl.User]:
    admin_user = os.getenv("AUTH_USER", "krisminds1@gmail.com")
    admin_pass = os.getenv("AUTH_PASSWORD", "admin")
    if username == admin_user and password == admin_pass:
        return cl.User(identifier=username, display_name=username, metadata={"role": "admin"})
    return None



SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TZ = os.getenv("TIMEZONE", "Asia/Kolkata")
# Ordered list of fallback models. Set GEMINI_MODEL in .env to pin a specific one.
_PRIMARY = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
MODELS = [_PRIMARY] + [m for m in [
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
] if m != _PRIMARY]
gclient = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_CALENDAR_SERVICE = None


# ---------- Google Calendar ----------
def get_service():
    global _CALENDAR_SERVICE
    if _CALENDAR_SERVICE is not None and getattr(_CALENDAR_SERVICE, "_http", None) and getattr(_CALENDAR_SERVICE._http, "credentials", None) and _CALENDAR_SERVICE._http.credentials.valid:
        return _CALENDAR_SERVICE

    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    _CALENDAR_SERVICE = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _CALENDAR_SERVICE


def list_events(time_min: str, time_max: str):
    svc = get_service()
    res = svc.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()
    return [
        {
            "id": e["id"],
            "title": e.get("summary"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
        }
        for e in res.get("items", [])
    ]


def build_body(a: dict) -> dict:
    body = {}
    if "title" in a:
        body["summary"] = a["title"]
    if "location" in a:
        body["location"] = a["location"]
    if "description" in a:
        body["description"] = a["description"]
    if "start" in a:
        if a.get("all_day"):
            start = dt.date.fromisoformat(a["start"][:10])
            end = dt.date.fromisoformat((a.get("end") or a["start"])[:10])
            body["start"] = {"date": start.isoformat()}
            body["end"] = {"date": (end + dt.timedelta(days=1)).isoformat()}
        else:
            start = a["start"]
            end = a.get("end") or (
                dt.datetime.fromisoformat(start) + dt.timedelta(hours=1)
            ).isoformat()
            body["start"] = {"dateTime": start, "timeZone": TZ}
            body["end"] = {"dateTime": end, "timeZone": TZ}
    if "reminder_minutes" in a:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": int(a["reminder_minutes"])}],
        }
    return body


def create_event(**a):
    e = get_service().events().insert(calendarId="primary", body=build_body(a)).execute()
    return {"id": e["id"], "link": e.get("htmlLink")}


def update_event(event_id: str, **a):
    e = get_service().events().patch(
        calendarId="primary", eventId=event_id, body=build_body(a)
    ).execute()
    return {"id": e["id"], "link": e.get("htmlLink")}


EVENT_PROPS = {
    "title": {"type": "string"},
    "start": {
        "type": "string",
        "description": "ISO 8601. Timed: 2026-10-17T16:00:00. All-day: 2026-10-17",
    },
    "end": {
        "type": "string",
        "description": "ISO 8601. For all-day multi-day events, the LAST day (inclusive). Optional.",
    },
    "all_day": {"type": "boolean"},
    "location": {"type": "string"},
    "description": {"type": "string"},
    "reminder_minutes": {
        "type": "integer",
        "description": "Popup reminder, minutes before start (1440 = one day before)",
    },
}

TOOLS = [
    {
        "name": "list_events",
        "description": "List calendar events in a time range. Use to check duplicates/conflicts before creating.",
        "input_schema": {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "RFC3339 with offset, e.g. 2026-10-17T00:00:00+05:30"},
                "time_max": {"type": "string", "description": "RFC3339 with offset"},
            },
            "required": ["time_min", "time_max"],
        },
    },
    {
        "name": "create_event",
        "description": "Create one event. Only call AFTER the user confirmed the draft.",
        "input_schema": {
            "type": "object",
            "properties": EVENT_PROPS,
            "required": ["title", "start"],
        },
    },
    {
        "name": "update_event",
        "description": "Update fields of an existing event by id (from list_events or create_event).",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}, **EVENT_PROPS},
            "required": ["event_id"],
        },
    },
]

IMPL = {
    "list_events": list_events,
    "create_event": create_event,
    "update_event": update_event,
}


def system_prompt() -> str:
    now = dt.datetime.now(ZoneInfo(TZ))
    return f"""You are a calendar assistant. Current date/time: {now.strftime('%A, %d %B %Y, %H:%M')} ({TZ}).
The user sends school notices (text, photo or PDF) or casual sentences. Turn them into Google Calendar events.

Rules:
- Resolve relative dates ("next Friday") from the current date above. If the year is missing, use the next upcoming occurrence.
- A notice may hold several events. Extract all of them.
- Deadlines ("submit by 20th") become all-day events with reminder_minutes=1440.
- If no end time is given, assume 1 hour for timed events.
- If a key detail is truly missing or ambiguous (date, AM/PM), ask ONE short question instead of guessing.
- First call list_events for the relevant day(s) to check for duplicates or conflicts.
- Then show a short draft list (title, date, time, location) and ask for confirmation. Do NOT create events until the user says yes.
- After the user confirms, call create_event for each, then reply briefly with what was added and the links.
- Edits like "make it 3:30" change the draft (or call update_event if already created).
- Keep replies short."""


# ---------- Gemini tool declarations (converted from the schemas above) ----------
def _upper_types(node):
    """Gemini's schema wants types like STRING/OBJECT; convert recursively."""
    if isinstance(node, dict):
        return {
            k: (v.upper() if k == "type" and isinstance(v, str) else _upper_types(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_upper_types(x) for x in node]
    return node


GEMINI_TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=_upper_types(t["input_schema"]),
            )
            for t in TOOLS
        ]
    )
]


# ---------- Chat ----------
@cl.on_chat_start
async def start():
    cl.user_session.set("history", [])
    user = cl.user_session.get("user")
    name = (user.display_name or user.identifier) if user else "there"
    await cl.Message(
        f"Hi {name}! Send me an event in plain words, or drop in a notice (photo/PDF/text). "
        "I'll show you what I found before adding anything to your calendar."
    ).send()



@cl.on_chat_resume
async def on_chat_resume(thread: cl.types.ThreadDict):
    history = []
    for step in thread.get("steps", []):
        if step.get("type") == "user_message":
            text = step.get("output") or step.get("input") or ""
            if text:
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        elif step.get("type") == "assistant_message":
            text = step.get("output") or ""
            if text:
                history.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
    cl.user_session.set("history", history)



def file_parts(elements):
    parts = []
    for el in elements or []:
        mime = el.mime or ""
        if not el.path or not (mime.startswith("image/") or mime == "application/pdf"):
            continue
        with open(el.path, "rb") as f:
            parts.append(types.Part.from_bytes(data=f.read(), mime_type=mime))
    return parts


STEP_TITLES = {
    "list_events": "Checking calendar...",
    "create_event": "Adding to Google Calendar...",
    "update_event": "Updating Google Calendar event...",
}


@cl.on_message
async def on_message(msg: cl.Message):
    history = cl.user_session.get("history")
    if history is None:
        history = []
        cl.user_session.set("history", history)

    parts = file_parts(msg.elements)
    parts.append(types.Part.from_text(text=msg.content or "(see attached notice)"))
    history.append(types.Content(role="user", parts=parts))

    # Keep recent conversation context to avoid unbounded prompt growth
    if len(history) > 20:
        history = history[-20:]
        cl.user_session.set("history", history)

    while True:
        config = types.GenerateContentConfig(
            system_instruction=system_prompt(),
            tools=GEMINI_TOOLS,
        )

        all_calls = []
        model_parts = []
        stream_msg = None
        last_err = None

        for model in MODELS:
            try:
                async for chunk in await gclient.aio.models.generate_content_stream(
                    model=model, contents=history, config=config
                ):
                    if chunk.function_calls:
                        all_calls.extend(chunk.function_calls)
                    if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                        for p in chunk.candidates[0].content.parts:
                            text = getattr(p, "text", None)
                            if text:
                                if stream_msg is None:
                                    stream_msg = cl.Message(content="")
                                    await stream_msg.send()
                                await stream_msg.stream_token(text)
                            if text == "":
                                continue
                            model_parts.append(p)
                break  # success
            except Exception as e:
                last_err = e
                err_str = str(e)
                if any(code in err_str for code in ("503", "429", "404", "UNAVAILABLE", "NOT_FOUND", "RESOURCE_EXHAUSTED")):
                    continue
                if stream_msg:
                    try:
                        await stream_msg.remove()
                    except Exception:
                        pass
                await cl.Message(f"Gemini error: {e}").send()
                return

        if not model_parts and not all_calls:
            if stream_msg:
                try:
                    await stream_msg.remove()
                except Exception:
                    pass
            await cl.Message(f"All models unavailable. Last error: {last_err}").send()
            return

        if stream_msg:
            await stream_msg.update()

        history.append(types.Content(role="model", parts=model_parts))

        if not all_calls:
            return  # text already streamed to user

        # Execute tool calls
        result_parts = []
        for fc in all_calls:
            args = dict(fc.args or {})
            title = STEP_TITLES.get(fc.name, fc.name)
            async with cl.Step(name=title) as step:
                step.input = str(args)
                try:
                    out = await cl.make_async(IMPL[fc.name])(**args)
                    step.output = str(out)
                    response = {"result": out}
                except Exception as e:
                    step.output = f"Error: {e}"
                    response = {"error": str(e)}
            result_parts.append(types.Part.from_function_response(name=fc.name, response=response))
        history.append(types.Content(role="user", parts=result_parts))


if __name__ == "__main__":
    from chainlit.cli import run_chainlit
    run_chainlit(__file__)



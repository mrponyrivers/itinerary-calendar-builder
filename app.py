import os
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Dict, Tuple

import pandas as pd
import streamlit as st
from dateutil.parser import parse as dtparse


# -----------------------------
# Sample loader
# -----------------------------
def load_sample_text(path: str = "sample_input.txt") -> str:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


# -----------------------------
# Data model
# -----------------------------
@dataclass
class Job:
    title: str
    location: str
    start_date: date
    end_date: date
    status: str
    kind: str          # WORK or HOLD (editable)
    notes: str = ""
    include_travel: bool = True  # override travel per job/run
    work_start_hour: Optional[int] = None
    work_end_hour: Optional[int] = None


# -----------------------------
# Parsing
# -----------------------------
STATUS_WORDS = ["Confirmed", "Hold", "First Option", "Pending Signature", "Pending", "Option"]

def normalize_ws(s: str) -> str:
    return " ".join((s or "").split()).strip()

def safe_date(s: str) -> Optional[date]:
    s = normalize_ws(s)
    if not s:
        return None
    try:
        return dtparse(s, dayfirst=False).date()
    except Exception:
        return None

def classify_kind(status: str) -> str:
    s = normalize_ws(status).lower()
    if "hold" in s:
        return "HOLD"
    return "WORK"

def normalize_location(loc: str) -> str:
    x = normalize_ws(loc).lower().replace(".", "")
    aliases = {
        "nyc": "new york",
        "new york city": "new york",
        "milan italy": "milan, italy",
        "paris france": "paris",
        "tbd": "tbd",
        "na": "tbd",
        "-": "tbd",
        "": "tbd",
    }
    return aliases.get(x, x)

def is_unknown_location(loc: str) -> bool:
    return normalize_location(loc) in {"tbd", "unknown"}

def parse_block(block: str) -> Optional[Job]:
    lines = [ln.rstrip() for ln in block.splitlines() if normalize_ws(ln)]
    if not lines:
        return None

    title = normalize_ws(lines[0])
    location = ""
    start_d = None
    end_d = None
    status = ""
    notes_lines = []

    for ln in lines[1:]:
        l = normalize_ws(ln)
        low = l.lower()

        if low.startswith("location:"):
            location = normalize_ws(l.split(":", 1)[1])
            continue

        if low.startswith("dates:"):
            rhs = normalize_ws(l.split(":", 1)[1])
            parts = [normalize_ws(p) for p in rhs.split("to")]
            if len(parts) == 2:
                start_d = safe_date(parts[0])
                end_d = safe_date(parts[1])
            elif len(parts) == 1:
                start_d = safe_date(parts[0])
                end_d = start_d
            continue

        found_status = False
        for w in STATUS_WORDS:
            if low == w.lower():
                status = w
                found_status = True
                break
        if found_status:
            continue

        notes_lines.append(l)

    if not start_d or not end_d:
        return None

    status = status or "WORK"
    kind = classify_kind(status)

    if not location:
        location = "TBD"

    return Job(
        title=title,
        location=location,
        start_date=start_d,
        end_date=end_d,
        status=status,
        kind=kind,
        notes=normalize_ws(" ".join(notes_lines)),
        include_travel=True,
    )

def parse_jobs(text: str) -> List[Job]:
    text = text.replace("\r\n", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    jobs: List[Job] = []
    for b in blocks:
        jb = parse_block(b)
        if jb:
            jobs.append(jb)
    return jobs


# -----------------------------
# ICS helpers
# -----------------------------
def dt_to_ics(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")

def make_uid(seed: str) -> str:
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"{h}@itinerary-calendar.local"

def escape_ics(text: str) -> str:
    t = (text or "").replace("\\", "\\\\").replace("\n", "\\n")
    t = t.replace(",", "\\,").replace(";", "\\;")
    return t

def add_runid(desc: str, run_id: str) -> str:
    tag = f"RunID: {run_id}"
    if tag in (desc or ""):
        return desc
    if (desc or "").strip():
        return f"{desc}\n\n{tag}"
    return tag

def vevent_timed(summary: str, start_dt: datetime, end_dt: datetime, location: str, description: str, uid: str) -> str:
    return "\n".join([
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dt_to_ics(datetime.utcnow())}",
        f"SUMMARY:{escape_ics(summary)}",
        f"DTSTART:{dt_to_ics(start_dt)}",
        f"DTEND:{dt_to_ics(end_dt)}",
        f"LOCATION:{escape_ics(location)}",
        f"DESCRIPTION:{escape_ics(description)}",
        "END:VEVENT",
    ])

def ics_wrap(events: List[str], cal_name: str) -> str:
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Itinerary Calendar Builder//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{escape_ics(cal_name)}",
    ]
    footer = ["END:VCALENDAR"]
    return "\n".join(header + events + footer) + "\n"


# -----------------------------
# Group runs (same city blocks)
# -----------------------------
def job_sort_key(j: Job):
    return (j.start_date, j.end_date, j.title.lower())

def merge_city_runs(jobs: List[Job]) -> List[Dict]:
    """
    Returns runs like:
    {city_norm, city_label, start_date, end_date, jobs:[...], include_travel_any:bool}
    A run is consecutive jobs (in time order) in the same normalized location.
    """
    jobs_sorted = sorted(jobs, key=job_sort_key)
    runs = []

    cur = None
    for j in jobs_sorted:
        city_norm = normalize_location(j.location)
        city_label = j.location

        if cur is None:
            cur = {
                "city_norm": city_norm,
                "city_label": city_label,
                "start_date": j.start_date,
                "end_date": j.end_date,
                "jobs": [j],
                "include_travel_any": bool(j.include_travel),
            }
            continue

        if city_norm == cur["city_norm"]:
            cur["start_date"] = min(cur["start_date"], j.start_date)
            cur["end_date"] = max(cur["end_date"], j.end_date)
            cur["jobs"].append(j)
            cur["include_travel_any"] = cur["include_travel_any"] or bool(j.include_travel)
        else:
            runs.append(cur)
            cur = {
                "city_norm": city_norm,
                "city_label": city_label,
                "start_date": j.start_date,
                "end_date": j.end_date,
                "jobs": [j],
                "include_travel_any": bool(j.include_travel),
            }

    if cur is not None:
        runs.append(cur)

    return runs


# -----------------------------
# Travel logic (V4)
# -----------------------------
def compute_trip_boundary_travel(
    jobs: List[Job],
    home_base: str,
    travel_mode: str,         # AUTO / MANUAL / OFF
    travel_start_hour: int,
    travel_end_hour: int,
    run_id: str,
) -> Tuple[List[str], List[str]]:
    """
    Creates ONE travel-in day before first job of a non-home, non-TBD run,
    and ONE travel-out day after last job of that run.

    Returns (travel_events, warnings)
    """
    if travel_mode == "OFF":
        return [], []

    home_norm = normalize_location(home_base)
    runs = merge_city_runs(jobs)

    travel_events = []
    warnings = []

    for r in runs:
        city_norm = r["city_norm"]
        if city_norm == home_norm:
            continue
        if is_unknown_location(r["city_label"]) or city_norm == "tbd":
            continue

        # In MANUAL mode, only create travel if user wants it for this run
        if travel_mode == "MANUAL" and not r["include_travel_any"]:
            continue

        trip_in_day = r["start_date"] - timedelta(days=1)
        trip_out_day = r["end_date"] + timedelta(days=1)

        in_start = datetime.combine(trip_in_day, time(travel_start_hour, 0))
        in_end = datetime.combine(trip_in_day, time(travel_end_hour, 0))
        if in_end <= in_start:
            in_end = in_start + timedelta(hours=2)

        out_start = datetime.combine(trip_out_day, time(travel_start_hour, 0))
        out_end = datetime.combine(trip_out_day, time(travel_end_hour, 0))
        if out_end <= out_start:
            out_end = out_start + timedelta(hours=2)

        desc_in = add_runid("Auto travel-in day (trip boundary).", run_id)
        desc_out = add_runid("Auto travel-out day (trip boundary).", run_id)

        uid_in = make_uid(f"TRAVELIN|{run_id}|{home_norm}->{city_norm}|{trip_in_day.isoformat()}")
        uid_out = make_uid(f"TRAVELOUT|{run_id}|{city_norm}->{home_norm}|{trip_out_day.isoformat()}")

        travel_events.append(
            vevent_timed(
                f"TRAVEL IN: {home_base} → {r['city_label']}",
                in_start,
                in_end,
                f"{home_base} → {r['city_label']}",
                desc_in,
                uid_in
            )
        )
        travel_events.append(
            vevent_timed(
                f"TRAVEL OUT: {r['city_label']} → {home_base}",
                out_start,
                out_end,
                f"{r['city_label']} → {home_base}",
                desc_out,
                uid_out
            )
        )

    return travel_events, warnings


# -----------------------------
# Event builders
# -----------------------------
def build_work_events(jobs: List[Job], default_start: int, default_end: int, run_id: str) -> List[str]:
    events = []
    for j in jobs:
        if j.kind != "WORK":
            continue

        start_h = j.work_start_hour if j.work_start_hour is not None else default_start
        end_h = j.work_end_hour if j.work_end_hour is not None else default_end
        if end_h <= start_h:
            end_h = min(23, start_h + 8)

        desc = add_runid(j.notes or f"Status: {j.status}", run_id)

        d = j.start_date
        while d <= j.end_date:
            start_dt = datetime.combine(d, time(start_h, 0))
            end_dt = datetime.combine(d, time(end_h, 0))
            uid = make_uid(f"WORK|{run_id}|{j.title}|{start_dt.isoformat()}|{end_dt.isoformat()}")
            events.append(vevent_timed(f"WORK: {j.title}", start_dt, end_dt, j.location, desc, uid))
            d += timedelta(days=1)

    return events

def build_hold_events(jobs: List[Job], hold_start: int, hold_end: int, run_id: str) -> List[str]:
    events = []
    for j in jobs:
        if j.kind != "HOLD":
            continue

        desc = add_runid(j.notes or f"Status: {j.status}", run_id)

        d = j.start_date
        while d <= j.end_date:
            start_dt = datetime.combine(d, time(hold_start, 0))
            end_dt = datetime.combine(d, time(hold_end, 0))
            uid = make_uid(f"HOLD|{run_id}|{j.title}|{start_dt.isoformat()}|{end_dt.isoformat()}")
            events.append(vevent_timed(f"HOLD: {j.title}", start_dt, end_dt, j.location, desc, uid))
            d += timedelta(days=1)

    return events


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Itinerary Calendar Builder (V4)", page_icon="🗓️", layout="wide")
st.title("🗓️ Itinerary Calendar Builder (V4)")
st.caption(
    "Travel is only created at trip boundaries: 1 travel-in day before first job, 1 travel-out day after last job, "
    "only for non-home cities. No between-job travel in same city."
)

# Session state init
if "jobs" not in st.session_state:
    st.session_state.jobs = []
if "raw_input" not in st.session_state:
    st.session_state.raw_input = ""

with st.sidebar:
    st.header("Batch Tag (Run ID)")
    default_run = datetime.now().strftime("%Y-%m-%d") + "-001"
    run_id = st.text_input(
        "Run ID",
        value=default_run,
        help="Added to every event description: search RunID in Google Calendar to bulk delete."
    )

    st.divider()
    st.header("Base + Defaults")
    home_base = st.text_input("Home base", value="Paris")

    st.subheader("Work default times")
    default_work_start = st.number_input("Work start hour", 0, 23, 9, 1)
    default_work_end = st.number_input("Work end hour", 0, 23, 19, 1)

    st.subheader("Hold times")
    hold_start = st.number_input("Hold start hour", 0, 23, 10, 1)
    hold_end = st.number_input("Hold end hour", 0, 23, 18, 1)

    st.divider()
    st.subheader("Travel settings")
    travel_mode = st.selectbox(
        "Travel generation",
        ["AUTO", "MANUAL", "OFF"],
        index=0,
        help="AUTO = always generate boundary travel. MANUAL = only generate travel for runs where include_travel is enabled. OFF = no travel."
    )
    travel_start_hour = st.number_input("Travel block start hour", 0, 23, 8, 1)
    travel_end_hour = st.number_input("Travel block end hour", 0, 23, 12, 1)

st.subheader("Paste your agency text")

# Sample loader row
c_load, c_note = st.columns([1, 5])
with c_load:
    if st.button("Load sample"):
        st.session_state.raw_input = load_sample_text("sample_input.txt")
with c_note:
    st.caption("Tip: Click **Load sample** to demo the app instantly.")

raw = st.text_area(
    "Paste the full block from your agency here…",
    height=300,
    value=st.session_state.raw_input
)

# Keep session in sync (so edits persist after reruns)
st.session_state.raw_input = raw

parse_btn = st.button("Parse jobs", type="primary")

if parse_btn:
    st.session_state.jobs = parse_jobs(raw)

jobs: List[Job] = st.session_state.jobs

if not jobs:
    st.info("Paste text (or click **Load sample**) and click **Parse jobs**.")
    st.stop()

st.subheader("Review / edit jobs")
df = pd.DataFrame([{
    "title": j.title,
    "location": j.location,
    "start_date": j.start_date,
    "end_date": j.end_date,
    "status": j.status,
    "kind": j.kind,
    "include_travel": j.include_travel,
    "work_start_hour": j.work_start_hour,
    "work_end_hour": j.work_end_hour,
    "notes": j.notes,
} for j in jobs])

edited = st.data_editor(
    df,
    use_container_width=True,
    num_rows="dynamic",
    column_config={
        "start_date": st.column_config.DateColumn("start_date"),
        "end_date": st.column_config.DateColumn("end_date"),
        "include_travel": st.column_config.CheckboxColumn("include_travel"),
        "work_start_hour": st.column_config.NumberColumn("work_start_hour"),
        "work_end_hour": st.column_config.NumberColumn("work_end_hour"),
        "kind": st.column_config.SelectboxColumn("kind", options=["WORK", "HOLD"]),
    }
)

new_jobs: List[Job] = []
for _, r in edited.iterrows():
    new_jobs.append(Job(
        title=str(r["title"]),
        location=str(r["location"]),
        start_date=pd.to_datetime(r["start_date"]).date(),
        end_date=pd.to_datetime(r["end_date"]).date(),
        status=str(r["status"]),
        kind=str(r["kind"]),
        include_travel=bool(r["include_travel"]),
        work_start_hour=None if pd.isna(r["work_start_hour"]) else int(r["work_start_hour"]),
        work_end_hour=None if pd.isna(r["work_end_hour"]) else int(r["work_end_hour"]),
        notes=str(r["notes"]) if not pd.isna(r["notes"]) else "",
    ))

st.session_state.jobs = new_jobs
jobs = new_jobs

work_events = build_work_events(jobs, int(default_work_start), int(default_work_end), run_id)
hold_events = build_hold_events(jobs, int(hold_start), int(hold_end), run_id)

travel_events, travel_warnings = compute_trip_boundary_travel(
    jobs=jobs,
    home_base=home_base,
    travel_mode=travel_mode,
    travel_start_hour=int(travel_start_hour),
    travel_end_hour=int(travel_end_hour),
    run_id=run_id,
)

st.subheader("Travel summary")
runs = merge_city_runs(jobs)
trip_runs = [
    r for r in runs
    if normalize_location(r["city_label"]) != normalize_location(home_base)
    and not is_unknown_location(r["city_label"])
]
st.write(f"Detected city runs: {len(runs)}  •  Non-home runs (eligible for travel): {len(trip_runs)}")
if travel_mode == "MANUAL":
    st.caption("MANUAL: a run gets travel only if at least one job in that run has include_travel checked.")
else:
    st.caption("AUTO: all eligible non-home runs get travel-in and travel-out events.")

st.subheader("Download .ics files")
work_ics = ics_wrap(work_events, "WORK (Itinerary)")
hold_ics = ics_wrap(hold_events, "HOLD (Itinerary)")
travel_ics = ics_wrap(travel_events, "TRAVEL (Itinerary)")

c1, c2, c3 = st.columns(3)
with c1:
    st.download_button(
        "Download work.ics",
        work_ics.encode("utf-8"),
        "work.ics",
        "text/calendar",
        use_container_width=True
    )
    st.caption(f"Events: {len(work_events)}")
with c2:
    st.download_button(
        "Download travel.ics",
        travel_ics.encode("utf-8"),
        "travel.ics",
        "text/calendar",
        use_container_width=True
    )
    st.caption(f"Events: {len(travel_events)}")
with c3:
    st.download_button(
        "Download hold.ics",
        hold_ics.encode("utf-8"),
        "hold.ics",
        "text/calendar",
        use_container_width=True
    )
    st.caption(f"Events: {len(hold_events)}")

st.subheader("Import tips (Google Calendar)")
st.markdown(
    """
- Create 3 calendars: **WORK**, **TRAVEL**, **HOLD** (so you can color them).
- Import each `.ics` into the matching calendar.

**Bulk delete:** search `RunID: <your-id>` in Google Calendar and delete that batch.
"""
with st.expander("Cleanup / Delete a RunID batch"):
    st.markdown(
        """
1. In Google Calendar, search: `RunID: <your-id>`
2. Select the events from that batch and delete them.
        """
    )


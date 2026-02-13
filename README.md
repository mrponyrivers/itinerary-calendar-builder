# Itinerary Calendar Builder

<p>
  <a href="https://mrponyrivers-itinerary-calendar-builder.streamlit.app/"><b>Live Demo</b></a> •
  <a href="https://github.com/mrponyrivers/itinerary-calendar-builder"><b>Repo</b></a>
</p>

<img src="assets/demo.gif" width="900" alt="Itinerary Calendar Builder demo" />


A Streamlit app that converts messy itinerary text into clean calendar events and exports **three ICS files**:
- **WORK**
- **TRAVEL**
- **HOLD**

Each export is tagged with a **RunID** so you can bulk-delete imported events later.

---

## Features

- Paste itinerary text → auto-parses into structured events
- Review/edit events before export
- Exports **3 separate calendars** (`WORK.ics`, `TRAVEL.ics`, `HOLD.ics`)
- **RunID tagging** for clean imports + easy cleanup
- Simple “boundary travel” logic (travel in/out around city runs)

---

## Screenshots

<img src="assets/input1.png" width="900" />
<img src="assets/input2.png" width="900" />
<img src="assets/input3.png" width="900" />

---

## How it works

1. **Paste itinerary text** (agency-style or free-form blocks)
2. The app parses the text into a table of events (date, time, city, notes)
3. It generates:
   - **WORK** events for the actual jobs
   - **HOLD** events for holds / placeholders (if present)
   - **TRAVEL** events using “boundary travel” rules (see below)
4. Download the ICS files and import them into your calendar

---

## Travel logic

This app uses **boundary travel** (simple + practical):

- **Travel IN** = day before the first job in a non-home city run  
- **Travel OUT** = day after the last job in that run  
- **Home-base jobs** = no travel blocks  
- It’s an itinerary planning aid — not a perfect logistics engine for stacked schedules

Tip: If you want full control, switch travel mode to manual (if enabled in your UI) or edit travel blocks after importing.

---

## Run locally

### 1) Create and activate a virtual environment (recommended)

```bash
cd ~/ai-journey/itinerary-calendar
python -m venv .venv
source .venv/bin/activate

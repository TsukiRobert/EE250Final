# server.py

from flask import Flask, request, jsonify, send_from_directory
import os
import base64
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple

# === Load config ===
from config import (
    EVENTS_DIR,
    TMP_DIR,
    DANGER_LIST_FILE,
    PERSON_THRESH,
    BOX_THRESH,
    WEAPON_THRESH,
    WEAPON_CLASSES,
    THREAT_MIN_DURATION_SEC,
    THREAT_COOLDOWN_SEC,
)

# === Dashboard HTML routes ===
from dashboard import register_dashboard_routes


# ============================================================
#                       Helper Functions
# ============================================================

def parse_iso(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.utcnow()


def normalize_person_list(person_info: Any) -> List[Dict[str, Any]]:
    if person_info is None:
        return []
    if isinstance(person_info, list):
        return [p for p in person_info if isinstance(p, dict)]
    if isinstance(person_info, dict):
        return [person_info]
    return []


def compute_flags(detections: List[Dict[str, Any]]) -> Dict[str, bool]:
    has_person = any(
        d.get("class_name") == "person" and float(d.get("confidence", 0)) >= PERSON_THRESH
        for d in detections
    )

    has_box = any(
        d.get("class_name") in ("box", "package", "backpack")
        and float(d.get("confidence", 0)) >= BOX_THRESH
        for d in detections
    )

    has_weapon = any(
        d.get("class_name") in WEAPON_CLASSES
        and float(d.get("confidence", 0)) >= WEAPON_THRESH
        for d in detections
    )

    return {
        "has_person": has_person,
        "has_box": has_box,
        "has_weapon": has_weapon,
    }


# ============================================================
#                      Global State
# ============================================================

app = Flask(__name__)
os.makedirs(EVENTS_DIR, exist_ok=True)

event_history: List[Dict[str, Any]] = []
next_event_id: int = 1
dangerous_persons: set[str] = set()

camera_states: Dict[str, Dict[str, Any]] = {}
camera_current_event = {}   

EVENT_END_COOLDOWN = 2.0  # seconds after person disappears

last_status: Dict[str, Any] = {
    "current_state": "idle",
    "danger": False,
    "needs_attention": False,
    "last_event_id": None,
    "last_event_type": None,
    "last_event_severity": "normal",
    "last_event_caption": None,
    "latest_snapshot_url": None,
}


# ============================================================
#                     Danger List Load/Save
# ============================================================

def load_danger_list():
    global dangerous_persons
    if os.path.exists(DANGER_LIST_FILE):
        try:
            with open(DANGER_LIST_FILE, "r", encoding="utf-8") as f:
                dangerous_persons = {name.lower() for name in json.load(f)}
        except:
            dangerous_persons = set()

def save_danger_list():
    with open(DANGER_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(dangerous_persons), f, indent=2)

load_danger_list()


def allocate_event_id() -> int:
    global next_event_id
    eid = next_event_id
    next_event_id += 1
    return eid


def get_camera_state(cid: str) -> Dict[str, Any]:
    if cid not in camera_states:
        camera_states[cid] = {
            "threat_state": "none",
            "threat_start_time": None,
            "last_no_weapon_time": None,
        }
    return camera_states[cid]


# ============================================================
#                    Build Event + Captions
# ============================================================

def build_event(camera_id, event_type, ts, frame_record, flags):
    eid = allocate_event_id()
    
    # Save snapshot
    snapshot_rel = None
    if frame_record.get("image_path"):
        src = frame_record["image_path"]
        ext = os.path.splitext(src)[1] or ".jpg"
        dest = os.path.join(EVENTS_DIR, f"event_{eid}{ext}")
        try:
            with open(src, "rb") as fsrc, open(dest, "wb") as fdst:
                fdst.write(fsrc.read())
            snapshot_rel = f"/events/img/event_{eid}{ext}"
        except:
            snapshot_rel = None

    persons = normalize_person_list(frame_record.get("person_info"))
    flagsum = {
        "person_count": len(persons) if persons else (1 if flags["has_person"] else 0),
        "box": flags["has_box"],
        "weapon": flags["has_weapon"],
    }

    # Determine severity
    severity = "normal"
    if flags["has_weapon"]:
        any_unknown = any(p.get("type") != "friend" for p in persons) if persons else True
        any_blacklisted = any(
            (p.get("name") or "").lower() in dangerous_persons
            for p in persons if p.get("name")
        )
        if any_unknown or any_blacklisted:
            severity = "danger"
        else:
            severity = "attention"

    event = {
        "event_id": eid,
        "camera_id": camera_id,
        "event_type": event_type,
        "start_time": ts.isoformat(),
        "end_time": ts.isoformat(),
        "duration_sec": 0.0,
        "objects_summary": flagsum,
        "person_info": persons,
        "severity": severity,
        "snapshot_path": snapshot_rel,
    }
    return event


def describe_event(ev):
    persons = normalize_person_list(ev["person_info"])
    obj = ev["objects_summary"]
    severity = ev["severity"]

    P = persons
    has_weapon = obj["weapon"]
    has_box = obj["box"]

    friend_names = [p["name"] for p in P if p.get("type") == "friend" and p.get("name")]
    num_unknown = sum(1 for p in P if p.get("type") != "friend")

    # weapon case
    if has_weapon:
        if severity == "danger":
            if num_unknown:
                return "An unknown person is at your door and appears to be holding a weapon. DANGER."
            if friend_names:
                return f"Your friend {friend_names[0]} has been marked as dangerous and is holding a weapon. DANGER."
            return "Someone holding a weapon is at your door. DANGER."
        else:
            # attention
            if friend_names:
                return f"Your friend {friend_names[0]} is at your door holding a potential weapon."
            return "Someone familiar is holding a potential weapon at your door."

    # box case
    if has_box:
        if friend_names:
            return f"Your friend {friend_names[0]} is delivering a package at your door."
        return "Someone is delivering a package at your door."

    # visitor
    if persons:
        if friend_names:
            return f"Your friend {friend_names[0]} is standing at your door."
        return "An unknown person is standing at your door."

    return "No one is at your door."


# ============================================================
#                  Threat State Machine (UPDATED)
# ============================================================
def process_frame(frame_record):
    cid = frame_record["camera_id"]
    ts = parse_iso(frame_record["timestamp"])
    flags = compute_flags(frame_record["detections"])

    has_person = flags["has_person"]
    has_weapon = flags["has_weapon"]
    has_box = flags["has_box"]
    persons = normalize_person_list(frame_record["person_info"])

    # access event state machine
    state = get_camera_state(cid)

    # The event we are building for logging
    new_event = None
    current_state = "idle"

    # -----------------------------------------------------------
    #              THREAT STATE MACHINE (unchanged)
    # -----------------------------------------------------------
    if has_person and has_weapon:

        if state["threat_state"] == "none":
            state["threat_state"] = "arming"
            state["threat_start_time"] = ts
            state["last_no_weapon_time"] = None
            current_state = "event_active"
            return current_state, None

        if state["threat_state"] == "arming":
            dur = (ts - state["threat_start_time"]).total_seconds()
            if dur >= THREAT_MIN_DURATION_SEC:
                state["threat_state"] = "active"
                new_event = build_event(cid, "threat", ts, frame_record, flags)
                new_event["start_time"] = state["threat_start_time"].isoformat()
                new_event["end_time"] = ts.isoformat()
                return "threat_active", new_event
            return "event_active", None

        if state["threat_state"] == "active":
            state["last_no_weapon_time"] = None
            return "threat_active", None

    # -----------------------------------------------------------
    #                THREAT COOLDOWN / EXIT
    # -----------------------------------------------------------
    if state["threat_state"] in ("arming", "active"):
        if state["last_no_weapon_time"] is None:
            state["last_no_weapon_time"] = ts
        else:
            cd = (ts - state["last_no_weapon_time"]).total_seconds()
            if cd >= THREAT_COOLDOWN_SEC:
                state["threat_state"] = "none"
                state["threat_start_time"] = None
                state["last_no_weapon_time"] = None

        if state["threat_state"] == "active":
            current_state = "threat_active"
            # Threat ongoing → but still allow normal events to log
        else:
            current_state = "event_active"
    else:
        current_state = "idle"

    # -----------------------------------------------------------
    #                  NORMAL EVENT MERGING (NEW)
    # -----------------------------------------------------------
    ongoing = camera_current_event.get(cid)

    if has_person:
        # determine event type
        if has_box:
            etype = "delivery"
        else:
            etype = "visitor"

        if ongoing is None:
            # NEW EVENT START
            ongoing = build_event(cid, etype, ts, frame_record, flags)
            ongoing["start_time"] = ts.isoformat()
            ongoing["end_time"] = ts.isoformat()
            ongoing["cooldown_start"] = None
            camera_current_event[cid] = ongoing
            return current_state, None

        else:
            # SAME PERSON STILL PRESENT → extend event
            ongoing["end_time"] = ts.isoformat()
            ongoing["cooldown_start"] = None
            return current_state, None

    else:
        # No person → close event if cooldown passes
        if ongoing:
            if ongoing.get("cooldown_start") is None:
                ongoing["cooldown_start"] = ts
                return current_state, None
            else:
                cd = (ts - ongoing["cooldown_start"]).total_seconds()
                if cd >= EVENT_END_COOLDOWN:
                    # finalize event
                    ongoing["duration_sec"] = (
                        parse_iso(ongoing["end_time"]) -
                        parse_iso(ongoing["start_time"])
                    ).total_seconds()

                    finished = ongoing
                    camera_current_event[cid] = None
                    return current_state, finished

        return current_state, None

# ============================================================
#                   Status + Event Update
# ============================================================

def update_last_status(current_state, new_event):
    if new_event:
        event_history.append(new_event)

        cap = describe_event(new_event)
        new_event["caption"] = cap

        sev = new_event["severity"]
        last_status["last_event_id"] = new_event["event_id"]
        last_status["last_event_type"] = new_event["event_type"]
        last_status["last_event_severity"] = sev
        last_status["last_event_caption"] = cap
        last_status["latest_snapshot_url"] = new_event.get("snapshot_path")

        if sev == "danger":
            last_status["danger"] = True
            last_status["needs_attention"] = False
        elif sev == "attention" and not last_status["danger"]:
            last_status["needs_attention"] = True

    last_status["current_state"] = current_state


# ============================================================
#                          Routes
# ============================================================

@app.post("/detections")
def detections():
    frames = request.get_json(force=True)
    if not isinstance(frames, list):
        return {"status": "error", "msg": "Expected list"}, 400

    return {"events": frames}


@app.route("/frame_result", methods=["POST"])
def frame_result():
    data = request.get_json(force=True)

    cid = data.get("camera_id", "cam1")
    frame_id = data.get("frame_id")
    ts = data.get("timestamp") or datetime.utcnow().isoformat() + "Z"
    dets = data.get("detections", [])
    pinfo = data.get("person_info", None)

    image_path = None
    if data.get("image_jpeg_base64"):
        try:
            raw = base64.b64decode(data["image_jpeg_base64"])
            fname = f"latest_{cid}.jpg"
            image_path = os.path.join(TMP_DIR, fname)
            with open(image_path, "wb") as f:
                f.write(raw)
        except:
            image_path = None

    fr = {
        "camera_id": cid,
        "frame_id": frame_id,
        "timestamp": ts,
        "detections": dets,
        "person_info": pinfo,
        "image_path": image_path,
        "image_meta": data.get("image_meta", {}),
    }

    state, ne = process_frame(fr)
    update_last_status(state, ne)

    return jsonify(last_status)


@app.route("/latest_status")
def latest_status_api():
    return jsonify(last_status)


@app.route("/events")
def events_api():
    N = int(request.args.get("limit", 50))
    out = []
    for ev in event_history[-N:]:
        out.append({
            "event_id": ev["event_id"],
            "event_type": ev["event_type"],
            "start_time": ev["start_time"],
            "end_time": ev["end_time"],
            "severity": ev["severity"],
            "caption": ev["caption"],
            "person_info": ev["person_info"],
            "snapshot_url": ev["snapshot_path"]
        })
    return jsonify(out)


@app.route("/events/img/<path:fn>")
def event_img(fn):
    return send_from_directory(EVENTS_DIR, fn)


@app.route("/ack_alert", methods=["POST"])
def ack_alert():
    last_status["danger"] = False
    last_status["needs_attention"] = False
    return {"status": "ok"}


@app.route("/danger_list", methods=["GET", "POST"])
def danger_list():
    if request.method == "GET":
        return {"dangerous_persons": sorted(dangerous_persons)}

    data = request.get_json(force=True)
    action = data.get("action")
    name = (data.get("name") or "").strip().lower()

    if not name:
        return {"status": "error", "error": "name required"}, 400

    if action == "add":
        dangerous_persons.add(name)
        save_danger_list()

    elif action == "remove":
        dangerous_persons.discard(name)
        save_danger_list()

    else:
        return {"status": "error", "error": "invalid action"}, 400

    return {"status": "ok", "dangerous_persons": sorted(dangerous_persons)}


# attach dashboard
register_dashboard_routes(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)

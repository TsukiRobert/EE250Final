from flask import Flask, request, jsonify, send_from_directory
import os, json, base64
from datetime import datetime
from typing import Dict, Any, List

from dashboard import register_dashboard_routes
from config import (
    EVENTS_DIR,
    TMP_DIR,
    DANGER_LIST_FILE,
    PERSON_THRESH,
    BOX_THRESH,
    WEAPON_THRESH,
    WEAPON_CLASSES,
    THREAT_MIN_DURATION_SEC,   # not used in this simplified version but kept for config compatibility
    THREAT_COOLDOWN_SEC,       # not used here either
)

app = Flask(__name__)
os.makedirs(EVENTS_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)

event_history: List[Dict[str, Any]] = []
next_event_id = 1

# names that have ever been seen (for "new_person" flag)
known_person_ids: set[str] = set()

# blacklist
dangerous_persons: set[str] = set()
if os.path.exists(DANGER_LIST_FILE):
    try:
        dangerous_persons = set(json.load(open(DANGER_LIST_FILE)))
    except Exception:
        dangerous_persons = set()

# what the dashboard & client see as "latest status"
last_status: Dict[str, Any] = {
    "current_state": "idle",          # idle | event_active | threat_active
    "danger": False,
    "needs_attention": False,

    "last_event_id": None,
    "last_event_type": None,
    "last_event_caption": None,
    "last_event_severity": "normal",
    "latest_snapshot_url": None,

    # live caption for the *current* frame
    "live_caption": None,

    # real-time threat info
    "threat_flag": False,            # True if current frame has a weapon
    "threat_image": None,            # URL of snapshot (for dashboard)
    "threat_name": None,             # e.g. "Bob" or "danger_7"

    # new-person + snapshot back to YOLO client
    "new_person": False,             # True if this is first time we saw this person_id
    "person_id": None,               # name or synthetic id
    "person_snapshot_b64": None,     # base64 of snapshot (only when new_person=True)

    # snapshot that caused this threat (always base64 when threat_flag=True)
    "threat_snapshot_b64": None,

    # threat history: list of snapshot URLs for all threat events
    "threat_history": [],
}


def parse_iso(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.utcnow()


def normalize_person_list(p):
    if p is None:
        return []
    if isinstance(p, list):
        return [x for x in p if isinstance(x, dict)]
    if isinstance(p, dict):
        return [p]
    return []


def compute_flags(dets):
    """Check for person / box / weapon."""
    has_person = False
    has_box = False
    has_weapon = False

    for d in dets:
        cname = d.get("class_name")
        conf = float(d.get("confidence", 0.0))

        if cname == "person" and conf >= PERSON_THRESH:
            has_person = True
        if cname in ("box", "backpack", "package") and conf >= BOX_THRESH:
            has_box = True
        if cname in WEAPON_CLASSES and conf >= WEAPON_THRESH:
            has_weapon = True

    return {
        "has_person": has_person,
        "has_box": has_box,
        "has_weapon": has_weapon,
    }


def compute_severity(flags, persons):
    """normal / attention / danger for this frame's event."""
    has_weapon = flags["has_weapon"]
    has_person = flags["has_person"]

    if not has_weapon or not has_person:
        return "normal"

    any_unknown = any(p.get("type") != "friend" for p in persons) if persons else True
    any_blacklisted = any(
        (p.get("name") or "").lower() in dangerous_persons
        for p in persons
        if p.get("name")
    )

    if any_unknown or any_blacklisted:
        return "danger"
    else:
        return "attention"


def objects_summary_from(flags, persons):
    person_count = len(persons) if persons else (1 if flags["has_person"] else 0)
    return {
        "person_count": person_count,
        "box": flags["has_box"],
        "weapon": flags["has_weapon"],
    }


def describe_event_like(persons, objs, severity):
    has_weapon = objs["weapon"]
    has_box = objs["box"]
    num_people = objs["person_count"]

    friend_names = [p.get("name") for p in persons if p.get("type") == "friend" and p.get("name")]
    num_unknown = sum(1 for p in persons if p.get("type") != "friend")

    # Threat
    if has_weapon:
        if severity == "danger":
            if num_unknown >= 1:
                return "An unknown person is holding a weapon. DANGER."
            if friend_names:
                return f"Your friend {friend_names[0]} is holding a weapon. DANGER."
            return "Someone is holding a weapon. DANGER."
        else:
            if friend_names:
                return f"Your friend {friend_names[0]} is holding a potential weapon. Pay attention."
            return "Someone is holding a potential weapon. Pay attention."

    # Delivery
    if has_box:
        if friend_names:
            return f"Your friend {friend_names[0]} is delivering a package."
        if num_unknown >= 1:
            return "Someone is delivering a package."
        return "A package is at your door."

    # Visitor
    if num_people >= 1:
        if friend_names:
            return f"Your friend {friend_names[0]} is standing at your door."
        if num_unknown == 1:
            return "An unknown person is standing at your door."
        if num_unknown > 1:
            return "Multiple unknown people are standing at your door."

    return "No one is at your door."


def decide_event_type(flags):
    if not flags["has_person"]:
        return None
    if flags["has_weapon"]:
        return "threat"
    if flags["has_box"]:
        return "delivery"
    return "visitor"


def next_id() -> int:
    global next_event_id
    eid = next_event_id
    next_event_id += 1
    return eid


def handle_frame(frame: Dict[str, Any]) -> None:
    global event_history, last_status, known_person_ids, dangerous_persons

    ts = parse_iso(frame["timestamp"])
    detections = frame.get("detections", [])
    persons = normalize_person_list(frame.get("person_info"))
    flags = compute_flags(detections)
    objs = objects_summary_from(flags, persons)
    severity = compute_severity(flags, persons)
    live_caption = describe_event_like(persons, objs, severity)
    event_type = decide_event_type(flags)

    person_key = None
    if persons:
        p0 = persons[0]
        if p0.get("name"):
            person_key = p0["name"].lower()

    new_person = False
    snapshot_rel_path = None
    snapshot_b64 = None
    new_event: Dict[str, Any] | None = None

    if event_type is not None:
        eid = next_id()

        img_src = frame.get("image_path")
        dest = None
        if img_src:
            ext = os.path.splitext(img_src)[1] or ".jpg"
            dest = os.path.join(EVENTS_DIR, f"event_{eid}{ext}")
            try:
                with open(img_src, "rb") as fsrc, open(dest, "wb") as fdst:
                    fdst.write(fsrc.read())
                snapshot_rel_path = f"/events/img/event_{eid}{ext}"
                with open(dest, "rb") as f:
                    snapshot_b64 = base64.b64encode(f.read()).decode("ascii")
            except Exception:
                snapshot_rel_path = None
                snapshot_b64 = None

        new_event = {
            "event_id": eid,
            "event_type": event_type,
            "start_time": ts.isoformat(),
            "end_time": ts.isoformat(),
            "duration_sec": 0.0,
            "severity": severity,
            "objects_summary": objs,
            "person_info": persons,
            "snapshot_path": snapshot_rel_path,
            "caption": live_caption,
        }
        event_history.append(new_event)

        last_status["last_event_id"] = eid
        last_status["last_event_type"] = event_type
        last_status["last_event_caption"] = live_caption
        last_status["last_event_severity"] = severity
        last_status["latest_snapshot_url"] = snapshot_rel_path

        if person_key:
            if person_key not in known_person_ids:
                known_person_ids.add(person_key)
                new_person = True

    if flags["has_weapon"]:
        last_status["current_state"] = "threat_active"
    elif flags["has_person"]:
        last_status["current_state"] = "event_active"
    else:
        last_status["current_state"] = "idle"

    last_status["live_caption"] = live_caption

    last_status["threat_flag"] = flags["has_weapon"]

    if flags["has_weapon"]:
        if new_event is not None:
            last_status["threat_image"] = new_event.get("snapshot_path")
        else:
            last_status["threat_image"] = None


        name = None
        for p in persons:
            if p.get("name"):
                name = p["name"]
                break

        if name:
            last_status["threat_name"] = name
            dangerous_persons.add(name.lower())
        else:
            synthetic = f"danger_{last_status['last_event_id'] or int(ts.timestamp())}"
            last_status["threat_name"] = synthetic
            dangerous_persons.add(synthetic)

        if severity == "danger":
            last_status["danger"] = True
        elif severity == "attention" and not last_status["danger"]:
            last_status["needs_attention"] = True
    else:
        last_status["threat_image"] = None
        last_status["threat_name"] = None

    last_status["new_person"] = new_person
    last_status["person_id"] = person_key
    last_status["person_snapshot_b64"] = snapshot_b64 if new_person else None

    if last_status["threat_flag"]:
        last_status["threat_snapshot_b64"] = snapshot_b64
    else:
        last_status["threat_snapshot_b64"] = None

    threat_urls = [
        ev["snapshot_path"]
        for ev in event_history
        if ev.get("event_type") == "threat" and ev.get("snapshot_path")
    ]
    last_status["threat_history"] = list(reversed(threat_urls))

    try:
        with open(DANGER_LIST_FILE, "w") as f:
            json.dump(sorted(list(dangerous_persons)), f, indent=2)
    except Exception:
        pass

# This part is made from GPT 

@app.route("/frame_result", methods=["POST"])
def frame_result():
    """
    Entry point for your YOLO client.
    Expects JSON:
      {
        "camera_id": "...",
        "frame_id": ...,
        "timestamp": "...",
        "detections": [...],
        "person_info": {...} or [...],
        "image_jpeg_base64": "..."     # optional (OR "image")
      }
    Returns `last_status` which includes threat_flag, threat_name,
    threat_snapshot_b64, new_person, person_snapshot_b64, threat_history, etc.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid JSON"}), 400

    # Accept both "image_jpeg_base64" and "image" (your friend's field)
    img_b64 = data.get("image_jpeg_base64") or data.get("image")

    # Save raw image (optional)
    image_path = None
    if img_b64:
        try:
            raw = base64.b64decode(img_b64)
            fname = f"latest_{data.get('camera_id', 'cam')}.jpg"
            image_path = os.path.join(TMP_DIR, fname)
            with open(image_path, "wb") as f:
                f.write(raw)
        except Exception:
            image_path = None

    frame = {
        "camera_id": data.get("camera_id", "cam"),
        "frame_id": data.get("frame_id"),
        "timestamp": data.get("timestamp") or datetime.utcnow().isoformat() + "Z",
        "detections": data.get("detections", []),
        "person_info": data.get("person_info"),
        "image_path": image_path,
    }

    handle_frame(frame)
    return jsonify(last_status)


@app.route("/latest_status")
def latest_status_route():
    return jsonify(last_status)


@app.route("/events")
def events_route():
    N = int(request.args.get("limit", 100))
    subset = event_history[-N:]
    out = []
    for ev in subset:
        out.append(
            {
                "event_id": ev["event_id"],
                "event_type": ev["event_type"],
                "start_time": ev["start_time"],
                "end_time": ev["end_time"],
                "duration_sec": ev["duration_sec"],
                "severity": ev["severity"],
                "caption": ev.get("caption"),
                "snapshot_url": ev.get("snapshot_path"),
            }
        )
    return jsonify(out)


@app.route("/events/img/<path:fn>")
def event_img(fn):
    return send_from_directory(EVENTS_DIR, fn)


@app.route("/ack_alert", methods=["POST"])
def ack():
    # Clear current warning/attention but keep history
    last_status["danger"] = False
    last_status["needs_attention"] = False
    last_status["threat_flag"] = False
    last_status["threat_image"] = None
    last_status["threat_name"] = None
    last_status["threat_snapshot_b64"] = None
    return jsonify({"status": "ok"})


@app.route("/danger_list", methods=["GET", "POST"])
def danger_list_route():
    global dangerous_persons
    if request.method == "GET":
        return jsonify({"dangerous_persons": sorted(list(dangerous_persons))})

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip().lower()
    if not name:
        return jsonify({"error": "name required"}), 400

    if data.get("action") == "remove":
        dangerous_persons.discard(name)
    else:
        dangerous_persons.add(name)

    try:
        with open(DANGER_LIST_FILE, "w") as f:
            json.dump(sorted(list(dangerous_persons)), f, indent=2)
    except Exception:
        pass

    return jsonify({"status": "ok", "dangerous_persons": sorted(list(dangerous_persons))})

register_dashboard_routes(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)

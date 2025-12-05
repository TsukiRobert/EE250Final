import requests, base64, time, random
from datetime import datetime, timedelta

SERVER = "http://127.0.0.1:5001"   # <-- Change to your server IP
# Example: SERVER = "http://10.23.229.165:5001"

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def now_iso(offset_sec=0):
    return (datetime.utcnow() + timedelta(seconds=offset_sec)).isoformat() + "Z"

def fake_jpeg_b64():
    # Just a tiny 1x1 pixel for simulation
    return base64.b64encode(b"\xFF\xD8\xFF\xD9").decode()

def send_frame(label, frame_id, detections, person_info, offset):
    payload = {
        "camera_id": "door_cam_1",
        "frame_id": frame_id,
        "timestamp": now_iso(offset),
        "image_meta": {"width":640, "height":480},
        "detections": detections,
        "person_info": person_info,
        "image_jpeg_base64": fake_jpeg_b64()
    }

    print(f"\n--- {label} FRAME {frame_id} ---")
    try:
        r = requests.post(f"{SERVER}/frame_result", json=payload, timeout=5)
        print("Response:", r.json())
    except Exception as e:
        print("Error:", e)


# ---------------------------------------------------------
# SCENARIO 1 — VISITOR (Friend Alice stays 5 seconds)
# ---------------------------------------------------------

def scenario_visitor_friend(start_offset=0):
    print("\n================ SCENARIO 1: Visitor - Friend Alice ================")
    offset = start_offset

    # 6 frames of Alice
    for i in range(6):
        dets = [
            {
                "class_name":"person",
                "class_id":0,
                "confidence":0.98,
                "bbox":{"x_center":320,"y_center":240,"width":200,"height":350}
            }
        ]
        pinfo = {"type":"friend", "name":"Alice"}
        send_frame("Alice present", i, dets, pinfo, offset)
        time.sleep(0.3)
        offset += 1

    # 3 frames no one → event ends
    for j in range(3):
        send_frame("No one", 100+j, [], None, offset)
        time.sleep(0.3)
        offset += 1

    return offset


# ---------------------------------------------------------
# SCENARIO 2 — DELIVERY (Unknown person with box)
# ---------------------------------------------------------

def scenario_delivery_unknown(start_offset):
    print("\n================ SCENARIO 2: Delivery - Unknown + Box ================")
    offset = start_offset

    for i in range(5):
        dets = [
            {"class_name":"person","class_id":0,"confidence":0.94,
             "bbox":{"x_center":330,"y_center":260,"width":180,"height":300}},
            {"class_name":"box","class_id":40,"confidence":0.90,
             "bbox":{"x_center":350,"y_center":300,"width":120,"height":80}},
        ]
        pinfo = {"type":"unknown","name":None}
        send_frame("Delivery frame", 200+i, dets, pinfo, offset)
        time.sleep(0.3)
        offset += 1

    for j in range(3):
        send_frame("No one", 300+j, [], None, offset)
        time.sleep(0.3)
        offset += 1

    return offset


# ---------------------------------------------------------
# SCENARIO 3 — THREAT (Unknown + Hammer)
# ---------------------------------------------------------

def scenario_threat_unknown(start_offset):
    print("\n================ SCENARIO 3: THREAT - Unknown + Hammer ================")
    offset = start_offset

    for i in range(7):  # enough frames to activate threat
        dets = [
            {"class_name":"person","class_id":0,"confidence":0.99,
             "bbox":{"x_center":310,"y_center":250,"width":190,"height":300}},
            {"class_name":"hammer","class_id":55,"confidence":0.90,
             "bbox":{"x_center":330,"y_center":260,"width":80,"height":40}}
        ]
        pinfo = {"type":"unknown","name":None}
        send_frame("Unknown + hammer", 400+i, dets, pinfo, offset)
        time.sleep(0.3)
        offset += 1

    # Now disappear → threat end cooling
    for j in range(4):
        send_frame("No one", 500+j, [], None, offset)
        time.sleep(0.3)
        offset += 1

    return offset


# ---------------------------------------------------------
# SCENARIO 4 — THREAT ATTENTION → DANGER (Friend Bob + Gun)
# ---------------------------------------------------------

def scenario_threat_friend(start_offset):
    print("\n================ SCENARIO 4: Threat Upgrade (Friend Bob + Gun) ================")
    offset = start_offset

    # A few frames → attention
    for i in range(3):
        dets = [
            {"class_name":"person","class_id":0,"confidence":0.95,
             "bbox":{"x_center":315,"y_center":240,"width":200,"height":350}},
            {"class_name":"gun","class_id":60,"confidence":0.92,
             "bbox":{"x_center":335,"y_center":265,"width":90,"height":50}}
        ]
        pinfo = {"type":"friend","name":"Bob"}
        send_frame("Bob with gun", 600+i, dets, pinfo, offset)
        time.sleep(0.3)
        offset += 1

    # More frames → upgrade to danger (simulate long duration)
    for k in range(4):
        dets = [
            {"class_name":"person","class_id":0,"confidence":0.95,
             "bbox":{"x_center":315,"y_center":240,"width":200,"height":350}},
            {"class_name":"gun","class_id":60,"confidence":0.92,
             "bbox":{"x_center":335,"y_center":265,"width":90,"height":50}}
        ]
        pinfo = {"type":"friend","name":"Bob"}
        send_frame("Bob danger upgrade", 650+k, dets, pinfo, offset)
        time.sleep(0.3)
        offset += 1

    # disappear → event end
    for j in range(4):
        send_frame("No one", 700+j, [], None, offset)
        time.sleep(0.3)
        offset += 1

    return offset


# ---------------------------------------------------------
# SCENARIO 5 — MULTIPLE PERSONS (Alice + Unknown + Box)
# ---------------------------------------------------------

def scenario_multi_person(start_offset):
    print("\n================ SCENARIO 5: Multi-person Event ================")
    offset = start_offset

    for i in range(6):
        dets = [
            {"class_name":"person","class_id":0,"confidence":0.97,
             "bbox":{"x_center":300,"y_center":240,"width":180,"height":320}},
            {"class_name":"person","class_id":0,"confidence":0.95,
             "bbox":{"x_center":420,"y_center":260,"width":175,"height":310}},
            {"class_name":"box","class_id":40,"confidence":0.90,
             "bbox":{"x_center":380,"y_center":300,"width":120,"height":80}},
        ]
        persons = [
            {"type":"friend","name":"Alice","center":(300,240)},
            {"type":"unknown","name":None,"center":(420,260)}
        ]
        send_frame("Group event", 800+i, dets, persons, offset)
        time.sleep(0.3)
        offset += 1

    for j in range(3):
        send_frame("No one", 900+j, [], None, offset)
        time.sleep(0.3)
        offset += 1

    return offset


if __name__ == "__main__":
    offset = 0
    
    offset = scenario_visitor_friend(offset)
    offset = scenario_delivery_unknown(offset)
    offset = scenario_threat_unknown(offset)
    offset = scenario_threat_friend(offset)
    offset = scenario_multi_person(offset)

    print("\n================ ALL SCENARIOS COMPLETE ================\n")

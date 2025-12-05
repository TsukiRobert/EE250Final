import requests
import base64
import json
import datetime
import time

SERVER = "http://192.168.1.159:5001/frame_result"


def send_event(title, detections, person_info=None, img_path=None):
    print(f"\n===== SENDING EVENT: {title} =====")

    # optional fake image
    img_b64 = None
    if img_path:
        try:
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
        except:
            pass

    payload = {
        "camera_id": "cam1",
        "frame_id": int(time.time()),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "detections": detections,
        "person_info": person_info,
        "image_jpeg_base64": img_b64
    }

    try:
        r = requests.post(SERVER, json=payload, timeout=2)
        print("STATUS:", r.status_code)
        print("RESPONSE JSON:")
        print(json.dumps(r.json(), indent=2))
    except Exception as e:
        print("ERROR:", e)


# =====================================================
# 1) visitor: friend Alice
# =====================================================
send_event(
    "VISITOR: friend Alice",
    detections=[{
        "class_name": "person",
        "confidence": 0.92,
        "bbox": {"x_center":100,"y_center":100,"width":50,"height":80}
    }],
    person_info={"type":"friend", "name":"Alice"}
)

time.sleep(2)

# =====================================================
# 2) delivery: unknown + box
# =====================================================
send_event(
    "DELIVERY: unknown + box",
    detections=[
        {"class_name": "person", "confidence": 0.95,
         "bbox": {"x_center":110,"y_center":120,"width":60,"height":90}},
        {"class_name": "box", "confidence": 0.88,
         "bbox": {"x_center":140,"y_center":130,"width":40,"height":40}}
    ],
    person_info={"type":"unknown", "name": None}
)

time.sleep(2)

# =====================================================
# 3) THREAT: friend Bob holding hammer (ATTENTION)
# =====================================================
send_event(
    "THREAT (ATTENTION): friend Bob + hammer",
    detections=[
        {"class_name":"person", "confidence":0.90,
         "bbox": {"x_center":120,"y_center":130,"width":55,"height":85}},
        {"class_name":"hammer", "confidence":0.93,
         "bbox": {"x_center":180,"y_center":140,"width":30,"height":30}}
    ],
    person_info={"type":"friend", "name":"Bob"}
)

time.sleep(2)

# =====================================================
# 4) THREAT: unknown + knife (DANGER)
# =====================================================
send_event(
    "THREAT (DANGER): unknown + knife",
    detections=[
        {"class_name":"person", "confidence":0.91,
         "bbox": {"x_center":120,"y_center":130,"width":55,"height":85}},
        {"class_name":"knife", "confidence":0.96,
         "bbox": {"x_center":180,"y_center":140,"width":30,"height":30}}
    ],
    person_info={"type":"unknown", "name": None}
)

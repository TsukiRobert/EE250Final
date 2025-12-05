import os

BASE_DIR = os.path.dirname(__file__)
EVENTS_DIR = os.path.join(BASE_DIR, "events")
TMP_DIR = "/tmp"

DANGER_LIST_FILE = os.path.join(BASE_DIR, "danger_list.json")

PERSON_THRESH = 0.5
BOX_THRESH = 0.5
WEAPON_THRESH = 0.5

WEAPON_CLASSES = [
    "knife", "scissors", "axe", "gun", "pistol", "rifle",
    "bat", "hammer", "crowbar", "wrench", "screwdriver"
]

THREAT_MIN_DURATION_SEC = 1.0
THREAT_COOLDOWN_SEC = 3.0

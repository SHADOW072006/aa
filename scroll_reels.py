
import os
import re
import json
import time
import random
import hashlib
import threading
import traceback
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime

import uiautomator2 as u2


# ============================================================
# CONFIGURATION
# ============================================================

DEVICE_ID = "SGTSEMKNF6Y9FQZH"
INSTAGRAM_PACKAGE = "com.instagram.android"

REELS_TAB_ID = "com.instagram.android:id/clips_tab"
USERNAME_ID = "com.instagram.android:id/clips_author_username"

# General Reel watch duration
MIN_GENERAL_WATCH = 3
MAX_GENERAL_WATCH = 7

# Multipliers for matching content
PARTIAL_MATCH_MULTIPLIER = 1.5
STRONG_MATCH_MULTIPLIER = 2.0
VERY_STRONG_MATCH_MULTIPLIER = 3.0

# Caption reading
CAPTION_OPEN_WAIT = 2

# Navigation
NEXT_REEL_WAIT = 2

# JSON autosave
AUTOSAVE_INTERVAL = 30

OUTPUT_DIR = Path(__file__).resolve().parent / "reel_data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

JSON_FILE = OUTPUT_DIR / f"reel_run_{RUN_ID}.json"
TEMP_JSON_FILE = OUTPUT_DIR / f"reel_run_{RUN_ID}.tmp"


# ============================================================
# REFERENCE REEL PATTERNS
# Based on Reels 26, 29 and 33 from your uploaded JSON.
# ============================================================

SEED_REELS = {
    26: {
        "creator": "anuj74129",
        "original_preview": "7498529018 WhatsApp number, call",
        "category": "whatsapp_contact",
        "keywords": [
            "whatsapp",
            "number",
            "call",
            "contact",
            "phone",
            "dm me",
            "message me"
        ],
        "phrases": []
    },

    29: {
        "creator": "hustler.files",
        "original_preview": "Click the popup link",
        "category": "popup_link",
        "keywords": [
            "popup",
            "link",
            "click",
            "tap",
            "link in bio",
            "click here",
            "visit link"
        ],
        "phrases": []
    },

    33: {
        "creator": "ritikyadav_0200",
        "original_preview": "Apna koi nhi hota",
        "category": "hindi_money_motivation",
        "keywords": [
            "apna koi nhi hota",
            "apna koi nahi hota",
            "koi apna nahi hota",
            "koi apna nhi hota",
            "💵"
        ],
        "phrases": [
            "apna koi nhi hota",
            "apna koi nahi hota",
            "koi apna nahi hota",
            "koi apna nhi hota"
        ]
    }
}

# IMPORTANT:
# No hashtags were captured in the original captions of
# these three seed Reels. Add actual hashtags here later
# if you obtain them from the videos.
SEED_HASHTAGS = set()


# ============================================================
# THREAD-SAFE RUN DATA
# ============================================================

def current_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


run_data = {
    "run_id": RUN_ID,
    "started_at": current_timestamp(),
    "ended_at": None,
    "status": "running",

    "device_id": DEVICE_ID,
    "instagram_package": INSTAGRAM_PACKAGE,

    "configuration": {
        "general_watch_seconds": [
            MIN_GENERAL_WATCH,
            MAX_GENERAL_WATCH
        ],
        "partial_match_multiplier": PARTIAL_MATCH_MULTIPLIER,
        "strong_match_multiplier": STRONG_MATCH_MULTIPLIER,
        "very_strong_match_multiplier": VERY_STRONG_MATCH_MULTIPLIER,
        "autosave_interval_seconds": AUTOSAVE_INTERVAL
    },

    "reference_reels": SEED_REELS,
    "reference_hashtags": sorted(SEED_HASHTAGS),

    "total_reels_seen": 0,
    "total_reels_processed": 0,
    "total_captions_found": 0,
    "total_expanded_captions": 0,
    "total_duplicates_skipped": 0,
    "total_matching_reels": 0,
    "total_partial_matches": 0,
    "total_strong_matches": 0,
    "total_very_strong_matches": 0,
    "total_watch_seconds": 0,
    "total_errors": 0,

    "last_saved_at": None,
    "reels": [],
    "duplicates": []
}

data_lock = threading.RLock()
autosave_stop = threading.Event()


# ============================================================
# JSON SAVING
# ============================================================

def save_run_data():

    with data_lock:

        run_data["last_saved_at"] = current_timestamp()

        try:

            with open(TEMP_JSON_FILE, "w", encoding="utf-8") as file:

                json.dump(
                    run_data,
                    file,
                    ensure_ascii=False,
                    indent=4
                )

                file.flush()
                os.fsync(file.fileno())

            os.replace(TEMP_JSON_FILE, JSON_FILE)

            print(
                f"\n[JSON SAVED] {current_timestamp()}"
            )

            return True

        except Exception as error:

            print(f"[JSON SAVE ERROR] {error}")
            return False


def autosave_worker():

    while not autosave_stop.wait(AUTOSAVE_INTERVAL):
        save_run_data()


# ============================================================
# TEXT UTILITIES
# ============================================================

def normalize_text(value):

    if not value:
        return ""

    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)

    return value


def normalize_for_matching(value):

    value = normalize_text(value)

    # Preserve Hindi and English letters/numbers.
    value = re.sub(
        r"[^\w\s\u0900-\u097F💵💸₹$]",
        " ",
        value
    )

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def parse_bounds(bounds):

    if not bounds:
        return None

    match = re.search(
        r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
        bounds
    )

    if not match:
        return None

    return tuple(map(int, match.groups()))


def get_node_text(node):

    text = node.attrib.get("text", "").strip()
    desc = node.attrib.get("content-desc", "").strip()

    if len(desc) > len(text):
        return desc

    return text or desc


def extract_hashtags(text):

    if not text:
        return []

    return sorted(
        set(
            tag.lower()
            for tag in re.findall(
                r"#[\w\u0900-\u097F]+",
                text
            )
        )
    )


def is_notification_text(value):

    normalized = normalize_text(value)

    bad_signals = [
        "browsernotification:",
        "rahul gandhi addresses bharat summit",
        "criticises bjp over democracy",
        "visa row"
    ]

    return any(
        signal in normalized
        for signal in bad_signals
    )


def is_ui_text(value):

    if not value:
        return True

    normalized = normalize_text(value)

    ignored_phrases = [
        "followed by ",
        "posts tagged ",
        "translate with ai",
        "ai content",
        "liked this reel",
        "profile picture of ",
        "more options",
        "comment",
        "share",
        "save",
        "reels",
        "home",
        "search",
        "create",
        "profile"
    ]

    return any(
        normalized.startswith(phrase)
        for phrase in ignored_phrases
    )


# ============================================================
# REEL PREFERENCE CLASSIFIER
# ============================================================

def classify_reel(caption, hashtags):

    text = normalize_for_matching(caption)

    matched_categories = []
    matched_keywords = []

    # Group 1: WhatsApp / phone / contact signals
    contact_signals = [
        "whatsapp",
        "phone number",
        "number",
        "call",
        "contact",
        "dm me",
        "message me"
    ]

    contact_matches = [
        word for word in contact_signals
        if word in text
    ]

    if contact_matches:
        matched_categories.append("whatsapp_contact")
        matched_keywords.extend(contact_matches)

    # Group 2: popup / link / click signals
    link_signals = [
        "popup",
        "pop up",
        "link",
        "click",
        "tap",
        "link in bio",
        "click here",
        "visit link"
    ]

    link_matches = [
        word for word in link_signals
        if word in text
    ]

    if link_matches:
        matched_categories.append("popup_link")
        matched_keywords.extend(link_matches)

    # Group 3: Hindi money / motivational signals
    hindi_money_signals = [
        "apna koi nhi hota",
        "apna koi nahi hota",
        "koi apna nahi hota",
        "koi apna nhi hota",
        "💵"
    ]

    hindi_matches = [
        word for word in hindi_money_signals
        if word in text
    ]

    if hindi_matches:
        matched_categories.append("hindi_money_motivation")
        matched_keywords.extend(hindi_matches)

    # Group 4: Exact reference hashtags.
    # This will activate when actual seed hashtags are supplied.
    matched_tags = sorted(
        set(hashtags).intersection(SEED_HASHTAGS)
    )

    if matched_tags:
        matched_categories.append("reference_hashtag")
        matched_keywords.extend(matched_tags)

    # Score by matching independent groups.
    score = len(matched_categories)

    # Exact Hindi phrase is a stronger signal.
    if any(
        phrase in text
        for phrase in [
            "apna koi nhi hota",
            "apna koi nahi hota",
            "koi apna nahi hota",
            "koi apna nhi hota"
        ]
    ):
        score += 2

    if matched_tags:
        score += min(len(matched_tags), 3)

    # Determine viewing multiplier.
    if score >= 5 or len(matched_categories) >= 2:

        match_level = "very_strong"
        multiplier = VERY_STRONG_MATCH_MULTIPLIER

    elif score >= 3:

        match_level = "strong"
        multiplier = STRONG_MATCH_MULTIPLIER

    elif score >= 1:

        match_level = "partial"
        multiplier = PARTIAL_MATCH_MULTIPLIER

    else:

        match_level = "general"
        multiplier = 1.0

    return {
        "preference_score": score,
        "match_level": match_level,
        "matched_categories": matched_categories,
        "matched_keywords": sorted(set(matched_keywords)),
        "matched_hashtags": matched_tags,
        "watch_multiplier": multiplier
    }


# ============================================================
# WATCH DURATION
# ============================================================

def calculate_watch_duration(classification):

    baseline = random.uniform(
        MIN_GENERAL_WATCH,
        MAX_GENERAL_WATCH
    )

    multiplier = classification["watch_multiplier"]

    watch_time = baseline * multiplier

    return {
        "general_baseline_seconds": round(baseline, 2),
        "multiplier": multiplier,
        "actual_watch_seconds": round(watch_time, 2)
    }


# ============================================================
# ANDROID HIERARCHY
# ============================================================

d = None


def get_hierarchy():

    try:
        return d.dump_hierarchy(compressed=False)

    except Exception as error:

        print(f"[HIERARCHY ERROR] {error}")
        return None


# ============================================================
# GET CURRENT REEL
# ============================================================

def get_reel_info():

    hierarchy = get_hierarchy()

    if not hierarchy:
        return None, None, None

    try:
        root = ET.fromstring(hierarchy)

    except ET.ParseError:
        print("[ERROR] Could not parse hierarchy.")
        return None, None, None

    username = None
    username_bottom = None

    for node in root.iter("node"):

        if node.attrib.get("resource-id") == USERNAME_ID:

            username = get_node_text(node)

            bounds = parse_bounds(
                node.attrib.get("bounds", "")
            )

            if bounds:
                username_bottom = bounds[3]

            break

    if not username:
        return None, None, None

    candidates = []

    for node in root.iter("node"):

        if node.attrib.get("resource-id"):
            continue

        value = get_node_text(node)

        if not value or is_ui_text(value):
            continue

        if is_notification_text(value):
            continue

        bounds = parse_bounds(
            node.attrib.get("bounds", "")
        )

        if not bounds:
            continue

        left, top, right, bottom = bounds

        if username_bottom is not None and top < username_bottom:
            continue

        if left < 20 or left > 120:
            continue

        if right > 950 or bottom > 2124:
            continue

        if len(value) < 3:
            continue

        candidates.append(
            (len(value), value, bounds)
        )

    if not candidates:
        return username, None, None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True
    )

    _, preview, bounds = candidates[0]

    return username, preview, bounds


# ============================================================
# OPEN AND READ CAPTION
# ============================================================

def open_caption(bounds):

    if not bounds:
        return False

    left, top, right, bottom = bounds

    x = min(left + 180, right - 20)
    y = (top + bottom) // 2

    try:

        d.click(x, y)
        time.sleep(CAPTION_OPEN_WAIT)

        return True

    except Exception as error:

        print(f"[CAPTION OPEN ERROR] {error}")
        return False


def read_expanded_caption(preview):

    hierarchy = get_hierarchy()

    if not hierarchy:
        return None

    try:
        root = ET.fromstring(hierarchy)

    except ET.ParseError:
        return None

    normalized_preview = normalize_for_matching(preview)

    # Avoid matching generic labels such as "See more".
    generic_previews = {
        "see more",
        "more",
        "..."
    }

    if normalized_preview in generic_previews:
        return None

    prefix = normalized_preview[:25]

    candidates = []

    for node in root.iter("node"):

        value = get_node_text(node)

        if not value or len(value) < 15:
            continue

        if is_notification_text(value):
            continue

        if is_ui_text(value):
            continue

        normalized_value = normalize_for_matching(value)

        if not prefix or prefix not in normalized_value:
            continue

        candidates.append(value)

    if not candidates:
        return None

    candidates.sort(
        key=len,
        reverse=True
    )

    return candidates[0]


# ============================================================
# DEDUPLICATION
# ============================================================

seen_reel_ids = set()


def create_reel_id(username, caption):

    identity = (
        normalize_text(username)
        + "|"
        + normalize_text(caption)
    )

    return hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()


def is_duplicate(username, caption):

    reel_id = create_reel_id(
        username,
        caption
    )

    if reel_id in seen_reel_ids:
        return True, reel_id

    seen_reel_ids.add(reel_id)

    return False, reel_id


# ============================================================
# PROCESS CAPTION
# ============================================================

def process_caption(reel_number, username, preview, bounds):

    record = {
        "reel_number": reel_number,
        "captured_at": current_timestamp(),
        "username": username,
        "caption_preview": preview,
        "full_caption": None,
        "caption_opened": False,
        "caption_status": "preview_detected"
    }

    if not preview or not bounds:

        record["caption_status"] = "no_preview_detected"
        return record

    print("\n" + "=" * 50)
    print(f"REEL {reel_number}")
    print(f"CREATOR: {username}")
    print(f"PREVIEW: {preview}")

    opened = open_caption(bounds)

    record["caption_opened"] = opened

    if opened:

        full_caption = read_expanded_caption(preview)

        if full_caption:

            record["full_caption"] = full_caption
            record["caption_status"] = "expanded_caption_read"

            print("\n[FULL CAPTION]")
            print(full_caption)

        else:

            record["caption_status"] = "expanded_text_not_found"
            print("[INFO] Full caption unavailable.")

        try:
            d.press("back")
            time.sleep(1)

        except Exception as error:
            print(f"[BACK ERROR] {error}")

    else:

        record["caption_status"] = "caption_open_failed"

    return record


# ============================================================
# INSTAGRAM NAVIGATION
# ============================================================

def launch_instagram():

    print("[START] Launching Instagram...")

    d.shell(
        f"monkey -p {INSTAGRAM_PACKAGE} "
        "-c android.intent.category.LAUNCHER 1"
    )

    time.sleep(7)


def open_reels():

    print("[ACTION] Opening Reels...")

    if d(resourceId=REELS_TAB_ID).click_exists(timeout=10):

        time.sleep(4)
        return True

    try:

        width, height = d.window_size()

        d.click(
            int(width * 0.50),
            int(height * 0.91)
        )

        time.sleep(4)

        return True

    except Exception as error:

        print(f"[REELS ERROR] {error}")
        return False


def next_reel():

    try:

        width, height = d.window_size()

        d.swipe(
            int(width * 0.50),
            int(height * 0.78),
            int(width * 0.50),
            int(height * 0.25),
            duration=0.35
        )

        time.sleep(NEXT_REEL_WAIT)

    except Exception as error:

        print(f"[SWIPE ERROR] {error}")
        time.sleep(2)


# ============================================================
# WATCH CURRENT REEL
# ============================================================

def watch_current_reel(classification):

    duration = calculate_watch_duration(classification)

    seconds = duration["actual_watch_seconds"]

    print("\n[WATCH DECISION]")
    print(f"Match level: {classification['match_level']}")
    print(f"Preference score: {classification['preference_score']}")
    print(f"Matched categories: {classification['matched_categories']}")
    print(f"Multiplier: {duration['multiplier']}x")
    print(f"Watching Reel for {seconds} seconds.")

    # This happens after the caption has been closed.
    # Instagram remains on the Reel during this period.
    time.sleep(seconds)

    return duration


# ============================================================
# UPDATE STATISTICS
# ============================================================

def update_statistics(record):

    with data_lock:

        run_data["total_reels_processed"] += 1

        if record.get("caption_preview"):
            run_data["total_captions_found"] += 1

        if record.get("full_caption"):
            run_data["total_expanded_captions"] += 1

        level = record["match_level"]

        if level != "general":
            run_data["total_matching_reels"] += 1

        if level == "partial":
            run_data["total_partial_matches"] += 1

        elif level == "strong":
            run_data["total_strong_matches"] += 1

        elif level == "very_strong":
            run_data["total_very_strong_matches"] += 1

        run_data["total_watch_seconds"] += (
            record["watch_time"]["actual_watch_seconds"]
        )


# ============================================================
# MAIN
# ============================================================

def main():

    global d

    print("=" * 60)
    print("INSTAGRAM REEL PREFERENCE WATCHER")
    print("=" * 60)

    print(f"Run ID: {RUN_ID}")
    print(f"Output: {JSON_FILE}")

    save_run_data()

    autosave_thread = threading.Thread(
        target=autosave_worker,
        daemon=True
    )

    autosave_thread.start()

    try:

        print("[DEVICE] Connecting...")

        d = u2.connect(DEVICE_ID)

        print("[SUCCESS] Device connected.")

        launch_instagram()

        if not open_reels():
            raise RuntimeError("Could not open Reels.")

        reel_number = 0

        while True:

            try:

                username, preview, bounds = get_reel_info()

                if not username:

                    print("[WARNING] Could not identify Reel.")
                    next_reel()
                    continue

                with data_lock:
                    run_data["total_reels_seen"] += 1

                # Use the preview for initial deduplication.
                identity_caption = preview or ""

                duplicate, reel_id = is_duplicate(
                    username,
                    identity_caption
                )

                if duplicate:

                    print(f"[DUPLICATE] Skipping {username}")

                    with data_lock:

                        run_data["total_duplicates_skipped"] += 1

                        run_data["duplicates"].append({
                            "detected_at": current_timestamp(),
                            "username": username,
                            "caption_preview": preview,
                            "reel_id": reel_id
                        })

                    save_run_data()
                    next_reel()
                    continue

                reel_number += 1

                record = process_caption(
                    reel_number,
                    username,
                    preview,
                    bounds
                )

                # Use the full caption when it is valid.
                # Otherwise use the preview.
                classification_text = (
                    record["full_caption"]
                    if record["full_caption"]
                    else preview or ""
                )

                hashtags = extract_hashtags(
                    classification_text
                )

                classification = classify_reel(
                    classification_text,
                    hashtags
                )

                watch_time = watch_current_reel(
                    classification
                )

                record["hashtags"] = hashtags

                record["preference_score"] = (
                    classification["preference_score"]
                )

                record["match_level"] = (
                    classification["match_level"]
                )

                record["matched_categories"] = (
                    classification["matched_categories"]
                )

                record["matched_keywords"] = (
                    classification["matched_keywords"]
                )

                record["matched_hashtags"] = (
                    classification["matched_hashtags"]
                )

                record["watch_multiplier"] = (
                    classification["watch_multiplier"]
                )

                record["watch_time"] = watch_time

                record["reel_id"] = reel_id

                with data_lock:
                    run_data["reels"].append(record)

                update_statistics(record)

                # Save after every Reel.
                save_run_data()

                print("\n[PROGRESS]")
                print(
                    f"Processed: {run_data['total_reels_processed']}"
                )
                print(
                    f"Matches: {run_data['total_matching_reels']}"
                )
                print(
                    f"Duplicates: {run_data['total_duplicates_skipped']}"
                )

                next_reel()

            except KeyboardInterrupt:
                raise

            except Exception as error:

                print(f"[REEL ERROR] {error}")
                traceback.print_exc()

                with data_lock:
                    run_data["total_errors"] += 1

                save_run_data()

                time.sleep(2)
                next_reel()

    except KeyboardInterrupt:

        print("\n[STOP] Ctrl+C detected.")

        with data_lock:
            run_data["status"] = "stopped_by_user"

    except Exception as error:

        print(f"\n[FATAL ERROR] {error}")
        traceback.print_exc()

        with data_lock:
            run_data["status"] = "error"
            run_data["error"] = str(error)

    finally:

        print("\n[SHUTDOWN] Saving final data...")

        autosave_stop.set()

        if "autosave_thread" in locals():
            autosave_thread.join(timeout=5)

        with data_lock:

            run_data["ended_at"] = current_timestamp()

            if run_data["status"] == "running":
                run_data["status"] = "completed"

        save_run_data()

        print("\n" + "=" * 60)
        print("FINAL RUN SUMMARY")
        print("=" * 60)

        print(f"Seen: {run_data['total_reels_seen']}")
        print(f"Processed: {run_data['total_reels_processed']}")
        print(f"Matches: {run_data['total_matching_reels']}")
        print(f"Partial: {run_data['total_partial_matches']}")
        print(f"Strong: {run_data['total_strong_matches']}")
        print(f"Very strong: {run_data['total_very_strong_matches']}")
        print(f"Duplicates: {run_data['total_duplicates_skipped']}")
        print(f"Errors: {run_data['total_errors']}")

        print(f"\nSaved JSON: {JSON_FILE}")


if __name__ == "__main__":
    main()

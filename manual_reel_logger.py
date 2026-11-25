
import os
import re
import json
import time
import hashlib
import logging
import tempfile

from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import uiautomator2 as u2
from PIL import Image


# ============================================================
# CONFIGURATION
# ============================================================

DEVICE_ID = "SGTSEMKNF6Y9FQZH"
INSTAGRAM_PACKAGE = "com.instagram.android"

POLL_INTERVAL = 1.0
SAVE_INTERVAL = 15

# Image detection thresholds.
# These are initial values and may need calibration against
# a screenshot showing a liked (filled red) heart.
MIN_RED_PIXELS = 25
MIN_WHITE_PIXELS = 30
MIN_COLOR_RATIO = 0.012

OUTPUT_DIR = Path("reel_data")
OUTPUT_DIR.mkdir(exist_ok=True)

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = OUTPUT_DIR / "manual_liked_reels.json"
LEGACY_FILE_PATTERN = "manual_liked_reels_*.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("ManualReelLogger")


# ============================================================
# REFERENCE REELS
# ============================================================

SEED_REELS = {
    "reel_26": {
        "creator": "anuj74129",
        "preview": "7498529018 WhatsApp number, cal",
        "category": "whatsapp_contact",
    },
    "reel_29": {
        "creator": "hustler.files",
        "preview": "Click the popup link",
        "category": "popup_link",
    },
    "reel_33": {
        "creator": "ritikyadav_0200",
        "preview": "Apna koi nhi hota",
        "category": "hindi_money_motivation",
    },
}

SEED_HASHTAGS = set()


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(value):
    if not value:
        return ""

    value = value.lower()
    value = value.replace("\u200b", "")
    value = value.replace("\u200c", "")
    value = value.replace("\u200d", "")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def extract_hashtags(text):
    if not text:
        return []

    tags = re.findall(
        r"(?<!\w)#([a-zA-Z0-9_\u0900-\u097F]+)",
        text
    )

    return list(dict.fromkeys(tag.lower() for tag in tags))


def clean_caption(text):
    if not text:
        return ""

    text = text.strip()
    normalized = normalize_text(text)

    # Android notification shade/accessibility text must never be
    # mistaken for an Instagram Reel caption.
    notification_prefixes = [
        "browsernotification:",
        "phonemanagernotification:",
        "phone managernotification:",
        "whatsappnotification:",
        "whatsapp notification:",
        "ajionotification:",
        "ajio notification:",
        "flipkartnotification:",
        "flipkart notification:",
        "linkedinnotification:",
        "linkedin notification:",
        "notification:",
    ]

    if any(normalized.startswith(prefix) for prefix in notification_prefixes):
        return ""

    bad_phrases = [
        "rahul gandhi addresses bharat summit 2026",
    ]

    if any(phrase in normalized for phrase in bad_phrases):
        return ""

    return text


def make_reel_key(username, caption):
    raw = (
        normalize_text(username)
        + "|"
        + normalize_text(caption)
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:20]


# ============================================================
# REFERENCE-BASED CLASSIFICATION
# ============================================================

def classify_reel(caption, hashtags):
    text = normalize_text(caption)
    tags = {tag.lower().lstrip("#") for tag in hashtags}

    matched_categories = []
    matched_keywords = []
    score = 0

    contact_keywords = [
        "whatsapp",
        "phone number",
        "mobile number",
        "contact number",
        "call me",
        "dm me",
        "message me",
        "number",
    ]

    link_keywords = [
        "popup",
        "pop up",
        "click the link",
        "click here",
        "tap here",
        "link in bio",
        "visit link",
    ]

    hindi_money_phrases = [
        "apna koi nhi hota",
        "apna koi nahi hota",
        "koi apna nahi hota",
        "koi apna nhi hota",
    ]

    contact_matches = [
        word for word in contact_keywords if word in text
    ]

    link_matches = [
        word for word in link_keywords if word in text
    ]

    hindi_matches = [
        phrase for phrase in hindi_money_phrases if phrase in text
    ]

    if contact_matches:
        score += 1
        matched_categories.append("whatsapp_contact")
        matched_keywords.extend(contact_matches)

    if link_matches:
        score += 1
        matched_categories.append("popup_link")
        matched_keywords.extend(link_matches)

    if hindi_matches:
        score += 3
        matched_categories.append("hindi_money_motivation")
        matched_keywords.extend(hindi_matches)

    hashtag_matches = sorted(tags.intersection(SEED_HASHTAGS))

    if hashtag_matches:
        score += len(hashtag_matches)
        matched_keywords.extend(
            ["#" + tag for tag in hashtag_matches]
        )

    if score >= 5 or len(matched_categories) >= 2:
        match_level = "very_strong"
        watch_multiplier = 3.0

    elif score >= 3:
        match_level = "strong"
        watch_multiplier = 2.0

    elif score >= 1:
        match_level = "partial"
        watch_multiplier = 1.5

    else:
        match_level = "general"
        watch_multiplier = 1.0

    return {
        "preference_score": score,
        "match_level": match_level,
        "matched_categories": matched_categories,
        "matched_keywords": list(dict.fromkeys(matched_keywords)),
        "matched_hashtags": hashtag_matches,
        "watch_multiplier": watch_multiplier,
    }


# ============================================================
# DEVICE CONNECTION
# ============================================================

def connect_device():
    log.info("Connecting to Android device: %s", DEVICE_ID)

    device = u2.connect(DEVICE_ID)

    try:
        device.screen_on()
    except Exception:
        pass

    log.info("Device connected.")
    log.info("Open Instagram and navigate to Reels manually.")
    log.info("The script will not control Instagram.")

    return device


# ============================================================
# XML / SCREEN HELPERS
# ============================================================

def get_bounds(bounds):
    if not bounds:
        return None

    numbers = re.findall(r"-?\d+", bounds)

    if len(numbers) != 4:
        return None

    return tuple(int(number) for number in numbers)


def get_bounds_center_y(bounds):
    values = get_bounds(bounds)

    if not values:
        return 0

    return (values[1] + values[3]) // 2


def get_node_resource_id(node):
    return node.attrib.get("resource-id", "")


def get_node_text(node):
    return (
        node.attrib.get("text", "")
        or node.attrib.get("content-desc", "")
    ).strip()


def is_reel_screen(root):
    for node in root.iter():
        if get_node_resource_id(node).endswith(
            "clips_media_component"
        ):
            return True

    return False


def find_username(root):
    for node in root.iter():
        resource_id = get_node_resource_id(node)

        if resource_id.endswith("clips_author_username"):
            value = get_node_text(node)

            if value:
                return value.lstrip("@").strip()

    return ""


# ============================================================
# CAPTION EXTRACTION
# ============================================================

def extract_caption_data(root):
    candidates = []
    all_visible_text = []

    ignored_ids = [
        "like_count",
        "comment_count",
        "repost_count",
        "save_count",
        "ufi_text_component",
        "clips_author_username",
        "like_button",
        "comment_button",
        "share_button",
        "save_button",
    ]

    for node in root.iter():
        text = get_node_text(node)

        if not text:
            continue

        resource_id = get_node_resource_id(node)

        if any(item in resource_id for item in ignored_ids):
            continue

        if text not in all_visible_text:
            all_visible_text.append(text)

        y = get_bounds_center_y(
            node.attrib.get("bounds", "")
        )

        if y > 0 and len(text) >= 3:
            candidates.append({
                "text": text,
                "y": y,
                "resource_id": resource_id,
            })

    candidates.sort(
        key=lambda item: (
            item["y"],
            len(item["text"]),
        ),
        reverse=True,
    )

    selected = []

    for item in candidates:
        text = clean_caption(item["text"])

        if not text:
            continue

        if text.lower() in [
            "follow",
            "following",
            "more",
            "less",
            "like",
            "comment",
            "share",
        ]:
            continue

        if text not in selected:
            selected.append(text)

    caption = ""

    if selected:
        caption = max(selected, key=len)

    caption = clean_caption(caption)

    return {
        "caption_preview": caption,
        "visible_text": all_visible_text,
        "hashtags": extract_hashtags(caption),
    }


# ============================================================
# VISUAL LIKE STATE DETECTION
# ============================================================

def find_like_button(root):
    for node in root.iter():
        resource_id = get_node_resource_id(node)

        if resource_id.endswith("like_button"):
            return node

    return None


def get_display_size(device):
    """
    Returns the coordinate dimensions used by the UI hierarchy.
    """

    try:
        width, height = device.window_size()

        if width and height:
            return int(width), int(height)

    except Exception:
        pass

    try:
        info = device.info

        width = info.get("displayWidth")
        height = info.get("displayHeight")

        if width and height:
            return int(width), int(height)

    except Exception:
        pass

    return None


def get_heart_crop(root, screenshot, device):
    """
    Uses the like_button XML bounds to crop the heart icon.

    Coordinates are scaled to the actual screenshot dimensions,
    so screenshots with different resolutions can be handled.
    """

    button = find_like_button(root)

    if button is None:
        return None

    bounds = get_bounds(
        button.attrib.get("bounds", "")
    )

    if not bounds:
        return None

    left, top, right, bottom = bounds

    display_size = get_display_size(device)

    if display_size:
        display_width, display_height = display_size

        scale_x = screenshot.width / display_width
        scale_y = screenshot.height / display_height

    else:
        # Fallback: infer scale from the XML bounds.
        scale_x = 1.0
        scale_y = 1.0

    left = int(left * scale_x)
    right = int(right * scale_x)
    top = int(top * scale_y)
    bottom = int(bottom * scale_y)

    width = right - left
    height = bottom - top

    if width <= 0 or height <= 0:
        return None

    # Keep the central area where the heart icon is located.
    # This avoids including most of the surrounding video.
    crop_left = left + int(width * 0.18)
    crop_right = right - int(width * 0.18)

    crop_top = top + int(height * 0.18)
    crop_bottom = bottom - int(height * 0.18)

    crop_left = max(0, crop_left)
    crop_top = max(0, crop_top)
    crop_right = min(screenshot.width, crop_right)
    crop_bottom = min(screenshot.height, crop_bottom)

    if crop_right <= crop_left or crop_bottom <= crop_top:
        return None

    return screenshot.crop((
        crop_left,
        crop_top,
        crop_right,
        crop_bottom,
    ))


def analyze_heart_image(heart_image):
    """
    Detects the heart using pixel colors.

    Liked:
        A sufficiently large group of saturated red pixels.

    Unliked:
        A sufficiently large group of near-white pixels
        consistent with the white outline heart.

    Unknown:
        The image does not provide enough confidence.

    The thresholds are initial estimates and should be
    calibrated after testing with a liked screenshot.
    """

    if heart_image is None:
        return None, {}

    image = heart_image.convert("RGB")
    hsv_image = image.convert("HSV")

    hsv_pixels = list(hsv_image.getdata())
    rgb_pixels = list(image.getdata())

    total_pixels = max(1, len(rgb_pixels))

    red_pixels = 0
    white_pixels = 0

    for (hue, saturation, value), (red, green, blue) in zip(
        hsv_pixels,
        rgb_pixels,
    ):

        # Instagram's red/pink heart.
        is_red = (
            (hue <= 15 or hue >= 245)
            and saturation >= 100
            and value >= 90
        )

        if is_red:
            red_pixels += 1

        # White outline heart.
        is_white = (
            red >= 190
            and green >= 190
            and blue >= 190
            and max(red, green, blue)
            - min(red, green, blue) <= 35
        )

        if is_white:
            white_pixels += 1

    red_ratio = red_pixels / total_pixels
    white_ratio = white_pixels / total_pixels

    measurements = {
        "red_pixels": red_pixels,
        "white_pixels": white_pixels,
        "red_ratio": round(red_ratio, 4),
        "white_ratio": round(white_ratio, 4),
    }

    # Filled red heart.
    if (
        red_pixels >= MIN_RED_PIXELS
        and red_ratio >= MIN_COLOR_RATIO
        and red_pixels > white_pixels
    ):
        return True, measurements

    # White outline heart.
    if (
        white_pixels >= MIN_WHITE_PIXELS
        and white_ratio >= MIN_COLOR_RATIO
        and white_pixels > red_pixels * 1.4
    ):
        return False, measurements

    return None, measurements


def get_like_state(root, device):
    """
    Returns:
        True  = visually detected liked heart
        False = visually detected unliked heart
        None  = uncertain

    Does not tap or interact with Instagram.
    """

    try:
        screenshot = device.screenshot()

        if screenshot is None:
            return None, {}

        screenshot = screenshot.convert("RGB")

        heart_crop = get_heart_crop(
            root,
            screenshot,
            device,
        )

        if heart_crop is None:
            return None, {}

        return analyze_heart_image(heart_crop)

    except Exception as error:
        log.debug("Heart image analysis failed: %s", error)

        return None, {}


# ============================================================
# REEL CAPTURE
# ============================================================

def capture_current_reel(root):
    username = find_username(root)

    caption_data = extract_caption_data(root)
    caption = caption_data["caption_preview"]

    if not username and not caption:
        return None

    reel_key = make_reel_key(username, caption)

    classification = classify_reel(
        caption,
        caption_data["hashtags"],
    )

    return {
        "reel_key": reel_key,
        "creator": username or None,
        "caption": caption or None,
        "hashtags": caption_data["hashtags"],
        "visible_text": caption_data["visible_text"],
        "classification": classification,
    }


# ============================================================
# JSON STORAGE
# ============================================================

run_data = {
    "run_id": RUN_ID,
    "started_at": datetime.now().astimezone().isoformat(),
    "device_id": DEVICE_ID,
    "package": INSTAGRAM_PACKAGE,
    "collection_mode": "manual_watch_and_manual_like",
    "automation_actions": {
        "auto_scroll": False,
        "auto_like": False,
        "auto_unlike": False,
        "auto_open_caption": False,
    },
    "reference_reels": SEED_REELS,
    "reference_hashtags": sorted(SEED_HASHTAGS),
    "statistics": {
        "liked_reels_detected": 0,
        "unliked_reels_removed": 0,
        "unknown_like_states": 0,
    },
    "reels": [],
}


def load_existing_collection():
    """Load the persistent liked-Reels collection across logger runs."""
    source_file = OUTPUT_FILE if OUTPUT_FILE.exists() else None

    # One-time migration: retain the latest file created by the older
    # timestamped-output version if the persistent file does not exist.
    if source_file is None:
        legacy_files = sorted(
            OUTPUT_DIR.glob(LEGACY_FILE_PATTERN),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if legacy_files:
            source_file = legacy_files[0]

    if source_file is None:
        log.info("No previous liked-Reels collection found; starting fresh.")
        return

    try:
        with source_file.open("r", encoding="utf-8") as file:
            previous = json.load(file)

        if not isinstance(previous, dict) or not isinstance(previous.get("reels"), list):
            raise ValueError("JSON does not contain a valid reels list")

        run_data["reels"] = previous["reels"]
        previous_stats = previous.get("statistics", {})
        for key in ("unliked_reels_removed", "unknown_like_states"):
            if key in previous_stats:
                run_data["statistics"][key] = previous_stats[key]

        log.info(
            "Loaded %d previously saved liked Reels from %s",
            len(run_data["reels"]),
            source_file,
        )

    except Exception as error:
        log.warning("Could not load previous collection (%s): %s", source_file, error)
        log.warning("Starting with an empty collection; original file was not changed.")


load_existing_collection()


def save_json():
    run_data["updated_at"] = datetime.now().astimezone().isoformat()

    run_data["statistics"]["liked_reels_detected"] = len(
        run_data["reels"]
    )

    OUTPUT_FILE.parent.mkdir(exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix="reel_logger_",
        suffix=".tmp",
        dir=str(OUTPUT_FILE.parent),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(
                run_data,
                file,
                indent=4,
                ensure_ascii=False,
            )

        os.replace(temp_path, OUTPUT_FILE)

    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass

        raise


def find_saved_reel(reel_key):
    for index, reel in enumerate(run_data["reels"]):
        if reel.get("reel_key") == reel_key:
            return index, reel

    return None, None


def record_liked_reel(reel):
    reel_key = reel["reel_key"]

    index, existing = find_saved_reel(reel_key)

    now = datetime.now().astimezone().isoformat()

    if existing:
        if len(reel.get("caption") or "") > len(
            existing.get("caption") or ""
        ):
            existing["caption"] = reel["caption"]

        existing["hashtags"] = list(dict.fromkeys(
            existing.get("hashtags", [])
            + reel.get("hashtags", [])
        ))

        existing["visible_text"] = list(dict.fromkeys(
            existing.get("visible_text", [])
            + reel.get("visible_text", [])
        ))

        existing["last_seen_at"] = now
        existing["like_status"] = "liked"

        existing["classification"] = classify_reel(
            existing.get("caption") or "",
            existing.get("hashtags", []),
        )

        return False

    record = {
        **reel,
        "first_seen_at": now,
        "last_seen_at": now,
        "liked_at": now,
        "like_status": "liked",
        "capture_source": "manual_instagram_interaction",
    }

    run_data["reels"].append(record)

    save_json()

    log.info(
        "LIKED REEL SAVED | Creator: %s | Match: %s",
        record.get("creator") or "Unknown",
        record["classification"]["match_level"],
    )

    log.info(
        "Caption: %s",
        (record.get("caption") or "Not detected")[:150],
    )

    return True


def remove_unliked_reel(reel_key):
    index, existing = find_saved_reel(reel_key)

    if existing is None:
        return

    removed = run_data["reels"].pop(index)

    run_data["statistics"]["unliked_reels_removed"] += 1

    save_json()

    log.info(
        "UNLIKED REEL REMOVED | Creator: %s",
        removed.get("creator") or "Unknown",
    )


# ============================================================
# MAIN OBSERVER
# ============================================================

def main():
    device = connect_device()

    log.info("---------------------------------------------")
    log.info("MANUAL REEL LOGGER STARTED")
    log.info("---------------------------------------------")
    log.info("Persistent collection: %s", OUTPUT_FILE.resolve())
    log.info("Previously saved liked Reels: %d", len(run_data["reels"]))
    log.info("Poll interval: %.1f seconds", POLL_INTERVAL)
    log.info("Like detection: screenshot pixel analysis")
    log.info("Waiting for Instagram Reels...")
    log.info("Like Reels manually. Ctrl+C stops the logger.")

    last_reel_key = None
    last_like_state = None
    last_save_time = time.time()

    last_error_time = 0
    last_unknown_log_time = 0

    while True:
        try:
            xml = device.dump_hierarchy(
                compressed=False,
                pretty=False,
            )

            root = ET.fromstring(xml)

            if not is_reel_screen(root):
                last_reel_key = None
                last_like_state = None

                time.sleep(POLL_INTERVAL)
                continue

            reel = capture_current_reel(root)

            if reel is None:
                time.sleep(POLL_INTERVAL)
                continue

            reel_key = reel["reel_key"]

            like_state, measurements = get_like_state(
                root,
                device,
            )

            # A different Reel has appeared.
            if reel_key != last_reel_key:
                last_reel_key = reel_key
                last_like_state = None

                log.info(
                    "REEL DETECTED | Creator: %s",
                    reel.get("creator") or "Unknown",
                )

            # Save only when the heart is visually detected
            # as filled red.
            if like_state is True:
                record_liked_reel(reel)

                if last_like_state is not True:
                    log.info(
                        "LIKE DETECTED | Red pixels: %s",
                        measurements.get("red_pixels", 0),
                    )

            # Remove a previously saved Reel when its heart
            # is confidently detected as an outline.
            elif like_state is False:
                remove_unliked_reel(reel_key)

                if last_like_state is not False:
                    log.info(
                        "UNLIKED STATE DETECTED | White pixels: %s",
                        measurements.get("white_pixels", 0),
                    )

            else:
                now = time.time()

                if now - last_unknown_log_time >= 10:
                    log.warning(
                        "LIKE STATE UNCERTAIN | "
                        "Red pixels: %s | White pixels: %s. "
                        "No action taken.",
                        measurements.get("red_pixels", 0),
                        measurements.get("white_pixels", 0),
                    )

                    last_unknown_log_time = now

                run_data["statistics"]["unknown_like_states"] += 1

            last_like_state = like_state

            # Periodic backup.
            if time.time() - last_save_time >= SAVE_INTERVAL:
                save_json()
                last_save_time = time.time()

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            raise

        except Exception as error:
            now = time.time()

            if now - last_error_time >= 5:
                log.warning(
                    "Screen reading error: %s",
                    error,
                )
                last_error_time = now

            time.sleep(2)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        log.info("Ctrl+C received. Saving collected data...")

    finally:
        try:
            save_json()

            log.info(
                "Final JSON saved: %s",
                OUTPUT_FILE.resolve(),
            )

            log.info(
                "Currently liked Reels saved: %d",
                len(run_data["reels"]),
            )

        except Exception as error:
            log.exception("Final save failed: %s", error)

        log.info("Logger stopped.")

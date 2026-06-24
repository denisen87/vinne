import json
import os
import sys
import time
from pathlib import Path
import ctypes

import cv2
import numpy as np
import pyautogui


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "fronted" / "current_live_cards.json"
DEBUG_HERO = ROOT / "fronted" / "hero_cards_debug_latest.png"
DEBUG_RAW = ROOT / "fronted" / "hero_cards_debug_raw.png"
DEBUG_WIDE = ROOT / "fronted" / "hero_cards_debug_wide.png"
CALIBRATION_CAPTURE = ROOT / "fronted" / "calibration_capture.png"
CALIBRATION_ARCHIVE = ROOT / "fronted" / "calibration_captures"
CALIBRATION_LATEST = CALIBRATION_ARCHIVE / "latest.txt"
CALIBRATION_INDEX = CALIBRATION_ARCHIVE / "index.json"
CURRENT_GAME = ROOT / "backend" / "current_game.json"
TEMPLATE_DIR = ROOT / ".github" / "vinne" / "card_templates"
VERSION = "green_table_suit_fallback_v46"
CALIBRATION_REVIEW = ROOT / "fronted" / "calibration_review.png"
SCREENSHOT_DELAY_SECONDS = float(os.getenv("SCREENSHOT_DELAY_SECONDS", "2.0"))

# Crop relative to the active BetSolid table window. Absolute screen crops broke
# whenever the browser/BetSolid windows moved or a replay window was opened.
BASE_HERO_REGION = (245, 330, 260, 190)
SEARCH_DX = (-70, -50, -30, -10, 0, 10, 30, 50, 70, 90, 110)
SEARCH_DY = (-60, -45, -30, -15, 0, 15, 30, 45, 60)

# Card boxes inside HERO_REGION. They are intentionally a bit generous.
LEFT_CARD_RECT = (78, 24, 58, 82)
RIGHT_CARD_RECTS = [
    (126, 24, 58, 82),
    (130, 24, 58, 82),
    (122, 24, 62, 82),
]
HERO_PAIR_CENTER_MIN = 95
HERO_PAIR_CENTER_MAX = 225
HERO_PAIR_CENTER_TARGET = 150

RANKS = "23456789TJQKA"
SUITS = "HDCS"
TEMPLATE_SIZE = (28, 28)
LAST_ARCHIVE_AT = 0.0
LAST_ARCHIVE_KEY = None


def save_debug_image(path: Path, img):
    ok, encoded = cv2.imencode(".png", img)
    if ok:
        path.write_bytes(encoded.tobytes())


def safe_label(value: str, fallback="blank"):
    label = "".join(ch if ch.isalnum() else "_" for ch in (value or "").strip())
    return label.strip("_") or fallback


def archive_calibration_crop(crop, region, score, cards, error):
    global LAST_ARCHIVE_AT, LAST_ARCHIVE_KEY

    now = time.time()
    key = (cards or "", error or "", str(region), int(score or 0))
    if key == LAST_ARCHIVE_KEY and now - LAST_ARCHIVE_AT < 5.0:
        return None
    if now - LAST_ARCHIVE_AT < 1.5:
        return None

    CALIBRATION_ARCHIVE.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
    suffix = safe_label(cards or error, "unread")[:60]
    path = CALIBRATION_ARCHIVE / f"{stamp}_{int((now % 1) * 1000):03d}_{suffix}.png"
    save_debug_image(path, crop)
    try:
        CALIBRATION_LATEST.write_text(str(path), encoding="utf-8")
    except Exception:
        pass
    LAST_ARCHIVE_AT = now
    LAST_ARCHIVE_KEY = key
    return path


def read_image(path: Path):
    try:
        raw = np.fromfile(str(path), dtype=np.uint8)
        if raw.size == 0:
            return None
        return cv2.imdecode(raw, cv2.IMREAD_COLOR)
    except Exception:
        return None


def valid_card_text(cards_text: str) -> list[str]:
    cards = []
    for raw in (cards_text or "").replace(",", " ").split():
        raw = raw.strip()
        if len(raw) < 2:
            continue
        rank = raw[:-1].upper().replace("10", "T")
        suit = raw[-1].upper()
        if rank in RANKS and suit in SUITS:
            cards.append(f"{rank}{suit}")
    return cards


def canonical_mask(mask, size=TEMPLATE_SIZE):
    if mask is None or mask.size == 0:
        return None
    _, b = cv2.threshold(mask, 80, 255, cv2.THRESH_BINARY)
    ys, xs = np.where(b > 0)
    if len(xs) < 4 or len(ys) < 4:
        return None

    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    glyph = b[y1:y2, x1:x2]
    gh, gw = glyph.shape[:2]
    if gh <= 1 or gw <= 1:
        return None

    canvas = np.zeros(size, dtype=np.uint8)
    scale = min((size[0] - 4) / max(gw, 1), (size[1] - 4) / max(gh, 1))
    nw = max(1, int(round(gw * scale)))
    nh = max(1, int(round(gh * scale)))
    resized = cv2.resize(glyph, (nw, nh), interpolation=cv2.INTER_NEAREST)
    ox = (size[0] - nw) // 2
    oy = (size[1] - nh) // 2
    canvas[oy : oy + nh, ox : ox + nw] = resized
    return canvas


def ink_mask(area):
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)
    mask = (
        ((hsv[:, :, 1] > 35) & (hsv[:, :, 2] < 245))
        | (hsv[:, :, 2] < 85)
    ).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))


def card_body_mask(hsv):
    return cv2.inRange(hsv, np.array([0, 0, 115]), np.array([180, 150, 255]))


def extract_rank_and_suit_masks(card_img):
    card_img = trim_to_card_body(card_img)
    h, w = card_img.shape[:2]
    rank_area = card_img[
        max(0, int(h * 0.04)) : min(h, int(h * 0.31)),
        max(0, int(w * 0.03)) : min(w, int(w * 0.38)),
    ]
    suit_area = card_img[
        max(0, int(h * 0.22)) : min(h, int(h * 0.58)),
        max(0, int(w * 0.03)) : min(w, int(w * 0.40)),
    ]
    return ink_mask(rank_area), ink_mask(suit_area)


def load_templates(kind: str):
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    templates = []
    for path in TEMPLATE_DIR.glob(f"{kind}_*.png"):
        parts = path.stem.split("_")
        if len(parts) < 2:
            continue
        try:
            raw = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        except Exception:
            img = None
        if img is None:
            continue
        templates.append((parts[1].upper(), img))
    return templates


def template_match(mask, kind: str):
    sample = canonical_mask(mask)
    if sample is None:
        return "", 0.0

    scores = {}
    for label, templ in load_templates(kind):
        if templ.shape != sample.shape:
            templ = cv2.resize(templ, sample.shape[::-1], interpolation=cv2.INTER_NEAREST)
        score = 1.0 - float(np.mean(cv2.absdiff(sample, templ))) / 255.0
        scores[label] = max(scores.get(label, 0.0), score)

    if not scores:
        return "", 0.0

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_label, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    if len(ranked) > 1 and best_score - second_score < 0.005:
        return "", best_score
    if best_score >= 0.98:
        return best_label, best_score
    if best_score >= 0.78 and best_score - second_score >= 0.025:
        return best_label, best_score
    return "", best_score


def save_template(kind: str, label: str, mask):
    label = label.upper()
    if (kind == "rank" and label not in RANKS) or (kind == "suit" and label not in SUITS):
        return False
    templ = canonical_mask(mask)
    if templ is None:
        return False
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_templates(kind)
    for existing_label, existing_img in existing:
        score = 1.0 - float(np.mean(cv2.absdiff(templ, existing_img))) / 255.0
        if existing_label != label and score > 0.96:
            return False
        if existing_label != label:
            continue
        if score > 0.97:
            return False
    path = TEMPLATE_DIR / f"{kind}_{label}_{time.time_ns()}.png"
    save_debug_image(path, templ)
    return True


def normalize_card(rank: str, suit: str) -> str:
    if not rank or not suit:
        return ""
    return f"{rank.upper()}{suit.upper()}"


def trim_to_card_body(card_img):
    hsv = cv2.cvtColor(card_img, cv2.COLOR_BGR2HSV)
    white = card_body_mask(hsv)
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h >= 80 and w >= 10 and h >= 10:
            boxes.append((x, y, w, h, cv2.contourArea(c)))
    if not boxes:
        return card_img

    main = max(boxes, key=lambda box: box[4])
    if main[2] >= 25 and main[3] >= 35:
        x, y, w, h, _ = main
        x1 = max(0, x - 1)
        y1 = max(0, y - 1)
        x2 = min(card_img.shape[1], x + w + 1)
        y2 = min(card_img.shape[0], y + h + 1)
        return card_img[y1:y2, x1:x2]

    x1 = max(0, min(x for x, _, _, _, _ in boxes) - 1)
    y1 = max(0, min(y for _, y, _, _, _ in boxes) - 1)
    x2 = min(card_img.shape[1], max(x + w for x, _, w, _, _ in boxes) + 1)
    y2 = min(card_img.shape[0], max(y + h for _, y, _, h, _ in boxes) + 1)
    if x2 - x1 < 16 or y2 - y1 < 20:
        return card_img
    return card_img[y1:y2, x1:x2]


def color_mask(hsv, suit):
    if suit == "H":
        return cv2.inRange(hsv, np.array([0, 45, 30]), np.array([14, 255, 255])) | cv2.inRange(
            hsv, np.array([165, 45, 30]), np.array([180, 255, 255])
        )
    if suit == "D":
        return cv2.inRange(hsv, np.array([85, 25, 30]), np.array([145, 255, 255]))
    if suit == "C":
        return cv2.inRange(hsv, np.array([35, 25, 25]), np.array([95, 255, 255]))
    return cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 170, 135]))


def suit_color_scores(card_img):
    card_img = trim_to_card_body(card_img)
    h, w = card_img.shape[:2]
    suit_area = card_img[
        max(0, int(h * 0.22)) : min(h, int(h * 0.55)),
        max(0, int(w * 0.03)) : min(w, int(w * 0.38)),
    ]
    suit_hsv = cv2.cvtColor(suit_area, cv2.COLOR_BGR2HSV)
    value_mask = cv2.inRange(suit_hsv[:, :, 2], 20, 235)
    return {
        suit: int(np.count_nonzero(cv2.bitwise_and(color_mask(suit_hsv, suit), value_mask)))
        for suit in ("H", "D", "C", "S")
    }


def suit_from_color(card_img):
    scores = suit_color_scores(card_img)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    if best_score < 18:
        return "", scores
    if best == "S" and scores["C"] >= best_score * 0.70:
        return "C", scores
    if best_score - second_score < 10 and best not in ("H", "D"):
        return "", scores
    return best, scores


def find_rank_blob_and_suit(card_img):
    # Only look in the upper-left corner of the physical card. BetSolid uses
    # tinted anti-aliasing, so selecting by suit color alone often captures
    # only a thin stroke of the rank. Read the rank as all non-white ink, then
    # infer suit from the small symbol below it.
    card_img = trim_to_card_body(card_img)
    h, w = card_img.shape[:2]
    rank_mask, suit_mask = extract_rank_and_suit_masks(card_img)
    contours, _ = cv2.findContours(rank_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rank_boxes = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw * bh < 6:
            continue
        if x > 18 or y > 20:
            continue
        rank_boxes.append((x, y, bw, bh))

    blob = rank_mask if rank_boxes else None

    templ_suit, suit_match_score = template_match(suit_mask, "suit")
    color_suit, suit_scores = suit_from_color(card_img)
    if templ_suit and suit_match_score >= 0.97:
        suit = templ_suit
    elif templ_suit and templ_suit == color_suit:
        suit = templ_suit
    elif templ_suit in ("H", "D", "C") and suit_scores.get(templ_suit, 0) >= 30:
        suit = templ_suit
    else:
        suit = color_suit

    if blob is not None:
        return blob, suit

    area = card_img[0 : min(48, h), 0 : min(42, w)]
    hsv = cv2.cvtColor(area, cv2.COLOR_BGR2HSV)

    candidates = []
    for suit in ("H", "D", "C", "S"):
        mask = color_mask(hsv, suit)
        # Keep ink-ish pixels, not bright card/background.
        mask = cv2.bitwise_and(mask, cv2.inRange(hsv[:, :, 2], 20, 235))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            area_px = bw * bh
            if area_px < 8:
                continue
            if not (2 <= bw <= 22 and 5 <= bh <= 30):
                continue
            if y > 26:
                continue
            candidates.append((y, x, -area_px, suit, mask, (x, y, bw, bh)))

    if not candidates:
        return None, ""

    candidates.sort()
    _, _, _, suit, mask, (x, y, bw, bh) = candidates[0]
    pad = 1
    x1, y1 = max(0, x - pad), max(0, y - pad)
    x2, y2 = min(mask.shape[1], x + bw + pad), min(mask.shape[0], y + bh + pad)
    return mask[y1:y2, x1:x2], suit


def rank_features(blob):
    if blob is None or blob.size == 0:
        return None
    _, b = cv2.threshold(blob, 80, 255, cv2.THRESH_BINARY)
    h, w = b.shape
    rows = np.array([np.count_nonzero(b[i, :]) for i in range(h)])
    cols = np.array([np.count_nonzero(b[:, i]) for i in range(w)])
    top = int(rows[: max(1, h // 3)].sum())
    mid = int(rows[h // 3 : max(h // 3 + 1, 2 * h // 3)].sum())
    bot = int(rows[2 * h // 3 :].sum())
    left = int(cols[: max(1, w // 3)].sum())
    center = int(cols[w // 3 : max(w // 3 + 1, 2 * w // 3)].sum())
    right = int(cols[2 * w // 3 :].sum())
    return {
        "h": h,
        "w": w,
        "top": top,
        "mid": mid,
        "bot": bot,
        "left": left,
        "center": center,
        "right": right,
        "ink": int(np.count_nonzero(b)),
        "rows": rows.tolist(),
        "cols": cols.tolist(),
    }


def classify_rank(blob):
    templ_rank, rank_match_score = template_match(blob, "rank")
    f = rank_features(blob)
    if not f:
        return ""
    if f["ink"] / max(1, f["h"] * f["w"]) > 0.68:
        return ""

    looks_like_ten = (
        f["h"] >= 13
        and f["w"] >= 15
        and f["left"] >= 14
        and f["right"] >= 18
        and f["center"] >= 10
        and f["mid"] >= f["top"] * 0.75
    )
    narrow_left_stroke = f["left"] >= max(40, f["ink"] * 0.75) and (f["center"] + f["right"]) <= max(8, f["ink"] * 0.15)
    if templ_rank == "T" and rank_match_score >= 0.88:
        return "T"

    # Template history can occasionally confuse BetSolid's wide 8 with 6.
    # Prefer the shape features when the glyph is clearly a broad, closed 8.
    if (
        templ_rank == "6"
        and f["w"] >= 14
        and f["ink"] >= 90
        and f["mid"] >= f["top"] * 0.9
        and f["bot"] >= f["top"] * 0.9
        and abs(f["left"] - f["right"]) < max(24, f["ink"] * 0.35)
    ):
        return "8"

    if templ_rank in "23456789" and rank_match_score >= 0.88 and not narrow_left_stroke:
        return templ_rank
    if templ_rank and rank_match_score >= 0.92 and not narrow_left_stroke:
        return templ_rank
    if rank_match_score >= 0.90:
        return ""

    # Keep shape-only guesses opt-in. They can read hidden/covered cards as
    # real cards when the avatar or table UI creates card-like white blobs.
    if os.getenv("SCREEN_READER_ALLOW_RANK_HEURISTICS", "").lower() not in ("1", "true", "yes"):
        return ""

    # Small, practical rules for BetSolid's tiny corner font.
    # They are intentionally conservative; blank is better than a false card.
    if f["ink"] < 12:
        return ""
    if f["w"] <= 5 and f["h"] >= 10:
        return "1"  # part of 10, handled below when possible
    if f["left"] > f["right"] * 1.7 and f["bot"] > f["top"]:
        return "5"
    if f["right"] > f["left"] * 1.5 and f["bot"] >= f["mid"]:
        return "4"
    if f["w"] >= 14 and f["ink"] >= 90 and f["mid"] >= f["top"] * 0.9 and f["bot"] >= f["top"] * 0.9:
        return "8"
    if f["bot"] > f["top"] * 1.3 and f["mid"] >= f["top"] * 0.8:
        return "6"
    if f["top"] > f["bot"] * 1.3 and f["right"] >= f["left"]:
        return "7"
    if f["ink"] > 55 and abs(f["left"] - f["right"]) < max(8, f["ink"] * 0.25):
        return "8"

    # Face cards often have wider blobs/crowns. Prefer blank unless obvious.
    if f["w"] >= 12 and f["h"] >= 12:
        if f["right"] > f["left"] and f["top"] >= f["bot"]:
            return "K"
        if f["left"] >= f["right"] and f["bot"] >= f["top"]:
            return "J"
        return "A"

    return ""


def read_card(card_rect, img):
    x, y, w, h = card_rect
    card = img[y : y + h, x : x + w]
    blob, suit = find_rank_blob_and_suit(card)
    rank = classify_rank(blob)

    # Handle 10 as a wider/combined blob fallback.
    if rank == "1":
        rank = "T"

    return normalize_card(rank, suit)


def detect_card_rects(crop):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = card_body_mask(hsv)
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((4, 4), np.uint8))
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if area < 250:
            continue
        if not (20 <= w <= 130 and 18 <= h <= 100):
            continue
        if y < 20 or y > 95:
            continue
        boxes.append((x, y, w, h, area))

    # Merge nearby fragments from the same physical card.
    boxes.sort(key=lambda b: b[0])
    merged = []
    for box in boxes:
        x, y, w, h, area = box
        if merged and x <= merged[-1][0] + merged[-1][2] + 8:
            px, py, pw, ph, pa = merged[-1]
            x1, y1 = min(px, x), min(py, y)
            x2, y2 = max(px + pw, x + w), max(py + ph, y + h)
            merged[-1] = (x1, y1, x2 - x1, y2 - y1, pa + area)
        else:
            merged.append(box)

    candidates = []
    for x, y, w, h, area in merged:
        pad_x, pad_y = 4, 5
        if w >= 85:
            half = w // 2
            for sx, sw in ((x, half + 4), (x + half - 4, w - half + 4)):
                rx = max(0, sx - pad_x)
                ry = max(0, y - pad_y)
                rw = min(crop.shape[1] - rx, sw + pad_x * 2)
                rh = min(crop.shape[0] - ry, max(h + pad_y * 2, 58))
                candidates.append((rx, ry, rw, rh))
        else:
            rx = max(0, x - pad_x)
            ry = max(0, y - pad_y)
            rw = min(crop.shape[1] - rx, w + pad_x * 2)
            rh = min(crop.shape[0] - ry, max(h + pad_y * 2, 58))
            candidates.append((rx, ry, rw, rh))

    candidates.sort(key=lambda r: r[0])
    pairs = []
    for i, left in enumerate(candidates):
        for right in candidates[i + 1 :]:
            lx, ly, lw, lh = left
            rx, ry, rw, rh = right
            if abs(ly - ry) > 22:
                continue
            if lw < 42 or rw < 42 or lh < 50 or rh < 50:
                continue
            gap = rx - (lx + lw)
            if gap < -25 or gap > 65:
                continue
            pairs.append((abs(ly - ry) + max(0, gap), left, right))
    if pairs:
        pairs.sort(key=lambda item: item[0])
        return [pairs[0][1], pairs[0][2]]
    return []


def card_rect_score(card_rect, img):
    x, y, w, h = card_rect
    card = img[y : y + h, x : x + w]
    if card.size == 0:
        return 0

    hsv = cv2.cvtColor(card, cv2.COLOR_BGR2HSV)
    white = card_body_mask(hsv)
    white_score = int(np.count_nonzero(white))

    # Real cards have a white body plus colored/dark ink in the top-left rank area.
    corner = card[0:34, 0:38]
    corner_hsv = cv2.cvtColor(corner, cv2.COLOR_BGR2HSV)
    ink_score = 0
    for suit in ("H", "D", "C", "S"):
        ink_score += int(np.count_nonzero(color_mask(corner_hsv, suit)))

    return white_score + (ink_score * 4)


def crop_score(crop):
    detected = detect_card_rects(crop)
    if len(detected) >= 2:
        left, right = detected[:2]
        pair_left = min(left[0], right[0])
        pair_right = max(left[0] + left[2], right[0] + right[2])
        pair_center = (pair_left + pair_right) / 2
        avg_y = (left[1] + right[1]) / 2
        if not (HERO_PAIR_CENTER_MIN <= pair_center <= HERO_PAIR_CENTER_MAX):
            return 0

        # Prefer the real hero-card zone inside the crop. Without this, white
        # chip stacks on the left side of the table can look enough like cards
        # to win the crop search.
        position_bonus = max(0, int(2500 - abs(pair_center - HERO_PAIR_CENTER_TARGET) * 35 - abs(avg_y - 55) * 20))
        return sum(card_rect_score(rect, crop) for rect in detected) + 10000 + position_bonus

    return 0


def candidate_regions():
    x, y, w, h = BASE_HERO_REGION
    for dy in SEARCH_DY:
        for dx in SEARCH_DX:
            region = (x + dx, y + dy, w, h)
            # Do not scan high board/player-card areas. If we cannot find hero
            # cards in this lower band, return blank instead of wrong cards.
            if 270 <= region[1] <= 390:
                yield region


def active_table_window():
    windows = []
    for win in pyautogui.getAllWindows():
        title = win.title or ""
        if win.left < -1000 or win.top < -1000 or win.width < 400 or win.height < 300:
            continue
        if title.startswith("Hand Replayer"):
            continue
        # Browser tabs can contain poker words too. The real BetSolid table
        # window has "NL Hold'em" plus the native client version marker.
        if "NL Hold'em" in title and "v.26." in title:
            windows.append(win)

    if not windows:
        return None

    # Prefer actual poker tables over browser tabs or small helper windows.
    windows.sort(key=lambda w: -(w.width * w.height))
    return windows[0]


def bring_window_to_front(win):
    if not win:
        return

    hwnd = getattr(win, "_hWnd", None)
    try:
        if hwnd:
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        win.activate()
    except Exception:
        pass


def best_hero_crop():
    table = active_table_window()
    bring_window_to_front(table)

    if SCREENSHOT_DELAY_SECONDS > 0:
        time.sleep(SCREENSHOT_DELAY_SECONDS)

    if table:
        full = pyautogui.screenshot(region=(table.left, table.top, table.width, table.height))
        window_offset = (table.left, table.top)
    else:
        full = pyautogui.screenshot()
        window_offset = (0, 0)

    full_bgr = cv2.cvtColor(np.array(full), cv2.COLOR_RGB2BGR)
    screen_h, screen_w = full_bgr.shape[:2]

    best = None
    best_score = -1
    best_region = BASE_HERO_REGION
    for region in candidate_regions():
        x, y, w, h = region
        if x < 0 or y < 0 or x + w > screen_w or y + h > screen_h:
            continue
        crop = full_bgr[y : y + h, x : x + w]
        score = crop_score(crop)
        if score > best_score:
            best = crop
            best_score = score
            best_region = region

    if best is None or best_score <= 0:
        x, y, w, h = BASE_HERO_REGION
        best = full_bgr[y : y + h, x : x + w]
        best_score = 0

    # Wide debug view around hero area, with the chosen crop marked.
    wx, wy, ww, wh = 250, 260, 520, 310
    wide = full_bgr[wy : wy + wh, wx : wx + ww].copy()
    bx, by, bw, bh = best_region
    cv2.rectangle(wide, (bx - wx, by - wy), (bx - wx + bw, by - wy + bh), (0, 255, 255), 2)
    abs_region = (
        best_region[0] + window_offset[0],
        best_region[1] + window_offset[1],
        best_region[2],
        best_region[3],
    )
    title = (table.title if table else "full-screen")[:70]
    cv2.putText(wide, f"region={abs_region} score={best_score}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    cv2.putText(wide, title, (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    save_debug_image(DEBUG_WIDE, wide)

    return best, abs_region, best_score


def read_cards_from_crop(crop):
    save_debug_image(DEBUG_RAW, crop)
    debug = crop.copy()
    detected = detect_card_rects(crop)
    rects = detected if len(detected) >= 2 else []

    for rect in rects:
        x, y, w, h = rect
        cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 255, 255), 1)
    save_debug_image(DEBUG_HERO, debug)

    if len(detected) < 2:
        return "", "no_two_card_boxes_detected"

    left = read_card(detected[0], crop)
    right_attempts = [read_card(detected[1], crop)]
    right = next((c for c in right_attempts if c), "")

    if left and right:
        return f"{left} {right}", None
    return "", f"fixed_crop_failed:left={left!r}, right_attempts={right_attempts!r}"


def current_game_known_hero():
    if not CURRENT_GAME.exists():
        return []
    try:
        data = json.loads(CURRENT_GAME.read_text(encoding="utf-8-sig"))
    except Exception:
        return []

    updated_at = data.get("updated_at")
    if updated_at:
        try:
            updated = time.mktime(time.strptime(updated_at[:19], "%Y-%m-%dT%H:%M:%S"))
            if time.time() - updated > 180:
                return []
        except Exception:
            pass

    return valid_card_text(data.get("hero") or data.get("hero_cards") or "")


def learn_templates_from_known_hero(crop):
    known = current_game_known_hero()
    if len(known) != 2:
        return 0

    rects = detect_card_rects(crop)
    if len(rects) < 2:
        return 0

    existing_read, _ = read_cards_from_crop(crop)
    if valid_card_text(existing_read) != known:
        return 0

    saved = 0
    for rect, card_text in zip(rects[:2], known):
        x, y, w, h = rect
        card_img = crop[y : y + h, x : x + w]
        rank_mask, suit_mask = extract_rank_and_suit_masks(card_img)
        saved += int(save_template("rank", card_text[0], rank_mask))
        saved += int(save_template("suit", card_text[1], suit_mask))
    return saved


def read_hero_cards_from_screen():
    crop, region, score = best_hero_crop()
    if score <= 0:
        archive = archive_calibration_crop(crop, region, score, "", "no_valid_hero_crop")
        extra = f"; capture={archive.name}" if archive else ""
        return "", f"no_valid_hero_crop; region={region}; score={score}; learned=0{extra}"
    learned = learn_templates_from_known_hero(crop)
    cards, error = read_cards_from_crop(crop)
    archive = archive_calibration_crop(crop, region, score, cards, error)
    capture = f"; capture={archive.name}" if archive else ""
    if error:
        error = f"{error}; region={region}; score={score}; learned={learned}{capture}"
    return cards, error


def calibrate_crop(crop, cards_text, region, score):
    expected = valid_card_text(cards_text)
    if len(expected) != 2:
        print('Bruk: python .github\\vinne\\screen_reader.py --calibrate "AS KH"')
        return 2

    save_debug_image(ROOT / "fronted" / "calibration_latest.png", crop)
    rects = detect_card_rects(crop)
    current_read, current_error = read_cards_from_crop(crop)
    print(f"region={region} score={score} rects={rects}")
    print(f"before={current_read!r} error={current_error!r} expected={' '.join(expected)!r}")
    if len(rects) < 2:
        print("Fant ikke to kortbokser. Bordet må være synlig foran nettleseren.")
        return 1

    saved = 0
    for rect, card_text in zip(rects[:2], expected):
        x, y, w, h = rect
        card_img = crop[y : y + h, x : x + w]
        rank_mask, suit_mask = extract_rank_and_suit_masks(card_img)
        saved += int(save_template("rank", card_text[0], rank_mask))
        saved += int(save_template("suit", card_text[1], suit_mask))

    after_read, after_error = read_cards_from_crop(crop)
    print(f"saved={saved} after={after_read!r} error={after_error!r}")
    return 0 if saved or valid_card_text(after_read) == expected else 1


def calibrate_from_current_screen(cards_text):
    crop, region, score = best_hero_crop()
    return calibrate_crop(crop, cards_text, region, score)


def capture_then_calibrate(cards_text=None):
    global SCREENSHOT_DELAY_SECONDS
    old_delay = SCREENSHOT_DELAY_SECONDS
    SCREENSHOT_DELAY_SECONDS = 0.05
    try:
        crop, region, score = best_hero_crop()
    finally:
        SCREENSHOT_DELAY_SECONDS = old_delay

    save_debug_image(CALIBRATION_CAPTURE, crop)
    print(f"Bildet er fanget. region={region} score={score}")
    print(r"Se eventuelt fronted\calibration_capture.png.")
    if cards_text is None:
        cards_text = input('Skriv kortene fra fanget bilde, f.eks. "8D 9C": ').strip()
    return calibrate_crop(crop, cards_text, region, score)


def calibrate_from_saved_capture(cards_text):
    crop = read_image(CALIBRATION_CAPTURE)
    if crop is None:
        print(r"Fant ikke fronted\calibration_capture.png. Kjor --capture-calibrate forst.")
        return 1
    return calibrate_crop(crop, cards_text, ("saved_capture",), crop_score(crop))


def resolve_capture_path(path_text):
    path = Path(path_text.strip().strip('"'))
    if not path.is_absolute():
        path = ROOT / path
    return path


def calibrate_from_file(path_text, cards_text):
    path = resolve_capture_path(path_text)
    crop = read_image(path)
    if crop is None:
        print(f"Fant ikke/kunne ikke lese: {path}")
        return 1
    print(f"Kalibrerer fra: {path}")
    return calibrate_crop(crop, cards_text, (str(path),), crop_score(crop))


def cards_from_capture_name(path: Path):
    cards = []
    for part in path.stem.upper().split("_"):
        if len(part) in (2, 3):
            parsed = valid_card_text(part)
            if len(parsed) == 1:
                cards.extend(parsed)
    return cards[-2:] if len(cards) >= 2 else []


def calibrate_from_latest(cards_text):
    if not CALIBRATION_LATEST.exists():
        print(r"Fant ingen latest.txt. Start screen_reader.py og la den fange minst ett bilde.")
        return 1
    path_text = CALIBRATION_LATEST.read_text(encoding="utf-8").strip()
    path = resolve_capture_path(path_text)
    expected = valid_card_text(cards_text)
    named = cards_from_capture_name(path)
    if named and expected and named != expected:
        print(f"STOPP: siste bilde ser ut til å være {' '.join(named)}, ikke {' '.join(expected)}.")
        print(f"Bruk riktig fasit for dette bildet, eller velg riktig fil fra:")
        print(CALIBRATION_ARCHIVE)
        return 2
    return calibrate_from_file(path_text, cards_text)


def recent_capture_paths(limit=20):
    if not CALIBRATION_ARCHIVE.exists():
        return []
    return sorted(
        CALIBRATION_ARCHIVE.glob("*.png"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]


def list_captures(limit_text=None):
    try:
        limit = int(limit_text) if limit_text else 20
    except ValueError:
        limit = 20
    paths = recent_capture_paths(limit)
    if not paths:
        print(r"Ingen bilder i fronted\calibration_captures ennå.")
        return 1
    CALIBRATION_ARCHIVE.mkdir(parents=True, exist_ok=True)
    CALIBRATION_INDEX.write_text(
        json.dumps([str(path) for path in paths], indent=2),
        encoding="utf-8",
    )
    print("Indeks låst. Bruk --calibrate-index med nummeret under.")
    for idx, path in enumerate(paths, 1):
        cards = cards_from_capture_name(path)
        label = " ".join(cards) if cards else "-"
        print(f"{idx:02d}: {path.name}  [{label}]")
    return 0


def review_captures(limit_text=None):
    try:
        limit = int(limit_text) if limit_text else 12
    except ValueError:
        limit = 12
    paths = recent_capture_paths(limit)
    if not paths:
        print(r"Ingen bilder i fronted\calibration_captures ennå.")
        return 1

    CALIBRATION_ARCHIVE.mkdir(parents=True, exist_ok=True)
    CALIBRATION_INDEX.write_text(
        json.dumps([str(path) for path in paths], indent=2),
        encoding="utf-8",
    )

    thumb_w, thumb_h = 260, 190
    label_h = 34
    cols = 3
    rows = int(np.ceil(len(paths) / cols))
    sheet = np.full((rows * (thumb_h + label_h), cols * thumb_w, 3), 245, dtype=np.uint8)

    for idx, path in enumerate(paths, 1):
        img = read_image(path)
        if img is None:
            img = np.zeros((thumb_h, thumb_w, 3), dtype=np.uint8)
        img = cv2.resize(img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        row = (idx - 1) // cols
        col = (idx - 1) % cols
        y = row * (thumb_h + label_h)
        x = col * thumb_w
        sheet[y : y + thumb_h, x : x + thumb_w] = img
        cv2.rectangle(sheet, (x, y), (x + thumb_w - 1, y + thumb_h + label_h - 1), (60, 60, 60), 1)
        cv2.rectangle(sheet, (x + 4, y + 4), (x + 58, y + 38), (0, 0, 0), -1)
        cv2.putText(sheet, f"{idx:02d}", (x + 10, y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2)
        cards = " ".join(cards_from_capture_name(path)) or "-"
        cv2.putText(sheet, cards, (x + 8, y + thumb_h + 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1)

    save_debug_image(CALIBRATION_REVIEW, sheet)
    print("Indeks låst. Send meg nummer + riktige kort, f.eks. '03 = JS 4S'.")
    print(CALIBRATION_REVIEW)
    return list_captures(str(limit))


def indexed_capture_paths():
    if not CALIBRATION_INDEX.exists():
        return []
    try:
        raw_paths = json.loads(CALIBRATION_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return []
    paths = [Path(path) for path in raw_paths]
    return [path for path in paths if path.exists()]


def calibrate_from_index(index_text, cards_text):
    try:
        index = int(index_text)
    except ValueError:
        print("Bruk nummer fra --list-captures, f.eks. --calibrate-index 3 \"JS 4S\"")
        return 2
    paths = indexed_capture_paths() or recent_capture_paths(max(20, index))
    if index < 1 or index > len(paths):
        print(f"Fant ikke bilde nummer {index}. Kjor --list-captures først.")
        return 1
    return calibrate_from_file(str(paths[index - 1]), cards_text)


def write_cards(hero_cards, source, error=None):
    data = {
        "hero_cards": hero_cards,
        "board": "",
        "source": source,
        "error": error,
        "version": VERSION,
        "timestamp": time.time(),
    }
    tmp = OUT.with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2)
    for attempt in range(8):
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(OUT)
            print(data)
            return
        except PermissionError:
            time.sleep(0.08 * (attempt + 1))
    print("Kunne ikke skrive live-kort:", data)


def main():
    print(f"Screen reader started ({VERSION})")
    print(f"Base crop: {BASE_HERO_REGION}")
    print(f"Debug: {DEBUG_HERO}")
    print(f"Wide debug: {DEBUG_WIDE}")

    last_good = None
    last_good_at = 0.0
    pending_cards = None
    pending_count = 0

    while True:
        try:
            hero_cards, error = read_hero_cards_from_screen()
            now = time.time()
            if hero_cards:
                if hero_cards == last_good:
                    pending_cards = None
                    pending_count = 0
                    last_good_at = now
                    write_cards(hero_cards, "screen_fixed_crop")
                else:
                    if hero_cards == pending_cards:
                        pending_count += 1
                    else:
                        pending_cards = hero_cards
                        pending_count = 1

                    if pending_count >= 2:
                        last_good = hero_cards
                        last_good_at = now
                        pending_cards = None
                        pending_count = 0
                        write_cards(hero_cards, "screen_fixed_crop")
                    elif last_good and now - last_good_at <= 4.0:
                        write_cards(last_good, "screen_last_good", f"confirming_new_read={hero_cards!r}")
                    else:
                        write_cards("", "screen_error", f"confirming_new_read={hero_cards!r}")
            elif last_good and now - last_good_at <= 2.0 and "left=''" not in (error or ""):
                pending_cards = None
                pending_count = 0
                write_cards(last_good, "screen_last_good", error)
            else:
                pending_cards = None
                pending_count = 0
                write_cards("", "screen_error", error)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            write_cards("", "screen_error", str(exc))
        time.sleep(0.5)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--calibrate":
        raise SystemExit(calibrate_from_current_screen(" ".join(sys.argv[2:])))
    if len(sys.argv) >= 2 and sys.argv[1] in ("--capture-calibrate", "--snap-calibrate"):
        cards_text = " ".join(sys.argv[2:]) if len(sys.argv) >= 3 else None
        raise SystemExit(capture_then_calibrate(cards_text))
    if len(sys.argv) >= 3 and sys.argv[1] == "--calibrate-capture":
        raise SystemExit(calibrate_from_saved_capture(" ".join(sys.argv[2:])))
    if len(sys.argv) >= 3 and sys.argv[1] == "--calibrate-latest":
        raise SystemExit(calibrate_from_latest(" ".join(sys.argv[2:])))
    if len(sys.argv) >= 4 and sys.argv[1] == "--calibrate-file":
        raise SystemExit(calibrate_from_file(sys.argv[2], " ".join(sys.argv[3:])))
    if len(sys.argv) >= 2 and sys.argv[1] == "--list-captures":
        limit_text = sys.argv[2] if len(sys.argv) >= 3 else None
        raise SystemExit(list_captures(limit_text))
    if len(sys.argv) >= 2 and sys.argv[1] == "--review-captures":
        limit_text = sys.argv[2] if len(sys.argv) >= 3 else None
        raise SystemExit(review_captures(limit_text))
    if len(sys.argv) >= 4 and sys.argv[1] == "--calibrate-index":
        raise SystemExit(calibrate_from_index(sys.argv[2], " ".join(sys.argv[3:])))
    main()

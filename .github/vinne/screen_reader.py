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
DEBUG_WIDE = ROOT / "fronted" / "hero_cards_debug_wide.png"
CURRENT_GAME = ROOT / "backend" / "current_game.json"
TEMPLATE_DIR = ROOT / ".github" / "vinne" / "card_templates"
VERSION = "green_table_suit_fallback_v25"
SCREENSHOT_DELAY_SECONDS = float(os.getenv("SCREENSHOT_DELAY_SECONDS", "2.0"))

# Crop relative to the active BetSolid table window. Absolute screen crops broke
# whenever the browser/BetSolid windows moved or a replay window was opened.
BASE_HERO_REGION = (245, 330, 260, 190)
SEARCH_DX = (-10, 0, 10, 20, 30)
SEARCH_DY = (-5, 0, 5, 10)

# Card boxes inside HERO_REGION. They are intentionally a bit generous.
LEFT_CARD_RECT = (78, 24, 58, 82)
RIGHT_CARD_RECTS = [
    (126, 24, 58, 82),
    (130, 24, 58, 82),
    (122, 24, 62, 82),
]

RANKS = "23456789TJQKA"
SUITS = "HDCS"
TEMPLATE_SIZE = (28, 28)


def save_debug_image(path: Path, img):
    ok, encoded = cv2.imencode(".png", img)
    if ok:
        path.write_bytes(encoded.tobytes())


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
    rank_area = card_img[3 : min(19, h), 2 : min(23, w)]
    suit_area = card_img[14 : min(36, h), 2 : min(24, w)]
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
            boxes.append((x, y, w, h))
    if not boxes:
        return card_img

    x1 = max(0, min(x for x, _, _, _ in boxes) - 1)
    y1 = max(0, min(y for _, y, _, _ in boxes) - 1)
    x2 = min(card_img.shape[1], max(x + w for x, _, w, _ in boxes) + 1)
    y2 = min(card_img.shape[0], max(y + h for _, y, _, h in boxes) + 1)
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
    if templ_suit:
        suit = templ_suit
    else:
        suit_area = card_img[14 : min(34, h), 2 : min(22, w)]
        suit_hsv = cv2.cvtColor(suit_area, cv2.COLOR_BGR2HSV)
        suit_scores = {
            suit: int(np.count_nonzero(cv2.bitwise_and(color_mask(suit_hsv, suit), cv2.inRange(suit_hsv[:, :, 2], 20, 235))))
            for suit in ("H", "D", "C", "S")
        }
        suit = max(suit_scores, key=suit_scores.get)
        if suit == "S" and suit_scores["C"] >= suit_scores["S"] * 0.85:
            suit = "C"
        if suit_scores[suit] < 8:
            suit = ""

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
    if templ_rank:
        return templ_rank
    if rank_match_score >= 0.90:
        return ""

    f = rank_features(blob)
    if not f:
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
        if y < 35 or y > 95:
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
        return sum(card_rect_score(rect, crop) for rect in detected) + 10000

    return 0


def candidate_regions():
    x, y, w, h = BASE_HERO_REGION
    for dy in SEARCH_DY:
        for dx in SEARCH_DX:
            region = (x + dx, y + dy, w, h)
            # Do not scan high board/player-card areas. If we cannot find hero
            # cards in this lower band, return blank instead of wrong cards.
            if 300 <= region[1] <= 350:
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
    learned = learn_templates_from_known_hero(crop)
    cards, error = read_cards_from_crop(crop)
    if error:
        error = f"{error}; region={region}; score={score}; learned={learned}"
    return cards, error


def calibrate_from_current_screen(cards_text):
    expected = valid_card_text(cards_text)
    if len(expected) != 2:
        print('Bruk: python .github\\vinne\\screen_reader.py --calibrate "AS KH"')
        return 2

    crop, region, score = best_hero_crop()
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

    while True:
        try:
            hero_cards, error = read_hero_cards_from_screen()
            now = time.time()
            if hero_cards:
                last_good = hero_cards
                last_good_at = now
                write_cards(hero_cards, "screen_fixed_crop")
            elif last_good and now - last_good_at <= 2.0 and "left=''" not in (error or ""):
                write_cards(last_good, "screen_last_good", error)
            else:
                write_cards("", "screen_error", error)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            write_cards("", "screen_error", str(exc))
        time.sleep(0.5)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--calibrate":
        raise SystemExit(calibrate_from_current_screen(" ".join(sys.argv[2:])))
    main()

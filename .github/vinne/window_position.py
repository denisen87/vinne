import argparse
import ctypes
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = ROOT / "fronted" / "betsolid_window_position.json"

user32 = ctypes.windll.user32

SW_RESTORE = 9
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def window_text(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def window_rect(hwnd):
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Kunne ikke lese vindusposisjon.")
    return {
        "x": int(rect.left),
        "y": int(rect.top),
        "width": int(rect.right - rect.left),
        "height": int(rect.bottom - rect.top),
    }


def enum_windows():
    windows = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = window_text(hwnd)
            if title:
                windows.append((int(hwnd), title))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def find_windows(contains):
    needle = contains.lower()
    return [(hwnd, title) for hwnd, title in enum_windows() if needle in title.lower()]


def save_active():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        raise RuntimeError("Fant ikke aktivt vindu.")
    title = window_text(hwnd)
    rect = window_rect(hwnd)
    data = {"title": title, **rect}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Lagret: {STATE_FILE}")
    print(f"title={title}")
    print(f"x={rect['x']} y={rect['y']} width={rect['width']} height={rect['height']}")


def restore(contains):
    if not STATE_FILE.exists():
        raise RuntimeError(f"Fant ikke {STATE_FILE}. Kjor --save-active forst.")
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    matches = find_windows(contains)
    if not matches:
        raise RuntimeError(f"Fant ingen synlige vinduer som inneholder: {contains!r}")
    x, y, width, height = data["x"], data["y"], data["width"], data["height"]
    for hwnd, title in matches:
        user32.ShowWindow(hwnd, SW_RESTORE)
        ok = user32.SetWindowPos(hwnd, 0, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE)
        print(("Flyttet" if ok else "Kunne ikke flytte") + f": {title}")
    print(f"Til: x={x} y={y} width={width} height={height}")


def show_active():
    hwnd = user32.GetForegroundWindow()
    title = window_text(hwnd)
    rect = window_rect(hwnd)
    print(f"title={title}")
    print(f"x={rect['x']} y={rect['y']} width={rect['width']} height={rect['height']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-active", action="store_true", help="Lagre posisjonen til aktivt vindu.")
    parser.add_argument("--restore", action="store_true", help="Flytt BetSolid-vindu tilbake til lagret posisjon.")
    parser.add_argument("--show-active", action="store_true", help="Vis posisjon for aktivt vindu.")
    parser.add_argument("--contains", default="NL Hold'em", help="Tekst som maa finnes i vindustittel ved restore.")
    args = parser.parse_args()

    if args.save_active:
        save_active()
    elif args.restore:
        restore(args.contains)
    elif args.show_active:
        show_active()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

import requests
import json
import piexif
import os
import time
import keyboard

# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────

# Debug / logging toggles
DEBUG_ENABLED = False
WARN_ENABLED = False
INFO_ENABLED = False

# API credentials
API_KEY  = ""
USER_ID  = ""

# Base output directory
DEFAULT_PATH = "C:/gelbooru_image/"

# API request limits
LIMIT         = 20
REQUEST_DELAY = 1.5  # delay between requests

# Save options
SAVE_TAGS_TO_TXT = True

# Optional tag filter added to all requests
IMPROVEMENT_TAG = ""
# Examples:
#   sort:id:asc       → oldest first
#   sort:id:desc      → newest first
#   sort:score:desc   → highest rated first
#   sort:updated:desc → recently updated first

# File naming mode:
SORT_MODE = "original"  # original | prefix | number
SORT_PAD = 6  # 000001 format
# - original: keep original filename
# - prefix: add index prefix
# - number: zero-padded numbering

# Cache file (stores progress between runs)
CACHE_FILE = "cache.json"

# ─────────────────────────────────────────────
#  SESSION SETUP
# ─────────────────────────────────────────────

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://gelbooru.com/"
})

# Global runtime counters
total_saved = 0
global_index = 0

# ─────────────────────────────────────────────
#  HOTKEY CONTROL SYSTEM
# ─────────────────────────────────────────────

HOTKEYS_ENABLED = False
PAUSED = False
STOP = False

def toggle_pause():
    global PAUSED, HOTKEYS_ENABLED
    if not HOTKEYS_ENABLED:
        return
    PAUSED = not PAUSED
    print("[PAUSE]" if PAUSED else "[RESUME]")


def stop_program():
    global STOP, HOTKEYS_ENABLED
    if not HOTKEYS_ENABLED:
        return
    STOP = True
    print("[STOP]")

def handle_pause_and_stop():
    while PAUSED:
        time.sleep(0.2)
    return STOP
# ─────────────────────────────────────────────
#  CACHE SYSTEM
# ─────────────────────────────────────────────

DEFAULT_CACHE = {
    "download": {
        # keyed by tag string, e.g. "1girl hoodie red_hair"
        # "1girl hoodie": { "page": 3, "folder": "1girl hoodie" }
    },
    "fill": {
        # keyed by artist folder name
        # "some_artist": { "page": 0, "done": false }
    },
    "tag_types": {
        # keyed by tag name, value is gelbooru type string
        # "some_artist": "artist", "blue_eyes": "general"
    }
}


def load_cache() -> dict:
    """Load cache from disk or create default cache file."""
    if not os.path.exists(CACHE_FILE):
        save_cache(DEFAULT_CACHE)
        return json.loads(json.dumps(DEFAULT_CACHE))  # deep copy
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache: dict):
    """Write cache to disk."""
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────
#  LOG HELPERS
# ─────────────────────────────────────────────

def dprint(*args, **kwargs):
    """Debug print."""
    if DEBUG_ENABLED:
        print(*args, **kwargs)

def wprint(*args, **kwargs):
    """Warning print."""
    if WARN_ENABLED:
        print(*args, **kwargs)

def iprint(*args, **kwargs):
    """Info print."""
    if INFO_ENABLED:
        print(*args, **kwargs)

# ─────────────────────────────────────────────
#  USER INPUT HELPERS
# ─────────────────────────────────────────────

def ask_choice(prompt: str, options: list) -> str:
    """Show numbered options and loop until a valid number is entered."""
    while True:
        print(prompt)
        for i, option in enumerate(options, 1):
            print(f"  {i}. {option}")
        answer = input("Your choice: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return answer
        print(f"[!] Please enter a number between 1 and {len(options)}.")


def ask_yes_no(prompt: str) -> bool:
    """Ask a y/n question and loop until a valid answer is given."""
    while True:
        answer = input(prompt).strip().lower()
        if answer in ("y", "n"):
            return answer == "y"
        print("[!] Please enter 'y' or 'n'.")

# ─────────────────────────────────────────────
#  UTILITY FUNCTIONS
# ─────────────────────────────────────────────

def sanitize_name(name: str) -> str:
    """Remove illegal filesystem characters."""
    for ch in r':/<>"\|?*':
        name = name.replace(ch, "")
    return name.strip()

def format_filename(index: int, original_name: str, mode: str) -> str:
    """Generate filename depending on naming mode."""
    ext = original_name.split(".")[-1]

    if mode == "original":
        return original_name
    if mode == "prefix":
        return f"{index}_{original_name}"
    if mode == "number":
        return f"{str(index).zfill(SORT_PAD)}.{ext}"

    return original_name

# ─────────────────────────────────────────────
#  TAG TYPE CACHE
# ─────────────────────────────────────────────

def get_tag_types(post_tags: str, cache: dict) -> dict:
    """
    Resolve tag types using cache + batch API request.
    Reduces API calls significantly.
    """
    tag_list    = post_tags.split()
    known       = cache.setdefault("tag_types", {})
    unknown     = [t for t in tag_list if t not in known]

    if unknown:
        # Gelbooru tag type numbers → human-readable strings
        TYPE_MAP = {
            0: "general",
            1: "artist",
            3: "copyright",
            4: "character",
            5: "metadata",
            6: "deprecated",
        }

        batch = "%20".join(unknown)
        url   = (
            f"https://gelbooru.com/index.php?page=dapi&s=tag&q=index"
            f"&json=1&limit={len(unknown)}"
            f"&names={batch}"
            f"&api_key={API_KEY}&user_id={USER_ID}"
        )
        dprint(f"[DEBUG] Fetching {len(unknown)} unknown tag types...")
        try:
            response = session.get(url)
            data     = response.json()
            # API returns {"@attributes": {...}, "tag": [...]} or {"tag": {...}} for single
            raw = data.get("tag", [])
            if isinstance(raw, dict):
                raw = [raw]
            for tag in raw:
                name = tag.get("name", "")
                if name:
                    known[name] = TYPE_MAP.get(tag.get("type", 0), "general")
            save_cache(cache)
        except Exception as e:
            dprint(f"[DEBUG] Tag type fetch failed: {e}")

    return {t: known.get(t, "general") for t in tag_list}


def find_artist_in_post(post_tags: str, cache: dict) -> str | None:
    """Return first detected artist tag if exists."""
    tag_types = get_tag_types(post_tags, cache)

    for tag, ttype in tag_types.items():
        if ttype == "artist":
            return sanitize_name(tag)

    return None

# ─────────────────────────────────────────────
#  EXIF HANDLING
# ─────────────────────────────────────────────

def insert_tags(image_path: str, tags: str) -> bool:
    """
    Embed tags into EXIF metadata.
    PNG may fail → fallback to TXT file.
    """
    try:
        exif_tags  = tags.replace(" ", ";") + ";"
        zeroth_ifd = {40094: exif_tags.encode("utf-16")}

        exif_bytes = piexif.dump({"0th": zeroth_ifd})
        piexif.insert(exif_bytes, image_path)
        return True
    except piexif._exceptions.InvalidImageDataError:
        wprint("[WARN] EXIF tags skipped (PNG or unsupported format) — tags saved to .txt only.")
        return False

# ─────────────────────────────────────────────
#  API
# ─────────────────────────────────────────────

def build_api_url(page_id: int, tags: list) -> str | None:
    """Build Gelbooru API URL."""
    active_tags = [t for t in tags if t]

    if not active_tags:
        print("[ERR] No tags provided.")
        return None

    url = (
        f"https://gelbooru.com/index.php?"
        f"page=dapi&s=post&q=index"
        f"&json=1&limit={LIMIT}&pid={page_id}"
        f"&tags={'%20'.join(active_tags)}"
        f"&api_key={API_KEY}&user_id={USER_ID}"
    )
    return url


def fetch_posts(api_url: str) -> list | None:
    """Fetch posts from API with error handling."""
    time.sleep(REQUEST_DELAY)

    dprint("[DEBUG] API URL:", api_url)
    dprint("[DEBUG] Requesting posts from server...")

    response = session.get(api_url)

    if response.status_code != 200:
        print(f"[ERR] HTTP {response.status_code}")
        dprint("[DEBUG] Response body:", response.text[:200])
        return None

    try:
        data = response.json()
    except Exception:
        print("[ERR] Server returned non-JSON response.")
        dprint("[DEBUG] Raw response:", response.text[:500])
        return None

    posts = data.get("post", [])
    if isinstance(posts, dict):
        posts = [posts]

    return posts

# ─────────────────────────────────────────────
#  FILE DOWNLOAD
# ─────────────────────────────────────────────

def save_post(post: dict, dest_folder: str, index: int):
    """Download and store image + metadata."""
    global total_saved, global_index

    file_url  = post["file_url"]
    file_name = post["image"]
    tags      = post["tags"]

    file_name = format_filename(index, post["image"], SORT_MODE)

    dest_folder = os.path.join(dest_folder, SORT_MODE)
    os.makedirs(dest_folder, exist_ok=True)

    if file_name in os.listdir(dest_folder):
        print(f"[SKIP] Already downloaded: {file_name}")
        return

    dest_path = os.path.join(dest_folder, file_name)
    post_page = f"https://gelbooru.com/index.php?page=post&s=view&id={post['id']}"
    headers   = {"User-Agent": "Mozilla/5.0", "Referer": post_page}

    time.sleep(REQUEST_DELAY)
    dprint("[DEBUG] Downloading:", file_url)

    content = session.get(file_url, headers=headers, timeout=10).content
    with open(dest_path, "wb") as f:
        f.write(content)

    insert_tags(dest_path, tags)

    if SAVE_TAGS_TO_TXT:
        txt_path = dest_path.rsplit(".", 1)[0] + ".txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(tags)

    print(f"[OK] Saved: {file_name} → {dest_folder}")
    total_saved += 1


# ─────────────────────────────────────────────
#  MENU MODES
# ─────────────────────────────────────────────

def mode_download_by_tag():
    global global_index

    """Mode 1 — download posts by tag with user-chosen folder strategy."""
    cache = load_cache()

    # Ask for tags
    tags_input = input("[?] Enter tags to search (space-separated): ").strip()
    if not tags_input:
        print("[ERR] No tags entered.")
        return

    search_tags = tags_input.split()
    if IMPROVEMENT_TAG:
        search_tags.append(IMPROVEMENT_TAG)

    # Ask where to save
    choice = ask_choice(
        "\n[?] Where to save downloaded images?",
        [
            f'Folder named after tags  →  "{tags_input}"',
            "Sort by artist (auto-detect per image)",
            "Custom folder name",
        ]
    )

    if choice == "1":
        folder_name = sanitize_name(tags_input)
        dest_mode   = "tag"
    elif choice == "2":
        folder_name = None   # determined per post
        dest_mode   = "artist"
    else:
        folder_name = input("[?] Enter folder name: ").strip()
        if not folder_name:
            print("[ERR] Folder name cannot be empty.")
            return
        folder_name = sanitize_name(folder_name)
        dest_mode   = "custom"

    # Resume progress if same tag set was used before
    cache_key    = tags_input
    entry        = cache["download"].get(cache_key, {"page": 0})
    page         = entry["page"]

    if page > 0:
        iprint(f"[INFO] Resuming from page {page} for tags: {tags_input}")
    try:
        global global_index, HOTKEYS_ENABLED
        HOTKEYS_ENABLED = True

        while True:
            print(f"\n{'─'*44}")
            print(f" Page: {page} | Saved: {total_saved}")
            print(f"{'─'*44}")

            url   = build_api_url(page, search_tags)
            posts = fetch_posts(url)

            if posts is None:
                print("[ERR] Request failed. Stopping.")
                break

            if not posts:
                print("\n>>> Done — no more posts found.")
                cache["download"].pop(cache_key, None)  # clear finished entry
                save_cache(cache)
                break

            for idx, post in enumerate(posts):
                if handle_pause_and_stop():
                    return
            
                iprint(f"[INFO] Page: {page} | Post {idx + 1}/{len(posts)} | Saved: {total_saved}")
                dprint(f"[DEBUG] File: {post['image']}")

                if dest_mode == "artist":
                    artist = find_artist_in_post(post["tags"], cache)
                    folder = os.path.join(DEFAULT_PATH, artist if artist else "_unknown")
                else:
                    folder = os.path.join(DEFAULT_PATH, folder_name)

                save_post(post, folder, global_index)
                global_index += 1

            page += 1
            cache["download"][cache_key] = {"page": page}
            save_cache(cache)
    finally:
        HOTKEYS_ENABLED = False


def mode_fill_existing():
    global global_index

    """Mode 2 — update all artist folders already present in DEFAULT_PATH."""
    cache   = load_cache()
    artists = [
        a for a in os.listdir(DEFAULT_PATH)
        if os.path.isdir(os.path.join(DEFAULT_PATH, a)) and a != "_unknown"
    ]

    if not artists:
        print("[ERR] No artist folders found in", DEFAULT_PATH)
        return

    if ask_yes_no("[?] Reset all progress and start from scratch? (y/n): "):
        cache["fill"] = {}
        save_cache(cache)
        print("[OK] Progress reset.")

    total_artists = len(artists)

    for artist in artists:
        entry = cache["fill"].get(artist, {"page": 0, "done": False})

        if entry["done"]:
            print(f"[SKIP] {artist} — already up to date.")
            continue

        page       = entry["page"]
        done_count = sum(1 for e in cache["fill"].values() if e.get("done"))
        tags       = [artist] + ([IMPROVEMENT_TAG] if IMPROVEMENT_TAG else [])

        iprint(f"\n[INFO] Artist: {artist} | From page: {page} | Progress: {done_count}/{total_artists}")

        try:
            global global_index, HOTKEYS_ENABLED
            HOTKEYS_ENABLED = True

            while True:
                print(f"\n{'─'*44}")
                print(f" Page: {page} | Saved: {total_saved}")
                print(f"{'─'*44}")

                url   = build_api_url(page, tags)
                posts = fetch_posts(url)

                if posts is None:
                    wprint(f"[WARN] Request failed for {artist}. Skipping.")
                    break

                if not posts:
                    break

                for idx, post in enumerate(posts):
                    if handle_pause_and_stop():
                        return
                 
                    iprint(f"[INFO] Page: {page} | Post {idx + 1}/{len(posts)} | Saved: {total_saved}")
                    dprint(f"[DEBUG] File: {post['image']}")
            
                    folder = os.path.join(DEFAULT_PATH, artist)
                    save_post(post, folder, global_index)
                    global_index += 1

                page += 1
                cache["fill"][artist] = {"page": page, "done": False}
                save_cache(cache)
        finally:
            HOTKEYS_ENABLED = False

        cache["fill"][artist] = {"page": 0, "done": True}
        save_cache(cache)
        print(f"[OK] {artist} — done.")

    print("\n>>> Fill complete.")


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

class StopProgram(Exception):
    """Custom exception used for controlled shutdown (if needed in future)."""
    pass

def main():
    """Program entry point with hotkeys."""
    keyboard.add_hotkey('p', toggle_pause)
    keyboard.add_hotkey('q', stop_program)

    # Reset runtime control flags
    global PAUSED, STOP, HOTKEYS_ENABLED
    HOTKEYS_ENABLED = False
    PAUSED = False
    STOP = False

    # Main menu UI
    menu = """
╔══════════════════════════════════════╗
║       GelBooru Parser  v0.8          ║
╠══════════════════════════════════════╣
║  1. Download by tag                  ║
║  2. Fill existing artist folders     ║
╠══════════════════════════════════════╣
║  Controls:                           ║
║  p → pause/resume   ║    q → stop    ║
╚══════════════════════════════════════╝
Your choice: """

    # Main loopq
    while True:
        choice = input(menu).strip()

        if choice == "1":
            mode_download_by_tag()
        elif choice == "2":
            mode_fill_existing()
        else:
            print("[!] Please choose 1 or 2.")

if __name__ == "__main__":
    try:
        main()
    except StopProgram:
        print("[INFO] Program interrupted, returning to menu.")
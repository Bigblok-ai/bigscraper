import requests
from bs4 import BeautifulSoup
import json
import hashlib
import re
import time
import os
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# ─────────────────────────────────────────────────────────────────────────────
# TIMEZONE & IS_LIVE
# ─────────────────────────────────────────────────────────────────────────────

VN_TZ       = timezone(timedelta(hours=7))
LIVE_BEFORE = timedelta(minutes=10)  # hiện LIVE trước giờ đấu 10 phút


def now_vn() -> datetime:
    return datetime.now(tz=VN_TZ)


def parse_kickoff(time_str: str):
    """Parse chuỗi giờ site → datetime aware (VN tz). Trả None nếu không parse được."""
    if not time_str or not time_str.strip():
        return None
    s     = time_str.strip()
    today = now_vn()
    year  = today.year

    patterns = [
        # "22:00 25/04/2025"
        (r"(\d{1,2}):(\d{2})\s+(\d{1,2})/(\d{1,2})/(\d{4})",
         lambda m: datetime(int(m[4]), int(m[3]), int(m[2]), int(m[0]), int(m[1]), tzinfo=VN_TZ)),
        # "22:00 25/04"
        (r"(\d{1,2}):(\d{2})\s+(\d{1,2})/(\d{1,2})$",
         lambda m: datetime(year, int(m[3]), int(m[2]), int(m[0]), int(m[1]), tzinfo=VN_TZ)),
        # "22:00"
        (r"^(\d{1,2}):(\d{2})$",
         lambda m: datetime(today.year, today.month, today.day, int(m[0]), int(m[1]), tzinfo=VN_TZ)),
    ]
    for pattern, builder in patterns:
        match = re.search(pattern, s)
        if match:
            try:
                return builder(match.groups())
            except ValueError:
                pass
    return None


def calc_is_live(html_flag: bool, time_str: str) -> bool:
    """True nếu HTML flag live, HOẶC còn trong 10p trước KO trở đi."""
    if html_flag:
        return True
    kickoff = parse_kickoff(time_str)
    if kickoff is None:
        return False
    now = now_vn()
    return now >= (kickoff - LIVE_BEFORE)


def has_live_stream(streams: list) -> bool:
    """Kiểm tra còn stream cdn-hls.phogatv8.com thực sự đang live không."""
    return any("cdn-hls.phogatv8.com" in s for s in streams)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://thapcam24h.net/"
}

BASE_URL      = "https://thapcam24h.net"
THUMBS_DIR    = "thumbs"
REPO_RAW      = os.environ.get("REPO_RAW", "")
THUMB_VERSION = "v2"

CATE_MAP = {
    "Bóng đá":     "⚽ Bóng Đá",
    "Tennis":      "🎾 Tennis",
    "Cầu Lông":    "🏸 Cầu Lông",
    "Bóng rổ":     "🏀 Bóng Rổ",
    "Billiards":   "🎱 Billiards",
    "Bóng chuyền": "🏐 Bóng Chuyền",
    "Đua xe F1":   "🏎️ Đua Xe F1",
    "Bóng bàn":    "🏓 Bóng Bàn",
    "Võ Thuật":    "🥊 Võ Thuật",
    "Pickleball":  "🏸 Pickleball",
}

CATE_ORDER = [
    "Bóng đá", "Bóng rổ", "Cầu Lông", "Tennis",
    "Billiards", "Bóng chuyền", "Võ Thuật", "Đua xe F1", "Bóng bàn", "Pickleball"
]

CATE_URLS = {
    "Bóng đá":     "/truc-tiep-bong-da-xoilac-tv",
    "Cầu Lông":    "/truc-tiep-cau-long",
    "Bóng rổ":     "/truc-tiep-bong-ro",
    "Tennis":      "/truc-tiep-tennis",
    "Billiards":   "/truc-tiep-bida",
    "Đua xe F1":   "/truc-tiep-dua-xe-f1",
    "Bóng chuyền": "/truc-tiep-bong-chuyen",
    "Bóng bàn":    "/truc-tiep-bong-ban",
    "Võ Thuật":    "/truc-tiep-vo-thuat",
    "Pickleball":  "/truc-tiep-pickleball",
}

EXCLUDE_LEAGUES = [
    "liga mx", "liga de expansion",
    "argentine", "argentina", "liga profesional", "copa de la liga",
    "colombian", "colombia", "liga betplay", "categoria primera", "primera a",
    "chile", "primera division chile",
    "ecuador", "liga pro ecuador",
    "peru", "liga 1 peru",
    "venezuela", "liga futve",
    "paraguay", "uruguay", "bolivia",
]


def is_excluded_league(league_name: str) -> bool:
    lower = league_name.lower()
    return any(kw in lower for kw in EXCLUDE_LEAGUES)


def make_id(text, prefix):
    h = hashlib.md5(text.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"


def fetch_image(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except:
        return None


def parse_time_sort(match_time: str) -> int:
    kickoff = parse_kickoff(match_time)
    if kickoff:
        return kickoff.month * 10_000_000 + kickoff.day * 10_000 + kickoff.hour * 100 + kickoff.minute
    return 999_999_999


def is_within_range(match_time: str, cate_name: str = "Bóng đá") -> bool:
    """
    Bóng đá: chỉ hiển thị trận trong 24h tới và tối đa 6h đã qua.
    Môn khác: không giới hạn theo thời gian.
    """
    if cate_name != "Bóng đá":
        return True
    kickoff = parse_kickoff(match_time)
    if kickoff is None:
        return True
    now   = now_vn()
    lower = now - timedelta(hours=6)
    upper = now + timedelta(hours=24)
    return lower <= kickoff <= upper


# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, channel_id):
    os.makedirs(THUMBS_DIR, exist_ok=True)
    cache_key = match.get("logo_a", "") + match.get("logo_b", "") + THUMB_VERSION
    logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
    out_path  = f"{THUMBS_DIR}/{channel_id}_{logo_hash}.png"

    if os.path.exists(out_path):
        return out_path

    W, H = 1600, 1200
    HEADER_H = 180
    FOOTER_H = 160

    bg   = Image.new("RGB", (W, H), (245, 245, 248))
    draw = ImageDraw.Draw(bg)

    # Gradient-like background: vẽ dải xám nhạt từ trên xuống
    for y in range(HEADER_H, H - FOOTER_H):
        ratio = (y - HEADER_H) / (H - FOOTER_H - HEADER_H)
        gray  = int(248 - ratio * 18)
        draw.line([(0, y), (W, y)], fill=(gray, gray, gray + 4))

    # Header & Footer
    draw.rectangle([(0, 0),            (W, HEADER_H)],   fill=(13, 20, 40))
    draw.rectangle([(0, H - FOOTER_H), (W, H)],          fill=(13, 20, 40))

    # Đường viền accent đỏ dưới header và trên footer
    ACCENT = (220, 30, 40)
    draw.rectangle([(0, HEADER_H),        (W, HEADER_H + 5)],   fill=ACCENT)
    draw.rectangle([(0, H - FOOTER_H - 5),(W, H - FOOTER_H)],   fill=ACCENT)

    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_vs     = ImageFont.truetype(FONT_BOLD, 160)
        font_time   = ImageFont.truetype(FONT_BOLD, 100)
        font_team   = ImageFont.truetype(FONT_BOLD, 58)
        font_league = ImageFont.truetype(FONT_BOLD, 62)
        font_blv    = ImageFont.truetype(FONT_BOLD, 58)
    except:
        font_vs = font_time = font_team = font_league = font_blv = ImageFont.load_default()

    content_top = HEADER_H + 5
    content_bot = H - FOOTER_H - 5
    content_h   = content_bot - content_top

    # Vùng logo + VS chiếm 55% chiều cao content, căn giữa dọc
    logo_size  = 380
    block_h    = logo_size + 70 + 60   # logo + gap + tên đội
    block_top  = content_top + (content_h - block_h) // 2 - 30
    logo_y     = block_top
    name_y     = logo_y + logo_size + 55

    # Thời gian đấu nằm dưới tên đội, căn giữa
    time_y = name_y + 80

    # Logo trái
    if match.get("logo_a"):
        img = fetch_image(match["logo_a"])
        if img:
            img = img.resize((logo_size, logo_size), Image.LANCZOS)
            x   = W // 4 - logo_size // 2
            bg.paste(img, (x, logo_y), img)

    # Logo phải
    if match.get("logo_b"):
        img = fetch_image(match["logo_b"])
        if img:
            img = img.resize((logo_size, logo_size), Image.LANCZOS)
            x   = W * 3 // 4 - logo_size // 2
            bg.paste(img, (x, logo_y), img)

    # VS — màu đỏ, nổi bật
    draw.text(
        (W // 2, logo_y + logo_size // 2),
        "VS",
        fill=ACCENT,
        font=font_vs,
        anchor="mm",
    )

    # Tên đội — hỗ trợ 2 dòng nếu quá dài
    def draw_team_name(text, cx):
        max_chars = 16
        if len(text) <= max_chars:
            draw.text((cx, name_y), text, fill=(20, 20, 20), font=font_team, anchor="mm")
        else:
            # Cắt tại khoảng trắng gần nhất
            mid  = len(text) // 2
            split = text.rfind(" ", 0, mid + 6)
            if split == -1:
                split = max_chars
            line1 = text[:split].strip()
            line2 = text[split:].strip()
            draw.text((cx, name_y - 30), line1, fill=(20, 20, 20), font=font_team, anchor="mm")
            draw.text((cx, name_y + 35), line2, fill=(20, 20, 20), font=font_team, anchor="mm")

    if match.get("team_a"):
        draw_team_name(match["team_a"], W // 4)
    if match.get("team_b"):
        draw_team_name(match["team_b"], W * 3 // 4)

    # Giờ đấu — badge nổi bật
    if match.get("time"):
        tw  = 320
        th  = 72
        tx  = W // 2 - tw // 2
        ty  = time_y
        draw.rounded_rectangle([(tx, ty), (tx + tw, ty + th)], radius=16, fill=(13, 20, 40))
        draw.text((W // 2, ty + th // 2), match["time"], fill=(255, 220, 50), font=font_time, anchor="mm")

    # Tên giải — header
    if match.get("league"):
        league_text = match["league"].upper()
        draw.text((W // 2, HEADER_H // 2), league_text,
                  fill=(255, 255, 255), font=font_league, anchor="mm")

    # BLV — footer
    if match.get("blv"):
        draw.text((W // 2, H - FOOTER_H // 2), f"BLV: {match['blv']}",
                  fill=(255, 255, 255), font=font_blv, anchor="mm")

    # Viền ngoài
    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(180, 180, 180), width=3)

    bg.save(out_path, "PNG", optimize=True)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPE MATCHES
# ─────────────────────────────────────────────────────────────────────────────

def normalize_time(t: str) -> str:
    return t.replace(" - ", " ").strip()


def get_matches():
    all_matches = []
    seen        = set()

    for cate_name, cate_path in CATE_URLS.items():
        print(f"  Scraping {cate_name}...")
        try:
            res  = requests.get(f"{BASE_URL}{cate_path}", headers=HEADERS, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception as e:
            print(f"    Loi fetch {cate_path}: {e}")
            continue

        for card in soup.select("div.grid-matches__item"):
            a_tag = card.select_one("a.grid-match__body")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            url      = BASE_URL + href if href.startswith("/") else href
            match_id = re.search(r'/(\d+)(?:\?|$)', href)
            if not match_id:
                continue
            match_id = match_id.group(1)

            card_class = " ".join(card.get("class", []))

            # ── Teams / Logos ──────────────────────────────────────────────
            logo_a = logo_b = team_a = team_b = ""

            home_div = card.select_one("div.grid-match__team-home")
            away_div = card.select_one("div.grid-match__team-away")
            if home_div:
                img = home_div.select_one("img.team__logo")
                if img:
                    logo_a = img.get("src", "")
                    team_a = img.get("alt", "")
            if away_div:
                img = away_div.select_one("img.team__logo")
                if img:
                    logo_b = img.get("src", "")
                    team_b = img.get("alt", "")

            # Trận đơn (F1, võ thuật, billiards...)
            if not team_a and not team_b:
                single = card.select_one("div.grid-match__team--name")
                if single:
                    team_a = single.get_text(strip=True)
                    logo_tag = card.select_one("div.gname-first__item img.team__logo")
                    if logo_tag:
                        logo_a = logo_tag.get("src", "")

            # ── League ────────────────────────────────────────────────────
            league_tag = card.select_one("div.grid-match__league")
            league     = ""
            if league_tag:
                # Lấy text, bỏ qua img alt
                league = league_tag.get_text(strip=True)

            # Bỏ giải châu Mỹ (chỉ bóng đá)
            if cate_name == "Bóng đá" and is_excluded_league(league):
                continue

            # ── Giờ ───────────────────────────────────────────────────────
            # Ưu tiên grid-match__date (chỉ giờ), fallback grid-match__datef (giờ + ngày)
            time_tag = card.select_one("div.grid-match__date")
            if time_tag:
                match_time = normalize_time(time_tag.get_text(strip=True))
            else:
                datef = card.select_one("div.grid-match__datef")
                match_time = normalize_time(datef.get_text(strip=True)) if datef else ""

            # Lọc 24h (chỉ bóng đá)
            if not is_within_range(match_time, cate_name):
                continue

            # ── is_live ───────────────────────────────────────────────────
            html_live = "stream_m_live" in card_class or bool(card.select_one("span.badge-live"))
            is_live   = calc_is_live(html_live, match_time)

            # ── BLV ───────────────────────────────────────────────────────
            blv_list = []
            for blv_span in card.select("span.MuiTypography-root.css-96jbn8"):
                blv_name = blv_span.get_text(strip=True)
                if blv_name and "quốc tế" not in blv_name.lower():
                    blv_list.append(blv_name)

            # Ẩn trận không có BLV có tên thật
            if not any(b.strip() for b in blv_list):
                continue

            blv_names = ", ".join(blv_list)

            if team_a and team_b:
                name = f"{team_a} vs {team_b}"
            elif team_a:
                name = team_a
            else:
                name = href.split("/")[2].replace("-", " ").title()[:60]

            all_matches.append({
                "url":       url,
                "match_id":  match_id,
                "name":      name,
                "time":      match_time,
                "time_sort": parse_time_sort(match_time),
                "team_a":    team_a,
                "team_b":    team_b,
                "logo_a":    logo_a,
                "logo_b":    logo_b,
                "league":    league,
                "blv":       blv_names,
                "blv_list":  blv_list,
                "is_live":   is_live,
                "cate_name": cate_name,
            })

        time.sleep(0.5)

    all_matches.sort(key=lambda m: (0 if m["is_live"] else 1, m["time_sort"]))
    return all_matches


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPE STREAMS
# ─────────────────────────────────────────────────────────────────────────────

def label_stream(url: str, blv_name: str = "", hd_count: dict = None) -> str | None:
    """
    - cdn-hls.phogatv8.com → tên BLV hoặc "Link HD N"
    - live.alilicloud.com  → "Link Nhà Đài"
    - domain khác          → ẩn (None)
    """
    if "cdn-hls.phogatv8.com" in url:
        if blv_name:
            return blv_name
        if hd_count is not None:
            hd_count["n"] = hd_count.get("n", 0) + 1
            return "Link HD" if hd_count["n"] == 1 else f"Link HD {hd_count['n']}"
        return "Link HD"
    if "live.alilicloud.com" in url:
        return "Link Nhà Đài"
    return None


def get_streams(match_url: str, blv_list: list = None) -> list:
    """
    Lấy stream từ trang trận đấu qua data-fileurl.
    Bỏ link có tên chứa 'quốc tế' hoặc 'quoc te'.
    """
    streams = []
    try:
        res  = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        for item in soup.select("[data-fileurl]"):
            # Tên BLV từ span.watch_userName__41lYM
            name_tag = item.select_one("span.watch_userName__41lYM")
            name     = name_tag.get_text(strip=True) if name_tag else ""

            if "quốc tế" in name.lower() or "quoc te" in name.lower():
                continue

            file_url = item.get("data-fileurl", "")
            if file_url and ".m3u8" in file_url:
                clean = file_url.replace("\\u0026", "&")
                if clean not in streams:
                    streams.append(clean)
                    print(f"    Stream [{name}]: {clean[:60]}...")

    except Exception as e:
        print(f"    Loi fetch stream: {e}")

    return streams


# ─────────────────────────────────────────────────────────────────────────────
# BUILD CHANNEL
# ─────────────────────────────────────────────────────────────────────────────

def build_channel(match, streams, thumb_url=""):
    uid    = make_id(match["url"], "thapcam")
    src_id = make_id(match["url"], "src")
    ct_id  = make_id(match["url"], "ct")
    st_id  = make_id(match["url"], "st")

    blv_names  = match.get("blv_list", [])
    hd_count   = {"n": 0}
    blv_cursor = 0

    stream_links = []
    for i, s_url in enumerate(streams):
        blv_name = ""
        if blv_cursor < len(blv_names):
            blv_name = blv_names[blv_cursor] if isinstance(blv_names[blv_cursor], str) else blv_names[blv_cursor].get("name", "")
            blv_cursor += 1

        name = label_stream(s_url, blv_name, hd_count)
        if name is None:
            continue
        lnk_id = make_id(s_url + str(i), "lnk")
        stream_links.append({
            "id":      lnk_id,
            "name":    name,
            "type":    "hls",
            "default": len(stream_links) == 0,
            "url":     s_url,
            "request_headers": [
                {"key": "Referer",    "value": "https://thapcam24h.net/"},
                {"key": "User-Agent", "value": "Mozilla/5.0"},
            ],
        })

    label_text  = "● LIVE" if match["is_live"] else "🕐 Sắp"
    label_color = "#ff4444" if match["is_live"] else "#aaaaaa"
    display_name = f"{match['name']} | {match['time']}" if match["time"] else match["name"]

    channel = {
        "id":            uid,
        "name":          display_name,
        "type":          "single",
        "display":       "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": label_text, "position": "top-left",
                    "color": "#00000080", "text_color": label_color}],
        "sources": [{
            "id":   src_id,
            "name": "ThapcamTV",
            "contents": [{
                "id":   ct_id,
                "name": match["name"],
                "streams": [{"id": st_id, "name": "KT", "stream_links": stream_links}],
            }],
        }],
        "org_metadata": {
            "league":    match.get("league",    ""),
            "team_a":    match.get("team_a",    ""),
            "team_b":    match.get("team_b",    ""),
            "logo_a":    match.get("logo_a",    ""),
            "logo_b":    match.get("logo_b",    ""),
            "time":      match.get("time",      ""),
            "blv":       match.get("blv",       ""),
            "is_live":   match["is_live"],
            "cate_name": match.get("cate_name", ""),
        },
    }

    if thumb_url:
        channel["image"] = {
            "padding":          1,
            "background_color": "#ffffff",
            "display":          "contain",
            "url":              thumb_url,
            "width":            1600,
            "height":           1200,
        }

    return channel


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(THUMBS_DIR, exist_ok=True)
    print(f"Gio VN hien tai: {now_vn().strftime('%H:%M %d/%m/%Y')}")
    print("Lay danh sach tran tu thapcam24h...")
    matches = get_matches()

    live_count = sum(1 for m in matches if m["is_live"])
    print(f"Tong: {len(matches)} | LIVE: {live_count} | Sap: {len(matches)-live_count}\n")

    # Cố định tất cả môn dù không có trận
    cate_channels = {c: [] for c in CATE_ORDER}

    for i, match in enumerate(matches):
        cate   = match["cate_name"]
        status = "LIVE" if match["is_live"] else "SAP"
        print(f"[{status} {i+1}/{len(matches)}] {match['name']} ({match['time']}) | BLV: {match['blv']}")

        streams = []
        if match["is_live"]:
            streams = get_streams(match["url"], match["blv_list"])

            # Nếu không còn cdn-hls.phogatv8.com stream → trận đã kết thúc, bỏ qua
            if not has_live_stream(streams):
                print(f"  Khong con stream cdn-hls.phogatv8.com → bo qua")
                continue

            # Bóng đá + Bóng rổ: đảo link[0] ↔ link[1]
            if cate in ("Bóng đá", "Bóng rổ") and len(streams) >= 2:
                streams = [streams[1], streams[0]] + streams[2:]
                print(f"  [{cate}] swapped link 1<->2")

            print(f"  stream: {len(streams)} link")

        uid        = make_id(match["url"], "thapcam")
        cache_key  = match.get("logo_a", "") + match.get("logo_b", "") + THUMB_VERSION
        logo_hash  = hashlib.md5(cache_key.encode()).hexdigest()[:8]
        thumb_path = make_thumbnail(match, uid)
        thumb_url  = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else ""

        channel = build_channel(match, streams, thumb_url)

        if cate not in cate_channels:
            cate_channels[cate] = []
        cate_channels[cate].append(channel)

        time.sleep(0.2)

    # Build groups — cố định theo CATE_ORDER, hiển thị số LIVE
    groups = []
    for cate in CATE_ORDER:
        channels     = cate_channels.get(cate, [])
        cate_display = CATE_MAP.get(cate, f"🏅 {cate}")
        live_n       = sum(1 for ch in channels
                          if ch.get("org_metadata", {}).get("is_live", False))
        name         = f"{cate_display} ({live_n} LIVE)" if live_n > 0 else cate_display
        groups.append({
            "id":            make_id(cate, "grp"),
            "name":          name,
            "display":       "vertical",
            "grid_number":   2,
            "enable_detail": False,
            "channels":      channels,
        })

    output = {
        "id":          "thapcam",
        "url":         "https://thapcam24h.net",
        "name":        "ThapcamTV",
        "color":       "#e63946",
        "grid_number": 3,
        "image":       {"type": "cover", "url": "https://thapcam24h.net/img/thapcam24h.png"},
        "groups":      groups,
    }

    # Ghi staging trước, so sánh rồi mới swap — tránh ghi thừa
    staging = "output_staging.json"
    with open(staging, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    def normalize(path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            s = json.dumps(d, sort_keys=True, ensure_ascii=False)
            return re.sub(r"\?expire=\d+", "", s)
        except Exception:
            return ""

    old_norm = normalize("output.json")
    new_norm = normalize(staging)

    total = sum(len(g["channels"]) for g in groups)
    if old_norm != new_norm:
        os.replace(staging, "output.json")
        print(f"\nXong! {total} kenh, {len(groups)} mon -> output.json (DA CAP NHAT)")
    else:
        os.remove(staging)
        print(f"\nXong! {total} kenh, {len(groups)} mon -> Khong co thay doi, giu nguyen output.json")


if __name__ == "__main__":
    main()

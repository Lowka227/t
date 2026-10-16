#!/usr/bin/env python3
"""Скачивает публичные страницы Telegram-канала в папку tg-data/,
откуда их читает tg.html (одинаково для всех пользователей)."""
import glob
import html as htmllib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CH = "kirillsmotrit"
OUT = "tg-data"
DAYS = 365
MAX_PAGES = 15
BOT = os.environ.get("TG_BOT_TOKEN", "").strip()
UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ru,en;q=0.8",
}


def get(url, binary=False, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def write(name, data):
    path = os.path.join(OUT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w", **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as f:
        f.write(data)


def strip_tags(s):
    return htmllib.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "before-*.html")):
        os.remove(f)

    # ---- посты (страница + пагинация за год) ----
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    all_html = []
    url = f"https://t.me/s/{CH}"
    before = 0
    pages = 0
    for _ in range(MAX_PAGES):
        page = get(url)
        if "tgme_widget_message" not in page:
            if pages == 0:
                raise SystemExit("страница канала без постов — выходим, старые данные остаются")
            break
        name = f"before-{before}.html" if before else "page.html"
        write(name, page)
        all_html.append(page)
        pages += 1
        ids = [int(x) for x in re.findall(r'data-post="[^"/]+/(\d+)"', page)]
        if not ids:
            break
        min_id = min(ids)
        times = re.findall(r'<time[^>]*datetime="([^"]+)"', page)
        oldest = parse_dt(times[0]) if times else None
        if min_id <= 1 or min_id == before or (oldest and oldest < cutoff):
            break
        before = min_id
        url = f"https://t.me/s/{CH}?before={before}"
        time.sleep(1)
    write("meta.json", json.dumps({"pages": pages, "updated": datetime.now(timezone.utc).isoformat()}))

    # ---- название, подписчики, аватарка ----
    info = {"name": "", "subs": "", "avatar": ""}
    try:
        ch = get(f"https://t.me/{CH}")
        write("channel.html", ch)
        m = re.search(r'class="tgme_page_title"[^>]*>(.*?)</div>', ch, re.S)
        if m:
            info["name"] = strip_tags(m.group(1))
        if not info["name"]:
            m = re.search(r'<meta property="og:title" content="([^"]*)"', ch)
            if m:
                info["name"] = htmllib.unescape(m.group(1))
        m = re.search(r'class="tgme_page_extra"[^>]*>([^<]*)<', ch)
        if m:
            n = re.match(r"\s*([\d\s\u00a0.,]*\d[KkMm]?)", htmllib.unescape(m.group(1)))
            if n:
                info["subs"] = n.group(1).strip()
        m = re.search(r'<img class="tgme_page_photo_image"[^>]*src="([^"]+)"', ch)
        av = htmllib.unescape(m.group(1)) if m else f"https://t.me/i/userpic/320/{CH}.jpg"
        try:
            write("avatar.jpg", get(av, binary=True))
            info["avatar"] = "avatar.jpg"
        except Exception as e:
            print("аватарка не скачалась:", e)
    except Exception as e:
        print("страница канала не загрузилась:", e)
    if info["name"] or info["subs"]:
        write("info.json", json.dumps(info, ensure_ascii=False))

    # ---- премиум-эмодзи (нужен секрет TG_BOT_TOKEN, иначе пропускается) ----
    if BOT:
        emoji_path = os.path.join(OUT, "emoji.json")
        try:
            known = json.load(open(emoji_path, encoding="utf-8"))
        except Exception:
            known = {}
        ids = set()
        for h in all_html:
            ids.update(re.findall(r'emoji-id="(\d+)"', h))
        need = [i for i in ids if i not in known]

        def api(method, **q):
            u = f"https://api.telegram.org/bot{BOT}/{method}?" + urllib.parse.urlencode(q)
            return json.loads(get(u))

        for k in range(0, len(need), 100):
            chunk = need[k:k + 100]
            try:
                j = api("getCustomEmojiStickers", custom_emoji_ids=json.dumps(chunk))
                for st in j.get("result", []):
                    fid = (st.get("thumbnail") or {}).get("file_id") if st.get("is_animated") else st.get("file_id")
                    if not fid:
                        continue
                    g = api("getFile", file_id=fid)
                    fp = g["result"]["file_path"]
                    ext = os.path.splitext(fp)[1] or ".webp"
                    rel = f"emoji/{st['custom_emoji_id']}{ext}"
                    write(rel, get(f"https://api.telegram.org/file/bot{BOT}/{fp}", binary=True))
                    known[st["custom_emoji_id"]] = {"f": rel, "v": bool(st.get("is_video")) and not st.get("is_animated")}
            except Exception as e:
                print("эмодзи:", type(e).__name__)
        write("emoji.json", json.dumps(known))
    print(f"готово: страниц {pages}")


if __name__ == "__main__":
    main()

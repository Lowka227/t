#!/usr/bin/env python3
"""Скачивает публичный канал Telegram в папку tg-data/, чтобы виджет tg.html
брал всё с того же сайта GitHub Pages (без прокси и без прямого доступа к t.me):
  page.html, before-N.html, channel.html  - страницы с постами и данными канала
  info.json + avatar.jpg                  - название, подписчики, аватарка
  emoji.json + emoji/*                    - премиум-эмодзи (нужен секрет BOT_TOKEN)
  meta.json                               - сколько страниц сохранено
"""
import html as htmllib
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

USER = 'kirillsmotrit'      # канал без @
PAGES = 7                   # сколько страниц хранить (~20 постов на страницу)
DAYS_BACK = 365             # как в виджете
OUT = pathlib.Path(__file__).resolve().parent.parent / 'tg-data'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36')


def get_bytes(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ru'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last


def get(url, tries=3):
    return get_bytes(url, tries).decode('utf-8', 'replace')


def clean(html):
    return re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S | re.I)


def save(name, html):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(html, encoding='utf-8')


def first_date(html):
    m = re.search(r'<time[^>]*datetime="([^"]+)"', html)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1).replace('Z', '+00:00'))
    except ValueError:
        return None


# ---------- название, подписчики, аватарка ----------
def parse_info(channel_html, page_html):
    info = {}
    for h in (channel_html, page_html):
        if not h:
            continue
        if not info.get('name'):
            m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', h)
            if m:
                info['name'] = htmllib.unescape(m.group(1)).strip()
        if not info.get('subs'):
            m = re.search(r'class="tgme_page_extra">\s*(.*?)\s*</div>', h, re.S)
            if m:
                t = htmllib.unescape(re.sub(r'<[^>]+>', ' ', m.group(1))).replace('\u00a0', ' ')
                mm = re.search(r'(\d[\d\s.,]*[KkMm]?)\s*(?:subscribers|members|подписчик|участник)', t, re.I)
                if mm:
                    info['subs'] = mm.group(1).strip()
        if not info.get('subs'):
            for v, t in re.findall(r'counter_value">([^<]+)</span>\s*<span class="counter_type">([^<]+)</span>', h):
                if re.search(r'subscri|подпис', t, re.I):
                    info['subs'] = htmllib.unescape(v).strip()
                    break
    return info


def avatar_urls(channel_html, page_html):
    urls = []
    for h in (channel_html, page_html):
        if not h:
            continue
        m = re.search(r'<img[^>]+class="tgme_page_photo_image"[^>]+src="([^"]+)"', h) \
            or re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', h)
        if m:
            urls.append(htmllib.unescape(m.group(1)))
    urls.append('https://t.me/i/userpic/320/%s.jpg' % USER)
    return urls


def save_info(channel_html, page_html):
    info = parse_info(channel_html, page_html)
    for u in avatar_urls(channel_html, page_html):
        try:
            data = get_bytes(u)
            if len(data) > 500:
                (OUT / 'avatar.jpg').write_bytes(data)
                info['avatar'] = 'avatar.jpg'
                break
        except Exception as e:  # noqa: BLE001
            print('avatar failed:', type(e).__name__)
    if info:
        save('info.json', json.dumps(info, ensure_ascii=False))
    print('info:', {k: v for k, v in info.items()})


# ---------- премиум-эмодзи ----------
def bot_api(token, method, query=''):
    return json.loads(get('https://api.telegram.org/bot%s/%s%s' % (token, method, query), tries=2))


def save_emoji(pages_html):
    token = os.environ.get('BOT_TOKEN', '').strip()
    ids = sorted(set(re.findall(r'emoji-id="(\d+)"', ' '.join(pages_html))))
    if not ids:
        print('премиум-эмодзи в постах не найдены')
        return
    if not token:
        print('BOT_TOKEN не задан, премиум-эмодзи пропускаю')
        return
    ef = OUT / 'emoji.json'
    emap = json.loads(ef.read_text(encoding='utf-8')) if ef.exists() else {}
    need = [i for i in ids if i not in emap or not (OUT / emap[i]['f']).exists()]
    (OUT / 'emoji').mkdir(parents=True, exist_ok=True)
    for k in range(0, len(need), 100):
        chunk = need[k:k + 100]
        try:
            j = bot_api(token, 'getCustomEmojiStickers',
                        '?custom_emoji_ids=' + urllib.parse.quote(json.dumps(chunk)))
            if not j.get('ok'):
                print('getCustomEmojiStickers:', j.get('description'))
                continue
            for st in j['result']:
                # .tgs (Lottie) не проигрываем: для них берём статичное превью
                fid = (st.get('thumbnail') or {}).get('file_id') if st.get('is_animated') else st.get('file_id')
                if not fid:
                    continue
                g = bot_api(token, 'getFile', '?file_id=' + urllib.parse.quote(fid))
                if not g.get('ok'):
                    continue
                path = g['result']['file_path']
                ext = path.rsplit('.', 1)[-1] if '.' in path else 'bin'
                name = 'emoji/%s.%s' % (st['custom_emoji_id'], ext)
                (OUT / name).write_bytes(get_bytes('https://api.telegram.org/file/bot%s/%s' % (token, path)))
                emap[st['custom_emoji_id']] = {'f': name, 'v': bool(st.get('is_video')) and not st.get('is_animated')}
        except Exception as e:  # noqa: BLE001
            print('emoji failed:', type(e).__name__)
    ef.write_text(json.dumps(emap), encoding='utf-8')
    print('премиум-эмодзи: всего %d, новых %d' % (len(emap), len(need)))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    channel_html = ''
    try:
        channel_html = get('https://t.me/%s' % USER)
        save('channel.html', clean(channel_html))
    except Exception as e:  # noqa: BLE001
        print('channel page failed:', type(e).__name__)

    html = get('https://t.me/s/%s' % USER)
    if 'tgme_widget_message' not in html:
        sys.exit('в ответе Telegram нет постов, старые файлы не трогаю')
    first_page = html
    save('page.html', clean(html))
    pages_html = [html]
    pages = 1
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    before = 0

    # цепочка страниц повторяет логику виджета: ?before=<минимальный id страницы>
    while pages < PAGES:
        ids = [int(x) for x in re.findall(r'data-post="%s/(\d+)"' % re.escape(USER), html)]
        if not ids:
            break
        mn = min(ids)
        if mn <= 1 or mn == before:
            break
        d = first_date(html)
        if d and d < cutoff:
            break
        before = mn
        time.sleep(1)
        html = get('https://t.me/s/%s?before=%d' % (USER, before))
        if 'tgme_widget_message' not in html:
            break
        save('before-%d.html' % before, clean(html))
        pages_html.append(html)
        pages += 1

    save('meta.json', json.dumps({
        'pages': pages,
        'updated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }))
    save_info(channel_html, first_page)
    save_emoji(pages_html)
    print('готово, страниц:', pages)


if __name__ == '__main__':
    main()

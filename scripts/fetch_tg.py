#!/usr/bin/env python3
"""Скачивает страницы публичного канала Telegram в папку tg-data/.
Их потом читает виджет tg.html (с того же сайта GitHub Pages), поэтому ему
не нужны ни CORS-прокси, ни прямой доступ пользователя к t.me."""
import json
import pathlib
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

USER = 'kirillsmotrit'      # канал без @
PAGES = 7                   # сколько страниц хранить (~20 постов на страницу)
DAYS_BACK = 365             # как в виджете
OUT = pathlib.Path(__file__).resolve().parent.parent / 'tg-data'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36')


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ru'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last


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


def main():
    # страница канала: название, подписчики, аватарка (не критична)
    try:
        save('channel.html', clean(get('https://t.me/%s' % USER)))
    except Exception as e:  # noqa: BLE001
        print('channel page failed:', e)

    html = get('https://t.me/s/%s' % USER)
    if 'tgme_widget_message' not in html:
        sys.exit('в ответе Telegram нет постов, старые файлы не трогаю')
    save('page.html', clean(html))
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
        pages += 1

    save('meta.json', json.dumps({
        'pages': pages,
        'updated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }))
    print('готово, страниц:', pages)


if __name__ == '__main__':
    main()

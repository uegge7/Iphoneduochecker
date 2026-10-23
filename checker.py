#!/usr/bin/env python3
"""iPhone-Duo-Abholungs-Checker.

Prüft minütlich, ob das iPhone Duo (256 GB / 512 GB, jede Farbe) in Apple Stores
in Süddeutschland, Zürich und Österreich zur Abholung verfügbar ist.
Nur Python-Standardbibliothek, keine Installation nötig.

Benachrichtigungen (optional, per Umgebungsvariable):
  EMAIL_TO            -> Empfänger-Adresse der E-Mail-Benachrichtigung
  SMTP_USER           -> Absender-Konto (z. B. Gmail-Adresse)
  SMTP_PASSWORD          (bei Gmail: App-Passwort), SMTP_HOST/SMTP_PORT optional
  NTFY_TOPIC          -> Push aufs Handy via https://ntfy.sh/<topic>
  TELEGRAM_BOT_TOKEN  -> Telegram-Bot (zusammen mit TELEGRAM_CHAT_ID)
  TELEGRAM_CHAT_ID
"""

import argparse
import json
import os
import random
import re
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from email.message import EmailMessage

BASE = "https://www.apple.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
# Apple antwortet bei Teilenummern-Batches > ~10 teils mit Fehlern
MAX_PARTS_PER_REQUEST = 8


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def http_get(url, accept="application/json"):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "de-DE,de;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Teilenummern ermitteln
# --------------------------------------------------------------------------

def extract_parts_from_html(html, capacities):
    """Sucht im Kauf-Seiten-HTML nach Produkt-Objekten mit partNumber + Kapazität.

    Gibt {partNumber: beschreibung} zurück, gefiltert auf die gewünschten Kapazitäten.
    """
    wanted = {c.lower() for c in capacities}
    parts = {}
    for m in re.finditer(r'\{[^{}]*"partNumber"\s*:\s*"[A-Z0-9]+/A"[^{}]*\}', html):
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            continue
        cap = str(obj.get("dimensionCapacity", "")).lower()
        if cap not in wanted:
            continue
        color = obj.get("dimensionColor", "?")
        parts[obj["partNumber"]] = f"{cap.upper()} {color}"
    return parts


def discover_parts(storefront, slug, capacities):
    url = f"{BASE}/{storefront}/shop/buy-iphone/{slug}"
    html = http_get(url, accept="text/html")
    return extract_parts_from_html(html, capacities)


# --------------------------------------------------------------------------
# Abhol-Verfügbarkeit
# --------------------------------------------------------------------------

def pickup_url(storefront, parts, location):
    # /shop/fulfillment-messages liefert Servern inzwischen HTTP 541, dieser Endpunkt funktioniert
    params = {"pl": "true", "location": location}
    for i, p in enumerate(parts):
        params[f"parts.{i}"] = p
    return f"{BASE}/{storefront}/shop/retail/pickup-message?" + urllib.parse.urlencode(params)


def parse_distance_km(store):
    raw = store.get("storedistance")
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(store.get("storeDistanceWithUnit") or raw or "")
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    return float(m.group(0).replace(",", ".")) if m else None


def store_matches(store, store_filter):
    if not store_filter:
        return True
    text = f"{store.get('storeName', '')} {store.get('city', '')}".lower()
    return any(f.lower() in text for f in store_filter)


def parse_pickup(data, max_distance_km=None, store_filter=None):
    """Liefert Liste von (store, city, part, available, quote) aus der API-Antwort."""
    body = data.get("body", {})
    stores = body.get("stores") or body.get("content", {}).get("pickupMessage", {}).get("stores", [])
    result = []
    for s in stores:
        dist = parse_distance_km(s)
        if max_distance_km is not None and dist is not None and dist > max_distance_km:
            continue
        if not store_matches(s, store_filter):
            continue
        for part, info in (s.get("partsAvailability") or {}).items():
            available = info.get("pickupDisplay") == "available"
            quote = info.get("pickupSearchQuote") or info.get("pickupDisplay", "")
            result.append((s.get("storeName", "?"), s.get("city", ""), part, available, quote))
    return result


def check_region(region, part_labels):
    parts = list(part_labels)
    rows = {}
    for loc in region["locations"]:
        for i in range(0, len(parts), MAX_PARTS_PER_REQUEST):
            batch = parts[i:i + MAX_PARTS_PER_REQUEST]
            data = json.loads(http_get(pickup_url(region["storefront"], batch, loc)))
            for row in parse_pickup(data, region.get("max_distance_km"), region.get("store_filter")):
                rows[(row[0], row[2])] = row  # gleiche Stores über mehrere PLZ deduplizieren
    return list(rows.values())


# --------------------------------------------------------------------------
# Shopify-Händler (z. B. epos Vorarlberg): Filialbestand über die Storefront-API
# --------------------------------------------------------------------------

SHOPIFY_API_VERSION = "2025-01"
SHOPIFY_QUERY_FIELDS = """title variants(first: 1) { nodes { sku storeAvailability(first: 20) {
  nodes { available pickUpTime quantityAvailable location { name address { city } } } } } }"""
_shopify_tokens = {}


def shopify_handle(region, part):
    template = region.get("handle_template", "iphone-duo-{part}")
    return template.format(part=part.lower().replace("/", "-"))


def shopify_token(base_url, handle, refresh=False):
    """Öffentlicher Storefront-Token, den der Shop selbst in jede Produktseite einbettet."""
    if refresh or base_url not in _shopify_tokens:
        html = http_get(f"{base_url}/products/{handle}", accept="text/html")
        m = re.search(r'data-storefront-api-access-token="([0-9a-f]+)"', html)
        if not m:
            raise RuntimeError("Storefront-Token nicht auf der Produktseite gefunden")
        _shopify_tokens[base_url] = m.group(1)
    return _shopify_tokens[base_url]


def shopify_query(parts, region):
    aliases = {f"p{i}": part for i, part in enumerate(parts)}
    body = " ".join(
        f'{a}: product(handle: "{shopify_handle(region, part)}") {{ {SHOPIFY_QUERY_FIELDS} }}'
        for a, part in aliases.items()
    )
    return "{ " + body + " }", aliases


def parse_shopify(data, aliases, store_filter=None):
    """Treffer nur bei echtem Filialbestand (quantityAvailable > 0).

    available=true allein heißt bei epos nur "bestellbar, Abholung in 2-4 Tagen".
    """
    result = []
    for alias, product in (data.get("data") or {}).items():
        if not product:
            continue
        for variant in product["variants"]["nodes"]:
            for sa in variant["storeAvailability"]["nodes"]:
                loc = sa["location"]
                store = {"storeName": loc["name"], "city": (loc.get("address") or {}).get("city", "")}
                if not store_matches(store, store_filter):
                    continue
                qty = sa.get("quantityAvailable") or 0
                in_stock = bool(sa.get("available")) and qty > 0
                quote = f"{qty} Stück vor Ort" if in_stock else "kein Filialbestand"
                result.append((store["storeName"], store["city"], aliases[alias], in_stock, quote))
    return result


def check_shopify(region, part_labels):
    base = region["base_url"].rstrip("/")
    query, aliases = shopify_query(list(part_labels), region)
    first_handle = shopify_handle(region, next(iter(part_labels)))
    for attempt in (1, 2):
        req = urllib.request.Request(
            f"{base}/api/{SHOPIFY_API_VERSION}/graphql.json",
            data=json.dumps({"query": query}).encode(),
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
                "X-Shopify-Storefront-Access-Token": shopify_token(base, first_handle, refresh=attempt > 1),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and attempt == 1:
                continue  # Token evtl. erneuert -> neu von der Seite lesen
            raise
    missing = [aliases[a] for a, p in (data.get("data") or {}).items() if not p]
    if missing:
        log(f"{region['name']}: Produkte nicht gefunden: {', '.join(missing)}")
    return parse_shopify(data, aliases, region.get("store_filter"))


def product_link(cfg, region, part):
    if region.get("type") == "shopify":
        return f"{region['base_url'].rstrip('/')}/products/{shopify_handle(region, part)}"
    return f"{BASE}/{region['storefront']}/shop/buy-iphone/{cfg['product_slug']}"


# --------------------------------------------------------------------------
# Benachrichtigung
# --------------------------------------------------------------------------

def send_email(title, message):
    to = os.environ.get("EMAIL_TO")
    user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    if not (to and user and password):
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = title, user, to
    msg.set_content(message)
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as e:  # noqa: BLE001
        log(f"E-Mail fehlgeschlagen: {e}")


def ntfy_headers(title, url=None):
    headers = {"Title": title.encode("utf-8"), "Priority": "high", "Tags": "iphone"}
    if url:
        headers["Click"] = url                          # Tippen auf die Push öffnet die Seite
        headers["Actions"] = f"view, Zur Seite, {url}"  # zusätzlicher Button in der Push
    return headers


def notify(title, message, url=None):
    log(f"*** {title}: {message}")
    print("\a", end="", flush=True)  # Terminal-Piepton
    send_email(title, message)
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{topic}",
                data=message.encode("utf-8"),
                headers=ntfy_headers(title, url),
            )
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:  # noqa: BLE001
            log(f"ntfy fehlgeschlagen: {e}")
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            body = urllib.parse.urlencode({"chat_id": chat, "text": f"{title}\n{message}"}).encode()
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=10
            ).read()
        except Exception as e:  # noqa: BLE001
            log(f"Telegram fehlgeschlagen: {e}")


# --------------------------------------------------------------------------
# Hauptschleife
# --------------------------------------------------------------------------

def resolve_parts(cfg, region, part_map=None):
    if region.get("parts_from"):
        # Händler mit denselben Apple-Teilenummern wie eine Apple-Region (z. B. epos = AT-Nummern)
        parts = (part_map or {}).get(region["parts_from"])
        if not parts:
            raise RuntimeError(f"Region '{region['parts_from']}' liefert keine Teilenummern")
        return dict(parts)
    if region.get("parts"):
        return {p: p for p in region["parts"]}
    parts = discover_parts(region["storefront"], cfg["product_slug"], cfg["capacities"])
    if not parts:
        raise RuntimeError(
            f"Keine Teilenummern für {region['name']} gefunden. "
            f"Bitte in config.json unter 'parts' manuell eintragen."
        )
    return parts


def load_state(path):
    if not path or not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {tuple(k) for k in json.load(f)}


def save_state(path, keys):
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(keys), f, ensure_ascii=False)


def run(cfg, loops=0, state_path=None, interval=None):
    """loops=0 läuft endlos; state_path merkt sich gemeldete Treffer über Neustarts hinweg."""
    part_map = {}
    # Apple-Regionen zuerst, damit Händler mit "parts_from" deren Teilenummern übernehmen können
    for region in sorted(cfg["regions"], key=lambda r: bool(r.get("parts_from"))):
        try:
            part_map[region["name"]] = resolve_parts(cfg, region, part_map)
            log(f"{region['name']}: {len(part_map[region['name']])} Varianten -> "
                + ", ".join(f"{p} ({l})" for p, l in part_map[region['name']].items()))
        except Exception as e:  # noqa: BLE001
            log(f"FEHLER {region['name']}: {e}")

    interval = interval or cfg.get("interval_seconds", 60)
    previously_available = load_state(state_path)
    round_no = 0
    while True:
        round_no += 1
        now_available = set()
        for region in cfg["regions"]:
            labels = part_map.get(region["name"])
            if not labels:
                continue
            try:
                if region.get("type") == "shopify":
                    rows = check_shopify(region, labels)
                else:
                    rows = check_region(region, labels)
            except Exception as e:  # noqa: BLE001
                log(f"{region['name']}: Abfrage fehlgeschlagen ({e})")
                continue
            hits = [r for r in rows if r[3]]
            quotes = sorted({r[4] for r in rows if not r[3]})
            log(f"{region['name']}: {len(hits)} von {len(rows)} Store/Varianten abholbereit"
                + (f" (sonst: {' / '.join(quotes)})" if quotes else ""))
            for store, city, part, _, quote in hits:
                key = (region["name"], store, part)
                now_available.add(key)
                if key not in previously_available:
                    link = product_link(cfg, region, part)
                    notify(
                        "iPhone Duo abholbereit!",
                        f"{labels.get(part, part)} in {store} ({city}) – {quote}\n{link}",
                        url=link,
                    )
        previously_available = now_available
        save_state(state_path, now_available)
        if loops and round_no >= loops:
            return
        time.sleep(interval + random.uniform(0, 10))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.json"))
    ap.add_argument("--once", action="store_true", help="nur einmal prüfen und beenden")
    ap.add_argument("--loops", type=int, default=0, help="Anzahl Prüfungen, dann beenden (0 = endlos)")
    ap.add_argument("--interval", type=int, help="Sekunden zwischen den Prüfungen (Standard aus config.json)")
    ap.add_argument("--state", help="Datei, die bereits gemeldete Treffer speichert")
    ap.add_argument("--test-notify", action="store_true", help="Test-Benachrichtigung senden")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    if args.test_notify:
        notify("iPhone Duo Checker", "Test-Benachrichtigung funktioniert ✅ – Tippen öffnet die epos-Seite",
               url="https://eposcomputer.com/products/iphone-duo-mk2g4zd-a")
        return
    try:
        run(cfg, loops=1 if args.once else args.loops, state_path=args.state, interval=args.interval)
    except KeyboardInterrupt:
        log("Beendet.")
        sys.exit(0)


if __name__ == "__main__":
    main()

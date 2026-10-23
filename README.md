# iPhone Duo – Abhol-Checker

Prüft jede Minute, ob das **iPhone Duo** mit **256 GB oder 512 GB** (Sternenweiß oder Nachthimmel)
in einem dieser Apple Stores **zur Abholung** verfügbar ist, und schickt dann eine Push-Nachricht über [ntfy](https://ntfy.sh):

| Region | Stores |
|---|---|
| Süddeutschland | München Rosenstraße, München OEZ, Augsburg City-Galerie, Sindelfingen |
| Zürich | Rennweg, Glattzentrum |
| Österreich | Wien Kärntner Straße |
| epos Vorarlberg (Apple Premium Partner) | Bürs Zimbapark, Götzis Garnmarkt, Dornbirn Messepark |

Das Tool läuft komplett auf **GitHub Actions**. Es muss kein PC laufen.

## Einrichtung (einmalig)

1. App **ntfy** aufs Handy, eigenes Topic abonnieren (schwer erratbarer Name).
2. Hier im Repo: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `NTFY_TOPIC`
   - Secret: dein Topic-Name
3. **Actions → iPhone Duo Abhol-Check → Run workflow** zum ersten Test.

## So funktioniert es

- Der Workflow läuft ab dem 23.10. und prüft in jedem Lauf bis zu ~5,5 Stunden lang ca. jede Minute. GitHub startet Zeitpläne bei Last nur alle paar Stunden; der nächste Lauf wartet in der Warteschlange und übernimmt direkt.
- Die Teilenummern pro Land liest das Tool selbst von `apple.com/<land>/shop/buy-iphone/iphone-duo` aus.
- Für die Abholung fragt es `apple.com/<land>/shop/retail/pickup-message?pl=true&parts.N=…&location=<PLZ>` ab.
- Für epos fragt es die Shopify-Storefront-API des Shops nach dem Filialbestand. Den öffentlichen Zugangsschlüssel liest es dabei von der Produktseite. Gemeldet wird nur **echter Bestand** (Stückzahl > 0), nicht „bestellbar, Abholung in 2–4 Tagen“.
- Pro Store und Variante kommt nur eine Push. Gemeldete Treffer merkt es sich in `state.json` im Actions-Cache.

GitHub startet zeitgesteuerte Workflows bei hoher Last teils mit einigen Minuten Verspätung.

## Anpassen

Stores, PLZ und Speichergrößen stehen in `config.json` (`store_filter`, `locations`, `capacities`).

## Stoppen

**Actions → iPhone Duo Abhol-Check → ··· → Disable workflow**

## Hinweise

- Das Tool nutzt inoffizielle Apple-Endpunkte. Die können sich jederzeit ändern. Nur für den privaten Gebrauch gedacht.
- Lokal starten (optional): `python3 checker.py` (Python 3.8+, keine Pakete).

# iPhone Duo – Abhol-Checker

Prüft jede Minute, ob das **iPhone Duo** mit **256 GB oder 512 GB** (Sternenweiß oder Nachthimmel)
in einem dieser Apple Stores **zur Abholung** verfügbar ist, und schickt dann eine Push-Nachricht über [ntfy](https://ntfy.sh):

| Region | Stores |
|---|---|
| Süddeutschland | München Rosenstraße, München OEZ, Augsburg City-Galerie, Sindelfingen |
| Zürich | Rennweg, Glattzentrum |
| Österreich | Wien Kärntner Straße |

Das Tool läuft komplett auf **GitHub Actions**. Es muss kein PC laufen.

## Einrichtung (einmalig)

1. App **ntfy** aufs Handy, eigenes Topic abonnieren (schwer erratbarer Name).
2. Hier im Repo: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `NTFY_TOPIC`
   - Secret: dein Topic-Name
3. **Actions → iPhone Duo Abhol-Check → Run workflow** zum ersten Test.

## So funktioniert es

- Der Workflow startet ab dem 23.10. alle 5 Minuten und prüft darin 5x im Abstand von ca. 1 Minute.
- Die Teilenummern pro Land liest das Tool selbst von `apple.com/<land>/shop/buy-iphone/iphone-duo` aus.
- Für die Abholung fragt es `apple.com/<land>/shop/retail/pickup-message?pl=true&parts.N=…&location=<PLZ>` ab.
- Pro Store und Variante kommt nur eine Push. Gemeldete Treffer merkt es sich in `state.json` im Actions-Cache.

GitHub startet zeitgesteuerte Workflows bei hoher Last teils mit einigen Minuten Verspätung.

## Anpassen

Stores, PLZ und Speichergrößen stehen in `config.json` (`store_filter`, `locations`, `capacities`).

## Stoppen

**Actions → iPhone Duo Abhol-Check → ··· → Disable workflow**

## Hinweise

- Das Tool nutzt inoffizielle Apple-Endpunkte. Die können sich jederzeit ändern. Nur für den privaten Gebrauch gedacht.
- Lokal starten (optional): `python3 checker.py` (Python 3.8+, keine Pakete).

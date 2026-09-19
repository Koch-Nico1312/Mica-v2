# Phase 2: Lernsystem und Recherche

## Betriebsmodell

Phase 2 erweitert den lokalen Markdown-Brain. Markdown bleibt die maßgebliche
Quelle; der SQLite-Index kann jederzeit neu aufgebaut werden. Es gibt keinen
Vektorserver und keine Cloud-Wissensdatenbank.

Die Startdomänen sind `it-programmierung` und `server-homelab`. Ihre
Konfiguration liegt standardmäßig unter `/data/learning/domains.json`. Jede
Domäne besitzt eine eigene Host-Allowlist. Änderungen laufen über
`PATCH /v1/learning/domains/{domain_id}` und die lokale parametergebundene
Freigabe.

## Sichere Aktivierung

Manuelle Recherche ist standardmäßig deaktiviert:

```env
MICA_LEARNING_NETWORK=0
MICA_LEARNING_MONITORING_ENABLED=0
```

Vor `MICA_LEARNING_NETWORK=1` müssen die Hosts in `domains.json` geprüft
werden. Monitoring bleibt bis zur erfolgreichen Alltagsabnahme der manuellen
Recherche aus. Es wird separat mit `MICA_LEARNING_MONITORING_ENABLED=1`
aktiviert.

Webabrufe erlauben nur HTTPS ohne Zugangsdaten, Port 443, öffentliche
IP-Adressen und Hosts aus der Domänen-Allowlist. Redirects werden erneut
geprüft. JavaScript wird nicht ausgeführt, Binärdateien werden abgelehnt und
Quellen sind auf eine begrenzte Textmenge beschränkt. Webseiteninhalt wird im
LLM-Prompt ausdrücklich als untrusted Daten gekennzeichnet.

## Verwendung

Die PWA enthält den Bereich **Lernen**. Alternativ funktioniert derselbe
Befehl per Text oder Sprache:

```text
Informier dich über <Thema> im Lernfeld <IT/Programmierung|Server/Homelab>.
```

Ohne eindeutiges Lernfeld startet kein Netzwerkzugriff. Ergebnisse enthalten
Kernaussagen, Quellen, Widersprüche, Unsicherheiten und offene Fragen. Es wird
nur eine Zusammenfassung mit Quellenmetadaten gespeichert, niemals eine
vollständige Webseite.

Monitoring erzeugt ausschließlich lokale `research-draft`-Dokumente. Ein
bestätigter Entwurf führt eine vollständige Recherche aus und verknüpft das
Ergebnis; bestehendes Wissen wird nicht still überschrieben.


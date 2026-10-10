# Aufmerksamkeit und interne Zustände

MICA nutzt neben dem bestehenden Sprachmodell eine kleine CPU-Zusatzschicht.
Sie lädt kein zweites Modell und beansprucht selbst keinen GPU-Speicher. Die
Zustände beschreiben Antwortverhalten und belegen kein subjektives Bewusstsein.

## Vier Funktionen

- **Gedächtnis:** Das vorhandene Markdown-Brain bleibt der dauerhafte Speicher.
  Die Einstellung „ohne Speicherung“ verhindert neue Gesprächsdokumente.
  Der kurzlebige Gesprächsverlauf liefert Bezüge für Rückfragen.
- **Aufmerksamkeit:** Gefundene Erinnerungen werden nach Begriffen der aktuellen
  Frage geordnet und begrenzt. Explizit ausgewählte Dokumente behalten ihre
  bestehende Quellenverarbeitung.
- **Selbstbeobachtung:** Die Schicht erfasst Modellfehler, ungültige Quellenangaben
  und Antwortlänge. Die nächsten Antworten erhalten daraus konkrete Hinweise.
  Es werden keine versteckten Gedankengänge oder zusätzlichen Abschriften gespeichert.
- **Interne Zustände:** Themenkontinuität, Vorsicht nach Korrekturen und zugewandtes
  Antwortverhalten beeinflussen den Systemkontext. Die Zustände fallen bei
  Inaktivität Richtung Ausgangswert zurück. Schlüsselworterkennung ist eine
  einfache Heuristik und kann Ironie, Negationen und komplexe Gefühle fehlinterpretieren.

## Hardware und Laufzeit

Die Zusatzschicht läuft ausschließlich auf der CPU und kann deshalb neben einem
lokalen Modell auf einer RTX 4060 (8 GB) oder GTX 970 (4 GB) eingesetzt werden.
Das Gesamtbudget hängt weiterhin vom Sprachmodell, Kontextfenster, GPU-Backend
und gleichzeitig geladenen Sprachdiensten ab. Die Zusatzschicht erweitert
das Kontextfenster des Modells nicht und garantiert keine Modellladefähigkeit.

| Profil | Erinnerungen | Titel und Ausschnitte zusammen | Steuerkontext |
|---|---:|---:|---:|
| `low_vram` | höchstens 3 | 1800 Zeichen | 900 Zeichen |
| `balanced` | höchstens 5 | 3200 Zeichen | 1200 Zeichen |

Diese Grenzen gelten für die Zusatzschicht, nicht für ausgewählte Dokumente oder
den gesamten Modellkontext. Profile verändern keine Modellinstallation und
keine laufenden GPU-Dienste. Auf älteren GPUs bleibt CPU-Inferenz oder teilweise
Auslagerung eine Option, falls das eingesetzte Backend die GPU nicht unterstützt.

## Bedienung und API

Die authentifizierten Endpunkte beziehen sich auf dieselbe 32-stellige
Gesprächskennung wie Text und Sprache:

- `GET /v1/dialog/{session_id}/cognition`: Zustand und Beobachtungen lesen.
- `PATCH /v1/dialog/{session_id}/cognition`: beispielsweise
  `{"enabled": true, "profile": "low_vram"}`.
- `DELETE /v1/dialog/{session_id}/cognition`: Zustände zurücksetzen, Profil behalten.

Die Zustände und Profilwahl leben nur innerhalb eines Gesprächs. Ein neues
Gespräch, Neustart oder 30 Minuten Inaktivität entfernt sie. Dauerhafte
Erinnerungen bleiben in der bestehenden Gedächtnisübersicht bearbeitbar.
Cloud-Antworten erhalten diese Zusatzschicht nicht. Zustände und Modellantworten
können weder Aktionen freigeben noch Freigaben oder Not-Aus umgehen.

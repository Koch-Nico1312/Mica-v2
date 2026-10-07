# Sprache einrichten

Die native MICA-Oberfläche bietet unter **Einstellungen → Audio-Geräte →
Sprache einrichten** Mikrofontest, Satzende-Pause, Namenwörterbuch,
Unterbrechen durch Sprechen und die aktuelle Sprachdiagnose.
Die gespeicherte Antwortlänge Kurz/Normal/Ausführlich und die gemeinsame
Dateiauswahl sind in [Gespräche und Dokumente](dialog-improvements.md) beschrieben.

## Mikrofon testen

Das gespeicherte Eingabegerät wird für zwei Sekunden Hintergrundmessung und
sechs Sekunden Testsatz verwendet. Der Test prüft Pegel, Übersteuerung,
Hintergrundgeräusche und die Übereinstimmung des erkannten Testsatzes. Bei einem
ausreichenden Ergebnis lässt sich die empfohlene Erkennungsschwelle übernehmen.
Unzureichende Messungen bieten Hinweise und keinen Übernehmen-Knopf.

Während der Kalibrierung pausieren Sprachsitzung und Wake-Word. Abbrechen,
Schließen oder Stummschalten beendet die Aufnahme. Der Testsatz wird über den
authentifizierten Endpunkt `POST /v1/voice/calibrate` ausschließlich vom lokalen
STT-Dienst erkannt: kein Turn, keine Aktion, kein Gedächtniseintrag und keine
Sprachausgabe. PCM liegt nur im Arbeitsspeicher; der Endpunkt akzeptiert maximal
zehn Sekunden 16-kHz-Mono-PCM mit 16 Bit. Nach Gerätewechsel wird die alte
Kalibrierung nicht ungeprüft für das neue Mikrofon verwendet.

## Pause und Namen

Die Satzende-Pause beträgt standardmäßig **0,8 Sekunden** und ist zwischen
0,4 und 3 Sekunden einstellbar. Sie gilt für automatisch abgeschlossene
Aufnahmen, einschließlich Wake-Word und der Aufnahme nach einer Unterbrechung.
Push-to-talk wird weiterhin durch Loslassen abgeschlossen. Einzelne kurze
Pegelspitzen gelten nicht als Sprache. Automatische Aufnahmen sind auf
standardmäßig 30 Sekunden begrenzt.

Das lokale Wörterbuch enthält bis zu 32 explizite Schreibweisen, beispielsweise
`Koko → Coucou`. Ersetzungen erfolgen an Wortgrenzen, ohne Verkettung. Nur die
Anrede am Satzanfang, etwa „Hallo Maika“, wird automatisch zu „Hallo Mica“.
„Ruf Maika an“ bleibt ohne eigenen Wörterbucheintrag erhalten. Die Korrektur
erfolgt nach der Transkription, nicht durch Training des STT-Modells.

Einstellungen werden atomar in `.mica-data/voice-settings.json` gespeichert.
Eine beschädigte Datei fällt auf sichere Standardwerte mit ausgeschaltetem
Unterbrechen durch Sprechen zurück. Änderungen gelten für die nächste Aufnahme.

## Durch Sprechen unterbrechen

Die Option ist standardmäßig aktiv. Während der Antwort öffnet MICA einen
gemeinsamen Aufnahme-/Wiedergabestrom auf den ausgewählten Geräten. Die bekannte
Sprachausgabe wird mit verzögerten Referenzen aus dem Mikrofonsignal entfernt;
mindestens 240 ms anhaltende verbleibende Sprache löst eine Unterbrechung aus.
Ein kurzer Vorlauf und die Wörter während des erneuten Verbindungsaufbaus
werden für die nächste Aufnahme im Speicher gehalten. Bei Pufferüberlauf wird
die Aufnahme verworfen und zum erneuten Sprechen aufgefordert.

Esc, Stummschalten und Wiederherstellung verwerfen eine vorgemerkte Folgeaufnahme.
Geräte ohne gemeinsamen Audiostrom verwenden die bisherige Wiedergabe und
zeigen den Grund in der Diagnose; Esc bleibt verfügbar. Die lokale Echoanalyse
ist keine Garantie für akustische Echounterdrückung bei jeder Raumakustik.

## Diagnose

Die Anzeige enthält das zuletzt erkannte Transkript, gegebenenfalls Original
und Namenkorrekturen, die STT-Dauer sowie den fehlerhaften Verarbeitungsschritt.
„Sprachdienste prüfen“ fragt den Zustand von STT und TTS über
`GET /v1/voice/health` ab. Transkript und Diagnose bleiben nur im Arbeitsspeicher
und lassen sich löschen. Die bestehende Gedächtnisoption für normale Gespräche
bleibt davon unabhängig.

## Nachweise und offene Abnahme, 2026-10-05

Automatisierte Tests prüfen Einstellungen nach Neustart, Kalibrierungsqualität,
Audio-/Authentifizierungsgrenzen, Satzende, begrenzte Namenskorrekturen,
verzögertes Lautsprecherecho, gleichzeitige menschliche Sprache, Unterbrechung,
Folgeaufnahme beim Verbindungsaufbau, Abbruch und die PyQt-Einstellungsansicht.

Die Windows-Gesamttests bestanden mit **675 Tests und 79 Untertests**
(`python -m pytest -q --ignore=backend/tests/test_chonkie_runtime.py`,
221,49 Sekunden). Die beiden Chonkie-Tests bestanden separat im neu gebauten
API-Docker-Image, das die hierfür benötigten Backend-Abhängigkeiten enthält.
Ruff für die geänderten Python-Dateien und die Repository-Prüfung bestanden;
Letztere prüfte 286 Python-Dateien und 106 lokale Dokumentationslinks.

Der reale API-Endpunkt mit dem lokalen Redux-Docker-Dienst erkannte den
synthetischen deutschen Testsatz vollständig: 4,645 Sekunden Audio,
1.010 ms STT einschließlich Dienstaufruf. Ohne Token wurde der Aufruf abgewiesen;
keine Aktion wurde ausgeführt. Nachweis:
[Kalibrierung](../artifacts/voice-improvements/calibration-runtime.json).
[Ansicht der Einstellungen](../artifacts/voice-improvements/voice-settings.png).

Noch nicht physisch abgenommen: Kalibrierung mit der tatsächlichen Stimme,
Dialekt und Zimmergeräuschen; Unterbrechen mit den verwendeten Mikrofonen und
Lautsprechern; Gerätewechsel im Alltag. Die Echo- und Unterbrechungstests nutzen
simulierte Audiosignale. Die bisherigen physischen Phase-0/Phase-1-Abnahmepunkte
bleiben offen.

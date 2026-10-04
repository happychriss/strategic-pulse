# Strategic Pulse: Lagebild Europa

Projektzusammenfassung, Stand 4. Oktober 2026
Repository: https://github.com/happychriss/strategic-pulse

---

## 1. Projektziel

Das Projekt soll **ein Gefühl für die Lage in Europa geben und anzeigen, wann sich etwas ändert.**
Es macht keine Vorhersage. Es soll nur sagen können: *Jetzt passiert gerade etwas, und zwar hier.*

Das Ergebnis begleitet einen strategischen Newsletter, der sich auf die wichtigen Themen
beschränkt und das Klein-Klein weglässt. Dazu gehört das Dashboard **„Lagebild Europa“**. Es
zeigt die Entwicklungen und wo sie herkommen. Jede Zahl ist bis zur amtlichen Quelle
zurückverfolgbar.

Ausgangspunkt war das Konzeptpapier `strategic_regime_monitor_concept.md`. Die erste Bewertung
steht in `docs/research/00_grounding_assessment.md`.

---

## 2. Grundsätze, die sich herausgebildet haben

1. **Nur amtliche, offene Quellen.** EZB, Eurostat, OECD, Weltbank. Jede Quelle hat eine
   Quellenkarte mit Zugang, Lizenz, Fallstricken und Prüfstatus.
2. **Nichts geht verloren.** Jede abgerufene Datei wird Byte für Byte archiviert
   (`data/raw/`) und bekommt eine Begleitdatei mit Herkunft, Zeitpunkt und Prüfsumme.
3. **Was wann bekannt war.** Die Datenbank speichert zu jedem Wert, für welchen Zeitraum er gilt
   und ab wann er bekannt war (bitemporal). So lassen sich Rückblicke ehrlich rechnen, ohne
   späteres Wissen.
4. **Keine festen Schwellen.** Werte wie „über 2,3 %“ oder „95 %-Grenze“ entscheiden still, was als
   ruhig gilt. Sie haben in die Irre geführt (siehe Abschnitt 6). Jede Zahl wird an ihrer eigenen
   Geschichte gemessen.
5. **Beschreiben statt urteilen.** Das Dashboard zeigt, wo eine Zahl im Vergleich zu ihrer
   Geschichte steht. Was davon wichtig ist, entscheidet der Leser.
6. **Methodik ist eine menschliche Entscheidung.** Der automatische Lauf darf Daten holen,
   rechnen und Seiten schreiben. Modell, Schwellen und Quellenregeln ändert er nicht.
7. **Ehrlich über Grenzen.** Annahmen, nachträgliche Änderungen und Schwächen werden
   dokumentiert, nicht geglättet.

---

## 3. Was gebaut wurde

| Baustein | Inhalt | Ort |
|---|---|---|
| Quellenkarten | 32 Karten, alle geprüften Quellen mit Zugang, Lizenz, Fallstricken | `sources/` |
| Rohdatenarchiv | Byte-genaue Snapshots mit Herkunftsdatei; nur bei Änderung neu gespeichert | `data/raw/` |
| Datenbank | PostgreSQL 16, bitemporal; Schemas für Register, Rohdaten, Beobachtungen, Modell, Bewertungen | `db/migrations/` |
| Modellversionen | v0.1 bis v0.5, eingefroren und mit Prüfsumme; Aussagen aus Fachtexten wörtlich belegt | `model/versions/` |
| Indikatoren | Umrechnungen (Vorjahr, Quartal, Mittelwerte, Verhältnisse), zeitrichtig verkettet | `src/srm/indicators.py` |
| Bewertung | Regime-Einschätzung zu Stichtagen mit Unsicherheitsgraden | `src/srm/assess.py` |
| Validierung | Prüfung der Regime-Einschätzungen gegen die tatsächliche Entwicklung | `src/srm/validate.py` |
| Veränderungsdetektor | Sechs Ebenen, 17 Monatssignale; Rückblick gegen 11 vorab festgelegte Ereignisse | `src/srm/detect.py` |
| Strukturachsen | 11 Jahresindikatoren für 27 Mitgliedstaaten (Demografie, Schulden, Rechtsstaat, Klima …) | `src/srm/structural.py` |
| Dashboard „Lagebild Europa“ | Deutsche Newsletter-Seite, jede Zahl mit Quelle und Abrufdatum | `src/srm/dashboard.py`, `reports/dashboard/` |
| Monatslauf | Holen, bauen, testen, bewerten, Seiten schreiben, Protokoll; nur auf Anforderung | `src/srm/run_monthly.py`, `docs/operations.md` |
| Tests | 96 automatische Tests | `tests/` |

**Die sechs Ebenen (monatlich):** Preise und Geldpolitik, Realwirtschaft, Rohstoffe und Energie,
Internationale Verflechtung, Gesellschaftlicher Zusammenhalt, Demografie und Migration.

**Die langsamen Achsen (jährlich):** Regierungsführung (Rechtsstaat, Mitsprache, Korruption),
Zusammenhalt (Ungleichheit), Wirtschaftsordnung (Staatsausgaben), Demografie (Altenquotient,
Geburtenrate), Technologie (Forschung), Klima (Schäden), Energie (Importabhängigkeit),
Staatsfinanzen (Schulden).

---

## 4. Verlauf

1. **Einordnung.** Konzept geprüft, Quellen recherchiert und Umfang begrenzt. Klare Linie zum
   Ergebnis, kein Endlosprojekt.
2. **Infrastruktur.** Startskript für Cloud-Sitzungen, Netzwerkfreigaben, erste Abrufe, Archiv.
3. **Datenmodell.** PostgreSQL 16 mit Gültigkeits- und Wissenszeit, stabile IDs,
   reproduzierbarer Aufbau.
4. **Modell v0.1–v0.3.** Regime-Einschätzungen mit belegten Aussagen. Die Lockerungsphase der
   EZB kam als v0.2 dazu.
5. **Validierung.** Die Regime-Etiketten treffen die tatsächliche Entwicklung nur in 44 % der
   Fälle. Daraus folgte die **Neuausrichtung**: Veränderung erkennen statt vorhersagen.
6. **Detektor v0.4/v0.5.** Tempo-Blick und Richtungswechsel. Neue und laufende Alarme werden
   getrennt. Rückblick 2008–2026.
7. **Strukturachsen.** Jahresdaten aller Mitgliedstaaten mit Trendvergleich.
8. **Dashboard, drei Durchgänge.**
   - mit Alarm-Etiketten;
   - mit Tempo und Niveau;
   - beschreibend, ohne Schwellen.
9. **Darstellungswerkstatt.** Verständlichere Formulierungen und Bilder für dieselben Zahlen
   (laufend).

Übernahmen nach `main`:
[PR 1](https://github.com/happychriss/strategic-pulse/pull/1),
[PR 2](https://github.com/happychriss/strategic-pulse/pull/2),
[PR 3](https://github.com/happychriss/strategic-pulse/pull/3),
[PR 4](https://github.com/happychriss/strategic-pulse/pull/4).

---

## 5. Ergebnisse

**Rückblick des Detektors 2008–2026** (Ereignisse vor dem ersten Lauf festgelegt):

| Version | Neu erkannt | Alarm lief schon | Verpasst | Alarme ohne Ereignis |
|---|---|---|---|---|
| v0.4 (nur Tempo) | 4 | 4 | 3 | 2 |
| v0.5 (Tempo + Richtung) | 5 | 4 | 2 | 7 |

Verpasst wurden der Negativzins 2014 (zu kleiner Schritt) und der Fluchtzuzug 2015 (Datenreihe
zu kurz).

**Lage Anfang Oktober 2026** (beschreibend, aus dem Dashboard):

- Energiepreise 14,3 % über Vorjahr: höchster Stand seit Januar 2023. Der Sprung kam im März und
  April 2026 (Krieg im Nahen Osten).
- Inflation 3,8 %. In nur etwa 8 % aller Monate seit 1997 lag sie höher.
- Exportvolumen: stärkster Drei-Monats-Anstieg seit Mai 2021, nach einem Tief im März. Die Daten
  reichen bis Juni.
- Arbeitslosigkeit 6,4 %, nahe am tiefsten Wert seit 2000. Die Preisschocks sind am Arbeitsmarkt
  noch nicht angekommen.
- Jahrestrend Geburtenrate: Sie fällt jetzt in 26 von 27 Mitgliedstaaten, in den fünf Jahren
  davor waren es 15.

---

## 6. Erkenntnisse

1. **Etiketten sind keine Prognosen.** Die Regime-Einschätzungen waren als Vorhersage schwach.
   Veränderung zu erkennen ist erreichbar, und genau das war die Ursprungsidee.
2. **Schwellen führen in die Irre.** Die Energiepreise standen als „im üblichen Rahmen“ da,
   obwohl das Niveau extrem hoch war. Gemessen wurde nur das Tempo. Beim Handel hatten die
   Krisenjahre den Maßstab so weit gemacht, dass eine große Bewegung als „ruhig“ galt. Deshalb
   beschreibt das Dashboard jetzt, statt zu urteilen.
3. **Niveau und Bewegung sind zwei Fragen.** Ein Schock kann da sein, auch wenn er gerade nicht
   weiter wächst.
4. **Die meiste Arbeit ist Datenbeschaffung und Harmonisierung, nicht die Auswertung.**
   Falsche Codes, leere Abfragen, Fehlermeldungen als Daten, fehlende EU-Aggregate. Hier
   hilft KI am meisten: Quellen finden, Formate verstehen, Parser schreiben. Geprüft wird über
   nachvollziehbare Zwischenschritte: Rohdatei, Code, Test, Stichprobe gegen die Quelle,
   menschliche Freigabe neuer Quellen. Ein KI-Ergebnis muss man so nicht blind glauben.
5. **Mehr Achsen ist nicht automatisch besser.** Viele Monatsreihen erzeugen Rauschen. Die
   langsamen Jahresachsen ergänzen die schnellen Signale.

---

## 7. Offene Entscheidungen und nächste Schritte

**Darstellung (laufend):**
- Form der Einordnung wählen, etwa „Höchster Stand seit …“ plus Spannweiten-Bild, statt
  Prozenträngen.
- Erklärender Satz unter jedem Signal: Tendenz aus den Zahlen plus fester Bedeutungssatz pro
  Signal. Später eventuell als KI-Entwurf mit Freigabe.
- Lagekarte: Niveau gegen Bewegung für alle Signale in einem Koordinatensystem (in Prüfung).

**Inhalt:**
- Die Ebene „Internationale Verflechtung“ verbreitern: Index für geopolitisches Risiko und Index
  für wirtschaftspolitische Unsicherheit (Karten angelegt, noch nicht geprüft).
- Alte Daten auf der Seite kennzeichnen (älter als drei Monate).
- Alarmmodell auf dieselbe Rangmessung umstellen (v0.6), mit neuem Rückblick.

**Betrieb:**
- Routine in claude.ai mit dem Repository neu anlegen. Sie läuft nur auf Anforderung.
- Aussagen aus Fachtexten: Prüfer benennen. Bis dahin bleiben sie „vorgeschlagen“.
- Optional ein ENTSO-E-Token für Strommarktdaten, nur als Umgebungsgeheimnis und nie im
  Repository.

---

## 8. Bedienung

```bash
# Monatslauf (holt Daten, baut, testet, bewertet, schreibt Seiten und Protokoll)
PYTHONPATH=src .venv/bin/python -m srm.run_monthly

# nur das Dashboard neu schreiben
PYTHONPATH=src .venv/bin/python -m srm.dashboard

# Tests
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Ergebnisse:
- `reports/dashboard/index.html`: Lagebild Europa;
- `reports/detector/`: Rückblick des Detektors;
- `reports/runs/`: Laufprotokolle.

Veröffentlichte Seiten (privat, Freigabe über „Share“ auf der Seite):
- Lagebild Europa: https://claude.ai/artifact/RRKNrEVKPnb3oqzxoaWqvQ
- Darstellungswerkstatt: https://claude.ai/artifact/CMoQBK2WtKc7aeKcx1WW1P
- Bewertungsseite v0.5 (englisch): https://claude.ai/artifact/5pxWmri8Cw7mgwnPV4TzoV

**Weiterführende Dokumente im Repository:**
- `docs/research/00_grounding_assessment.md`: erste Einordnung;
- `docs/data_model.md`: Datenbankentwurf;
- `docs/model_review.md`: Modellprüfung und Versionsgeschichte;
- `docs/operations.md`: Betrieb, Monatslauf, Dashboard.

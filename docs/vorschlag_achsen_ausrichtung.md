# Vorschlag: Hauptachsen und Ausrichtung der Signale

Stand 4. Oktober 2026. Entwurf zur Prüfung, noch nicht im Modell.

Jede Hauptachse wird von Signalen betrieben. Ein Signal hat eine Ausrichtung:

- **+**: Ein höherer Wert zieht zum oberen Pol der Achse.
- **−**: Ein höherer Wert zieht zum unteren Pol.

Niveau und Dynamik jedes Signals werden so gedreht, dass alle Signale einer Achse auf derselben
Skala liegen (0 = unterer Pol, 1 = oberer Pol). Die Achse zeigt ihre Signale einzeln und markiert
die Mitte (Median). Eine gemittelte Achsenzahl gibt es nicht. Alle Signale zählen gleich.

**Abgleich mit dem bestehenden Modell.** Die Modellversion v0.5 führt für jedes Monatssignal
bereits eine Ausrichtung (`semantics: higher_is_toward_high_pole / low_pole`). Für alle Signale an
den neun Hauptachsen stimmt dieser Vorschlag damit überein, auch bei den Asylanträgen (−). Es gibt
eine bewusste Abweichung: Im Block „Konjunktur“ ist der obere Pol hier der Abschwung, im Modell
ist es beim Knoten „Output growth“ die Expansion. So bedeutet „oben“ auf der Lagekarte fast
überall „mehr Belastung“. Ausnahmen sind Wirtschaftsordnung und Technologie, deren Pole keine
Belastung beschreiben.

Nach der Freigabe wandert die Tabelle als `orientation` in die nächste Modellversion (v0.6) und
ist dann eingefroren. Jede spätere Änderung braucht eine neue Version.

## Die neun Hauptachsen

| Hauptachse | unterer Pol | oberer Pol |
|---|---|---|
| Ressourcen / Energie | Fülle, Widerstandskraft | Knappheit, Verwundbarkeit |
| Staatsfinanzen | Spielraum | Stress |
| Internationale Verflechtung | Integration | Fragmentierung, Blockbildung |
| Gesellschaftlicher Zusammenhalt | Vertrauen | Spaltung |
| Demografie und Migration | Wachstum | Alterung, Schrumpfung |
| Regierungsführung | Pluralismus, Kontrolle der Macht | Machtkonzentration |
| Wirtschaftsordnung | Markt | stärkere staatliche Lenkung |
| Technologie | langsamer Wandel | schneller Wandel |
| Klima / Umwelt | Stabilität | wachsende physische Belastung |

Die Pole sind keine Bewertung. „Schneller Wandel“ oder „staatliche Lenkung“ sind weder gut noch
schlecht.

## Zuordnung und Ausrichtung

M = monatlich, Q = quartalsweise, J = jährlich.

| Signal | Takt | Hauptachse | Ausrichtung | Begründung | Strittig |
|---|---|---|---|---|---|
| Energiepreise zum Vorjahr | M | Ressourcen / Energie | + | Steigende Energiepreise zeigen Knappheit und Verwundbarkeit. | Misst die Veränderung zum Vorjahr, nicht das Preisniveau |
| Russlands Anteil an den EU-Gasimporten | M | Ressourcen / Energie | + | Mehr Abhängigkeit von einem Lieferanten heißt mehr Verwundbarkeit. | |
| Energieimportabhängigkeit | J | Ressourcen / Energie | + | Mehr Importe heißt mehr Abhängigkeit. | |
| Staatsschulden, % des BIP | J | Staatsfinanzen | + | Mehr Schulden heißt weniger Spielraum. | |
| Rendite 10-jähriger Staatsanleihen | M | Staatsfinanzen | + | Höhere Finanzierungskosten heißen mehr Stress. | Hängt auch an Leitzins und Wachstum; alternativ Block „Preisdruck“ |
| Haushaltssaldo, % des BIP *(im Modell, neu im Dashboard)* | J | Staatsfinanzen | − | Ein höherer Saldo (Überschuss) heißt mehr Spielraum. | |
| Zinsausgaben, % des BIP *(im Modell, neu im Dashboard)* | J | Staatsfinanzen | + | Höhere Zinslast heißt weniger Spielraum. | |
| Exportvolumen zum Vorjahr | M | Internationale Verflechtung | − | Wachsender Außenhandel heißt mehr Verflechtung. | Misst stark die Konjunktur; besser ergänzen durch Unsicherheits-Indizes |
| Importvolumen zum Vorjahr | M | Internationale Verflechtung | − | wie oben | wie oben |
| Geopolitisches Risiko *(Karte angelegt, noch nicht geladen)* | M | Internationale Verflechtung | + | Mehr Risiko heißt mehr Blockbildung. | |
| Wirtschaftspolitische Unsicherheit *(Karte angelegt, noch nicht geladen)* | M | Internationale Verflechtung | + | Unsicherheit über Handel und Politik deutet auf Fragmentierung. | Passt auch zu „Zusammenhalt“ |
| Verbrauchervertrauen | M | Zusammenhalt | − | Mehr Vertrauen heißt mehr Zusammenhalt. | |
| Sorge vor Arbeitslosigkeit | M | Zusammenhalt | + | Mehr Sorge heißt mehr Verunsicherung. | |
| Jugendarbeitslosigkeit | M | Zusammenhalt | + | Steht für den Generationenkonflikt, den das Konzept nennt. | Auch Konjunktur |
| Einkommensungleichheit S80/S20 | J | Zusammenhalt | + | Mehr Ungleichheit heißt mehr Verteilungskonflikt. | |
| Asylerstanträge je 100.000 | M | Demografie und Migration | − | Zuwanderung wirkt der Schrumpfung entgegen. | **Ja.** Als Migrationsdruck ließe es sich auch bei „Zusammenhalt“ mit + einordnen. Ihre Entscheidung |
| Altenquotient | J | Demografie und Migration | + | Mehr Ältere je Erwerbsperson heißt Alterung. | |
| Geburtenrate | J | Demografie und Migration | − | Mehr Geburten heißt Wachstum. | |
| Rechtsstaatlichkeit (Weltbank) | J | Regierungsführung | − | Stärkerer Rechtsstaat heißt mehr Kontrolle der Macht. | |
| Mitsprache und Rechenschaft (Weltbank) | J | Regierungsführung | − | wie oben | |
| Korruptionswahrnehmung (höher = sauberer) | J | Regierungsführung | − | Sauberere Institutionen heißen mehr Kontrolle der Macht. | |
| Staatsausgaben, % des BIP | J | Wirtschaftsordnung | + | Höhere Staatsquote heißt mehr staatliche Lenkung. | Grobes Maß; Subventionen oder Industriepolitik fehlen |
| Forschungsausgaben, % des BIP | J | Technologie | + | Mehr Forschung heißt schnellerer Wandel. | Misst Einsatz, nicht Verbreitung |
| Schäden durch Klimaextreme | J | Klima / Umwelt | + | Mehr Schäden heißt mehr physische Belastung. | |

## Die schnelle Schicht: Konjunktur, Preise, Zinsen

Das Konzept nennt diese Signale Zustandsgrößen, nicht Achsen. Sie zeigen Schocks zuerst. Für die
Lagekarte bekommen sie zwei eigene Blöcke mit Polen:

| Block | unterer Pol | oberer Pol |
|---|---|---|
| Preisdruck | gering | hoch |
| Konjunktur | Aufschwung | Abschwung |

| Signal | Takt | Block | Ausrichtung | Begründung | Strittig |
|---|---|---|---|---|---|
| Inflation (HVPI) | M | Preisdruck | + | direkt | |
| Kerninflation | M | Preisdruck | + | direkt, ohne Energie und Lebensmittel | |
| Preiserwartungen der Haushalte | M | Preisdruck | + | Erwartungen gehen der Inflation oft voraus. | |
| EZB-Einlagezins | M | Preisdruck | + | Die EZB erhöht, wenn der Preisdruck steigt. | **Ja.** Das ist eine Reaktion, kein Druck. Alternative: eigener Block „Finanzierungsbedingungen“ zusammen mit der Anleiherendite |
| Arbeitslosenquote | M | Konjunktur | + | Mehr Arbeitslose heißt Abschwung. | |
| Wachstum zum Vorquartal | Q | Konjunktur | − | Mehr Wachstum heißt Aufschwung. | |
| Wirtschaftsstimmung (ESI) | M | Konjunktur | − | Bessere Stimmung heißt Aufschwung. | |
| Vertrauen in der Industrie | M | Konjunktur | − | wie oben | |

## Was die Tabelle offenlegt

- **Vier Achsen haben nur Jahresdaten:** Regierungsführung, Wirtschaftsordnung, Technologie,
  Klima. Ihre Dynamik ist der Trend der letzten fünf Jahre gegenüber den fünf davor. Sie ändert
  sich einmal im Jahr.
- **Dünn besetzt:**
  - Wirtschaftsordnung, Technologie und Klima haben je ein Signal.
  - Die Verflechtung misst bisher eigentlich Konjunktur.
  - Ein Kreuz aus einem Signal hat keine Arme, die Aussage ist entsprechend schwach.
- **Kandidaten zum Verstärken, alle offen verfügbar:**
  - Verflechtung: geopolitisches Risiko, wirtschaftspolitische Unsicherheit;
  - Staatsfinanzen: Saldo und Zinslast;
  - Technologie: Patentanmeldungen oder Breitband (Eurostat);
  - Klima: Temperaturabweichung (Copernicus).

## Zu entscheiden

1. Asylanträge: bei Demografie mit − (Zuwanderung gegen Schrumpfung) oder bei Zusammenhalt mit +
   (Migrationsdruck)?
2. EZB-Zins und Anleiherendite: getrennt (Zins bei Preisdruck, Rendite bei Staatsfinanzen) oder
   zusammen als Block „Finanzierungsbedingungen“?
3. Exporte und Importe vorerst bei Verflechtung lassen, bis die Unsicherheits-Indizes geladen
   sind?
4. Saldo und Zinslast bei den Staatsfinanzen ins Dashboard aufnehmen?

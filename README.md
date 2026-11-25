# Audilege Server 0.4.18

Abgleichaufträge zeigen den gemessenen Fortschritt je Phase. Unter Linux nach dem Update `sh worker/install.sh` im neuen Serverordner ausführen, damit der installierte Worker die Fortschrittswerte meldet.

Der einmalige Audiobookshelf-Import steht unter Einstellungen → Audiobookshelf-Statistik.

For Windows and Linux, with a German and English web interface. See [the English quick start](README.en.md) and the [release downloads](https://github.com/yourneeds-app/audilege-server/releases).

## Update auf 0.4.8

Die Startseite zeigt den zuletzt genutzten Titel mit Modus und Fortschritt. Darunter stehen weitere angefangene Bücher, Neuzugänge und abonnierte Podcasts.

## Update auf 0.4.7

Hörbücher und Podcasts spielen beim Wechsel zwischen Bibliothek, Titeldetails, Statistik und Einstellungen weiter. Ein kompakter Player zeigt Cover, Titel und Pause. Bei Podcasts mit einem einzigen Abschnitt entfallen die doppelte Kapitelüberschrift und die Dateiendung als Kapitelanzeige.

Unter Verwaltung → Bibliothek prüfen ergänzt Audilege fehlende Angaben aus Titelordnern und ausgewählten Katalogen. Reihen und Bandnummern lassen sich über passende Titel und Autoren zuordnen, ausgabenspezifische Angaben wie Erscheinungsjahr und Verlag über eine übereinstimmende ISBN. Unklare Treffer bleiben zur Prüfung. Übernommene Änderungen lassen sich zurücknehmen. In „KI-Anbieter & Modell“ kann ein Admin zusätzlich die automatische Prüfung neuer Buchimporte einschalten. Ausgewählte Onlinekataloge erhalten Suchanfragen, ein aktiviertes Modell erhält die Vergleichsdaten.

Der Webreader passt die zentrierte Buchseite an die Fensterhöhe an. Breite Fenster zeigen zwei Textspalten, kleinere eine. Die Blättertasten bleiben sichtbar. Beim Erstellen einer Audilege-Fassung ist eine eindeutige, eingelesene Gegenausgabe im selben Titelordner vorausgewählt. Bei mehreren Ausgaben wählst du selbst.

Im Webregal lässt sich nach Reihe oder Speicherort in beide Richtungen sortieren. Innerhalb einer Reihe folgen die Bände ihrer Nummer. „Reihe anzeigen“ blendet Reihennamen und vorhandene Bandnummern unter den Titeln ein. Bei der Sortierung nach Speicherort zeigen gescannte Titel ihren relativen Quellpfad. Bei einer Ordnerstruktur wie `Autor/Reihe/Vol 02 - Titel` ergänzt das Webregal fehlende Reihen- und Bandangaben aus dem Pfad. Vorhandene Angaben haben Vorrang.

Der Scanner fasst CD-Unterordner innerhalb eines Titelordners zu einem Hörbuch zusammen, etwa `Autor/Buchtitel/CD 1` und `Autor/Buchtitel/CD 2`. Die Wiedergabe folgt der Nummerierung von CDs und Titeln. Bereits einzeln eingelesene CD-Ordner werden beim nächsten stabilen Scan im Regal zusammengeführt. Das gilt für den Medieneingang und direkt eingebundene Sammlungen.

Den bisherigen Server mit seiner vorhandenen Aufgabe oder seinem Dienst anhalten, den Datenordner sichern und die Programmdateien aus dem neuen Paket in den bisherigen Programmordner übernehmen. Anschließend dieselbe Aufgabe oder denselben Dienst wieder starten. Der vorhandene Aufruf bestimmt weiterhin Bindeadresse, Port, Datenpfad und Worker. Bei einer vorhandenen Installation mit eigenem Autostart ist **Start-Audilege.cmd** nur für eine separate Neueinrichtung gedacht. Den externen Medienbestand separat sichern.

**Vorhandene Sammlung.** Als Admin unter **Verwaltung → Medieneingang → Bibliothek direkt einbinden → Sammlungsordner wählen** den bestehenden Hauptordner auswählen. Der Scanner liest auch Unterordner und benötigt dort nur Leserechte. Pro mehrteiligem Hörbuch einen Titelordner verwenden. EPUB und Hörbuch dürfen im selben Titelordner liegen. Titel, Kapitelindex und Cover werden im Datenordner gespeichert. Wiedergabe und EPUB-Download greifen auf die Quelldateien zu. Beim expliziten Offline-Download eines reinen Hörbuchs entsteht vorübergehend eine vollständige EPUB-Datei im Temp-Verzeichnis des Servers. Abgleichaufträge benötigen eigenen Arbeitsspeicherplatz. Der normale Medieneingang für kopierte Importe bleibt separat. Ein fehlendes Laufwerk behält seinen Katalogeintrag. Bereits importierte Kopien bleiben erhalten. Die Wahl des Sammlungsordners ist dauerhaft und kann mit **Überwachung beenden** zurückgenommen werden.

**Adressen.** Dieselbe Oberfläche funktioniert am lokalen Port, über einen Schul-DNS-Namen und unter einem beliebigen Proxy-Unterpfad. Für den Unterpfad die Adresse mit abschließendem Schrägstrich öffnen. Der Proxy leitet die Form ohne Schrägstrich dorthin um, entfernt das Präfix für das Backend und erhält den öffentlichen Host-Header. Beispiel für eine vorhandene Caddy-Site:

```caddyfile
redir /medien/audilege /medien/audilege/ 308
handle_path /medien/audilege/* {
    reverse_proxy 127.0.0.1:8472
}
```

Das Proxyziel ist die vom Proxy erreichbare Adresse des Audilege-Prozesses. Bestehende Caddy-Routen, Zertifikate und Windows-Aufgaben sind installationsspezifisch. In Android die vollständige Adresse einschließlich Unterpfad angeben. Ein lokaler Name wie audilege.local muss im Netzwerk auflösbar sein.

**Statistik.** App- und Websitzungen sowie Audiobookshelf-Importe bilden je Profil einen Verlauf. Eindeutige gleiche Buchtitel werden gemeinsam angezeigt. Identische Hörsitzungen mit übereinstimmender Zuordnung und Sitzungskennung oder gleichem Startzeitpunkt und gleicher Dauer zählen einmal. Gleicher Titel und Tag allein reichen dafür nicht aus. Aktuelle und längste Serie zählen aufeinanderfolgende Tage mit Hör-, Lese- oder Vorlesezeit. Bis zum Ende des heutigen Tages kann die gestern aktive Serie fortgesetzt werden. Audilege-Sitzungen verwenden das Serverkonto mit UTC, Importe behalten den von Audiobookshelf gelieferten Kalendertag. Android ab 0.4.20 übernimmt die zusammengeführten Zeiten und Titel, auch für importierte Bücher außerhalb des Katalogs.

## Neu in 0.4.0

Die Startseite zeigt begonnene Titel und kurze Regale. Die Suche findet Titel, Hörfolgen, Personen, Reihen und Genres. Im Reader öffnet **Aa** die Leseeinstellungen. **Werkzeuge** enthält Buchsuche, Lesezeichen und die zur Ausgabe passenden Audiofunktionen. Der Browser merkt ausstehende Positionsänderungen für das angemeldete Konto.

Unter **Verwaltung → Bibliothek prüfen** können Admins einen Modellanbieter einrichten. Unterstützt werden OpenAI, Anthropic, Google Gemini, Ollama und kompatible Endpunkte. Bei einer Prüfung mit aktiviertem Modell erhält der Anbieter die ausgewählten Titelmetadaten, zum Vergleich bis zu 25 benachbarte Katalogeinträge und gegebenenfalls Treffer der gewählten Suchanbieter. Ein passendes lokales Modell lässt sich mit Ollama auf demselben Rechner verwenden.

Unter **Speicher & System** lassen sich die Updateprüfung und die optionale Passwortwiederherstellung konfigurieren. SMTP verwendet STARTTLS. Das Passwort kommt aus der Umgebungsvariable `AUDILEGE_SMTP_PASSWORD`. Die tägliche Updateprüfung und die KI sind bei der Installation ausgeschaltet. **Server & Profil** führt zu den Gerätesitzungen und zur Bestätigung der eigenen E-Mail-Adresse, sobald die Wiederherstellung eingerichtet ist.

Der gewählte Medienordner enthält **Ebooks**, **Audiobooks**, **Podcasts** und **Readaloud**. Neue abgeschlossene Abgleiche exportiert der Scanner als EPUB nach Readaloud. Die Entscheidung über die verwalteten Originale steht unter **Speicher & System**. Der Papierkorb behält sie zur Wiederherstellung. Bei angehaltenem Server erstellt `AudilegeServer.exe --backup ZIELORDNER` eine Sicherung mit Prüfsummen. `--restore SICHERUNG` prüft sie vor der Wiederherstellung und bewahrt den vorherigen Bestand separat. Auf Linux stehen dieselben Optionen über `python3 server.py` zur Verfügung. Ein externer Medienordner und separat eingerichtete Zugangsdaten werden auf dem jeweiligen System gesichert.

Eine eigene Bibliothek auf dem Mini-PC für die Audilege-App und den Browser. Der Server verwaltet Medien, Konten, Hörstände und Importhistorie in einem lokalen Datenordner. Ein BookOrbit-Konto ist für diesen Server optional. Bestehende BookOrbit-Profile können parallel in der App genutzt werden.

## Starten

| System | Erster Start |
| --- | --- |
| Windows x64 | ZIP vollständig entpacken und **Start-Audilege.cmd** öffnen. Beim ersten Start das Administratorkonto anlegen. Die Einrichtung lädt den CPU-Worker und das deutsche Sprachmodell und prüft beide vor dem Öffnen der Bibliothek. |
| Linux | Archiv entpacken und im Serverordner `sh start.sh` aufrufen. Python ab 3.10 mit SQLite muss installiert sein. Beim ersten Start das Konto im Terminal anlegen. |

Die Startdateien stellen die Bibliothek im Heimnetz auf Port **8472** bereit. Am Mini-PC lautet die Adresse `http://localhost:8472`. Auf anderen Geräten die lokale IP-Adresse des Mini-PCs mit demselben Port verwenden. Für Zugriffe über das Internet einen HTTPS-Reverse-Proxy vor den Server setzen. Der direkte Programmaufruf ohne Startdatei bindet an die Loopback-Adresse.

**Android verbinden.** Unter **Profil → Profil hinzufügen → Mit BookOrbit-Konto anmelden** die Adresse dieses Mini-PCs sowie dessen Audilege-Benutzernamen und Passwort eingeben. Für eine lokale HTTP-Adresse den Heimnetz-Zugriff im Profil erlauben. Im Browser und in der App dasselbe Serverkonto verwenden. Beim Pausieren und während der Wiedergabe speichert der Browser Ausgabe, Abschnitt, Textstelle und Hörposition. Im laufenden Player auf dem anderen Gerät den Titel neu öffnen, um einen neueren Hörstand zu laden.

**Datenordner.** Windows nutzt `%LOCALAPPDATA%\AudilegeServer`, Linux standardmäßig `~/.local/share/AudilegeServer`. Mit `--data` lässt sich ein anderer Pfad angeben. Für eine vollständige Sicherung den Server beenden und den gesamten Datenordner kopieren. Mit `--add-user` ein weiteres Konto anlegen. Die Medienbibliothek ist gemeinsam, Hörstände und Hörhistorie gehören jeweils zum angemeldeten Konto.

## Bibliothek und Verwaltung

Über das Menü lässt sich die Seitenleiste ein- und ausblenden. Unter **Kategorien → Entdecken** findest du Titel über die Medienarten hinweg. Die Sortierung wird im Browser gespeichert. **Server & Profil** und **Einstellungen** stehen unten im Menü. Unter Einstellungen lassen sich Schrift, Größe, Zeilenabstand, Ränder, Blättermodus und Sprungweiten anpassen.

Bei Audilege-Büchern verwenden Lesen und Mitlesen die Absätze des EPUB. Beim Moduswechsel sucht der Player die zugehörige Zeitmarke. Beim Lesen dient die erste Textstelle der Seite als Ausgangspunkt. Ein Klick in den Text setzt eine genauere Stelle. Wie genau der Wechsel gelingt, hängt von den Wort- oder Satzmarken der Ausgabe ab.

Die Statistik zeigt die Hörminuten der vergangenen sieben Tage, die aktuelle Hörserie, die letzten Aktivitäten und einen Kalender pro Hörjahr. Importierte Hörtage behalten das Datum aus Audiobookshelf. Für ältere Importe ohne Uhrzeit erscheint das Datum. Ein erneuter Import ergänzt verfügbare Uhrzeiten.

Im Menü **Verwaltung → Benutzer** legt ein Administrator Konten an, setzt Passwörter, vergibt Administratorrechte und deaktiviert Konten. Beim Update von 0.1 übernimmt das zuerst angelegte Konto die Administration. Eine Deaktivierung beendet die Sitzungen des Kontos. Für die Übertragung von Anmeldedaten außerhalb eines vertrauenswürdigen Heimnetzes HTTPS verwenden.

**Verwaltung → Medieneingang** zeigt den überwachten Ordner und den letzten Scan. Der Server prüft ihn alle 15 Sekunden. Neue und geänderte Dateien werden nach zwei stabilen Prüfungen importiert. EPUBs und einzelne Audiodateien können direkt hineingelegt werden. Für ein mehrteiliges Hörbuch einen Unterordner pro Titel verwenden. Im Unterordner **Podcasts** zählt jede Audiodatei als Folge. Ein erneuter Scan erkennt bereits eingelesene Quellen. Entfernte Quelldateien lassen die importierte Bibliothekskopie bestehen. Über **Ordner ändern** lässt sich ein bestehender Medienordner dauerhaft auswählen. Mit `--medienordner "D:\Medien"` kann ein eigener Ordner überwacht werden.

In der Bibliotheksübersicht hat jede abonnierte Sendung ein quadratisches Cover. Der Podcastordner enthält die neuesten Folgen und die Auswahl nach Sendung. Dort sind auch einzeln importierte Folgen erreichbar.

Unter **Titel hinzufügen → Podcast aus RSS-Feed → Feed abonnieren** richten Administratoren ein Abo ein. Die Adresse muss vom Server aus erreichbar sein. Audilege startet den ersten Abruf im Hintergrund und prüft den Feed danach alle 15 Minuten, bei Fehlern nach fünf Minuten. Für Pinchflat-Feeds mit Video extrahiert FFmpeg die Tonspur. Der Browser kann währenddessen geschlossen sein.

Pro abonniertem Feed bleiben die fünf neuesten abspielbaren Folgen nach Veröffentlichungsdatum. Bei fehlenden Datumsangaben dient die Reihenfolge im Feed als Ersatz. Audilege löscht ältere Bibliothekseinträge und deren Mediendateien aus seinem Datenordner. Neue Folgen ersetzen ältere erst nach erfolgreichem Download und Medienimport. Hörstatistiken bleiben erhalten. Das Aufräumen betrifft auch frühere Einzelimporte derselben RSS-Adresse, sobald du sie abonnierst. Unter **Abonnierte Feeds → Abo beenden** endet die Aktualisierung. Für einzelne Folgen steht im selben Dialog **Einzelne Folgen importieren** zur Verfügung.

Im geöffneten Buch liegen unter **Optionen → Metadaten bearbeiten** die Dateitags, Katalogsuche und Coverauswahl. Audible.de, Audible.com, Google Books und Open Library sind einzeln wählbar. Titel, Autoren, Sprecher, Serie, ISBN, Verlag, Jahr, Beschreibung und Schlagwörter können auch von Hand bearbeitet werden. Übernommene Daten und Cover gelten im Serverkatalog und für die App. Die importierten Originaldateien behalten ihre Tags. Einzelne Kataloge können ihre Anfragen begrenzen. Für eigenes Google-Books-Kontingent unterstützt der Server die Umgebungsvariable `AUDILEGE_GOOGLE_BOOKS_KEY`.

Die Buchdetails zeigen Cover, Angaben zum Buch und die verfügbaren Modi. **Lesen** bietet Blättern mit Schaltflächen, Pfeiltasten und Wischen. **Hören** zeigt das verfügbare Hörbuchcover, die Kapitelliste, die Zeit im aktuellen Kapitel, Sprungtasten und Tempo. **Mitlesen** folgt den eingebetteten Zeitmarken. Bei laufender Wiedergabe klappt der Player nach vier Sekunden Ruhe ein. Über **Player anzeigen** oder einen Tipp ins Textfeld lässt er sich wieder öffnen.

## Bücher und Podcasts

Über **Titel hinzufügen** eine EPUB-Datei, ein Hörbuch oder eine Podcastfolge auswählen. Mehrteilige Hörbücher nach der gewünschten Reihenfolge benennen, etwa `01.mp3`, `02.mp3`. Unter Windows verwendet der Import bei Bedarf das mit eingerichtete FFprobe des Workers. Unter Linux muss FFprobe im Suchpfad des Servers verfügbar sein. Unterstützte Audioformate sind MP3, M4A, M4B, Ogg, WAV und FLAC. Die Wiedergabe ist vom jeweiligen Browsercodec abhängig.

Die Bibliothek zeigt nur belegte Rubriken. **Hörbücher** enthalten reine Hörfassungen, **E-Books** die Textfassungen und **Audilege** Bücher mit verknüpftem Text und Ton. Ein bereits vertontes EPUB mit gültigen Zeitmarken landet direkt in **Audilege**. **Podcasts** zeigt zuerst die neuesten Folgen über alle Sendungen. Über **Nach Podcast** lässt sich eine einzelne Sendung auswählen. Die Angaben stammen aus dem Feed.

## EPUB und Hörbuch verbinden

1. Unter Windows richtet der normale Start den Worker ein. Unter Linux gilt die Worker-Anleitung unten.
2. Ein E-Book oder ein Hörbuch öffnen und **Audilege-Fassung erstellen** auswählen. Die passende Ausgabe aus der Bibliothek wählen oder die fehlende Datei hochladen. Sprache und Reihenfolge der Hördateien kontrollieren.
3. Der Auftrag läuft auf dem Mini-PC. Die Bibliothek zeigt den Fortschrittsstatus. Unter Windows ist Deutsch nach der Einrichtung einsatzbereit. Weitere Modelle lädt der Worker bei der ersten Verwendung. Text und Ton werden anschließend lokal verarbeitet.
4. Sobald das Ergebnis lesbare Textstellen mit gültigen Tonverweisen enthält, wechselt der Ausgangstitel zu **Audilege**. Wenn zwei vorhandene Titel gewählt wurden, erscheint eine gemeinsame Fassung. Bis zum erfolgreichen Abschluss bleiben beide Originale erreichbar. Unter **Aufträge → Erneut versuchen** lassen sich gespeicherte Arbeitsdateien nach einem Fehler nochmals verwenden. Die Anzeige nennt den aktuellen Verarbeitungsschritt.
5. In der Hörfassung **Wort** oder **Satz** wählen. Die Markierung folgt demselben Ton. Auf Android ab **0.4.17** liegt die Auswahl unter **Mitlesen anpassen → Text markieren**. Die Einstellung wird auf jedem Gerät separat gespeichert.

Die automatische Zuordnung setzt eine zur Textausgabe passende Lesung voraus. Gekürzte Fassungen und deutlich abweichende Übersetzungen können Lücken ergeben. Bereits fertige EPUBs verwenden ihre mitgelieferten Zeitmarken. Der Webreader bietet den Wort/Satz-Schalter auch in Kapiteln mit gemischten Wort- und Satzzeitmarken an. Bei einer einzelnen Satzzeitmarke leuchtet der ganze Satz auf.

## CPU-Worker einrichten

Der Worker verwendet STAlign mit **QuartzNet15x5**. Er zerlegt das EPUB in Sätze und Wörter und erstellt ein herunterladbares EPUB mit eingebettetem Ton und SMIL-Zeitmarken. Ein Auftrag läuft zur gleichen Zeit. Für die Verarbeitung werden zusätzliche Arbeitskopien von EPUB, Audio und Modelldaten benötigt.

- **Linux x64.** Node.js **24 LTS** mit npm sowie FFmpeg und FFprobe **ab 7** installieren. In derselben Shell `sh worker/install.sh` im entpackten Serverordner ausführen. Die Installation speichert die gefundenen Programmpfade für den späteren Serverstart.
- **Windows x64.** Auf einem aktuellen Windows 10/11 mit aktivierter Virtualisierung prüft der Start eine vorhandene Audilege-Installation in Ubuntu. Auf einem frischen Rechner richtet er WSL 2 sowie die separate Umgebung **Audilege-Worker** ein. Windows kann dafür Administratorrechte und einen Neustart verlangen. Anschließend dieselbe Startdatei erneut öffnen. Die einmaligen Downloads benötigen Internet und mehrere GB freien Platz auf dem Systemlaufwerk. Node.js 24, FFmpeg/FFprobe 7, die festgelegten npm-Pakete und das deutsche QuartzNet-Modell werden automatisch installiert. Der Worker verarbeitet die Bücher als eigener Linux-Benutzer. Weitere Sprachmodelle lädt er beim ersten Einsatz der jeweiligen Sprache. `AudilegeServer.exe --setup-worker` führt ausschließlich die Einrichtung und Funktionsprüfung aus. `--ohne-worker` startet die Bibliothek für die Wiedergabe. Bei einem bestehenden eigenen WSL-Benutzer können `AUDILEGE_WSL` und `AUDILEGE_WSL_USER` gesetzt werden.

Standardmäßig installiert das Skript die festgelegten Worker-Versionen in `~/.local/share/audilege-worker`. `AUDILEGE_WORKER_DIR` erlaubt einen eigenen Linux-Pfad und muss dann bei Installation und Serverstart gesetzt sein. Fehlgeschlagene Aufträge behalten das technische Protokoll unter `jobs/<Auftrag>/worker.log`. Die Modelldateien werden vom verwendeten Sprachpaket bereitgestellt.

## Audiobookshelf-Statistik einmalig übernehmen

1. **Audiobookshelf-Statistik.cmd** unter Windows oder `sh Audiobookshelf-Statistik.sh` unter Linux starten. Die Adresse der bestehenden Audiobookshelf-Instanz und einen Zugangsschlüssel des gewünschten Benutzers eingeben. Der Schlüssel wird verdeckt eingegeben und nur für diesen Export im Arbeitsspeicher verwendet.
2. In Audilege mit dem gewünschten Zielkonto anmelden. Unter **Einstellungen → Audiobookshelf-Statistik → Aus Audiobookshelf importieren** die erzeugte JSON-Datei aus dem Downloadordner auswählen.
3. Die Vorschau nennt neue Hörsitzungen, zusätzliche Hörzeit und die Anzahl der Fortschrittseinträge. Mit **Importieren** bestätigen. Eine wiederholt ausgewählte Datei zählt dieselben Sitzungen einmal.

Der Export liest die paginierte persönliche Hörhistorie und die gespeicherten Medienfortschritte. Für Titel ohne Hörsitzung fragt er bei Bedarf die Buchmetadaten ab. Die Historie zeigt tatsächliche Hörsekunden je Titel und Tag, verfügbare E-Book- und Hörfortschritte sowie Abschlüsse. Ein E-Book-Prozentwert liefert keine Lesedauer. Die ursprünglichen Audiobookshelf-Kennungen werden für die Historie aufbewahrt. Das ersetzt keine Buchdateien und überschreibt keine aktuellen Audilege-Hörstände. Es gibt keinen laufenden Hintergrundabgleich mit Audiobookshelf.

## Betrieb und Kompatibilität

Die Weboberfläche verwendet das Wortzeichen und App-Symbol des Audilege-Players. Python, SQLite und die lokalen Webdateien reichen für Bibliothek, Konten und EPUB-Wiedergabe. Android-Katalog, Hörstände, Sitzungen und Audio-Bereichsanfragen verwenden die vom Audilege-Client benötigten BookOrbit-kompatiblen Endpunkte. Zum Vergleich wurde auch der bereitgestellte BookOrbit-3.10.0-Quellstand herangezogen. BookOrbit läuft eigenständig weiter, wenn es als separates Profil eingerichtet ist.

Für die Prüfung im Quellordner `python -m unittest discover -s tests -v` verwenden, unter Linux entsprechend `python3`. Für den Audiotest muss FFprobe installiert sein. Die Tests verwenden erfundene Bücher und Konten.

[STAlign](https://www.npmjs.com/package/@storyteller-platform/align) · [Ghost Story](https://www.npmjs.com/package/@storyteller-platform/ghost-story) · [Audiobookshelf](https://github.com/advplyr/audiobookshelf) · [Audilege für Android](https://github.com/yourneeds-app/audilege/releases/latest)

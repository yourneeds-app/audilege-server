"use strict";
const uiLanguage=localStorage.getItem("audilege-ui-language")||(navigator.language.toLowerCase().startsWith("de")?"de":"en");
document.documentElement.lang=uiLanguage;
const strings=Object.fromEntries((
"Audilege · Bibliothek|Audilege · Library\nAnmelden|Sign in\nBenutzername|Username\nPasswort|Password\nBibliothek|Library\nKategorien|Categories\nEntdecken|Discover\nStatistik|Statistics\nVerwaltung|Administration\nServer & Profil|Server & profile\nEinstellungen|Settings\nAngemeldet als|Signed in as\nAbmelden|Sign out\n← Bibliothek|← Library\nTitel hinzufügen|Add title\nNeueste zuerst|Newest first\nÄlteste zuerst|Oldest first\nTitel A–Z|Title A–Z\nTitel Z–A|Title Z–A\nAutor A–Z|Author A–Z\nAus Audiobookshelf importieren|Import from Audiobookshelf\nBenutzer anlegen|Create user\nBenutzer|User\nMedieneingang|Media inbox\nÜberwachter Ordner|Watched folder\nEPUBs und einzelne Hördateien hier ablegen. Für mehrteilige Hörbücher einen Unterordner pro Buch verwenden. Dateien im Unterordner „Podcasts“ erscheinen als einzelne Folgen.|Drop EPUBs and audio files here. Use one subfolder per multi-part audiobook. Audio files in Podcasts appear as individual episodes.\nOrdner ändern|Change folder\nOrdnerpfad auf dem Server|Server folder path\nOrdner übernehmen|Use folder\nJetzt scannen|Scan now\nOptionen|Options\nEPUB laden|Download EPUB\nAudilege-Fassung erstellen|Create read-along\nMetadaten bearbeiten|Edit metadata\nKapitel|Chapters\nMarkierung|Highlighting\nWort|Word\nSatz|Sentence\nAbspielen|Play\nTempo|Speed\nPlayer anzeigen|Show player\n← Zurück|← Back\nWeiter →|Next →\nMedium|Media type\nHörbuch|Audiobook\nHörbücher|Audiobooks\nPodcastdatei|Podcast file\nPodcast aus RSS-Feed|Podcast from RSS feed\nTitel|Title\nAutor oder Podcast|Author or show\nSprache|Language\nDeutsch|German\nEnglisch|English\nFranzösisch|French\nSpanisch|Spanish\nPassende Ausgabe|Companion edition\nEPUB-Datei|EPUB file\nÜbernahme|Import mode\nAutomatisch abonnieren|Subscribe automatically\nEinzelne Folgen importieren|Import individual episodes\nAlle 15 Minuten aktualisieren. Die fünf neuesten Folgen je Abo bleiben auf diesem Server. Ältere Folgen und ihre Mediendateien werden gelöscht.|Check every 15 minutes. Keep the latest five episodes per subscription. Older episodes and their media files are deleted.\nFolgen anzeigen|Show episodes\nSchließen|Close\nHinzufügen|Add\nAudiobookshelf-Statistik|Audiobookshelf statistics\nStarte „Audiobookshelf-Statistik“ aus dem Serverordner und wähle anschließend die exportierte Datei. Deine Historie wird diesem Audilege-Profil zugeordnet.|Run the Audiobookshelf statistics tool from the server folder, then select the exported file. Your history will be linked to this profile.\nStatistikdatei|Statistics file\nImportieren|Import\nKonto aktiv|Account enabled\nAbbrechen|Cancel\nSpeichern|Save\nNach Titel, Autor oder ISBN suchen|Search by title, author or ISBN\nSuchanbieter|Catalogue sources\nTreffer suchen|Find matches\nDateitags auslesen|Read file tags\nCover übernehmen|Use cover\nEigenes Cover|Upload cover\nMetadaten speichern|Save metadata\nBibliothek durchsuchen|Search library\nNavigationsmenü|Navigation menu\nMenü schließen|Close menu\nSortierung|Sort order\nModus wechseln|Switch mode\nPosition im Kapitel|Position in chapter\nPlayer ausblenden|Hide player\nVerwaltungsbereich|Administration area\nBuchcover|Book cover\nAudiocover|Audiobook cover\nVerwendung|Use for\nEingebettetes Cover wiederherstellen|Restore embedded cover\nÜbersicht|Overview\nFortsetzen|Continue\nAlle anzeigen|View all\nReihen|Series\nGenres|Genres\nAutoren|Authors\nNoch keine Einträge vorhanden.|No entries yet.\nNächster Band|Next in series\nNoch nicht begonnen|Not started\nSuchergebnisse|Search results\nKeine passenden Titel gefunden.|No matching titles found.\nWeitere Titel anzeigen|Show more titles\nSendungen|Shows\nPodcastfolgen|Podcast episodes\nStart|Home\nServeradresse|Server address\nInfo & Updates|About & updates\nDeine Bibliothek ist leer.|Your library is empty.\nAls Nächstes|Up next\nSchrift|Font\nBuchschrift|Book typeface\nSystemschrift|System typeface\nSchriftgröße|Font size\nKlein|Small\nMittel|Medium\nGroß|Large\nSehr groß|Extra large\nZeilenabstand|Line spacing\nEng|Tight\nWeit|Wide\nSeitenrand|Margins\nSchmal|Narrow\nBreit|Wide\nLesedarstellung|Reading layout\nBlättern|Pages\nScrollen|Scrolling\nDarstellung|Appearance\nLesen & Mitlesen|Reading & read-along\nWiedergabe|Playback\nLesen|Read\nHören|Listen\nMitlesen|Read along\nFarbschema|Theme\nHell|Light\nDunkel|Dark\nZurückspringen|Skip back\nVorspringen|Skip forward\nRücksprung beim Fortsetzen|Rewind on resume\nAus|Off\nIm Buch suchen|Search this book\nLeseeinstellungen|Reading preferences\nHervorhebung|Highlight style\nHinterlegen|Background\nUnterstreichen|Underline\nZur Hörstelle|Back to audio position\nWerkzeuge|Tools\nLesezeichen|Bookmarks\nSleep-Timer|Sleep timer\nKapitelende|End of chapter\nSuchbegriff|Search term\nSuchen|Search\nTreffer|matches\nStelle merken|Bookmark this passage\nEntfernen|Remove\nNach vorn|Move to front\nDie Warteschlange ist leer.|The queue is empty.\nGespielt / Ungespielt|Played / unplayed\nAls gespielt markieren|Mark as played\nAls ungespielt markieren|Mark as unplayed\nWiedergabestatus|Playback status\nZu „Als Nächstes“ hinzufügen|Add to Up next\nText vorlesen|Read aloud\nAb dieser Stelle vorlesen|Read aloud from here\nStoppen|Stop\nKein lesbarer Abschnitt verfügbar.|No readable section available.\n" +
"Bibliothek prüfen|Review library\nKI-Anbieter & Modell|AI provider & model\nKI-Prüfungen aktivieren|Enable AI reviews\nDie KI-Prüfung ist ausgeschaltet.|AI reviews are disabled.\nUmfang|Scope\nGesamte Bibliothek|Entire library\nPrüfung starten|Start review\nPrüfung läuft|Review running\nPrüfung abgeschlossen|Review completed\nPrüfung unterbrochen|Review interrupted\nVorschlag|Suggestion\nÜbernehmen|Apply\nVerwerfen|Dismiss\nRückgängig|Undo\nAnbieter|Provider\nAPI-Schlüssel|API key\nGespeicherten Schlüssel entfernen|Remove saved key\nModell|Model\nKataloge zum Abgleich|Reference catalogues\nSpeichern & Modelle laden|Save & list models\nMedienordner wählen|Choose media folder\nLaufwerke|Drives\nÜbergeordneter Ordner|Parent folder\nDiesen Ordner wählen|Select folder\nOrdner durchsuchen|Browse folders\nSpeicher & System|Storage & system\nMitlesefassungen|Read-along editions\nKeine offenen Speicherentscheidungen.|No pending storage decisions.\nAlle Dateien behalten|Keep all files\nNur Mitlesefassung behalten …|Keep read-along only …\nOriginale in den Papierkorb verschieben|Move original media to trash\nIn Papierkorb verschieben|Move to trash\nOriginale wiederherstellen|Restore originals\nOriginale erhalten|Originals retained\nSicherung & Wiederherstellung|Backup & restore\nBei beendetem Server: AudilegeServer.exe --backup ZIELORDNER oder --restore SICHERUNG. Eine Wiederherstellung bewahrt den vorherigen Bestand separat auf.|With the server stopped, run AudilegeServer.exe --backup NEW_FOLDER or --restore BACKUP. Restore preserves the previous installation separately.\nNach Updates suchen|Check for updates\nPasswortwiederherstellung per E-Mail|Email account recovery\nE-Mail-Wiederherstellung aktivieren|Enable email recovery\nErreichbare HTTPS-Adresse|Public HTTPS address\nSMTP-Benutzer|SMTP username\nAbsenderadresse|Sender email\nDas SMTP-Passwort wird auf dem Server als AUDILEGE_SMTP_PASSWORD hinterlegt.|Set AUDILEGE_SMTP_PASSWORD on the server to supply the SMTP password.\nGespeichert.|Saved.\nTestempfänger|Test recipient\nTestmail senden|Send test email\nTestmail gesendet.|Test email sent.\nPasswort vergessen?|Forgot password?\nPasswort zurücksetzen|Reset password\nBenutzername oder bestätigte E-Mail-Adresse|Username or verified email\nLink anfordern|Request link\nWenn ein bestätigtes Konto existiert, erhältst du eine E-Mail.|If a verified account exists, you will receive an email.\nE-Mail-Adresse bestätigen|Verify email\nE-Mail-Adresse|Email address\nBestätigungslink senden|Send verification link\nBestätigungslink versandt.|Verification link sent.\nNeues Passwort|New password\nBestätigen|Confirm\n← Buchdetails|← Book details\nZuletzt hinzugefügt|Recently added\nFortschritt|Progress\nBuchinformationen|Book information\nAutor|Author\nReihe|Series\nBand|Volume\nSprecher|Narrator\nErscheinungsjahr|Publication year\nVerlag|Publisher\nSchlagwörter|Tags\nGenres und Schlagwörter|Genres and tags\nBeschreibung|Description\nBearbeiten|Edit\nKonto bearbeiten|Edit account\nNeues Passwort (optional)|New password (optional)\nKeine abonnierten Podcasts.|No podcast subscriptions.\nPodcastordner öffnen →|Open podcast folder →\nNeueste Folgen|Latest episodes\nFolgen|Episodes\nNach Podcast|Browse shows\nAlle Podcasts|All shows\nNoch keine Folgen vorhanden.|No episodes yet.\nAlle Folgen anzeigen|Show all episodes\nWeniger anzeigen|Show less\nMehr anzeigen|Show more\nGehörte Medien|Media played\nHörtage|Listening days\nHörminuten|Minutes listened\nHörminuten der letzten sieben Tage|Minutes listened in the last seven days\n7 Tage gesamt|Last 7 days\nTagesdurchschnitt|Daily average\nLängste Serie|Longest streak\nNeueste Ereignisse|Latest activity\nDein Hörjahr|Your listening year\nJahr auswählen|Choose year\nDatei hochladen|Upload file\nAudiodatei|Audio file\nAbgleich starten|Start alignment\nAufträge|Jobs\nErneut versuchen|Retry\nAlle|All\nMitlesen fortsetzen|Continue read-along\nSenden|Send\nReihen und Bandfolge|Series and volume order\nMetadaten abgleichen|Compare metadata\nE-Book und Hörbuch zuordnen|Match ebook and audiobook\nCover zuordnen|Assign cover roles\nAutoren und Genres|Authors and genres\nDubletten und Reihenlücken|Duplicates and missing volumes\nEigene Bibliothek|Local library\nKeine Gerätesitzungen vorhanden.|No device sessions."
).split("\n").map(x=>x.split("|")));
Object.assign(strings,{"Dieses Gerät":"This device","Gerätestand übernehmen? Abbrechen übernimmt den Serverstand.":"Use the device position? Cancel uses the server position.","Der Stand wurde erneut geändert.":"The position has changed again.","Serverstand übernommen. Öffne den Titel erneut.":"Server position selected. Reopen the title to resume.","Täglich nach Updates suchen":"Check for updates daily","Gerätesitzungen":"Device sessions","Sitzung beenden":"End session","Gespielt":"Played","Dieses Gerät wird abgemeldet.":"This device will be signed out.","Seite":"Page","von":"of","Gelesen von":"Narrated by","Steuerung":"Controls","Installierte Version":"Installed version","Wiedergabegerät":"Playback device"});
Object.assign(strings,{
  "Reihe A–Z":"Series A–Z", "Reihe Z–A":"Series Z–A", "Band":"Volume",
  "Speicherort A–Z":"Storage location A–Z", "Speicherort Z–A":"Storage location Z–A",
  "Reihe anzeigen":"Show series", "Sammlung":"Collection", "Quellordner":"Source folder",
  "Serverbibliothek":"Server library",
  "In Warteschlange": "Queued",
  "Abgleich wird gestartet": "Starting alignment",
  "Dateien prüfen …": "Checking files …",
  "Übertrage ": "Uploading ",
  "Deine Bibliothek ist leer. Füge ein EPUB, ein Hörbuch oder eine Podcastfolge hinzu.": "Your library is empty. Add an EPUB, audiobook or podcast episode.",
  "Vorlesen": "Read aloud",
  "Hörzeit aus Audiobookshelf": "Listening time from Audiobookshelf",
  "Fortschritt aus Audiobookshelf": "Progress from Audiobookshelf",
  "Abgeschlossen": "Finished",
  "Lesen ": "Reading ",
  "Hören ": "Listening ",
  "Die Datei ist größer als 32 MB.": "The file is larger than 32 MB.",
  " neue Hörsitzungen · ": " new listening sessions · ",
  " Fortschrittseinträge": " progress records",
  "Statistik importiert.": "Statistics imported.",
  "Täglicher Ø": "Daily average",
  "Hörserie": "Listening streak",
  "Tag": "day",
  "Tage": "days",
  " Hörtage · ": " listening days · ",
  "Letzte Aktivitäten": "Recent activity",
  "Noch keine Sitzungen erfasst.": "No sessions recorded yet.",
  "Unbekannter Titel": "Unknown title",
  "Bitte den Feed laden und Folgen auswählen.": "Load the feed and select episodes.",
  "Bitte ein Cover bis 5 MB wählen.": "Select a cover up to 5 MB.",
  "Bitte einen Suchanbieter auswählen.": "Select a catalogue source.",
  "Dateitags ausgelesen. Änderungen mit Speichern bestätigen.": "File tags loaded. Save to confirm the changes.",
  "Gewählte Folgen importieren": "Import selected episodes",
  "Hördateien": "Audio files",
  "Keine passenden Folgen gefunden.": "No matching episodes found.",
  "Scan läuft …": "Scan in progress …",
  "Zuletzt geprüft am ": "Last checked on ",
  "Zuletzt geprüft um ": "Last checked at ",
  " Treffer": " matches",
  " Sekunden ": " seconds ",
  " Sekunden.": " seconds.",
  " zurück": " back",
  "zurück": "back",
  "vor": "forward",
  "Kapitel ": "Chapter ",
  " von ": " of ",
  " ist abonniert. Audilege lädt die neuesten Folgen im Hintergrund.": " is subscribed. Audilege downloads new episodes in the background.",
  " – ist abonniert. Audilege lädt die neuesten Folgen im Hintergrund.": " is subscribed. New episodes download in the background.",
  " Modelle": " models",
  "Bisher: ": "Previously: ",
  "Covervorschlag": "Suggested cover",
  "Fehlender Band: ": "Missing volume: ",
  "Anfrage fehlgeschlagen.": "Request failed.",
  "Bitte anmelden.": "Please sign in.",
  "Anmeldung fehlgeschlagen.": "Sign-in failed.",
  "Hierfür sind Administratorrechte erforderlich.": "Administrator access is required.",
  "Link ungültig oder abgelaufen.": "This link is invalid or has expired.",
  "Kein öffentliches Release erreichbar.": "The public release could not be reached.",
  "Ungültige E-Mail-Adresse.": "Invalid email address.",
  "Dieser Benutzername ist bereits vergeben.": "This username is already in use.",
  "Das eigene Administratorkonto muss aktiv bleiben.": "Your administrator account must remain active.",
  "Bitte einen Anbieter aktivieren und ein Modell wählen.": "Enable a provider and select a model first.",
  "Die E-Mail-Wiederherstellung ist nicht eingerichtet.": "Email recovery has not been configured.",
  "Modellserver nicht erreichbar oder ungültige Antwort.": "The model provider could not be reached or returned an invalid response.",
  "Diese Dateien passen nicht zur Rubrik.": "These files do not match the selected media type.",
  "Das Cover wurde geändert.": "The cover has changed.",
  "Dieses Feld wurde inzwischen geändert.": "This field has changed since it was reviewed.",
  "Vorschlag bereits bearbeitet.": "This suggestion has already been reviewed.",
  "Python · SQLite · PyInstaller (Windows). Der optionale Abgleich verwendet STAlign, Ghost Story, FFmpeg und ein separat geladenes Sprachmodell.": "Python · SQLite · PyInstaller (Windows). Optional alignment uses STAlign, Ghost Story, FFmpeg and a separately downloaded language model."
});
Object.assign(strings,{
  " Folge": " episode",
  " Folgen": " episodes",
  " · Deaktiviert": " · Disabled",
  " · In der Bibliothek": " · In library",
  " · Zurzeit nicht erreichbar: ": " · Unavailable: ",
  "Abo beenden": "Unsubscribe",
  "Abo beendet. Die gespeicherten Folgen bleiben in der Bibliothek.": "Subscription ended. Saved episodes remain in your library.",
  "Abonnierte Feeds": "Subscribed feeds",
  "Abschnitt konnte nicht geladen werden.": "Could not load this section.",
  "Automatischer Scan alle ": "Automatic scan every ",
  "Cover konnte nicht gelesen werden.": "Could not read the cover.",
  "Längste Serie":"Longest streak",
  "Aktuelle Serie":"Current streak",
  "Bibliothek direkt einbinden":"Link existing library",
  "Hörbücher und EPUBs am vorhandenen Speicherort nutzen. Der Server liest diesen Ordner und seine Unterordner.":"Use audiobooks and EPUBs at their existing location. The server reads this folder and its subfolders.",
  "Sammlungsordner wählen":"Choose collection folder",
  "Keine Sammlung eingebunden.":"No linked collection.",
  "Überwachung beenden":"Stop monitoring",
  "Erster Abruf steht an": "First update pending",
  "Feed abonnieren": "Subscribe to feed",
  "Folgen werden geladen …": "Loading episodes …",
  "Gelesen von ": "Narrated by ",
  "Importiere Folge ": "Importing episode ",
  "Kataloge werden durchsucht …": "Searching catalogues …",
  "Mehrere Dateien werden nach Dateinamen abgespielt.": "Multiple files play in filename order.",
  "Ohne Podcastangabe": "Unknown show",
  "Originalformatierung konnte nicht geladen werden. Der Abschnitt wird als Text angezeigt.": "Original formatting could not be loaded. Showing plain text.",
  "Scan angefordert.": "Scan requested.",
  "Treffer übernommen. Angaben prüfen und speichern.": "Match selected. Review and save your changes.",
  "“ ist abonniert. Audilege lädt die neuesten Folgen im Hintergrund.": "” subscribed. Latest episodes download in the background."
});
function tr(text){return uiLanguage==="en"&&Object.hasOwn(strings,text)?strings[text]:text;}
function staticLocale(){
  if(uiLanguage!=="en")return;
  const tree=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  for(let n=tree.nextNode();n;n=tree.nextNode()){
    const source=n.nodeValue.trim();if(strings[source])n.nodeValue=n.nodeValue.replace(source,strings[source]);
  }
  for(const e of document.querySelectorAll("[aria-label],[placeholder],[title]"))for(const attr of ["aria-label","placeholder","title"]){
    const v=e.getAttribute(attr);if(v&&strings[v])e.setAttribute(attr,strings[v]);
  }
  document.title=tr(document.title);
}
staticLocale();

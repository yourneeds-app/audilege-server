# Audilege Server 0.4.0

Keep ebooks, audiobooks, synchronized read-along editions and subscribed podcasts on your own computer. A profile shares positions between the web reader and Audilege for Android. BookOrbit can be used through a separate app profile.

## Install

On Windows x64, extract the complete release ZIP and open **Start-Audilege.cmd**. Create an administrator account in the console. The optional CPU alignment worker uses WSL 2, Node.js, FFmpeg and a language model. First-time setup needs internet access, several GB of free disk space and may require a restart. For library playback without worker setup, run `AudilegeServer.exe --ohne-worker --bind 0.0.0.0`.

On Linux, extract the release archive and run `sh start.sh` with Python 3.10 or later. Install Node.js 24, FFmpeg and FFprobe 7 or later and run `sh worker/install.sh` to set up alignment. Pillow is optional for generating smaller shelf thumbnails.

Open port 8472 at the server’s LAN address in a browser, or enter that address when adding a server profile in the Android app. For internet access, serve it through an HTTPS reverse proxy. Choose the interface language at sign-in or in Settings.

## Use the library

Select the server media folder from Administration. The server monitors Ebooks, Audiobooks, Readaloud and Podcasts. Subscribe with a podcast RSS URL to automatically keep the five newest episodes on this server. To create a synchronized edition, open a title and select its companion ebook or audio. After conversion, pick whether to keep the original managed files or move them into the recoverable trash. External source files remain under your control.

Search for titles, authors, series or genres from the main navigation. Open a book to read, listen or follow the real narration, depending on the available media. **Aa** controls the reading layout. Tools provide in-book search, bookmarks, a sleep timer and browser text-to-speech where available.

## Administration

Library checks can use Ollama, OpenAI, Anthropic, Gemini or a compatible endpoint. An administrator selects the provider, model, scope and catalogues. Running a check sends catalogue metadata from the selected titles and nearby matches to that model. Review each suggested change before applying it. A saved API key belongs to its configured endpoint. For a compatible provider using environment variables, set both `AUDILEGE_AI_KEY` and `AUDILEGE_AI_ENDPOINT`.

For account recovery, configure SMTP with STARTTLS and the public HTTPS address. Supply the SMTP password through `AUDILEGE_SMTP_PASSWORD`. Users must verify their email address. A reset link expires after 20 minutes.

With the server stopped, use `--backup NEW_FOLDER` or `--restore BACKUP` with the executable or Python entry point. Restore verifies checksums and keeps the previous data separately. Back up any external media folder and private service credentials separately. Use `--reset-password USERNAME` for local account recovery.

The Windows and Linux packages, release notes and SHA-256 checksums are available from [GitHub Releases](https://github.com/yourneeds-app/audilege-server/releases). Component information is in [THIRD_PARTY.md](THIRD_PARTY.md).

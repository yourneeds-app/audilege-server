# Distributed software and optional downloads

| Component | Distribution and notices |
| --- | --- |
| Python | The Windows executable bundles the CPython runtime. See Lizenzen/Python.txt. Linux uses the system Python. |
| SQLite | Used through Python's sqlite3 module. SQLite is in the public domain. |
| PyInstaller | Used to build and launch the Windows executable. See Lizenzen/PyInstaller.txt for its license and bootloader exception. |
| Pillow | Used for shelf thumbnails when available. The Windows archive includes its license, which also lists the image libraries used in the binary wheel. |
| OpenSSL | CPython on Windows includes OpenSSL 3 under the Apache License 2.0. |
| Audilege artwork | The web interface uses the Audilege player logo and icon from yourneeds. |

## Alignment worker

The downloadable server packages include the Audilege worker scripts and npm lockfile. The installer obtains the following programs and models separately on the administrator's computer.

| Download | Information |
| --- | --- |
| STAlign 0.2.16 | MIT according to the locked package metadata. [Package](https://www.npmjs.com/package/@storyteller-platform/align) |
| Ghost Story 0.3.4 | GPL-3.0 according to the locked package metadata. [Package](https://www.npmjs.com/package/@storyteller-platform/ghost-story) |
| Node.js | Node.js license and notices accompany the runtime. [Project](https://nodejs.org/en/about/previous-releases) |
| FFmpeg and FFprobe | The Windows worker downloads the specified Linux static build. Its license and source references accompany that release. [Build distributor](https://johnvansickle.com/ffmpeg/) |
| QuartzNet15x5 | Language-specific weights are obtained via Ghost Story's model loader. Each model's source and accompanying terms apply to its weights. |
| Ubuntu on WSL | The Windows worker uses an Ubuntu environment. Its packages carry their own license and copyright files. |

The npm lockfile records the exact artifacts and integrity hashes of the worker's dependencies. All library media reside on the user's server. Android AirPlay notices and corresponding sources are distributed with the [Android release](https://github.com/yourneeds-app/audilege/releases).

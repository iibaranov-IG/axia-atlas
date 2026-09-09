# Axia Atlas — Windows preview

## Start the application

1. Download `AxiaAtlas-0.1.0-preview.1-windows-x64.zip` from this project's GitHub Releases.
2. Extract the **entire** archive to a folder you can access. Keep `AxiaAtlas.exe` beside its `_internal` folder.
3. Double-click **AxiaAtlas.exe**. Python and a separate MP3 encoder are not required.
4. On a new standalone installation, create your director account in the Administration window. To join an existing team, use **Connect to Account Server** instead; obtain its address and certificate fingerprint from your director.
5. Choose the broadcast network adapter in the network discovery controls and start discovery. Your computer must have access to the Livewire network.
6. Open **Audio**, select a numbered source, choose your Windows audio output and press **Play**. Use **Record** to save WAV or MP3.

This is a portable folder distribution, not an installer. It does not install a Windows service or configure network/firewall settings. The executable is not code-signed. It was checked on Windows 10 x64; a clean Windows 11 installation has not been tested.

## Data and accounts

The portable build stores its settings, inventory, account data and library under `%LOCALAPPDATA%\AxiaAtlas` for the current Windows user. Recording files go to the folder selected in the Save dialog. Updating the application folder does not replace these saved settings.

The first preview does not import data from a developer source checkout automatically. It ships with no station inventory, saved credentials or default account password.

For multiple computers, follow [ADMINISTRATION.md](ADMINISTRATION.md). The hosting Atlas must remain open. Losing contact with the account server locks a client and stops monitoring/recording when detected. Protect the hosting Windows profile as well as its database; DPAPI-encrypted secrets are tied to that Windows account.

## Before relying on a recording

Inspect reception statistics. Packet gaps in the input can also appear in the recording; a higher MP3 bitrate does not repair missing audio. Loss-free reception and listening acceptance remain open validation items. Supported live audio is currently stereo L24/48 kHz RTP; other formats are not claimed.

## Developer build and verification

Use Windows x64 and Python 3.11 in an isolated environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe build_windows.py
.\dist\AxiaAtlas\AxiaAtlas.exe --self-test build\frozen-check
```

The explicit self-test uses temporary fixtures and loopback servers; inspect `build/frozen-check/self-test.json`. It exercises desktop creation, PDF rendering, embedded web content, protected secrets, HTTPS accounts, resampling and MP3 encoding. It does not certify live network reception or audible output. Independent MP3 decode tests require FFmpeg and FFprobe on the developer PATH; those tests are skipped if the tools are missing. They are not required to run the application.

Source-mode development stores state beside the source; frozen builds use the user data location above. Do not commit your local state, recordings or credentials.

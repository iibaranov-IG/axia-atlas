# Axia Atlas 0.1.0-preview.1

First public source and portable Windows x64 preview. This is a **Pre-release** for evaluation, not a production acceptance announcement.

## Download and launch

Download `AxiaAtlas-0.1.0-preview.1-windows-x64.zip`, extract the whole archive and open `AxiaAtlas.exe`. Keep its `_internal` directory alongside it. No Python installation is required. The archive includes a quick-start guide and dependency notices.

This is a portable folder package, not an installer. It is not code-signed. GitHub's automatically generated **Source code** archives are for developers; they are not the runnable Windows package.

## Included

- Livewire discovery and grouped device/source inventory.
- Embedded device web interfaces and saved credential profiles.
- Stereo L24/48 kHz audio monitoring; WAV/MP3 recording and playback.
- Unified Events, selected-channel Health, observed changes and diagnostic ZIP export.
- Equipment-matched Library with internal PDF viewing.
- Central accounts and per-function engineering permissions.

## Verification

- 46 automated tests passed on Windows 10 x64 / Python 3.11.9, including independent MP3 decoding with FFmpeg/FFprobe.
- The frozen EXE passed its fixture-based desktop, PDF, WebEngine, DPAPI/HTTPS account, resampling and MP3 checks with Python paths removed from its environment.
- Public source exports contain no private deployment state. Verification uses generated fixtures and loopback services.

## Known limitations

- Clean-machine and Windows 11 acceptance have not been performed.
- Loss-free real-network audio reception and subjective listening acceptance remain unresolved; inspect packet-gap statistics before relying on recordings.
- Live input support is currently stereo L24/48 kHz RTP, not every Livewire/AES67 format.
- Scenarios, firmware installation and configuration restoration are not implemented. Tasks remains a placeholder.
- The central account host must keep Atlas open; there is no background Windows service.
- First launch creates a new local setup; private development inventory and passwords are not imported or shipped.

See the README, full product description and Administration guide for details. Original Atlas code is MIT; bundled dependencies retain their respective licenses. Atlas is independent and is not an official Telos Alliance product.

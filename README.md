# Axia Atlas

Free, independent Windows software for broadcast engineers working with Axia Livewire networks. The interface is available in Russian and English. Atlas is not affiliated with or certified by Telos Alliance.

**Current candidate: 0.2.0-rc.1.** This is a release candidate for supervised evaluation, not a claim of certified on-air operation.

[Начало работы на русском](QUICKSTART.ru.md) · [English quick start](QUICKSTART.md) · [Release notes](RELEASE_NOTES.md) · [Product description](PRODUCT.ru.md)

## What Atlas does

- Discovers Livewire announcements on a selected adapter and reads supported device details.
- Shows numbered, enabled audio sources; monitors supported stereo streams and records WAV or MP3.
- Keeps device web interfaces, PDF manuals and reference searches inside the application.
- Maintains equipment cards, a signal map, event history, device syslog and diagnostic reports.
- Provides multi-source health monitoring, configuration snapshots and guarded routing scenarios.
- Keeps local shift schedules, leave and replacements.
- Supports user permissions and reusable encrypted device credential profiles.
- Offers optional local speech transcription and an advisory Virtual Engineer.
- Opens ATLAS Broadcast Player as a separate application module with its own library and process.

Network discovery, monitoring and device commands start only through explicit user actions. Fresh installations contain no station inventory, staff records, saved credentials or private knowledge base. Existing workstation data remains in the same per-user directory.

## Scope and limits

Supported audio reception is the implemented Livewire/RTP PCM path, not universal AES67 certification. Configuration snapshots are not a full restore mechanism. Routing scenarios require preflight and arming; automated continuous failover and firmware installation are not included. Shared accounts do not synchronize equipment cards, shift schedules or scenarios between computers.

Transcription downloads its recognition files after confirmation. The Virtual Engineer needs a separately installed local service and an available profile; it does not execute device commands. Atlas works without either optional component.

## Build and test

Windows x64 and Python 3.11 are used for this candidate. Install requirements-build.txt in a virtual environment, then run:

~~~powershell
python tooling/run_desktop_tests.py
python build_windows.py
dist/release-candidate/AxiaAtlas/AxiaAtlas.exe --self-test state/frozen-acceptance
~~~

The build includes its source hashes and dependency notices. Release acceptance must use the packaged executable, not just the source tests. See RELEASE_NOTES.md for measured results and remaining gaps.

Original Atlas source is MIT licensed. Dependency notices and vendor document rights remain separate: see THIRD_PARTY.md.

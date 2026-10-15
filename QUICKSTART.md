# Quick start — Axia Atlas 0.2.0-rc.1

Extract the entire portable ZIP and open **AxiaAtlas.exe**. Keep its **_internal** directory beside it. Python is not required. The application is unsigned.

Create a technical director account on first launch, or connect to your organization's account server. No default password is supplied. The first-run interface is Russian; **Вид → Язык → English** applies English on the next launch.

Select a broadcast adapter before starting Network discovery. Under Audio choose a numbered enabled source and an output device, then press Play. Recording is a separate action. Library manuals and device web interfaces open inside Atlas. External devices belong in Devices; routing plans belong in Scenarios and require preflight and arming.

The Virtual Engineer and speech recognition are optional. Recognition files download only after confirmation; audio is processed locally. The assistant requires a separate local service and profile.

Before upgrading, close Atlas and back up **%LOCALAPPDATA%\\AxiaAtlas**. Extract the new version to another folder. Existing per-user state is retained; a fresh installation starts empty. Device passwords are protected by Windows for the original user and computer, and cannot simply be copied to another workstation.

Shared accounts do not synchronize equipment, scenarios or shifts. Configuration snapshots do not provide full device restore; firmware installation and continuous automatic failover are not implemented. Read RELEASE_NOTES.md before supervised use.

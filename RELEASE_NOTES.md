# 0.2.0-rc.1 — release candidate

This candidate consolidates the working Atlas application after 0.1.0-preview.1.

## Included

Russian and English interface; Windows/macOS visual styles; collapsible workspace and assistant panes; Network, Audio, Library, Devices and Scenarios; embedded device web pages and PDF manuals; numbered-source listening and WAV/MP3 recording; events/syslog; health monitoring; equipment records; local signal map, shift calendar and guarded routing plans; configuration snapshots; diagnostic exports; local transcription; optional advisory assistant; separate Broadcast Player process.

## Release preparation

Fresh installations no longer receive an embedded studio map or station reference. Existing studio records are retained. Russian is the initial language and a saved language choice is preserved. Network status labels and grouping are translated. Only one normal Atlas process can lock a workspace. Device groups belong to that workspace; malformed group files are preserved and reported. Build tooling includes translations, recognition runtime, dependency versions and source hashes.

## Validation

Acceptance results for this exact candidate are recorded in VALIDATION.json. Tests use synthetic data and loopback services. No production radio equipment is contacted by the acceptance suite.

Acceptance found and fixed a Windows extraction failure caused by unused QML assets with long filenames. The build now excludes those UI modules while retaining the QWidget browser/PDF and native runtime dependencies. Packaging checks a 140-character destination-folder budget. The scenario explanation also wraps within the available panel width.

The packaged self-test now checks workspace navigation, source filtering, equipment/scenario/favorite persistence, Russian/English restart behavior and visual-style persistence. With explicit local speech fixtures it also presses the transcription control and verifies the recognized phrase. The separate host-only multicast harness measures packet accounting, bit-exact WAV output and independently decoded MP3 channels.

## Known limits

- This is an unsigned portable Windows x64 candidate, not an installer or an on-air certification.
- A clean Windows machine and prolonged operation with physical audio/network equipment still require acceptance.
- Supported Livewire/RTP PCM reception is not universal AES67/PTP compatibility.
- Routing needs compatible LWRP devices; preflight does not prove the backup audio is good. Continuous automatic failover is not implemented.
- Configuration snapshots are partial; full restoration and firmware installation are not implemented.
- The account host must keep Atlas running. Equipment cards, scenarios, maps and shifts are local.
- Optional assistant and recognition quality depend on local resources and supplied references. Source tests and runtime loading alone do not establish answer or transcript quality.
- Vendor pages and reference contents retain their original language.
- Broadcast Player is a separate preview module; no claim of unattended playout reliability is made.

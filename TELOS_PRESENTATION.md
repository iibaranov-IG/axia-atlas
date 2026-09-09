# Axia Atlas — technical preview for Telos Alliance

**An independent Windows engineering workspace for Axia and Livewire environments.**

## The operational problem

Broadcast engineers move between device pages, channel lists, audio players, event logs and manuals to understand an incident. Context is easily lost between those tools. Atlas brings these workflows into one desktop workspace while preserving the difference between observed facts and unverified assumptions.

## What the preview provides

- Livewire inventory discovery and bounded, read-only LWRP information queries.
- Grouped equipment and searchable source lists with disabled or unnumbered audio sources excluded.
- Embedded device web interfaces with authentication and saved credential profiles.
- Stereo L24/48 kHz RTP monitoring, output selection and reception measurements.
- WAV recording at 44.1/48 kHz and 16/24 bits; MP3 at 128–320 kbps; recording history and playback.
- A unified application and device Syslog timeline.
- Selected-channel Health, observed configuration changes and diagnostic ZIP export.
- An inventory-matched reference library with internal PDF viewing and curated official downloads.
- Central user accounts, per-function permissions and encrypted device credential profiles for multiple workstations.
- An optional Ollama text panel without autonomous device control.

The interface is English. The project is intended to be released under MIT; dependency licenses remain applicable. No Telos endorsement or certification is claimed.

## Suggested demonstration — 15 minutes

1. Discover equipment on a demonstration network; explain last-observed status and source availability.
2. Find an audio channel, listen, record a short WAV and replay the file.
3. Keep monitoring while opening a device page and its manual inside Atlas.
4. Show reception measurements and a clearly labelled simulated fault or fixture; export a diagnostic package.
5. Demonstrate an engineer account with restricted functions using test credentials.
6. Discuss compatibility, operational limits and the next validation stage.

Use a test network or sanitized fixtures. Do not include station credentials, private addressing, operational recordings or downloaded vendor firmware in the public project. Demonstrated fixtures must be labelled; they are not evidence of hardware compatibility.

## Roadmap

**Scenarios:** computer- or server-stored operational sequences, primary/backup selection, reserve checks, explicit step results and a return procedure. Devices execute supported actions; they are not assumed to store the scenarios.

**Signal Path:** confirmed source-to-destination relationships with provenance.

**Operational resilience:** sustained silence and clipping alarms, multi-channel monitoring, configuration backup and comparison, equipment records, and diagnostic exports with a short test recording.

**Deployment:** standalone distribution validation, an installer, a central-account Windows service and physical multi-workstation acceptance.

## Current limitations to disclose

This is a preview, not a production-certified monitoring system. Loss-free reception and subjective audio acceptance remain unresolved. Support for every Livewire/AES67 audio format is not claimed. Scenarios, configuration restoration and firmware installation are not operational features yet. Central accounts currently require the hosting Atlas application to remain open. Permissions govern access to an entire embedded device UI, not individual controls within vendor pages.

## What we would like to discuss

We would welcome a technical review with Telos Alliance covering:

- Recommended and supported discovery, status and control interfaces across product generations.
- RTP compatibility and a representative hardware validation matrix.
- Supported access to manuals, firmware references and compatibility information.
- Safe operational boundaries for future scenarios and configuration workflows.
- The appropriate way to describe ecosystem compatibility and use product names publicly.

The proposed first step is a technical demonstration and feedback session, followed by an agreed test scope. A commercial arrangement or formal partnership is not assumed.

## Draft introductory message — not sent

**Subject: Axia Atlas — independent engineering workspace for Livewire environments**

Hello Telos Alliance team,

We are developing Axia Atlas, an independent Windows engineering workspace for Axia and Livewire environments, informed by practical radio engineering workflows.

The preview combines equipment discovery, embedded device interfaces, audio monitoring and recording, events, diagnostics, an equipment-matched documentation library, and shared user administration. Our aim is to help engineers retain context while investigating an issue and produce useful evidence for follow-up support.

We plan to publish the project under MIT. We would welcome a short technical demonstration and your feedback on supported interfaces, compatibility validation and the appropriate scope for future operational scenarios.

We will clearly distinguish implemented functions, experimental support and planned work. We are not presenting Atlas as an official or certified Telos Alliance product.

Would your team be interested in a technical review?

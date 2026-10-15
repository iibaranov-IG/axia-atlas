# ATLAS Broadcast Player

## Development frozen — 2026-10-15

Version `0.1.0-preview.2` is frozen at the owner's request. Preserve this module
as a local rehearsal preview; resume development only after a new explicit
owner decision. The delivery sequence below is retained as a deferred backlog,
not an active implementation plan. This freeze applies only to Broadcast Player;
the main Axia Atlas project remains active.

Source snapshot tag: `broadcast-player-v0.1.0-preview.2-frozen`.
See [freeze record and verification](BROADCAST_PLAYER_FREEZE.md) and
[source checksums](BROADCAST_PLAYER_FREEZE.json). This snapshot does not qualify
the player for unattended on-air operation and does not introduce a new binary.

## Implemented preview — 2026-10-13

Independent Windows desktop application, version `0.1.0-preview.2`. The Atlas
Tools menu starts it in a separate process. Closing Atlas does not stop this
module. The module itself needs only PySide6, NumPy and PyAV; it does not start
discovery, contact studio devices or initialize the Virtual Engineer.

Available now:

- Russian by default; English can be selected while playback/import is stopped.
- Station name, local SQLite media catalogue and saved named playlists.
- WAV, MP3, FLAC, OGG, M4A and AAC import with full audio decoding in a cancellable
  worker. One mono/stereo audio track is accepted; video and multichannel are
  rejected. Validation describes readability, not editorial quality or loudness.
- Duplicate imports update the existing catalogue entry. Original files are
  referenced in place and never changed or deleted. Missing or changed files
  require a fresh import; paths and validation status remain visible.
- Search, queue editing and ordering, duration totals, current/next titles.
  Queue contents persist automatically, including repeated items.
- Explicit local output selection, Start, Pause/Resume, Stop, Next, seek,
  volume, remaining time and L/R mixed-signal peak meters before volume control.
  Start begins at the selected queue row, or the first row when none is selected.
- Independent preview device and eight jingle pads with Ctrl+1…Ctrl+8 shortcuts.
  These pads play into **preview**, not into the queue output. Preview is blocked
  while the queue is active on the same device. Starting a queue stops preview
  on a shared output.
- Stop after current; deterministic fail-stop for playback errors, missing media,
  output removal and stalled playback. No implicit skipping or output fallback.
- Timestamped history for import, edits and actual playback start/completion.
  Failed and operator-skipped items are not recorded as completed.
- Single writer per library; every launch starts stopped with no selected outputs.
- Background preparation of the current item and two following items. The first
  two must be ready before playback starts (one with Stop after current). Float
  stereo PCM is stored in disposable files, keeping decode memory bounded.
- One QAudioSink for the complete queue, at a supported stereo output format.
  Files are resampled to this output's rate; mono is duplicated at unity gain.
  The original media and catalogue are preserved. No output fallback is selected.
- Configurable 0–10 second linear crossfade, saved locally. Zero joins decoded
  samples directly without adding silence; authored silence remains. Overlap is
  limited to half of either file. The queue estimate includes these overlaps.
- A prepared/failed/being-prepared indication for the next item. Missing, changed
  or late next material finishes the current file dry, then stops with an error.
- Transition events include the actual overlap duration. Starts/completions follow
  output progress, not preparation. Interrupted outgoing tails are recorded.
  Stop drops buffered audio; Stop after current retains the entire current tail.
  Seek and Stop after current are temporarily locked during a rendered/audible
  transition. Next remains an explicit immediate skip.
- Output underruns and missed feed deadlines stop the queue visibly. A missed
  deadline means continuity is unconfirmed, not a measurement of acoustic loss.

The executable is `dist/AtlasBroadcastPlayer/AtlasBroadcastPlayer.exe`. Keep its
`_internal` folder beside it. Normal state lives in
`%LOCALAPPDATA%/AtlasBroadcastPlayer`; test runs use isolated directories.

Developer entry: `python -m broadcast_player`. Build:
`python tooling/build_player.py`. An optional `--dist-dir` builds alongside an
already running release. Dependencies: `requirements-player.txt`.

### Current limits

This is a **local rehearsal preview**, not a qualified 24/7 on-air release.
Scheduler, relay/reserve,
archive recording, AES67 transmission, Icecast publishing and remote API remain
future deliveries. The station name is one local workspace profile; multiple
station profiles and shared users are not implemented in this module yet.
It does not inherit Atlas accounts for standalone use. The Atlas launch command
is covered by Atlas's existing audio permission.

Local player history is implemented; aggregation into the central Atlas Events
timeline is still pending. Windows output/device behaviour and audible sound on
a real broadcast workstation require separate acceptance beyond RDP testing.
The mixer produces continuous PCM at item boundaries; uninterrupted physical
playout is not certified. The preview feeds a 250 ms requested output buffer
from the Qt event loop, with explicit deadline and underrun checks. A dedicated
real-time feed and long-duration load qualification remain prerequisites for
24/7 broadcast use. Pause suspends the output; seek reopens it and may have a
startup delay. PCM cache space is checked before each decode, with 256 MiB left
free. Very long files can require substantial disk space and preparation time.
No silence trimming, loudness normalization or broadcast limiter is implemented.

### Verification scope

`test_broadcast_player.py` exercises full-file validation, corrupt/truncated media,
changed/missing files, persistence, GUI import/queue/save/reopen, real Qt decoding
of generated stereo WAV and MP3, channel frequencies, pause/resume, sequential
completion, cue isolation, jingle hotkeys, device removal and cancellation of a
pending preparation. Audio is muted in these tests; accepted PCM is measured.
`test_broadcast_player_integration.py` verifies source/frozen launch arguments and
the Atlas menu permission check. These tests do not certify acoustic sound,
clock synchronization, AES67 interoperability or on-air reliability.
`test_broadcast_player_transitions.py` measures sample-for-sample transitions,
stereo integrity, short files, mono resampling, retained silence, cancellation,
stop/seek/skip controls, missing next media and deliberate feed starvation.
Its real-output test compares every sample accepted by the single Windows sink
against the mixer reference. Set `ATLAS_PLAYER_EVIDENCE_DIR` to a disposable
directory to retain its pre-volume WAV, numerical result and RU/EN widget renders.

Initial preview acceptance on 2026-10-13: 12 player tests and 2 Atlas integration tests passed.
The actual standalone Windows EXE was launched and WAV + MP3 were imported
through its graphical file chooser; both completed validation without errors.
RU/EN layouts were rendered and visually inspected. Windows screen capture over
the current remote session timed out; the executable's UI was checked through
its accessibility tree and keyboard input, in addition to Qt widget tests.

Transition acceptance: 27 tests passed across the three player test modules.
The Windows RDP output selected 44,100 Hz stereo. WAV → MP3 with a 500 ms fade
produced 111,662 accepted frames (2.532018 seconds) through one output instance;
maximum sample difference from the reference was 0.0. The saved 16-bit evidence
WAV is a pre-volume tap, not an acoustic or loopback recording. Results and RU/EN
renders are in `state/player-transition-evidence/`; test output is in
`state/broadcast-player-tests.txt`. Physical sound and long-term on-air operation
remain unverified. Preview 2 is packaged alongside the running original at
`dist/player-preview2/AtlasBroadcastPlayer/AtlasBroadcastPlayer.exe`.
The final preview.2 EXE was launched with an isolated test catalogue. Its
accessibility tree confirmed version, queue, crossfade control and stopped state;
the volume control accepted zero. Native selection/click verification was limited
by the remote desktop (`GetCursorPos: access denied`, unavailable coordinate
geometry). Packaged playback has not been certified by that UI run; the full
playback workflow above was verified in source-based Qt GUI tests.

Playback API reference: [Qt QMediaPlayer](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html)
and [decoded audio buffers](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QAudioBufferOutput.html)
for cue; [Qt QAudioSink](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QAudioSink.html)
and [PyAV audio](https://pyav.org/docs/stable/api/audio.html) for prepared queue output.

## Purpose

**ATLAS Broadcast Player** is a standalone Atlas module for managed programme
playout. It is separate from **Audio Monitor**:

- Audio Monitor receives and measures an existing Livewire source.
- Broadcast Player prepares and, only after explicit engineering setup, delivers
  programme audio from local media, scheduled playlists or an approved relay
  source.

The module must never choose an on-air destination, begin playout, change a
device route, publish an Internet stream, or enable automatic reserve mode by
default.

## Confirmed functional reference

The supplied RADIO Player Pro manual describes these functional areas:

- current and next item, playout queue, playlists and media-file properties;
- manual jingle launch and a configurable jingle wall;
- playout archive and application-event history;
- scheduled playlists, imports and profile separation for multiple stations;
- relay from a local input or HTTP(S) audio stream, with optional fallback to
  local content after loss of the relay source;
- configurable output, cue and auxiliary audio devices;
- crossfades, fades, preloading and optional audio processing;
- Internet publishing, current-track metadata, HTTP remote control and alerts;
- DTMF/audio detection for local insertion.

The manual is a feature reference only. Atlas will use its own implementation,
data model and user interface.

## Atlas delivery sequence

### 1. Playout preparation (safe first delivery)

The implemented preview above covers library, queue, local rehearsal and cue pads.
Central event aggregation and multiple profiles remain open within this phase.

- station profile, media library and file validation;
- playlist editor with durations, item types, queue and next-item view;
- preview/cue playback on an explicitly selected local output;
- jingle-wall editor and keyboard mappings, disabled until a cue device is
  selected;
- playout and editing history recorded in Atlas Events;
- no programme output or automation.

### 2. Controlled programme delivery

- explicit output profile linked to an approved equipment card;
- arm/start/stop workflow with clear on-air indication;
- fades and crossfades validated on a test output first;
- archive recording and diagnostic evidence;
- permission and audit requirements for arming and operation.

### 3. Relay, reserve and scheduling

- named relay source with health evidence and loss threshold;
- named local reserve playlist, test workflow and manual return control;
- schedule preview, conflict detection and approval;
- alerts recorded in Atlas Events.

### 4. Integrations only after the endpoint is documented

- Icecast/Shoutcast publishing and metadata;
- RDS metadata;
- HTTP remote control with Atlas authentication;
- DTMF/audio-detector triggers;
- external automation interfaces.

## Information required before programme delivery

1. Which station profile is the first target.
2. Approved programme output device and its physical or Livewire path.
3. Cue output device and who may hear it.
4. Approved reserve content and the conditions for activation/return.
5. Whether Internet publishing, RDS, DTMF or remote control are required.

No live playout path is inferred from a file, a saved playlist or a device card.

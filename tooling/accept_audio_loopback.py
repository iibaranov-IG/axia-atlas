"""Exercise the real receiver via host-only multicast; never use a studio NIC."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import wave

import av
import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QNetworkInterface

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audio_monitor import AudioReceiver
from recording import WaveRecorder, MP3Recorder, float_to_pcm


def run(output, seconds, drop_every=0):
    output.mkdir(parents=True, exist_ok=False)
    interfaces = [i for i in QNetworkInterface.allInterfaces()
                  if i.flags() & QNetworkInterface.IsLoopBack]
    if len(interfaces) != 1:
        raise RuntimeError('Exactly one loopback interface is required; no NIC fallback.')
    source = dict(ip='127.0.0.1', multicast='239.255.42.42', channel=12345)
    receiver = AudioReceiver(source, interfaces[0].index())
    wav = WaveRecorder(output / 'received.wav', source, sample_width=3, input_width=3)
    mp3 = MP3Recorder(output / 'received.mp3', source, bitrate=192, input_width=3)
    receiver.buffer.recording_taps = [wav, mp3]
    # A repeated one-second integer-frequency reference has no boundary clicks.
    t = np.arange(48000, dtype=np.float64) / 48000
    pcm = float_to_pcm(np.column_stack((.4*np.sin(2*np.pi*997*t),
                                       .2*np.sin(2*np.pi*1499*t))), 3)
    network = np.frombuffer(pcm, dtype=np.uint8).reshape(-1, 3)[:, ::-1].tobytes()
    packets = [network[i:i+72] for i in range(0, len(network), 72)]
    total = seconds * 4000
    omitted = 0
    sent = 0
    expected = hashlib.sha256()
    drain_stop = threading.Event()

    def drain():
        # Consume the monitor queue without using an actual sound device.
        while not drain_stop.wait(.01):
            with receiver.buffer.lock:
                receiver.buffer.pcm.clear()

    consumer = threading.Thread(target=drain, daemon=True)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.bind(('127.0.0.1', 0))
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('127.0.0.1'))
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    receiver.start()
    consumer.start()
    start = time.monotonic()
    try:
        deadline = start + 5
        while not receiver.buffer.bound and not receiver.buffer.error and time.monotonic() < deadline:
            time.sleep(.01)
        assert receiver.buffer.bound, receiver.buffer.error or 'Receiver did not bind'
        start = time.monotonic()
        for index in range(total):
            skip = bool(drop_every and index and index < total-1 and index % drop_every == 0)
            offset = (index % 4000)*72
            expected.update(bytes(72) if skip else pcm[offset:offset+72])
            if skip:
                omitted += 1
            else:
                # Both RTP counters wrap; the legacy SSRC field varies per packet.
                header = struct.pack('!BBHII', 0x80, 96, (65500+index)&65535,
                                     (0xffff0000+index*12)&0xffffffff, index+1)
                sender.sendto(header+packets[index % 4000], (source['multicast'], 5004))
                sent += 1
            if index % 8 == 7:
                remaining = start + (index+1)/4000 - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
        deadline = time.monotonic()+3
        while receiver.buffer.packets < sent and time.monotonic() < deadline:
            time.sleep(.01)
    finally:
        sender.close()
        receiver.requestInterruption()
        receiver.wait(3000)
        drain_stop.set()
        consumer.join(1)
        wav_ok, mp3_ok = wav.stop(), mp3.stop()
    stats = dict(seconds=seconds, sent=sent, received=receiver.buffer.packets,
                 injected_missing=omitted, reported_missing=receiver.buffer.gaps,
                 late=receiver.buffer.late, invalid=receiver.buffer.invalid,
                 foreign=receiver.buffer.foreign, overflows=receiver.buffer.overflows,
                 receiver_error=receiver.buffer.error, wav_error=wav.error, mp3_error=mp3.error)
    with wave.open(str(wav.path), 'rb') as recording:
        stats['wav_frames'] = recording.getnframes()
        stats['pcm_sha256'] = hashlib.sha256(recording.readframes(recording.getnframes())).hexdigest()
    stats['expected_pcm_sha256'] = expected.hexdigest()
    frames = []
    with av.open(str(mp3.path)) as media:
        for frame in media.decode(audio=0):
            frames.append(frame.to_ndarray())
    decoded = np.concatenate(frames, axis=1).T
    center = decoded[12000:60000]
    spectra = np.abs(np.fft.rfft(center*np.hanning(len(center))[:, None], axis=0))
    frequencies = np.fft.rfftfreq(len(center), 1/48000)
    stats['mp3_frequencies_hz'] = [float(frequencies[np.argmax(spectra[:,i])]) for i in (0,1)]
    stats['passed'] = (not receiver.isRunning() and wav_ok and mp3_ok
        and not receiver.buffer.error and sent == receiver.buffer.packets
        and omitted == receiver.buffer.gaps and not receiver.buffer.invalid
        and not receiver.buffer.late and not receiver.buffer.foreign
        and stats['wav_frames'] == seconds*48000
        and stats['pcm_sha256'] == stats['expected_pcm_sha256']
        and all(abs(actual-target) <= 2 for actual,target in zip(stats['mp3_frequencies_hz'],(997,1499))))
    (output/'result.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
    print(json.dumps(stats,indent=2),flush=True)
    return stats['passed']


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=60,choices=range(2,601))
    parser.add_argument('--drop-every',type=int,default=0)
    args=parser.parse_args()
    app=QCoreApplication([])
    sys.exit(0 if run(args.output,args.seconds,args.drop_every) else 1)

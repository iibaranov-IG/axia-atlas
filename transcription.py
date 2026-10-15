"""Local speech recognition in a disposable process, independent of live audio."""
import json
import os
import sys
from pathlib import Path

MODEL_REVISION = '536b0662742c02347bc0e980a01041f333bce120'


def timestamp(seconds, separator='.'):
    millis = max(0, round(float(seconds) * 1000))
    seconds, ms = divmod(millis, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}{separator}{ms:03}'


def as_srt(segments):
    return '\n\n'.join(f'{i}\n{timestamp(s["start"], ",")} --> {timestamp(s["end"], ",")}\n{s["text"].strip()}'
                        for i, s in enumerate(segments, 1)) + '\n'


def worker(mode, model_dir, audio='', language='auto'):
    def emit(kind, **data):
        print(json.dumps(dict(kind=kind, **data), ensure_ascii=True), flush=True)
    try:
        # Cache stays beside the application data. No audio is sent to any server.
        os.environ['HF_HOME'] = str(Path(model_dir).parent / 'speech-download-cache')
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
        if mode in ('prepare', 'prepare_transcribe'):
            from faster_whisper.utils import download_model
            download_model('small', output_dir=model_dir, revision=MODEL_REVISION, use_auth_token=False)
            if mode == 'prepare':
                emit('ready')
                return 0
            mode = 'transcribe'
            emit('recognizing')
        if mode != 'transcribe': raise ValueError('Unknown operation')
        path = Path(audio)
        if not path.is_file(): raise ValueError('Audio file is unavailable')
        if path.suffix.lower() not in {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.aac', '.wma'}:
            raise ValueError('Unsupported audio format')
        from faster_whisper import WhisperModel
        model = WhisperModel(str(model_dir), device='cpu', compute_type='int8', cpu_threads=2,
                             num_workers=1, local_files_only=True)
        segments, info = model.transcribe(str(path), language=None if language == 'auto' else language,
                                         beam_size=5, vad_filter=True, condition_on_previous_text=False)
        emit('language', language=info.language, duration=info.duration)
        count = 0
        for segment in segments:
            if not segment.text.strip(): continue
            emit('segment', start=segment.start, end=segment.end, text=segment.text.strip(),
                 progress=min(99, int(segment.end / max(info.duration, .01) * 100)))
            count += 1
        emit('done', count=count)
        return 0
    except Exception as exc:
        emit('error', message=str(exc))
        return 1


def worker_main(args):
    # A windowed PyInstaller executable starts with Python streams set to None.
    # QProcess supplies dedicated pipes; attach only this child to those handles.
    if os.name == 'nt' and sys.stdout is None:
        import ctypes
        import msvcrt
        from ctypes import wintypes
        get_handle = ctypes.windll.kernel32.GetStdHandle
        get_handle.argtypes = [wintypes.DWORD]
        get_handle.restype = wintypes.HANDLE
        for attr, number in (('stdout', -11), ('stderr', -12)):
            handle = get_handle(number)
            if handle and handle != wintypes.HANDLE(-1).value:
                fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
                setattr(sys, attr, os.fdopen(fd, 'w', encoding='utf-8', buffering=1))
    return worker(*args)

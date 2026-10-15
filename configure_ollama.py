"""Maintainer setup for the existing local Ollama installation; never downloads a base model."""
import json
import urllib.request
from ollama_profile import MODEL, BASE_MODEL, creation_payload


def request(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request('http://127.0.0.1:11434/api/' + path,
                                 data=body, headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as response:
        return json.load(response)


def configure():
    names = {m['name'] for m in request('tags')['models']}
    if MODEL in names:
        actual = request('show', {'model': MODEL})
        if actual.get('system', '').strip() != creation_payload()['system'].strip():
            raise RuntimeError('An existing profile differs. It was preserved; review before replacing it.')
        return {'status': 'existing', 'model': MODEL, 'profile': actual}
    if BASE_MODEL not in names:
        raise RuntimeError('Required local base model is absent. No model was downloaded.')
    result = request('create', creation_payload())
    if result.get('status') != 'success':
        raise RuntimeError('Ollama did not confirm profile creation.')
    return {'status': 'created', 'model': MODEL, 'profile': request('show', {'model': MODEL})}


if __name__ == '__main__':
    result = configure()
    print(json.dumps({k: result[k] for k in ('status', 'model')}, ensure_ascii=False))

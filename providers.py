"""Các provider cùng một interface. Không chứa agent loop."""
import json
import os
from pathlib import Path
import math
import sys
import threading
import time
import urllib.error
import urllib.request


def load_env(path=None):
    """Read simple .env assignments; existing process variables take priority."""
    env_path = Path(path) if path is not None else Path(__file__).resolve().parent / '.env'
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        name, separator, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if not separator or not name:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].rstrip()
        os.environ.setdefault(name, value)


CONFIG = {
    'groq': ('GROQ_API_KEY', 'https://api.groq.com/openai/v1/chat/completions'),
    'openai': ('OPENAI_API_KEY', 'https://api.openai.com/v1/chat/completions'),
    'gemini': ('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'),
    'openrouter': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1/chat/completions'),
    'anthropic': ('ANTHROPIC_API_KEY', 'https://api.anthropic.com/v1/messages'),
}



_GROQ_SCHEDULE = {}
_GROQ_LOCK = threading.Lock()
_GROQ_MAX_RETRIES = 4
_GROQ_RETRY_BUDGET = 180.0


def _wait_for_groq(slot, interval):
    # All Provider instances, including the judge, share the same schedule.
    with _GROQ_LOCK:
        delay = max(0.0, _GROQ_SCHEDULE.get(slot, 0.0) - time.monotonic())
        if delay:
            time.sleep(delay)
        _GROQ_SCHEDULE[slot] = time.monotonic() + interval


def _defer_groq(slot, delay):
    with _GROQ_LOCK:
        _GROQ_SCHEDULE[slot] = max(
            _GROQ_SCHEDULE.get(slot, 0.0), time.monotonic() + delay)


def _retry_delay(headers, attempt):
    value = headers.get('Retry-After') if headers else None
    try:
        delay = float(value)
        if math.isfinite(delay) and delay >= 0:
            return delay
    except (TypeError, ValueError):
        pass
    return min(30.0 * (2 ** attempt), 60.0)


def post_json(url, headers, payload):
    is_groq = url.startswith('https://api.groq.com/')
    interval = float(os.getenv('GROQ_MIN_INTERVAL', '3')) if is_groq else 0.0
    if not math.isfinite(interval) or interval < 0:
        raise ValueError('GROQ_MIN_INTERVAL must be a finite number >= 0.')
    slot = (url, payload.get('model'))
    budget = float(os.getenv('GROQ_RETRY_BUDGET', str(_GROQ_RETRY_BUDGET))) if is_groq else _GROQ_RETRY_BUDGET
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError('GROQ_RETRY_BUDGET must be a finite number > 0.')
    deadline = time.monotonic() + budget
    retries = _GROQ_MAX_RETRIES if is_groq else 0
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json',
                 'User-Agent': 'StatusAgentLab/1.0', **headers})
    for attempt in range(retries + 1):
        if is_groq:
            _wait_for_groq(slot, interval)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if is_groq and exc.code == 429 and attempt < retries:
                delay = _retry_delay(exc.headers, attempt)
                if time.monotonic() + delay <= deadline:
                    exc.close()
                    print(
                        f'Groq HTTP 429: waiting {delay:.1f}s before retry '
                        f'{attempt + 1}/{retries}.',
                        file=sys.stderr, flush=True)
                    _defer_groq(slot, delay)
                    continue
            # Do not print response bodies, account identifiers, or API keys.
            raise RuntimeError(
                f'Provider tra HTTP {exc.code}; kiem tra model, key va quota.'
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f'Khong ket noi duoc provider: {exc.reason}.'
            ) from exc


class Provider:
    """complete(messages, schemas) -> {message, calls, finish, usage}.

    messages: system/user/assistant/tool theo format Chat Completions. message trả về
    cần được append nguyên vẹn; tool result có role, tool_call_id, content (JSON string).
    """
    def __init__(self, name, model):
        if name not in CONFIG:
            raise ValueError(f'Provider không hợp lệ: {name}')
        if not model:
            raise ValueError('Cần đặt MODEL là model có hỗ trợ tool calling.')
        self.name, self.model = name, model
        key_name, self.url = CONFIG[name]
        self.key = os.getenv(key_name)
        if not self.key:
            raise ValueError(f'Thiếu {key_name}; xem README.md.')

    def complete(self, messages, schemas):
        if self.name == 'anthropic':
            return self._anthropic(messages, schemas)
        payload = {'model': self.model, 'messages': messages}
        if schemas:
            payload['tools'] = schemas
        data = post_json(self.url, {'Authorization': f'Bearer {self.key}'}, payload)
        choice = data['choices'][0]
        message = choice['message']
        calls = [{'id': c['id'], 'name': c['function']['name'], 'arguments': c['function']['arguments']} for c in message.get('tool_calls', [])]
        return {'message': message, 'calls': calls, 'finish': choice.get('finish_reason'), 'usage': data.get('usage', {})}

    def _anthropic(self, messages, schemas):
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        native = []
        for m in messages:
            if m['role'] == 'system':
                continue
            if m['role'] == 'assistant':
                blocks = []
                if m.get('content'):
                    blocks.append({'type': 'text', 'text': m['content']})
                for call in m.get('tool_calls', []):
                    blocks.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'], 'input': json.loads(call['function']['arguments'])})
                native.append({'role': 'assistant', 'content': blocks})
            elif m['role'] == 'tool':
                block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}
                if native and native[-1]['role'] == 'user' and isinstance(native[-1]['content'], list):
                    native[-1]['content'].append(block)
                else:
                    native.append({'role': 'user', 'content': [block]})
            else:
                native.append({'role': 'user', 'content': m['content']})
        tools = [{'name': x['function']['name'], 'description': x['function']['description'], 'input_schema': x['function']['parameters']} for x in schemas]
        payload = {'model': self.model, 'max_tokens': 1024, 'system': system, 'messages': native}
        if tools:
            payload['tools'] = tools
        data = post_json(self.url, {'x-api-key': self.key, 'anthropic-version': '2023-06-01'}, payload)
        blocks = data['content']
        calls = [{'id': b['id'], 'name': b['name'], 'arguments': json.dumps(b['input'], ensure_ascii=False)} for b in blocks if b['type'] == 'tool_use']
        text = '\n'.join(b['text'] for b in blocks if b['type'] == 'text')
        message = {'role': 'assistant', 'content': text or None}
        if calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]
        reason = {'end_turn': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length'}.get(data.get('stop_reason'), data.get('stop_reason'))
        return {'message': message, 'calls': calls, 'finish': reason, 'usage': data.get('usage', {})}

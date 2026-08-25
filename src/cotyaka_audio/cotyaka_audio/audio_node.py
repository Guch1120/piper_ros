import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class AudioNode(Node):
    """Audio output using cached fixed WAV files and local VOICEVOX TTS."""

    def __init__(self):
        super().__init__('audio_node', namespace='/cotyaka')
        self.declare_parameter('cache_dir', '/opt/cotyaka/audio/cache')
        self.declare_parameter(
            'messages_file', '/opt/cotyaka/audio/config/startup_messages.json')
        self.declare_parameter('voicevox_url', 'http://127.0.0.1:50021')
        self.declare_parameter('speaker_id', 1)
        self.declare_parameter('speed_scale', 1.0)
        self.declare_parameter('audio_device', 'default')
        self.declare_parameter('max_tts_chars', 300)
        self.declare_parameter('request_timeout_sec', 10.0)
        self.declare_parameter('voicevox_retry_count', 15)
        self.declare_parameter('voicevox_retry_interval_sec', 1.0)

        self.create_subscription(
            String, '/cotyaka/audio/play_fixed', self._on_fixed, 10)
        self.create_subscription(
            String, '/cotyaka/audio/speak', self._on_tts, 10)

        self._messages = self._load_messages()
        self._queue = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()
        self.get_logger().info(
            'Audio node ready: fixed WAV cache + local VOICEVOX TTS')

    def _load_messages(self):
        path = str(self.get_parameter('messages_file').value)
        try:
            with open(path, 'r', encoding='utf-8') as stream:
                data = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            self.get_logger().error(f'Failed to load fixed messages: {exc}')
            return {}

        if not isinstance(data, dict):
            self.get_logger().error('Fixed messages file must contain a JSON object')
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def _on_fixed(self, msg: String) -> None:
        self._queue.put(('fixed', msg.data.strip()))

    def _on_tts(self, msg: String) -> None:
        self._queue.put(('tts', msg.data.strip()))

    def _run_worker(self) -> None:
        while rclpy.ok():
            try:
                kind, value = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if kind == 'fixed':
                    self._play_fixed(value)
                else:
                    self._speak(value)
            except Exception as exc:
                self.get_logger().error(f'Audio request failed: {exc}')
            finally:
                self._queue.task_done()

    def _play_fixed(self, key: str) -> None:
        text = self._messages.get(key)
        if text is None:
            self.get_logger().warning(f'Unknown fixed audio key: {key}')
            return

        cache_dir = os.path.abspath(str(self.get_parameter('cache_dir').value))
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.abspath(os.path.join(cache_dir, f'{key}.wav'))
        if not path.startswith(cache_dir + os.sep):
            raise RuntimeError('Invalid fixed audio cache path')

        if not os.path.isfile(path):
            self.get_logger().info(
                f'No cached WAV for {key}; generating it with VOICEVOX')
            wav = self._synthesize_with_retry(text)
            tmp_path = f'{path}.tmp'
            with open(tmp_path, 'wb') as stream:
                stream.write(wav)
            os.replace(tmp_path, path)

        self.get_logger().info(f'Playing fixed WAV: {path}')
        self._play_wav(path)

    def _speak(self, text: str) -> None:
        if not text:
            return
        max_chars = int(self.get_parameter('max_tts_chars').value)
        text = text[:max_chars]
        wav = self._synthesize_with_retry(text)

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp.write(wav)
            temp_path = tmp.name
        try:
            self._play_wav(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _synthesize_with_retry(self, text: str) -> bytes:
        retry_count = int(self.get_parameter('voicevox_retry_count').value)
        retry_interval = float(
            self.get_parameter('voicevox_retry_interval_sec').value)
        last_error = None
        for attempt in range(1, retry_count + 1):
            try:
                return self._synthesize(text)
            except (OSError, RuntimeError, urllib.error.URLError) as exc:
                last_error = exc
                self.get_logger().warning(
                    f'VOICEVOX request failed ({attempt}/{retry_count}): {exc}')
                if attempt < retry_count:
                    time.sleep(retry_interval)
        raise RuntimeError(f'VOICEVOX is unavailable: {last_error}')

    def _synthesize(self, text: str) -> bytes:
        base_url = str(self.get_parameter('voicevox_url').value).rstrip('/')
        speaker_id = int(self.get_parameter('speaker_id').value)
        timeout = float(self.get_parameter('request_timeout_sec').value)

        query_params = urllib.parse.urlencode({
            'text': text,
            'speaker': speaker_id,
        })
        query_request = urllib.request.Request(
            f'{base_url}/audio_query?{query_params}',
            data=b'',
            method='POST',
        )
        with urllib.request.urlopen(query_request, timeout=timeout) as response:
            query = json.loads(response.read().decode('utf-8'))

        query['speedScale'] = float(self.get_parameter('speed_scale').value)
        synthesis_body = json.dumps(query, ensure_ascii=False).encode('utf-8')
        synthesis_request = urllib.request.Request(
            f'{base_url}/synthesis?speaker={speaker_id}',
            data=synthesis_body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(synthesis_request, timeout=timeout) as response:
            wav = response.read()

        if not wav.startswith(b'RIFF'):
            raise RuntimeError('VOICEVOX returned invalid WAV data')
        return wav

    def _play_wav(self, path: str) -> None:
        device = str(self.get_parameter('audio_device').value)
        command = ['aplay', '-q']
        if device:
            command.extend(['-D', device])
        command.append(path)
        subprocess.run(command, check=True)


def main(args=None):
    rclpy.init(args=args)
    node = AudioNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

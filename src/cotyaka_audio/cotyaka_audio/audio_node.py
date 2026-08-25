import os
import queue
import subprocess
import tempfile
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

try:
    from gtts import gTTS
except ImportError:
    gTTS = None


class AudioNode(Node):
    """Two-path audio output: fixed MP3 assets and arbitrary TTS."""

    FIXED_FILES = {
        'startup_full': 'startup_full.mp3',
        'startup_piper_only': 'startup_piper_only.mp3',
        'startup_kobuki_only': 'startup_kobuki_only.mp3',
        'startup_no_robot': 'startup_no_robot.mp3',
    }

    def __init__(self):
        super().__init__('audio_node', namespace='/cotyaka')
        self.declare_parameter('audio_dir', '/opt/cotyaka/audio')
        self.declare_parameter('tts_lang', 'ja')
        self.declare_parameter('tts_fallback_engine', 'espeak-ng')
        self.declare_parameter('max_tts_chars', 300)

        self.create_subscription(String, '/cotyaka/audio/play_mp3', self._on_mp3, 10)
        self.create_subscription(String, '/cotyaka/audio/speak', self._on_tts, 10)

        self._queue = queue.Queue()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()
        self.get_logger().info('Audio node ready: MP3 + TTS')

    def _on_mp3(self, msg: String) -> None:
        key, _, fallback = msg.data.partition('|')
        self._queue.put(('mp3', key.strip(), fallback.strip()))

    def _on_tts(self, msg: String) -> None:
        self._queue.put(('tts', msg.data.strip(), ''))

    def _run_worker(self) -> None:
        while rclpy.ok():
            try:
                kind, value, fallback = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if kind == 'mp3':
                    self._play_fixed(value, fallback)
                else:
                    self._speak(value)
            except Exception as exc:
                self.get_logger().error(f'Audio request failed: {exc}')
            finally:
                self._queue.task_done()

    def _play_fixed(self, key: str, fallback: str) -> None:
        filename = self.FIXED_FILES.get(key)
        if filename is None:
            self.get_logger().warning(f'Unknown fixed audio key: {key}')
            if fallback:
                self._speak(fallback)
            return

        audio_dir = os.path.abspath(str(self.get_parameter('audio_dir').value))
        path = os.path.abspath(os.path.join(audio_dir, filename))
        if not path.startswith(audio_dir + os.sep):
            raise RuntimeError('Invalid audio path')

        if os.path.isfile(path):
            self.get_logger().info(f'Playing fixed MP3: {path}')
            subprocess.run(['mpg123', '-q', path], check=True)
            return

        self.get_logger().warning(f'Fixed MP3 not found: {path}; using TTS fallback')
        if fallback:
            self._speak(fallback)

    def _speak(self, text: str) -> None:
        if not text:
            return
        max_chars = int(self.get_parameter('max_tts_chars').value)
        text = text[:max_chars]
        lang = str(self.get_parameter('tts_lang').value)

        if gTTS is not None:
            try:
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                    temp_path = tmp.name
                try:
                    gTTS(text=text, lang=lang).save(temp_path)
                    subprocess.run(['mpg123', '-q', temp_path], check=True)
                    return
                finally:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
            except Exception as exc:
                self.get_logger().warning(f'gTTS failed; using offline fallback: {exc}')

        engine = str(self.get_parameter('tts_fallback_engine').value)
        if engine != 'espeak-ng':
            raise RuntimeError('No available TTS engine')
        subprocess.run(['espeak-ng', '-v', lang, text], check=True)


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

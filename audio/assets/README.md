# Cotyaka fixed audio assets

起動時など、内容が固定されている通知はここに MP3 を配置すると TTS より優先して再生されます。

対応するファイル名:

- `startup_full.mp3`: Piper + Kobuki の両方で起動
- `startup_piper_only.mp3`: Piper のみで起動
- `startup_kobuki_only.mp3`: Kobuki のみで起動
- `startup_no_robot.mp3`: どちらのロボットも検出できず監視のみ起動

MP3 が存在しない場合、`cotyaka_audio` は System Monitor から渡された定型文を TTS で読み上げます。

TTS は gTTS を優先し、利用できない場合は `espeak-ng` の日本語音声へフォールバックします。

from faster_whisper import WhisperModel

model = WhisperModel("base", device="cpu", compute_type="int8")


def transcribe(audio_path: str) -> str:
    segments, info = model.transcribe(
        audio_path,
        language="zh",
        initial_prompt="以下是普通话的句子。",
    )
    return "".join(seg.text for seg in segments)


if __name__ == '__main__':
    text = transcribe("test_Xiaoyi.mp3")
    print(text)
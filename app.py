import streamlit as st
import asyncio
import edge_tts
from pathlib import Path
from faster_whisper import WhisperModel

st.set_page_config(page_title="贪心", page_icon="🧠")
st.title("🧠 贪心")
st.caption("哼，又来了？说吧。")


@st.cache_resource
def get_agent():
    from my_agent import run_agent
    return run_agent


@st.cache_resource
def get_asr_model():
    return WhisperModel("base", device="cpu", compute_type="int8")


run_agent = get_agent()
asr_model = get_asr_model()

VOICE = "zh-CN-XiaoyiNeural"


def transcribe(audio_path: str) -> str:
    segments, _ = asr_model.transcribe(audio_path, language="zh", initial_prompt="以下是普通话的句子。")
    return "".join(seg.text for seg in segments)


async def _tts(text: str, output: str) -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output)


def speak(text: str, output: str = "reply.mp3") -> str:
    asyncio.run(_tts(text, output))
    return output


if "history" not in st.session_state:
    st.session_state.history = []

for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 语音输入
audio = st.audio_input("🎤 按一下，说话")
if audio:
    with st.spinner("识别中..."):
        # 保存录音
        audio_path = "input.wav"
        Path(audio_path).write_bytes(audio.read())
        prompt = transcribe(audio_path)
    st.write(f"你说：{prompt}")

    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("贪心思考中..."):
            answer, new_history = run_agent(prompt, st.session_state.history)
            st.write(answer)
        with st.spinner("生成语音..."):
            audio_file = speak(answer)
            st.audio(audio_file)

    st.session_state.history = new_history

# 文字输入
if prompt := st.chat_input("或者打字..."):
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("贪心思考中..."):
            answer, new_history = run_agent(prompt, st.session_state.history)
            st.write(answer)
        with st.spinner("生成语音..."):
            audio_file = speak(answer)
            st.audio(audio_file)

    st.session_state.history = new_history
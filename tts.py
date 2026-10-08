import asyncio
import edge_tts

VOICE = "zh-CN-XiaoyiNeural"


async def text_to_speech(text: str, output: str = "output.mp3") -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output)


if __name__ == '__main__':
    asyncio.run(text_to_speech("哼，杂鱼，测试一下。"))
    print("已生成 output.mp3")
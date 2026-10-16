/**
 * 语音实现（占位）
 *
 * ⚠️ 为什么这里是空的：
 *
 * 鸿蒙语音 API（@kit.CoreSpeechKit）**不支持 ArkUI-X 跨平台**，
 * 静态引用会报 11706007 can't support crossplatform application。
 * 而动态引用又会被 arkts-no-ns-as-obj / arkts-no-structural-typing 拦住。
 *
 * 详细排查过程见 app/VOICE.md（穷举了 9 种写法，全部失败）。
 *
 * 结论：在 ArkUI-X 工程里无法使用鸿蒙语音。
 * 需要语音时，用鸿蒙单端工程（见 VOICE.md 的方案 C）。
 *
 * 此类的作用：让共享层有统一的注入点，
 * 其他平台（Android）走 NoopVoiceService 降级，UI 自动隐藏语音入口。
 */

import { IVoiceService, VoiceAvailability, AsrCallbacks } from './Voice';

export class HarmonyVoiceService implements IVoiceService {
  availability(): VoiceAvailability {
    return {
      asr: false,
      tts: false,
      reason: '跨端版本不含语音（鸿蒙语音 API 不支持 ArkUI-X），可用打字'
    };
  }

  async startAsr(cb: AsrCallbacks): Promise<boolean> {
    cb.onError('跨端版本不含语音识别');
    return false;
  }

  stopAsr(): void {
  }

  cancelAsr(): void {
  }

  async speak(_text: string, _onDone?: () => void, onError?: (m: string) => void): Promise<boolean> {
    if (onError) {
      onError('跨端版本不含语音合成');
    }
    return false;
  }

  stopSpeak(): void {
  }

  release(): void {
  }
}

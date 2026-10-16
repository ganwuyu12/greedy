/**
 * 语音实现（HarmonyOS 单端版本）
 *
 * ✅ 这个版本可以用**静态 import**，因为本工程是鸿蒙单端，
 *    不受 ArkUI-X 的跨平台检查限制。
 *
 * 对比跨端工程（greedy-app）：
 *   那边静态 import 会报 11706007 can't support crossplatform application，
 *   动态 import 又被 arkts-no-ns-as-obj / arkts-no-structural-typing 拦住，
 *   所以那边**无法使用语音**，只能走 NoopVoiceService 降级。
 *
 * 这正是「双工程」方案存在的原因：
 *   跨端工程满足「一套代码多端」，单端工程满足「鸿蒙语音链路」。
 *
 * 能力边界（读自 SDK 接口定义）：
 *   ASR：仅 zh-CN、仅离线、支持最多 200 个热词
 *   TTS：person 13 = 凌小杉（女声，与「贪心」人格对得上）、仅离线
 */

import { speechRecognizer, textToSpeech } from '@kit.CoreSpeechKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { IVoiceService, VoiceAvailability, AsrCallbacks, ALGO_HOTWORDS,
         stripMarkdown } from './Voice';

export class HarmonyVoiceService implements IVoiceService {
  private asrEngine: speechRecognizer.SpeechRecognitionEngine | null = null;
  private ttsEngine: textToSpeech.TextToSpeechEngine | null = null;
  private lastError: string = '';
  /** 当前识别会话 ID（finish / cancel 都要它） */
  private sessionId: string = '';

  availability(): VoiceAvailability {
    let asr = false;
    let tts = false;
    try {
      asr = canIUse('SystemCapability.AI.SpeechRecognizer');
    } catch (e) {
      asr = false;
    }
    try {
      tts = canIUse('SystemCapability.AI.TextToSpeech');
    } catch (e) {
      tts = false;
    }
    let reason = '';
    if (!asr && !tts) {
      reason = '本设备不支持语音能力，可以用打字';
    } else if (!asr) {
      reason = '本设备不支持语音识别，可以用打字';
    } else if (!tts) {
      reason = '本设备不支持语音合成，回答不会朗读';
    }
    return { asr, tts, reason };
  }

  // ------------------------------------------------------------ ASR

  async startAsr(cb: AsrCallbacks): Promise<boolean> {
    try {
      if (this.asrEngine === null) {
        const params: speechRecognizer.CreateEngineParams = {
          language: 'zh-CN',
          online: 1,                      // 1 = 离线（当前只支持离线）
          extraParams: {
            'locate': 'CN',
            'recognizerMode': 'short'
            // ⚠️ 热词（sysGeneralLexicon）暂时不加。
            //
            // 实测报错：createEngine code = 601
            // 日志：CheckLexicons: lexicons length exceeds limit, length: 21
            //       并伴随 not system app! reset config to default
            //
            // 查证：热词表本身合规（79 个词，每个 2–7 字，
            //       文档说限「最多 200 个、每个 2–20 字」，都满足）。
            // 所以 601 更可能来自「非系统应用不允许配热词」这条限制。
            //
            // 热词只是识别率的优化项，不是必需项——先保证功能可用。
            // 真机 + 系统应用签名时可以再试；热词表见 Voice.ets 的 ALGO_HOTWORDS。
          }
        };
        this.asrEngine = await speechRecognizer.createEngine(params);
      }
      const engine = this.asrEngine;

      // 上一次识别没结束时直接 start 会报状态错，先取消
      if (this.sessionId.length > 0) {
        try {
          engine.cancel(this.sessionId);
        } catch (e) {
          // 没有进行中的会话时 cancel 抛错是正常的
        }
      }

      const listener: speechRecognizer.RecognitionListener = {
        onStart: (sessionId: string, eventMessage: string): void => {
        },
        onEvent: (sessionId: string, eventCode: number, eventMessage: string): void => {
        },
        onResult: (sessionId: string, result: speechRecognizer.SpeechRecognitionResult): void => {
          const text = result.result ?? '';
          if (result.isFinal === true) {
            cb.onFinal(text);
          } else {
            cb.onPartial(text);
          }
        },
        onComplete: (sessionId: string, eventMessage: string): void => {
        },
        onError: (sessionId: string, errorCode: number, errorMessage: string): void => {
          cb.onError(HarmonyVoiceService.asrErrorText(errorCode, errorMessage));
        }
      };
      engine.setListener(listener);

      // audioInfo 四个字段都是必填（读自 SDK 定义）
      const audioInfo: speechRecognizer.AudioInfo = {
        audioType: 'pcm',        // 当前只支持 pcm
        sampleRate: 16000,       // 当前只支持 16000
        soundChannel: 1,         // 当前只支持单声道
        sampleBit: 16            // 当前只支持 16 位
      };
      this.sessionId = `greedy_${Date.now()}`;
      const startParams: speechRecognizer.StartParams = {
        sessionId: this.sessionId,
        audioInfo: audioInfo
      };
      engine.startListening(startParams);
      return true;
    } catch (e) {
      // 把 code 也带出来——只有 message 时经常是空串（实测显示成「msg」），
      // 错误码才是定位问题的关键
      const err = e as BusinessError;
      const code: number = err.code ?? -1;
      const msg: string = err.message ?? String(e);
      this.lastError = `code=${code} msg=${msg}`;
      cb.onError(`启动识别失败（${HarmonyVoiceService.explainCode(code)}）`);
      return false;
    }
  }

  /**
   * 把错误码翻译成可操作的建议
   *
   * 401 = 权限没给；801 = 能力不支持。
   */
  private static explainCode(code: number): string {
    if (code === 401) {
      return '401 没有录音权限，请在系统设置里允许麦克风';
    }
    if (code === 801) {
      return '801 设备不支持该能力';
    }
    return `code=${code}`;
  }

  stopAsr(): void {
    if (this.asrEngine === null || this.sessionId.length === 0) {
      return;
    }
    try {
      this.asrEngine.finish(this.sessionId);
    } catch (e) {
      // 没在识别时调用会抛错
    }
  }

  /**
   * 结束并**保证回调一定被触发**
   *
   * 为什么需要：如果设备没有麦克风（模拟器常见），
   * 引擎收不到音频就不会产生 onResult/onComplete，
   * 界面会永远卡在「正在听…」。
   * 所以这里做一个兜底：等一小段时间，没等到回调就主动报错让 UI 复位。
   */
  finishWithFallback(onTimeout: () => void, waitMs: number = 2500): void {
    this.stopAsr();
    setTimeout(() => {
      // 若引擎已释放或已回调过，说明正常结束，不用兜底
      if (this.asrEngine === null) {
        return;
      }
      onTimeout();
    }, waitMs);
  }

  cancelAsr(): void {
    if (this.asrEngine === null || this.sessionId.length === 0) {
      return;
    }
    try {
      this.asrEngine.cancel(this.sessionId);
    } catch (e) {
      // 同上
    }
  }

  /** 把错误码翻译成人话——直接抛错误码用户看不懂 */
  private static asrErrorText(code: number, msg: string): string {
    if (code === 1001) {
      return '没有录音权限，请在系统设置里允许麦克风';
    }
    if (code === 1002) {
      return '麦克风被占用';
    }
    if (code === 1003) {
      return '没听清，再说一次？';
    }
    if (code === 1004) {
      return '识别服务不可用';
    }
    return `识别出错（${code}）${msg ?? ''}`;
  }

  // ------------------------------------------------------------ TTS

  async speak(text: string, onDone?: () => void, onError?: (m: string) => void): Promise<boolean> {
    // 先把 Markdown 去掉——TTS 会把 `**` 念成「星号星号」
    const clean = stripMarkdown(text);
    if (clean.length === 0) {
      if (onDone) {
        onDone();
      }
      return true;
    }

    try {
      if (this.ttsEngine === null) {
        const ep: textToSpeech.CreateEngineParams = {
          language: 'zh-CN',
          person: 13,      // 凌小杉，女声（与「贪心」人格对得上）
          online: 1        // 1 = 离线
        };
        this.ttsEngine = await textToSpeech.createEngine(ep);
      }
      const engine = this.ttsEngine;

      const listener: textToSpeech.SpeakListener = {
        onStart: (requestId: string, response: textToSpeech.StartResponse): void => {
        },
        onComplete: (requestId: string, response: textToSpeech.CompleteResponse): void => {
          if (onDone) {
            onDone();
          }
        },
        onStop: (requestId: string, response: textToSpeech.StopResponse): void => {
          if (onDone) {
            onDone();
          }
        },
        // onData 是三个参数：音频数据 + 合成信息（读自 SDK 定义）
        onData: (requestId: string, audio: ArrayBuffer,
                 response: textToSpeech.SynthesisResponse): void => {
        },
        onError: (requestId: string, errorCode: number, errorMessage: string): void => {
          if (onError) {
            onError(`朗读出错（${errorCode}）${errorMessage ?? ''}`);
          }
        }
      };
      engine.setListener(listener);

      // SpeakParams 只有 requestId 和 extraParams（读自 SDK 定义）
      // 语速等参数不在这个接口里，只支持 style / locate / name / isBackStage
      const sp: textToSpeech.SpeakParams = {
        requestId: `greedy_tts_${Date.now()}`,
        extraParams: {
          'style': 'interaction-broadcast',   // 播报风格（当前只支持这一种）
          'locate': 'CN'
        }
      };
      engine.speak(clean, sp);
      return true;
    } catch (e) {
      const err = e as BusinessError;
      if (onError) {
        onError(`朗读失败：${err.message ?? String(e)}`);
      }
      return false;
    }
  }

  stopSpeak(): void {
    if (this.ttsEngine === null) {
      return;
    }
    try {
      this.ttsEngine.stop();
    } catch (e) {
      // 没在朗读时调用会抛错
    }
  }

  release(): void {
    try {
      if (this.asrEngine !== null) {
        this.asrEngine.shutdown();
      }
    } catch (e) {
      // 忽略
    }
    try {
      if (this.ttsEngine !== null) {
        this.ttsEngine.shutdown();
      }
    } catch (e) {
      // 忽略
    }
    this.asrEngine = null;
    this.ttsEngine = null;
  }
}

/**
 * 语音链路的「接口层」（跨平台，不含任何平台特有 API）
 *
 * ⛔ 为什么要有这一层（重要）：
 *
 * 编译时发现，鸿蒙的语音 API（@kit.CoreSpeechKit）**不支持 ArkUI-X 跨平台**：
 *
 *   11706007 can't support crossplatform application.
 *   'speechRecognizer' can't support crossplatform application.
 *
 * 而课程有两条要求是冲突的：
 *   1. 同一套代码 → 鸿蒙 + Android 包（要求代码跨平台兼容）
 *   2. 鸿蒙端必须打通语音（语音 API 不是跨平台 API）
 *
 * 解法：**平台差异化**
 *   - 本文件（共享目录）只放**接口 + 空实现**，不引用任何平台 API → 编译得过
 *   - 鸿蒙端提供真实现（放在平台特有目录）
 *   - Android / iOS 走空实现 → 语音按钮不显示，但 App 正常工作
 *
 * 运行时通过 `VoiceFactory` 注入具体实现，共享层不关心是哪个平台。
 */

/** 语音链路的可用性 */
export interface VoiceAvailability {
  asr: boolean;
  tts: boolean;
  reason: string;
}

/** ASR 回调 */
export interface AsrCallbacks {
  onPartial: (text: string) => void;
  onFinal: (text: string) => void;
  onError: (msg: string) => void;
}

/**
 * 语音服务接口
 *
 * 共享层只依赖这个接口。各平台提供实现：
 *   - HarmonyOS：调 @kit.CoreSpeechKit（离线 ASR + TTS）
 *   - 其他平台：空实现（能力查询返回 false，UI 自动隐藏语音入口）
 */
export interface IVoiceService {
  availability(): VoiceAvailability;
  startAsr(cb: AsrCallbacks): Promise<boolean>;
  stopAsr(): void;
  cancelAsr(): void;
  speak(text: string, onDone?: () => void, onError?: (m: string) => void): Promise<boolean>;
  stopSpeak(): void;
  release(): void;
}

/**
 * 空实现（降级用）
 *
 * 为什么要有它：Android 端没有语音实现时，
 * 共享层的调用不能崩——返回「不可用」让 UI 隐藏入口即可。
 */
export class NoopVoiceService implements IVoiceService {
  availability(): VoiceAvailability {
    return { asr: false, tts: false, reason: '本平台暂不支持语音，可以用打字' };
  }

  async startAsr(cb: AsrCallbacks): Promise<boolean> {
    cb.onError('本平台暂不支持语音识别');
    return false;
  }

  stopAsr(): void {
  }

  cancelAsr(): void {
  }

  async speak(_text: string, _onDone?: () => void, onError?: (m: string) => void): Promise<boolean> {
    if (onError) {
      onError('本平台暂不支持语音合成');
    }
    return false;
  }

  stopSpeak(): void {
  }

  release(): void {
  }
}

/**
 * 语音服务工厂
 *
 * 共享层不直接 import 平台实现，而是从这里取。
 * 各平台的入口（EntryAbility）在启动时把实现注册进来。
 */
export class VoiceFactory {
  private static impl: IVoiceService = new NoopVoiceService();

  /** 平台实现注册（鸿蒙端在 EntryAbility 里调） */
  static register(svc: IVoiceService): void {
    VoiceFactory.impl = svc;
  }

  static get(): IVoiceService {
    return VoiceFactory.impl;
  }
}

/** 算法术语热词（各平台实现共用） */
export const ALGO_HOTWORDS: string[] = [
  '线段树', '树状数组', '并查集', '主席树', '平衡树', '二叉搜索树',
  '单调队列', '单调栈', '优先队列', '哈希表', '链表', '后缀数组',
  '后缀自动机', '字典树', '块状链表', '左偏树',
  '动态规划', '数位动态规划', '状压动态规划', '树形动态规划', '区间动态规划',
  '背包问题', '贪心', '二分查找', '二分答案', '三分', '分治', '倍增',
  '深度优先搜索', '广度优先搜索', '记忆化搜索', '回溯', '剪枝',
  '最短路', '最小生成树', '拓扑排序', '强连通分量', '最近公共祖先',
  '网络流', '最大流', '最小费用流', '二分图', '匈牙利算法',
  '字符串哈希', '回文串', '前缀函数',
  '快速幂', '快速傅里叶变换', '快速数论变换', '高斯消元', '矩阵快速幂',
  '欧拉函数', '中国剩余定理', '扩展欧几里得', '素数筛', '线性筛',
  '莫比乌斯反演', '容斥原理', '组合数', '卡特兰数', '抽屉原理', '鸽巢原理',
  '博弈论', '凸包', '扫描线', '离散化', '前缀和', '差分',
  '时间复杂度', '空间复杂度', '常数优化', '卡常', '对拍', '构造',
  '样例', '边界情况', '数据范围', '评测机', '罚时'
];

/**
 * 去掉 Markdown 标记（跨平台共用，纯字符串处理）
 *
 * 为什么必须做：TTS 会把 `**` 念成「星号星号」，
 * 把 `###` 念成「井号井号井号」。直接念原文体验很差。
 */
export function stripMarkdown(text: string): string {
  let s = text;
  s = s.replace(/```[\s\S]*?```/g, '，这里有一段代码，');
  s = s.replace(/`([^`]*)`/g, '$1');
  s = s.replace(/\*\*([^*]*)\*\*/g, '$1');
  s = s.replace(/\*([^*]*)\*/g, '$1');
  s = s.replace(/^#{1,6}\s*/gm, '');
  s = s.replace(/^[-*+]\s+/gm, '');
  s = s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1');
  s = s.replace(/^\|?[\s:|-]+\|[\s:|-]*$/gm, '');
  s = s.replace(/\|/g, '，');
  s = s.replace(/\n{2,}/g, '。');
  s = s.replace(/\n/g, '，');
  s = s.replace(/[ \t]+/g, ' ');
  return s.trim();
}

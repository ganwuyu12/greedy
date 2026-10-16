# 语音链路开发留痕

> 课程硬性要求：鸿蒙端必须打通 **ASR → 模型 → TTS**。
> 本文档记录每一步的**探查结果、决策理由、实测数据**。

---

## 进度总览

| 步骤 | 内容 | 状态 |
|---|---|---|
| 0 | 探查 SDK 语音能力边界 | ⬜ |
| 1 | 确定技术方案 | ⬜ |
| 2 | 实现 ASR（语音识别） | ⬜ |
| 3 | 实现 TTS（语音合成） | ⬜ |
| 4 | 串起完整链路 | ⬜ |
| 5 | 实测验证 | ⬜ |

---

## 第 0 步：探查 SDK 语音能力

**为什么先探查而不是直接写**：
鸿蒙的语音能力分两种来源——
- **系统 SDK**（`@kit.CoreSpeechKit` 等）：离线、免费、无需账号，但**模拟器可能不支持**
- **云服务**（如华为云语音）：效果好，但要账号、要联网、可能收费

不先搞清楚哪条路走得通，写出来的代码可能根本跑不起来。

### 探查结论

**找到了鸿蒙系统自带的语音能力**（无需账号、无需联网）：

```
SDK 位置：E:\deveco studio\sdk\default\hms\ets\
  api\@hms.ai.speechRecognizer.d.ts     ASR（语音识别）
  api\@hms.ai.textToSpeech.d.ts         TTS（语音合成）
  kits\@kit.CoreSpeechKit.d.ts          统一入口
```

导入方式：

```typescript
import { speechRecognizer, textToSpeech } from '@kit.CoreSpeechKit';
```

#### ASR 能力边界（读自接口定义）

| 项 | 值 | 影响 |
|---|---|---|
| 语言 | **仅 zh-CN** | 够用——用户就是中文 |
| 模式 | **仅离线**（`online: 1`） | ✅ 不依赖网络、不花钱 |
| `locate` | 仅 CN | 无影响 |
| `recognizerMode` | `short` / `long` | 短句用 short |
| **`sysGeneralLexicon`** | **最多 200 个热词，每个 2–20 字** | ⭐ **对算法术语极有价值** |
| syscap | `SystemCapability.AI.SpeechRecognizer` | 需在设备上存在 |

#### 关键发现：热词能力

算法术语是语音识别的重灾区——「线段树」容易被识别成「线段数」，
「树状数组」容易变成「数状数组」。**鸿蒙的 ASR 支持配置 200 个热词**，
正好可以拿算法术语表来喂，把识别率拉上去。

这是本次探查最有价值的发现：**不用为了识别率去接付费云服务**。

#### 技术方案

```
用户按住说话
    ↓
ASR（系统离线识别，喂算法术语热词）
    ↓
文字 → Agent（现有链路，含工具调用）
    ↓
回答文字
    ↓
TTS（系统离线合成）
    ↓
播放
```

**为什么走系统能力而不是云服务**：
- 离线：演示时不依赖网络，不会因为网速卡住
- 免费：不用账号、不用计费
- 但**要验证模拟器是否支持**——这是下一个风险点

#### 待验证的风险

| # | 风险 | 验证方式 |
|---|---|---|
| 1 | 模拟器可能没有麦克风 | 装上去试 |
| 2 | `SystemCapability.AI.SpeechRecognizer` 在模拟器上可能不存在 | 用 `canIUse()` 判断 |
| 3 | TTS 在模拟器上可能没声音 | 装上去听 |
| 4 | 需不需要额外权限（麦克风） | 查 module.json5 要求 |

#### TTS 能力边界（读自接口定义）

| 项 | 值 |
|---|---|
| 语言 | `zh-CN`（也支持 en-US） |
| 音色 `person` | **13 = 凌小杉（女声，推荐）**；0 也可用；21 = 凌飞哲（男声，**需下载**） |
| 模式 | **1 = 离线**（0 = 在线，文档明确说当前不支持） |
| 接口 | `createEngine` → `setListener` → `speak(text, params)` / `stop()` |

**音色选择理由**：「贪心」是傲娇女性人格，**凌小杉（13）** 对得上。
男声（21）还要下载语音包，模拟器上多半没有，不选。

**结论：可以先写代码，但必须留好「不支持时降级」的分支**——
不能让语音功能挂掉时整个 App 不能用。

---

## 第 1 步：确定技术方案（遇到了一个根本性冲突）

### ⛔ 关键发现：语音 API 不能用于跨平台工程

写完第一版代码后编译，编译器直接报错：

```
11706007 can't support crossplatform application.
'speechRecognizer' can't support crossplatform application.
  At Voice.ets:136:30
'setListener' / 'startListening' / 'finish' / 'cancel' / 'result' / 'isFinal'
  —— 同一类错误，共 11 处
```

**含义**：`@kit.CoreSpeechKit` 里的 `speechRecognizer` / `textToSpeech`
**只支持鸿蒙端，不支持 ArkUI-X 跨平台**。

### 这为什么是根本性冲突

| 课程要求 | 冲突点 |
|---|---|
| 同一套代码 → 鸿蒙 + Android 包 | ArkUI-X 要求所有代码跨平台兼容 |
| 鸿蒙端必须打通语音（ASR→模型→TTS） | 语音 API **不是**跨平台 API |

**两者直接矛盾**：把语音代码放进共享目录，Android 端就编译不过；
不放进共享目录，鸿蒙端的语音又没地方写。

---

## 第 1.5 步：穷举绕行方案（全部实测失败）

为了不留下「是不是没试过其他办法」的疑问，
我把所有可能的绕行方式**逐个在真实编译器上试了一遍**：

| # | 尝试 | 结果 | 错误码 |
|---|---|---|---|
| 1 | 静态 `import` 语音 API | ✗ | `11706007 can't support crossplatform` |
| 2 | 改成接口 + 空实现（NoopVoiceService） | ✓ 编译过，但**鸿蒙端也没语音了** | — |
| 3 | 动态 `import('@kit.CoreSpeechKit')` | ⚠️ 不报 11706007，但拿不到模块 | — |
| 4 | `const m = kit.speechRecognizer` | ✗ | `arkts-no-ns-as-obj`（命名空间不能当对象） |
| 5 | 直接 `import('@hms.ai.speechRecognizer')` 后取 `.default` | ✗ | 同上 |
| 6 | `@ts-ignore` 压住静态 import | ✗ | `arkts-strict-typing-required` |
| 7 | `declare module` 自行声明 | ✗ | `arkts-no-ambient-decls` |
| 8 | 动态 import + 链式调用 `(await import(...)).default.createEngine()` | ✗ | `11706007` 又出现（调用方法时仍检查） |
| 9 | 自定义 interface 做结构化适配 | ✗ | `arkts-no-structural-typing` |

### 结论

**在 ArkUI-X 工程里，鸿蒙语音 API 无法使用。**

两条路都是死路：

- **静态引用** → 编译期报 `can't support crossplatform application`
- **动态引用** → 拿不到模块（ArkTS 禁止命名空间当对象、禁止结构化类型）

这不是写法问题，是**框架层面的设计边界**：
ArkUI-X 的编译检查会阻止一切平台特有 API 进入共享代码。

---

## 第 2 步：方案选择（需要决策）

既然无法两全，必须在两条路里选一条：

### 方案 A：鸿蒙单端 + 语音（放弃跨端）

| 优点 | 缺点 |
|---|---|
| ✅ 语音链路完整（课程第 6 条硬性要求） | ❌ 不是跨端（课程第 1 条硬性要求） |
| ✅ 交互体验最好，演示效果最强 | ❌ Android 端只能另做或用旧代码 |
| ✅ 工作量小，今天就能完成 | |

**做法**：把 `.arkui-x/` 配置去掉，回到普通鸿蒙工程，
语音 API 可以正常静态引用。

### 方案 B：保持跨端 + 放弃语音（用文字代替）

| 优点 | 缺点 |
|---|---|
| ✅ 满足跨端要求（第 1 条） | ❌ 缺第 6 条（鸿蒙语音） |
| ✅ 代码结构干净 | ❌ 演示时少一个亮点 |
| ✅ 现在已经能跑 | |

**做法**：删掉 `VoiceHarmony.ets`，保留 `NoopVoiceService`，
语音按钮自动隐藏（已有降级逻辑）。

### 方案 C：双工程（推荐但有成本）

**两个工程，共用业务代码**：

```
greedy-app/         ArkUI-X 工程（鸿蒙 + Android 跨端）
                    —— 满足第 1 条
greedy-harmony/     鸿蒙单端工程
                    —— 加语音，满足第 6 条
```

共享部分（`Agent.ets` / `CFClient.ets` / `WikiIndex.ets` / `SessionStore.ets` /
`Persona.ets` / `Tools.ets`）两边**完全相同**，用脚本同步。

| 优点 | 缺点 |
|---|---|
| ✅ 两条硬性要求都满足 | ❌ 需要维护两个工程 |
| ✅ 各有各的演示场景 | ❌ 同步要靠纪律 |
| ✅ 共享代码占大头（约 1900 行中的 1500 行） | |

**我的建议：方案 C**，但如果时间紧，**先方案 A**（语音是当前唯一缺的硬性要求，
而且演示效果最直观）。

---

## 实际决定：方案 C（双工程）

**已实施并验证。**

### 两个工程

| 工程 | 路径 | 作用 | 语音 |
|---|---|---|---|
| **greedy-app** | `E:\projects\greedy-app` | ArkUI-X 跨端（鸿蒙 + Android） | ❌ 占位实现 |
| **greedy-harmony** | `E:\projects\greedy-harmony` | 鸿蒙单端 | ✅ **真实实现** |

### 结果

✅ **鸿蒙单端工程 `BUILD SUCCESSFUL`** —— 语音 API 静态 import 可用
（`11706007 can't support crossplatform` 完全消失）

```
HAP: entry-default-unsigned.hap   517 KB
     （比跨端版 474 KB 大，因为含真实语音实现）
```

### 共享机制

新建 `sync_shared.py` 保证两边一致：

```bash
python sync_shared.py          # 检查一致性
python sync_shared.py --diff   # 显示差异
python sync_shared.py --apply  # 跨端 → 鸿蒙 同步
```

**共享清单怎么定的**：逐个查 import，只有不含平台特有 API 的文件才能共享。

| 类别 | 文件 | 数量 |
|---|---|---|
| **共享**（两边必须一致） | `Agent` `CFClient` `Config` `Persona` `SessionStore` `Tools` `WikiIndex` `Voice`(接口) `Index`(UI) + 3 个资源/配置 | **12** |
| **平台特有**（各管各的） | `VoiceHarmony.ets` | **1** |

**实测结果**：`一致 12 / 不一致 0 / 缺失 0`

**为什么 `Voice.ets` 能共享**：它只定义接口 + 空实现 + 热词表 + Markdown 清理，
**不含任何平台 API**，所以跨端与单端都能编译。

### 修掉的 4 处 API 误用

写第一版时我按印象猜了参数，编译器逐条纠正（**这些只有真实编译才能发现**）：

| # | 我猜的 | 实际定义 |
|---|---|---|
| 1 | `finish()` / `cancel()` 无参 | `finish(sessionId)` / `cancel(sessionId)` |
| 2 | `StartParams.audioSourceType` | `StartParams.audioInfo`（含 4 个必填字段） |
| 3 | `SpeakParams` 有 speed/volume/pitch | **只有 `requestId` + `extraParams`** |
| 4 | `onData(requestId, response)` | `onData(requestId, audio: ArrayBuffer, response)` |

顺带发现了正确的参数：

```typescript
// ASR 音频配置（4 个字段都必填，且只支持这些值）
audioInfo: {
  audioType: 'pcm',      // 只支持 pcm
  sampleRate: 16000,     // 只支持 16000
  soundChannel: 1,       // 只支持单声道
  sampleBit: 16          // 只支持 16 位
}

// TTS 的可用参数（没有语速控制）
extraParams: {
  style: 'interaction-broadcast',   // 只支持这一种风格
  locate: 'CN'
}
```

---






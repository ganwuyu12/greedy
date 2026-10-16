# 鸿蒙单端工程（方案 C 之一）

跨端工程见 `app/`，本目录只放**鸿蒙单端特有的部分**。

## 为什么有两个工程

课程两条硬性要求在技术上冲突：

| 要求 | 冲突点 |
|---|---|
| 同一套代码 → 鸿蒙 + Android 包 | ArkUI-X 要求代码跨平台兼容 |
| 鸿蒙端必须打通语音 | 语音 API（@kit.CoreSpeechKit）**不是**跨平台 API |

放进共享目录 → Android 编译不过（`11706007 can't support crossplatform`）；
不放进 → 鸿蒙端语音没地方写。

**解法：双工程 + 共享业务代码。**

| 工程 | 位置 | 语音 |
|---|---|---|
| `greedy-app` | `E:\projects\greedy-app` | ❌ ArkUI-X 限制，走占位实现 |
| `greedy-harmony` | `E:\projects\greedy-harmony` | ✅ 真实实现 |

## 本目录内容

只留**平台特有**的文件，共享部分见 `../app/`。

```
build-profile.json5          工程配置（标准鸿蒙，无跨端标记）
entry/build-profile.json5
oh-package.json5
hvigorfile.ts
entry/hvigorfile.ts
entry/src/main/ets/core/VoiceHarmony.ets    ← 真实语音实现（静态 import）
```

## 共享机制

用 `sync_shared.py` 保证两边一致（在仓库根目录）：

```bash
python sync_shared.py          # 检查一致性
python sync_shared.py --diff   # 显示差异
python sync_shared.py --apply  # 跨端 → 鸿蒙 同步
```

**共享清单**（12 个文件，两边必须逐字节一致）：
`Agent` `CFClient` `Config` `Persona` `SessionStore` `Tools` `WikiIndex`
`Voice`（接口层）`Index`（UI）+ `kb_index.json` + `string.json` + `module.json5`

**平台特有**（1 个，各管各的）：`VoiceHarmony.ets`

## 构建

```powershell
cd E:\projects\greedy-harmony
$env:DEVECO_SDK_HOME = "E:\deveco studio\sdk"
& "E:\deveco studio\tools\ohpm\bin\ohpm.bat" install
& "E:\deveco studio\tools\hvigor\bin\hvigorw.bat" -p buildMode=debug `
    -p product=default --mode module -p module=entry assembleHap `
    --no-daemon --no-parallel
```

> ⚠️ 单端工程用 **hvigorw** 构建，不用 `ace build hap`
> （`ace` 是 ArkUI-X 工具，会去找 `.arkui-x` 目录而报错）。

## 完整搭建步骤

见 [`../app/VOICE.md`](../app/VOICE.md) —— 含全部探查记录、
9 种失败尝试的对照表、以及 SDK 能力边界。

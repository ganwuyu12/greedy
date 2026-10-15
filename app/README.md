# 贪心 · 跨端应用（ArkTS）

把「贪心」从 Python 命令行搬到手机上。目标平台：**鸿蒙 + Android**（ArkUI-X 一套代码）。

---

## ✅ 当前状态（已在真机验证）

| 项目 | 状态 |
|---|---|
| ArkTS 业务代码 | ✅ 完成（约 1900 行） |
| UI 界面 | ✅ 完成（聊天 + 成长记录 + 设置面板） |
| **HAP 编译** | ✅ **已验证**（261 KB，零 ArkTS 错误） |
| **鸿蒙模拟器运行** | ✅ **已验证**（Mate 90 Pro 镜像） |
| **工具调用** | ✅ **已验证**（`get_progress` / `get_recent_log` 成功返回真实数据） |
| **多轮对话** | ✅ **已验证** |
| Android 端 | ⚠️ 代码就绪，需装 Android SDK 才能打包 |
| 搜索知识库 | ❌ **未通**（`WIKI_ENDPOINT` 为空） |
| 语音链路（ASR→模型→TTS） | ❌ 未做 |
| 会话持久化 | ❌ 未做 |

### 实测效果

问「我最近怎么样」，返回：

```
累计 148 道，活跃 65 天，从 2025-10-12 走到现在。
最高难度 2300。当前 rating 1291，历史最高 1451。

148 道了。挺能熬的嘛，笨蛋。上次那个 1451 掉下来了是吧？
哼，rating 起起落落而已，你又不是没见过——别告诉我你在意这个。

调用了：✓ get_progress  ✓ get_recent_log
```

**数据全部来自 Codeforces 真实接口**，工具调用痕迹显示在气泡下方。

---

## 一、环境（本机已验证可用）

```
ArkUI-X SDK 26.0.0.28    E:\DevEcoSDK
ace 工具                  E:\DevEcoSDK\26.0.0\arkui-x\toolchains\bin\ace.cmd
hdc                      E:\deveco studio\sdk\default\openharmony\toolchains\hdc.exe
模拟器镜像                已部署（Mate 90 Pro / Mate X7 / MatePad Pro / MateBook Pro）
```

配置 ace（已做过，换机器需要重做）：

```powershell
$ace = "E:\DevEcoSDK\26.0.0\arkui-x\toolchains\bin\ace.cmd"
& $ace config `
  --arkui-x-sdk "E:\DevEcoSDK" `
  --harmonyos-sdk "E:\deveco studio\sdk" `
  --deveco-studio-path "E:\deveco studio" `
  --java-sdk "E:\deveco studio\jbr" `
  --ohpm-dir "E:\deveco studio\tools\ohpm" `
  --nodejs-dir "C:\Program Files\nodejs"
```

验证：`& $ace check -v` 应显示 `[√] HarmonyOS toolchains`。

---

## 二、构建与部署（不依赖 DevEco 的 Run 按钮）

DevEco 的模块索引有时识别不到手工加入的文件（运行配置里模块显示 `[none]`）。
**命令行可以完全绕开它**：

```powershell
$ace = "E:\DevEcoSDK\26.0.0\arkui-x\toolchains\bin\ace.cmd"
$hdc = "E:\deveco studio\sdk\default\openharmony\toolchains\hdc.exe"

# 1. 编译（产物：entry/build/default/outputs/default/entry-default-unsigned.hap）
& $ace build hap --debug

# 2. 安装到模拟器（模拟器不校验签名，unsigned HAP 可直接装）
& $hdc install -r "entry\build\default\outputs\default\entry-default-unsigned.hap"

# 3. 启动
& $hdc shell aa start -a EntryAbility -b com.example.greedy_app

# 4. 截图（可选）
& $hdc shell snapshot_display -f /data/local/tmp/shot.jpeg
& $hdc file recv /data/local/tmp/shot.jpeg .\shot.jpeg
```

> ⚠️ `ace build hap` 最后会报一个 iOS 的 ENOENT 错误（它想把三端产物都准备齐）。
> **这个错误可以忽略**——HAP 在此之前已经打包完成（看 `:entry:default@PackageHap Finished`）。

> **签名**：模拟器不需要。真机需要 HarmonyOS 开发者证书，
> 在 DevEco 的 `Project Structure` → `Signing Configs` → 勾「自动生成签名」，
> 但要先连上设备才能生成 profile。

---

## 三、首次使用

应用启动后**自动弹出设置面板**，填两项：

1. **API 密钥**（DeepSeek）——只存本机 `preferences`，不进源码
2. **Codeforces 用户名**——默认 `ganwuyu`

保存后立即生效，不用重启。

---

## 四、工程结构

```
entry/src/main/ets/
├── core/
│   ├── Config.ets      配置与本地键值存储封装
│   ├── Persona.ets     「贪心」人格（伙伴定位，不是教练）
│   ├── CFClient.ets    Codeforces 数据层 + 练习日志归档
│   ├── Agent.ets       Agent 主循环
│   └── Tools.ets       工具集 + 笔记存储（长期记忆）
└── pages/
    └── Index.ets       主界面
.arkui-x/
├── arkui-x-config.json5    {"crossplatform": true, "modules": ["entry"]}
└── android/                Android 工程脚手架
```

### Agent 主循环实现的七件事

| # | 能力 | 位置 |
|---|---|---|
| 1 | 工具注册（自动生成 function-calling schema） | `ToolRegistry.toSchema()` |
| 2 | 主循环（模型要工具 → 执行 → 结果回灌） | `Agent.run()` |
| 3 | 状态管理（assistant / tool 消息拼接） | `Agent.run()` 内 `messages` |
| 4 | 循环终止（最大轮数 + **连续**重复调用检测） | `repeatCount` |
| 5 | 失败回灌（工具报错结构化返回给模型） | `ToolRegistry.execute()` |
| 6 | Token 预算 | `Agent.run()` |
| 7 | 追踪日志（UI 上可见） | `TraceStep` |

### 8 个工具

| 工具 | 作用 |
|---|---|
| `get_progress` | 成长记录（累计、活跃天数、最近一次） |
| `get_milestones` | 里程碑（首次解出各难度的日期） |
| `get_recent_log` | 最近几天的练习详情 |
| `search_wiki` | 检索算法知识库（⚠️ 未通） |
| `save_note` | 记下想法 |
| `list_notes` | 查看记过的笔记 |
| `get_date` | 取今天日期 |

**工具定位遵循「陪伴而非教练」**：有记录、有检索，没有水平评判、没有训练指令。

---

## 五、踩过的坑（都是真实编译/运行暴露的）

### 1. ArkTS 禁止匿名对象字面量

```
arkts-no-untyped-obj-literals
```

必须为每个结构声明显式 `interface`。`Agent.ets` 里定义了 13 个接口。
另外 `Map` 不能直接进对象字面量，`properties` 要用 `Record`。

### 2. 对话历史必须保留成对结构（**只在第二轮暴露**）

第一轮消息是当轮新建的、结构完整；第二轮带上历史时，如果把
assistant 的 `tool_calls` 丢掉，`tool` 结果消息就变成孤儿，接口报：

```
Messages with role 'tool' must be a response to a preceding
message with 'tool_calls'
```

**修法**：历史直接以 wire 格式保存（`WireMessage[]`），保留
`assistant(tool_calls)` ↔ `tool(tool_call_id)` 的成对关系。

### 3. `user.status` 不带难度

```
problem.rating → null     （只有 problem.tags 有值）
```

所以**难度数据必须来自题库表**（`problemset.problems`，约 2 MB / 5000+ 题）。
但成长记录不需要它——改成两步加载：

- 第一步：拉提交记录（约 2 秒）→ 成长记录立即可用
- 第二步：后台补全题库表（不 `await`），需要难度的工具调 `ensureMeta()` 等它

### 4. 异常不能静默吞掉

之前 `doLoad()` 把异常吃掉，`stats` 保持 `null`，工具就返回
「还没有成长记录」——**真实故障（超时）完全看不到**，排查时被误导。

修法：记住失败原因并**抛出**，让模型看到真实错误。

---

## 六、下一步

| 优先 | 任务 | 说明 |
|---|---|---|
| 🔴 | **会话持久化 + 回看** | 课程硬性要求 |
| 🔴 | **搜索知识库打通** | `WIKI_ENDPOINT` 为空；索引 42 MB 不适合打进 App，需本地服务或换方案 |
| 🟡 | 鸿蒙语音链路（ASR→模型→TTS） | 课程硬性要求，工作量最大，放最后 |
| 🟡 | Android 端打包 | 需装 Android SDK |
| 🟢 | 流式输出 | 体验加分项 |

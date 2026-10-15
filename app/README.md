# 贪心 · 跨端应用（ArkTS）

把「贪心」从 Python 命令行搬到手机上的客户端。目标平台：**鸿蒙 + Android**（ArkUI-X 一套代码）。

---

## ⚠️ 先读这段：状态与限制

| 项目 | 状态 |
|---|---|
| **ArkTS 业务代码** | ✅ 已写完，逻辑与 Python 版一致 |
| **UI 界面** | ✅ 已写完（聊天优先 + 成长记录侧栏） |
| **工程配置文件** | ⚠️ **没写**——见下方理由 |
| **能否编译验证** | ❌ **没有验证过**——本机未安装 ArkUI-X SDK |
| **能否运行验证** | ❌ **没有验证过**——无模拟器镜像、无签名 |

### 为什么配置文件不由我提供

`build-profile.json5` / `oh-package.json5` / `hvigorfile.ts` / `module.json5` 这几个文件
**强依赖 DevEco Studio 的版本和 ArkUI-X 插件**，字段名和结构随版本变化。

我如果凭印象写，你很可能卡在「工程结构异常」这类编译错误上，而且
**很难判断是配置错了还是代码错了**。

**正确做法**：用 DevEco Studio 的官方模板生成骨架（结构 100% 正确），
再把我写的 `core/` 和 `pages/` 覆盖进去。见下面的步骤。

---

## 一、搭骨架（必须用 DevEco Studio）

### 前置：装 ArkUI-X SDK

1. 打开 DevEco Studio
2. `File` → `Settings` → **ArkUI-X**
3. 选择 SDK 下载路径，下载需要的版本
4. 把 ArkUI-X 的 toolchains/bin 加进系统 `Path` 环境变量，例如：
   ```
   D:\CodeAPP\DevEcoStudio\ArkUI-X-SDK\17\arkui-x\toolchains\bin
   ```
5. 验证：
   ```bash
   ace check -v
   ```

> 参考：[ArkUI-X 跨平台框架入门详解](https://cloud.tencent.com.cn/developer/article/2544591)、
> [ArkUI-X 应用工程结构说明](https://blog.csdn.net/weixin_40526189/article/details/149480764)

### 创建工程

1. `File` → `New` → `Create Project`
2. 选 **Application** → **ArkUI-X** → **Empty Ability**
3. 工程名填 `greedy`，模块名保持 `entry`
4. 生成后先**编译一次**，确认模板本身能跑通

### 生成后的目录长这样

```
greedy/
├── .arkui-x/
│   ├── android/                    ← Android 平台工程
│   ├── ios/                        ← iOS 平台工程（选做）
│   └── arkui-x-config.json5        ← 标记哪些模块跨平台
├── AppScope/
├── entry/
│   └── src/main/
│       ├── ets/
│       │   ├── core/               ← 【放我写的业务代码】
│       │   ├── pages/              ← 【放我写的界面】
│       │   └── entryability/
│       ├── resources/
│       └── module.json5
├── hvigor/
├── build-profile.json5
├── hvigorfile.ts
└── oh-package.json5
```

### 确认跨平台标记

`entry/src/main/module.json5` 里的模块名（应为 `entry`），要出现在
`.arkui-x/arkui-x-config.json5` 的 `modules` 数组中：

```json
{
  "crossplatform": true,
  "modules": ["entry"]
}
```

---

## 二、放入业务代码

把本目录下的文件复制到工程里：

| 本仓库文件 | 目标位置 |
|---|---|
| `app/entry/src/main/ets/core/Config.ets` | `entry/src/main/ets/core/Config.ets` |
| `app/entry/src/main/ets/core/Persona.ets` | `entry/src/main/ets/core/Persona.ets` |
| `app/entry/src/main/ets/core/CFClient.ets` | `entry/src/main/ets/core/CFClient.ets` |
| `app/entry/src/main/ets/core/Agent.ets` | `entry/src/main/ets/core/Agent.ets` |
| `app/entry/src/main/ets/core/Tools.ets` | `entry/src/main/ets/core/Tools.ets` |
| `app/entry/src/main/ets/pages/Index.ets` | `entry/src/main/ets/pages/Index.ets`（覆盖模板同名文件） |

### 申请权限

`entry/src/main/module.json5` 的 `requestPermissions` 里加上：

```json5
{
  "name": "ohos.permission.INTERNET"
}
```

没有这个权限，网络请求会直接失败。

---

## 三、运行

### 鸿蒙端

1. `Build` → `Build Hap(s)/APP(s)` → `Build APP(s)`
2. 用模拟器或真机运行

### Android 端

1. 用 ACE 工具或 Android Studio 把 `.arkui-x/android` 工程打成 APK
2. 安装到 Android 手机

### 首次使用要配密钥

应用启动后如果提示「还没配密钥」，需要：
- 在 `entry/src/main/ets/pages/Index.ets` 里，或者后续加一个设置页，
  把 DeepSeek 的 API Key 写进 `AppStorageUtil`：
  ```typescript
  await AppStorageUtil.setString(AppConfig.KEY_API_KEY, 'sk-xxxx');
  ```
- **不要把密钥硬编码进源码后提交**——`.gitignore` 已经排除 `.env`，
  但 ArkTS 里没有 .env 机制，建议走设置页写入本地存储

---

## 四、已实现的代码结构

```
core/
├── Config.ets     配置与本地键值存储封装
├── Persona.ets    「贪心」的人格设定（伙伴定位，不是教练）
├── CFClient.ets   Codeforces 数据层（限流 + 重试 + 缓存）
├── Agent.ets      Agent 主循环（工具注册 + 执行 + 回灌 + 终止）
└── Tools.ets      工具集 + 笔记存储（长期记忆）
pages/
└── Index.ets      主界面（聊天 + 成长记录侧栏）
```

### Agent 主循环实现了这七件事

| # | 能力 | 位置 |
|---|---|---|
| 1 | 工具注册（自动生成 function-calling schema） | `ToolRegistry.toSchema()` |
| 2 | 主循环（模型要工具 → 执行 → 结果回灌） | `Agent.run()` |
| 3 | 状态管理（assistant / tool 消息拼接） | `Agent.run()` 内 `messages` |
| 4 | 循环终止（最大轮数 + **连续**重复调用检测） | `repeatCount` 逻辑 |
| 5 | 失败回灌（工具报错结构化返回给模型） | `ToolRegistry.execute()` |
| 6 | Token 预算 | `Agent.run()` 内累计判断 |
| 7 | 追踪日志（每步留痕，UI 上可见） | `TraceStep` + 气泡下方小字 |

### 已注册的工具（8 个）

| 工具 | 作用 |
|---|---|
| `get_progress` | 成长记录（累计、活跃天数、最近一次） |
| `get_milestones` | 里程碑（首次解出各难度的日期） |
| `get_recent_log` | 最近几天的练习详情 |
| `search_wiki` | 检索算法知识库 |
| `save_note` | 记下想法 |
| `list_notes` | 查看记过的笔记 |
| `get_date` | 取今天日期 |

工具定位遵循「陪伴而非教练」：**有记录、有检索，没有水平评判和训练指令。**

---

## 五、已知风险（我没能验证的地方）

按可能出问题的概率排序：

| # | 风险 | 表现 | 处理 |
|---|---|---|---|
| 1 | **ArkTS 语法严格性** | 编译报错（ArkTS 禁止 `any`、部分动态特性） | 代码里已尽量用显式类型；报错处按提示收紧 |
| 2 | `http` 请求的 `extraData` 传参 | 请求体格式不对 | 检查 `Agent.callModel()` 里的 payload 序列化 |
| 3 | `@Builder` 里用 `this` | 上下文丢失 | 已避免在 Builder 内改状态 |
| 4 | `ForEach` 的键生成 | 列表不刷新 | 键里带了 `loading` 状态 |
| 5 | `preferences` 初始化时机 | 读写静默失败 | 已在 `aboutToAppear` 里 await 初始化 |
| 6 | ArkUI-X 的部分 API 不支持 | 鸿蒙能跑、Android 报错 | 优先用基础组件（Column/Row/Text/List/Button） |

**第 6 条要特别留意**：ArkUI-X 对 ArkUI 的 API 支持是**子集**。
我刻意只用了最基础的组件，就是为了降低这个风险。
如果 Android 端报某个 API 不支持，优先换实现方式，不要硬扛。

---

## 六、下一步

| 优先 | 任务 | 说明 |
|---|---|---|
| 🔴 | 搭骨架 + 放入代码 + 跑通鸿蒙端 | 这是当前唯一的目标 |
| 🟡 | 加设置页（填 API Key、改 handle） | 现在密钥要写代码里，不方便 |
| 🟡 | 流式输出 | 课程加分项，且体验提升明显 |
| 🟡 | 会话历史持久化 + 回看 | 课程硬性要求（第 5 条） |
| 🟢 | 语音链路（ASR → Agent → TTS） | 鸿蒙必做（第 6 条），工作量较大 |
| 🟢 | Android 端适配 | 先鸿蒙跑通再谈 |

**建议的顺序**：跑通鸿蒙端 → 加设置页 → 会话持久化 → 流式 → 语音。

**不要一上来就纠结两端都能跑**——先让鸿蒙端转起来。

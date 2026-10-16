/**
 * 贪心 · 主界面
 *
 * UI 定位：聊天优先，成长记录在侧。
 *   主路径 = 打开就能聊
 *   次要路径 = 点头像看成长记录
 *
 * 交互上做了三件事：
 *   1. 等待时显示「正在检索…」这类状态，不是干等——也让工具调用可见
 *   2. 工具调用过程在消息里留痕，能看出它真的调了工具而不是编答案
 *   3. 空态有引导（给几个可以点的例子），不是一片空白
 */

import { Agent, AgentConfig, ChatMessage, PlainHistoryItem, ToolRegistry } from '../core/Agent';
import { AppConfig, AppStorageUtil } from '../core/Config';
import { buildRegistry, CompanionService, NoteStore } from '../core/Tools';
import { WikiIndex } from '../core/WikiIndex';
import { prompt as personaPrompt } from '../core/Persona';
import { Session, SessionStore } from '../core/SessionStore';
import { VoiceFactory, IVoiceService, AsrCallbacks, VoiceAvailability } from '../core/Voice';
import { HarmonyVoiceService } from '../core/VoiceHarmony';
import { common, abilityAccessCtrl, Permissions } from '@kit.AbilityKit';
import { resourceManager } from '@kit.LocalizationKit';

/** 聊天列表里的一条 */
interface Bubble {
  id: number;
  role: string;          // 'user' | 'assistant' | 'tool'
  text: string;
  loading: boolean;
  /** 工具调用痕迹（展示在气泡下方的小字） */
  trace: string;
}

/** 空态引导：点一下就能问 */
const SUGGESTIONS: string[] = [
  '我最近怎么样',
  '我的里程碑',
  '什么是线段树',
  '帮我回顾一下最近的比赛'
];

@Entry
@Component
struct Index {
  @State bubbles: Bubble[] = [];
  @State inputText: string = '';
  @State sending: boolean = false;
  @State statusText: string = '';
  @State showProgress: boolean = false;
  @State progressText: string = '';
  @State milestonesText: string = '';
  @State showSettings: boolean = false;
  @State keyDraft: string = '';
  @State handleDraft: string = '';
  @State settingsHint: string = '';
  @State hasKey: boolean = false;
  @State showSessions: boolean = false;
  @State sessionList: Session[] = [];
  @State voiceOk: boolean = false;         // 语音可用性
  @State ttsOk: boolean = false;
  @State listening: boolean = false;       // 正在识别
  /** 正在启动（申请权限 / 建引擎）——这期间用户可能已松手 */
  private voiceStarting: boolean = false;
  /** 用户是否已松手 */
  private released: boolean = false;
  @State partialText: string = '';         // 识别中的实时文字
  @State voiceHint: string = '';           // 语音相关提示
  @State autoSpeak: boolean = true;        // 自动朗读回答

  private seq: number = 0;
  private agent: Agent | null = null;
  private registry: ToolRegistry | null = null;
  private companion: CompanionService | null = null;
  private notes: NoteStore = new NoteStore();
  private sessions: SessionStore = new SessionStore();
  private wiki: WikiIndex = new WikiIndex();
  private wikiMgr: resourceManager.ResourceManager | null = null;
  private voice: IVoiceService = new HarmonyVoiceService();
  private scroller: Scroller = new Scroller();

  aboutToAppear(): void {
    this.initAgent();
  }

  private async initAgent(): Promise<void> {
    // 存储必须先初始化，否则读写会静默失效（拿不到密钥、笔记存不下来）
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      await AppStorageUtil.init(ctx);
    } catch (e) {
      // 初始化失败不阻断启动，后续读写会走空值分支
    }

    const apiKey = await AppStorageUtil.getString(AppConfig.KEY_API_KEY);
    let handle = await AppStorageUtil.getString(AppConfig.KEY_HANDLE);
    if (handle.length === 0) {
      handle = AppConfig.DEFAULT_HANDLE;
    }
    this.hasKey = apiKey.length > 0;
    this.handleDraft = handle;

    this.companion = new CompanionService(handle);
    // resourceManager 用于读 rawfile 里的知识索引
    if (this.wikiMgr === null) {
      try {
        const ctx = getContext(this) as common.UIAbilityContext;
        this.wikiMgr = ctx.resourceManager;
      } catch (e) {
        this.wikiMgr = null;
      }
    }
    // 预加载知识索引（137 KB，启动时读比首次提问时读体验好）
    if (this.wikiMgr !== null) {
      try {
        await this.wiki.load(this.wikiMgr);
      } catch (e) {
        // 读不到不影响其他功能，提问时还会再试一次
      }
    }
    this.registry = buildRegistry(this.companion, this.notes, this.wiki,
      this.wikiMgr as resourceManager.ResourceManager);

    const cfg: AgentConfig = {
      apiKey,
      model: AppConfig.LLM_MODEL,
      endpoint: AppConfig.LLM_ENDPOINT,
      systemPrompt: personaPrompt,
      maxRounds: AppConfig.MAX_ROUNDS,
      tokenBudget: AppConfig.TOKEN_BUDGET,
      maxDuplicateCalls: AppConfig.MAX_DUPLICATE_CALLS
    };
    this.agent = new Agent(this.registry, cfg);

    // 恢复上次的对话
    await this.sessions.load();
    const cur = this.sessions.current();
    this.restoreBubbles(cur);

    if (apiKey.length === 0) {
      if (this.bubbles.length === 0) {
        this.pushBubbleNow('assistant',
          '哼，你还没配密钥呢……点右上角「设置」填一下，不然本小姐没法说话。', '');
      }
      this.showSettings = true;      // 第一次启动直接把设置打开，省得找不到
    } else if (this.bubbles.length === 0) {
      // 没有历史才说开场白；有历史就直接接着聊
      await this.sessions.append('assistant', '来了？说吧，今天又卡在哪了。', '');
      this.pushBubbleNow('assistant', '来了？说吧，今天又卡在哪了。', '');
    }
    this.scrollToBottom();

    // 语音能力：只检测，不急着建引擎（建引擎较慢，等用户真要用再建）
    const av = this.voice.availability();
    this.voiceOk = av.asr;
    this.ttsOk = av.tts;
    this.voiceHint = av.reason;
  }

  // ------------------------------------------------------------ 语音

  /** 申请麦克风权限 */
  private async requestMic(): Promise<boolean> {
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      const mgr = abilityAccessCtrl.createAtManager();
      const perms: Permissions[] = ['ohos.permission.MICROPHONE'];
      const result = await mgr.requestPermissionsFromUser(ctx, perms);
      // 0 = 已授权
      return result.authResults.length > 0 && result.authResults[0] === 0;
    } catch (e) {
      return false;
    }
  }

  /** 按下麦克风：开始识别 */
  private async startVoice(): Promise<void> {
    if (this.listening || this.voiceStarting) {
      return;
    }
    if (!this.voiceOk) {
      this.voiceHint = '本设备不支持语音识别，可以用打字';
      return;
    }
    // 标记「正在启动」——因为申请权限是异步的（首次会弹窗），
    // 这期间用户可能已经松手了，必须记住这个意图
    this.voiceStarting = true;
    this.released = false;

    const granted = await this.requestMic();
    if (!granted) {
      this.voiceStarting = false;
      this.voiceHint = '没有麦克风权限，请在系统设置里允许';
      return;
    }
    this.voice.stopSpeak();      // 说话时打断正在朗读的回答
    this.listening = true;
    this.voiceStarting = false;
    this.partialText = '';
    this.voiceHint = '正在听…';

    const cb: AsrCallbacks = {
      onPartial: (t: string) => {
        this.partialText = t;
      },
      onFinal: (t: string) => {
        this.listening = false;
        this.partialText = '';
        this.voiceHint = '';
        if (t.trim().length > 0) {
          this.send(t);
        }
      },
      onError: (m: string) => {
        this.listening = false;
        this.partialText = '';
        this.voiceHint = m;
      }
    };
    const started = await this.voice.startAsr(cb);

    // 启动期间用户已经松手 → 立刻结束这次识别
    // （否则会一直录到静音超时，用户以为没反应）
    if (started && this.released) {
      this.voice.stopAsr();
    }
  }

  /**
   * 松开麦克风：结束识别
   *
   * 注意：不能只判断 this.listening——
   * 权限申请和引擎创建都是异步的，用户可能在那期间就松手了。
   * 所以记一个 released 标记，让 startVoice 启动完成后自己收尾。
   */
  private stopVoice(): void {
    this.released = true;
    if (!this.listening) {
      return;
    }
    this.listening = false;
    this.voice.stopAsr();
    // 兜底：设备没麦克风时引擎不会回调，界面会卡在「正在听…」
    // 所以等一段时间还没结果就自己复位并给出提示
    setTimeout(() => {
      if (this.partialText.length === 0 && this.voiceHint === '正在听…') {
        this.voiceHint = '没听到声音——模拟器通常没有麦克风，可以打字';
        this.partialText = '';
      }
    }, 2500);
  }

  /** 朗读一段回答 */
  private speakAnswer(text: string): void {
    if (!this.ttsOk || !this.autoSpeak) {
      return;
    }
    this.voice.speak(text, undefined, (m: string) => {
      this.voiceHint = m;
    });
  }

  /** 把存储的会话还原成气泡列表，并把纯文本历史灌进 Agent */
  private restoreBubbles(s: Session): void {
    const list: Bubble[] = [];
    const plain: PlainHistoryItem[] = [];
    for (let i = 0; i < s.messages.length; i++) {
      const m = s.messages[i];
      list.push({
        id: ++this.seq,
        role: m.role,
        text: m.text,
        loading: false,
        trace: m.trace
      });
      plain.push({ role: m.role, text: m.text });
    }
    this.bubbles = list;
    if (this.agent !== null) {
      this.agent.loadPlainHistory(plain);
    }
  }

  /** 只往界面加气泡，不写存储（用于恢复与开场白） */
  private pushBubbleNow(role: string, text: string, trace: string): void {
    const list = this.bubbles.slice();
    list.push({ id: ++this.seq, role, text, loading: false, trace });
    this.bubbles = list;
  }

  /** 切换会话 */
  private async openSession(id: string): Promise<void> {
    const s = await this.sessions.switchTo(id);
    if (s === null) {
      return;
    }
    this.restoreBubbles(s);
    this.showSessions = false;
    this.scrollToBottom();
  }

  /** 新建会话 */
  private async newSession(): Promise<void> {
    this.sessions.createSession();
    this.bubbles = [];
    if (this.agent !== null) {
      this.agent.clearHistory();
    }
    this.showSessions = false;
  }

  private async removeSession(id: string): Promise<void> {
    await this.sessions.remove(id);
    this.sessionList = this.sessions.list();
    // 删掉的正是当前会话时，界面要跟着切
    const cur = this.sessions.current();
    this.restoreBubbles(cur);
  }

  private refreshSessionList(): void {
    this.sessionList = this.sessions.list();
  }

  /** 保存设置：写进本地存储并重建 Agent */
  private async saveSettings(): Promise<void> {
    const key = this.keyDraft.trim();
    const handle = this.handleDraft.trim();
    if (key.length === 0) {
      this.settingsHint = '密钥不能为空';
      return;
    }
    await AppStorageUtil.setString(AppConfig.KEY_API_KEY, key);
    await AppStorageUtil.setString(AppConfig.KEY_HANDLE,
      handle.length > 0 ? handle : AppConfig.DEFAULT_HANDLE);
    this.settingsHint = '已保存';
    this.hasKey = true;
    this.showSettings = false;
    // 重建 Agent 让新密钥生效，但**保留当前对话**
    const plain: PlainHistoryItem[] = [];
    for (let i = 0; i < this.bubbles.length; i++) {
      const b = this.bubbles[i];
      if (b.role === 'user' || b.role === 'assistant') {
        plain.push({ role: b.role, text: b.text });
      }
    }
    const keep = this.bubbles;
    await this.initAgent();
    this.bubbles = keep;
    if (this.agent !== null) {
      this.agent.loadPlainHistory(plain);
    }
  }

  private pushBubble(role: string, text: string, trace: string): number {
    const id = ++this.seq;
    const list = this.bubbles.slice();
    list.push({ id, role, text, loading: false, trace });
    this.bubbles = list;
    return id;
  }

  /** 更新某条气泡（用于把「正在思考」替换成真实回答） */
  private updateBubble(id: number, text: string, trace: string, loading: boolean): void {
    const list: Bubble[] = [];
    for (let i = 0; i < this.bubbles.length; i++) {
      const b = this.bubbles[i];
      if (b.id === id) {
        list.push({ id: b.id, role: b.role, text, loading, trace });
      } else {
        list.push(b);
      }
    }
    this.bubbles = list;
  }

  private async send(text: string): Promise<void> {
    const content = text.trim();
    if (content.length === 0 || this.sending) {
      return;
    }
    if (this.agent === null) {
      return;
    }

    this.pushBubble('user', content, '');
    this.inputText = '';
    this.sending = true;
    // 用户消息先落盘——即使后面请求失败，问过的问题也不会丢
    await this.sessions.append('user', content, '');

    // 先放一条「正在…」的气泡，让等待可见
    const pendingId = this.pushBubble('assistant', '', '');
    this.updateBubble(pendingId, '', '', true);
    this.statusText = '正在想…';

    try {
      const run = await this.agent.run(content);

      // 把工具调用痕迹整理成一行小字
      const traceParts: string[] = [];
      for (let i = 0; i < run.steps.length; i++) {
        const s = run.steps[i];
        traceParts.push(`${s.ok ? '✓' : '✗'} ${s.tool}`);
      }
      const trace = traceParts.length > 0 ? `调用了：${traceParts.join('  ')}` : '';

      this.updateBubble(pendingId, run.answer, trace, false);
      this.statusText = '';
      await this.sessions.append('assistant', run.answer, trace);
      // 回答完自动朗读（可在设置里关）
      this.speakAnswer(run.answer);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const errText = `……出错了：${msg}`;
      this.updateBubble(pendingId, errText, '', false);
      this.statusText = '';
      await this.sessions.append('assistant', errText, '');
    } finally {
      this.sending = false;
      this.scrollToBottom();
    }
  }

  private scrollToBottom(): void {
    // 列表用 reverse 布局，最新在索引 0，所以滚到顶部即最新
    this.scroller.scrollEdge(Edge.Top);
  }

  private async loadProgress(): Promise<void> {
    this.progressText = '正在取数据…';
    try {
      if (this.companion === null) {
        this.progressText = '还没初始化';
        return;
      }
      await this.companion.ensureLoaded();
      const st = this.companion.getStats();
      if (st === null) {
        this.progressText = '还没有记录';
        return;
      }
      const info = this.companion.getUserInfo();
      const lines: string[] = [];
      lines.push(`累计解出 ${st.totalSolved} 道`);
      lines.push(`活跃 ${st.activeDays} 天`);
      lines.push(`${st.firstDay} 起`);
      if (st.currentStreak > 1) {
        lines.push(`连续 ${st.currentStreak} 天`);
      }
      if (st.hardestSolved > 0) {
        lines.push(`最高难度 ${st.hardestSolved}`);
      }
      if (info !== null && info.rating > 0) {
        lines.push(`当前 rating ${info.rating}（最高 ${info.maxRating}）`);
      }
      this.progressText = lines.join('\n');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.progressText = `取数据失败：${msg}`;
    }
  }

  // ------------------------------------------------------------ 子组件

  @Builder
  messageBubble(b: Bubble) {
    Row() {
      if (b.role === 'user') {
        Blank()
        Column() {
          Text(b.text)
            .fontSize(15)
            .fontColor('#FFFFFF')
            .lineHeight(22)
        }
        .padding({ left: 14, right: 14, top: 10, bottom: 10 })
        .backgroundColor('#2E6BE6')
        .borderRadius({ topLeft: 14, topRight: 14, bottomLeft: 14, bottomRight: 4 })
        .constraintSize({ maxWidth: '78%' })
      } else {
        Column() {
          if (b.loading) {
            Row() {
              LoadingProgress().width(16).height(16).color('#8A8A8A')
              Text(this.statusText.length > 0 ? this.statusText : '正在想…')
                .fontSize(14).fontColor('#8A8A8A').margin({ left: 8 })
            }
          } else {
            Text(b.text)
              .fontSize(15)
              .fontColor('#1A1A1A')
              .lineHeight(23)
            if (b.trace.length > 0) {
              Text(b.trace)
                .fontSize(11)
                .fontColor('#9A9A9A')
                .margin({ top: 6 })
            }
          }
        }
        .alignItems(HorizontalAlign.Start)
        .padding({ left: 14, right: 14, top: 10, bottom: 10 })
        .backgroundColor('#F4F5F7')
        .borderRadius({ topLeft: 14, topRight: 14, bottomLeft: 4, bottomRight: 14 })
        .constraintSize({ maxWidth: '82%' })
        Blank()
      }
    }
    .width('100%')
    .padding({ left: 14, right: 14, top: 6, bottom: 6 })
  }

  @Builder
  sessionsPanel() {
    Column() {
      Row() {
        Text('对话记录').fontSize(16).fontWeight(FontWeight.Medium)
        Blank()
        Text('新建').fontSize(13).fontColor('#2E6BE6')
          .padding({ left: 10, right: 10, top: 4, bottom: 4 })
          .onClick(() => { this.newSession(); })
        Text('关闭').fontSize(13).fontColor('#8A8A8A')
          .margin({ left: 12 })
          .onClick(() => { this.showSessions = false; })
      }
      .width('100%')

      if (this.sessionList.length === 0) {
        Text('还没有对话记录').fontSize(13).fontColor('#AAAAAA')
          .margin({ top: 14 }).width('100%')
      } else {
        List({ space: 0 }) {
          ForEach(this.sessionList, (s: Session) => {
            ListItem() {
              Row() {
                Column() {
                  Text(s.title)
                    .fontSize(14)
                    .fontColor(s.id === this.sessions.current().id ? '#2E6BE6' : '#1A1A1A')
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                  Text(`${s.updatedAt}  ·  ${s.messages.length} 条`)
                    .fontSize(11).fontColor('#9A9A9A').margin({ top: 3 })
                }
                .alignItems(HorizontalAlign.Start)
                .layoutWeight(1)

                Text('删').fontSize(12).fontColor('#C0C0C0')
                  .padding(6)
                  .onClick(() => { this.removeSession(s.id); })
              }
              .width('100%')
              .padding({ top: 10, bottom: 10 })
              .onClick(() => { this.openSession(s.id); })
            }
          }, (s: Session) => s.id)
        }
        .height(210)
        .margin({ top: 8 })
      }
    }
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#EEEEEE' })
  }

  @Builder
  settingsPanel() {
    Column() {
      Row() {
        Text('设置').fontSize(16).fontWeight(FontWeight.Medium)
        Blank()
        Text('关闭').fontSize(13).fontColor('#8A8A8A')
          .onClick(() => { this.showSettings = false; })
      }
      .width('100%')

      Text('API 密钥（DeepSeek）').fontSize(13).fontColor('#666666')
        .margin({ top: 14 }).width('100%')
      TextInput({ text: this.keyDraft, placeholder: 'sk-...' })
        .height(42).fontSize(14).type(InputType.Password)
        .backgroundColor('#F4F5F7').borderRadius(8)
        .margin({ top: 6 })
        .onChange((v: string) => { this.keyDraft = v; })

      Text('Codeforces 用户名').fontSize(13).fontColor('#666666')
        .margin({ top: 12 }).width('100%')
      TextInput({ text: this.handleDraft, placeholder: 'ganwuyu' })
        .height(42).fontSize(14)
        .backgroundColor('#F4F5F7').borderRadius(8)
        .margin({ top: 6 })
        .onChange((v: string) => { this.handleDraft = v; })

      Row() {
        Button('保存').fontSize(14).height(38)
          .backgroundColor('#2E6BE6').layoutWeight(1)
          .onClick(() => { this.saveSettings(); })
        if (this.settingsHint.length > 0) {
          Text(this.settingsHint).fontSize(12).fontColor('#2E6BE6')
            .margin({ left: 12 })
        }
      }
      .width('100%').margin({ top: 16 })

      Text('密钥只存在本机，不会上传。')
        .fontSize(11).fontColor('#AAAAAA').margin({ top: 10 }).width('100%')
    }
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .border({ width: { bottom: 1 }, color: '#EEEEEE' })
  }

  @Builder
  emptyState() {
    Column() {
      Text('贪心')
        .fontSize(28).fontWeight(FontWeight.Bold).fontColor('#1A1A1A')
      Text('算法世界里的精灵，陪你把题一道道过完')
        .fontSize(13).fontColor('#8A8A8A').margin({ top: 8 })
      Column() {
        ForEach(SUGGESTIONS, (s: string) => {
          Text(s)
            .fontSize(14)
            .fontColor('#2E6BE6')
            .padding({ left: 16, right: 16, top: 10, bottom: 10 })
            .margin({ top: 10 })
            .backgroundColor('#F0F4FF')
            .borderRadius(18)
            .onClick(() => {
              this.send(s);
            })
        }, (s: string) => s)
      }
      .margin({ top: 20 })
    }
    .width('100%')
    .layoutWeight(1)
    .justifyContent(FlexAlign.Center)
  }

  @Builder
  progressPanel() {
    Column() {
      Row() {
        Text('成长记录').fontSize(16).fontWeight(FontWeight.Medium)
        Blank()
        Text('关闭').fontSize(13).fontColor('#8A8A8A')
          .onClick(() => { this.showProgress = false; })
      }
      .width('100%')

      Text(this.progressText.length > 0 ? this.progressText : '点下面的按钮取数据')
        .fontSize(14).fontColor('#333333').lineHeight(22)
        .margin({ top: 12 })
        .width('100%')

      Button('刷新')
        .fontSize(13)
        .height(34)
        .backgroundColor('#2E6BE6')
        .margin({ top: 12 })
        .onClick(() => { this.loadProgress(); })
    }
    .width('100%')
    .padding(16)
    .backgroundColor('#FFFFFF')
    .borderRadius({ topLeft: 0, topRight: 0, bottomLeft: 12, bottomRight: 12 })
    .border({ width: { bottom: 1 }, color: '#EEEEEE' })
  }

  // ------------------------------------------------------------ 主结构

  build() {
    Column() {
      // 顶栏
      Row() {
        Column() {
          Text('贪心').fontSize(18).fontWeight(FontWeight.Bold).fontColor('#1A1A1A')
        }
        .alignItems(HorizontalAlign.Start)

        Blank()

        Button('记录')
          .fontSize(13).height(32).backgroundColor('#F4F5F7').fontColor('#666666')
          .onClick(() => {
            const next = !this.showSessions;
            this.showSessions = next;
            if (next) {
              this.refreshSessionList();
              this.showProgress = false;
              this.showSettings = false;
            }
          })

        Button('成长')
          .fontSize(13).height(32).margin({ left: 8 })
          .backgroundColor('#F0F4FF').fontColor('#2E6BE6')
          .onClick(() => {
            const next = !this.showProgress;
            this.showProgress = next;
            if (next) {
              this.showSessions = false;
              this.showSettings = false;
              if (this.progressText.length === 0) {
                this.loadProgress();
              }
            }
          })

        Button('设置')
          .fontSize(13).height(32).margin({ left: 8 })
          .backgroundColor('#F4F5F7').fontColor('#666666')
          .onClick(() => {
            this.showSettings = !this.showSettings;
            if (this.showSettings) {
              this.showSessions = false;
              this.showProgress = false;
            }
          })
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 10, bottom: 10 })
      .backgroundColor('#FFFFFF')

      if (this.showSessions) {
        this.sessionsPanel()
      }

      if (this.showSettings) {
        this.settingsPanel()
      }

      if (this.showProgress) {
        this.progressPanel()
      }

      // 消息区
      if (this.bubbles.length === 0) {
        this.emptyState()
      } else {
        List({ space: 0, scroller: this.scroller }) {
          ForEach(this.bubbles, (b: Bubble) => {
            ListItem() {
              this.messageBubble(b)
            }
          }, (b: Bubble) => `${b.id}-${b.loading}`)
        }
        .width('100%')
        .layoutWeight(1)
        .backgroundColor('#FAFAFA')
        .onAppear(() => { this.scrollToBottom(); })
      }

      // 语音提示条（说话中 / 出错时显示）
      if (this.listening || this.voiceHint.length > 0) {
        Row() {
          if (this.listening) {
            LoadingProgress().width(14).height(14).color('#E6483C')
          }
          Text(this.listening
            ? (this.partialText.length > 0 ? this.partialText : '正在听…')
            : this.voiceHint)
            .fontSize(13)
            .fontColor(this.listening ? '#E6483C' : '#999999')
            .margin({ left: this.listening ? 8 : 0 })
            .layoutWeight(1)
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .padding({ left: 18, right: 18, top: 6, bottom: 6 })
        .backgroundColor('#FFF8F8')
      }

      // 输入区
      Row() {
        TextInput({ text: this.inputText, placeholder: '说点什么…' })
          .layoutWeight(1)
          .height(42)
          .fontSize(15)
          .backgroundColor('#F4F5F7')
          .borderRadius(21)
          .padding({ left: 16, right: 16 })
          .enabled(!this.sending)
          .onChange((v: string) => { this.inputText = v; })
          .onSubmit(() => { this.send(this.inputText); })

        // 语音按钮：点一下开始、再点一下结束
        //
        // 为什么不做成「按住说话」：
        //   按住需要 Down/Up 配对，而权限申请和引擎创建是异步的，
        //   首次使用时用户往往在弹窗期间就松手了，容易「没反应」。
        //   点按式更宽容：两种操作都支持，也更容易在模拟器上验证。
        if (this.voiceOk) {
          Button(this.listening ? '停' : '说')
            .width(46).height(42).fontSize(14)
            .margin({ left: 8 })
            .backgroundColor(this.listening ? '#E6483C' : '#EEF2FF')
            .fontColor(this.listening ? '#FFFFFF' : '#2E6BE6')
            .enabled(!this.sending)
            .onClick(() => {
              if (this.listening) {
                this.stopVoice();
              } else {
                this.startVoice();
              }
            })
        }

        Button(this.sending ? '…' : '发')
          .width(56).height(42).fontSize(15)
          .backgroundColor(this.sending ? '#C9D3E5' : '#2E6BE6')
          .margin({ left: 8 })
          .enabled(!this.sending)
          .onClick(() => { this.send(this.inputText); })
      }
      .width('100%')
      .padding({ left: 14, right: 14, top: 10, bottom: 10 })
      .backgroundColor('#FFFFFF')
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#FAFAFA')
  }
}

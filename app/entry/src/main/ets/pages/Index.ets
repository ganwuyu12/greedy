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

import { Agent, AgentConfig, ChatMessage, ToolRegistry } from '../core/Agent';
import { AppConfig, AppStorageUtil } from '../core/Config';
import { buildRegistry, CompanionService, NoteStore } from '../core/Tools';
import { prompt as personaPrompt } from '../core/Persona';
import { common } from '@kit.AbilityKit';

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

  private seq: number = 0;
  private agent: Agent | null = null;
  private registry: ToolRegistry | null = null;
  private companion: CompanionService | null = null;
  private notes: NoteStore = new NoteStore();
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

    this.companion = new CompanionService(handle);
    this.registry = buildRegistry(this.companion, this.notes);

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

    if (apiKey.length === 0) {
      this.pushBubble('assistant',
        '哼，你还没配密钥呢……去设置里填一下，不然本小姐没法说话。', '');
    } else {
      this.pushBubble('assistant', '来了？说吧，今天又卡在哪了。', '');
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
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.updateBubble(pendingId, `……出错了：${msg}`, '', false);
      this.statusText = '';
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

        Button('成长')
          .fontSize(13).height(32).backgroundColor('#F0F4FF').fontColor('#2E6BE6')
          .onClick(() => {
            const next = !this.showProgress;
            this.showProgress = next;
            if (next && this.progressText.length === 0) {
              this.loadProgress();
            }
          })
      }
      .width('100%')
      .padding({ left: 16, right: 16, top: 10, bottom: 10 })
      .backgroundColor('#FFFFFF')

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

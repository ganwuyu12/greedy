/**
 * 会话持久化
 *
 * 目标（课程要求）：会话记录持久化 + 支持回看。
 *
 * 设计上要回答三个问题：
 *
 * 1. **存什么**
 *    只存「用户可见的对话」（问与答），不存工具调用的中间消息。
 *    理由：中间消息体积大（一次工具结果可能几千字符），
 *    而且结构脆弱——assistant(tool_calls) 与 tool(tool_call_id) 必须成对，
 *    跨会话恢复时一旦对不上，接口会直接拒绝（400）。
 *    重放对话时只需让模型知道「之前聊过什么」，工具结果不必原样恢复。
 *
 * 2. **存多少**
 *    preferences 单值有大小上限，长对话必须裁剪。
 *    策略：按条数保留最近 N 条，且单条超长时截断。
 *    宁可丢早期内容，也不能写失败——写失败会导致整个会话丢失。
 *
 * 3. **多会话**
 *    存一个会话列表 + 每个会话的消息。
 *    当前会话 ID 单独记，启动时自动恢复。
 */

import { AppStorageUtil, AppConfig } from './Config';

/** 一条对话消息（用户可见的） */
export interface StoredMessage {
  role: string;        // 'user' | 'assistant'
  text: string;
  at: string;          // HH:MM
  trace: string;       // 工具调用痕迹（可选，展示用）
}

/** 一个会话 */
export interface Session {
  id: string;
  title: string;
  createdAt: string;   // YYYY-MM-DD HH:MM
  updatedAt: string;
  messages: StoredMessage[];
}

/** 存盘的顶层结构 */
interface SessionStoreData {
  version: number;
  currentId: string;
  sessions: Session[];
}

const MAX_SESSIONS = 20;          // 最多保留 20 个会话
const MAX_MESSAGES = 60;          // 每个会话最多 60 条消息
const MAX_TEXT_LEN = 2000;        // 单条消息最长 2000 字符

export class SessionStore {
  private data: SessionStoreData = { version: 1, currentId: '', sessions: [] };
  private loaded: boolean = false;

  // ------------------------------------------------------------ 生命周期

  async load(): Promise<void> {
    if (this.loaded) {
      return;
    }
    const raw = await AppStorageUtil.getString(AppConfig.KEY_CHAT_HISTORY);
    if (raw.length > 0) {
      try {
        const parsed = JSON.parse(raw) as SessionStoreData;
        if (parsed.sessions !== undefined) {
          this.data = parsed;
        }
      } catch (e) {
        // 数据损坏时不要卡死——丢弃并从空的开始
        this.data = { version: 1, currentId: '', sessions: [] };
      }
    }
    this.loaded = true;
  }

  private async persist(): Promise<void> {
    const trimmed = this.trim(this.data);
    try {
      await AppStorageUtil.setString(
        AppConfig.KEY_CHAT_HISTORY, JSON.stringify(trimmed));
    } catch (e) {
      // 写失败不能影响正在进行的对话，只是这次没存上
    }
  }

  /**
   * 裁剪到可存储的规模
   *
   * 从最新往前保留。注意：会话列表按 updatedAt 排序后保留前 MAX_SESSIONS 个。
   */
  private trim(d: SessionStoreData): SessionStoreData {
    const sessions: Session[] = [];
    for (let i = 0; i < d.sessions.length; i++) {
      const s = d.sessions[i];
      let msgs = s.messages;
      if (msgs.length > MAX_MESSAGES) {
        msgs = msgs.slice(msgs.length - MAX_MESSAGES);
      }
      const kept: StoredMessage[] = [];
      for (let j = 0; j < msgs.length; j++) {
        const m = msgs[j];
        let text = m.text;
        if (text.length > MAX_TEXT_LEN) {
          text = text.substring(0, MAX_TEXT_LEN) + '……（已截断）';
        }
        kept.push({ role: m.role, text: text, at: m.at, trace: m.trace });
      }
      sessions.push({
        id: s.id,
        title: s.title,
        createdAt: s.createdAt,
        updatedAt: s.updatedAt,
        messages: kept
      });
    }
    sessions.sort((a: Session, b: Session) =>
      a.updatedAt < b.updatedAt ? 1 : (a.updatedAt > b.updatedAt ? -1 : 0));
    const finalSessions = sessions.length > MAX_SESSIONS
      ? sessions.slice(0, MAX_SESSIONS) : sessions;
    return { version: 1, currentId: d.currentId, sessions: finalSessions };
  }

  // ------------------------------------------------------------ 会话操作

  /** 当前会话；没有就建一个 */
  current(): Session {
    let s = this.findById(this.data.currentId);
    if (s === null) {
      s = this.createSession();
    }
    return s;
  }

  findById(id: string): Session | null {
    for (let i = 0; i < this.data.sessions.length; i++) {
      if (this.data.sessions[i].id === id) {
        return this.data.sessions[i];
      }
    }
    return null;
  }

  /** 新建会话并切为当前 */
  createSession(): Session {
    const now = new Date();
    const id = `${now.getTime()}`;
    const s: Session = {
      id,
      title: '新的对话',
      createdAt: SessionStore.fmt(now),
      updatedAt: SessionStore.fmt(now),
      messages: []
    };
    this.data.sessions.unshift(s);
    this.data.currentId = id;
    return s;
  }

  /** 切换当前会话 */
  async switchTo(id: string): Promise<Session | null> {
    const s = this.findById(id);
    if (s === null) {
      return null;
    }
    this.data.currentId = id;
    await this.persist();
    return s;
  }

  /** 追加一条消息并落盘 */
  async append(role: string, text: string, trace: string): Promise<void> {
    const s = this.current();
    const d = new Date();
    s.messages.push({ role, text, at: SessionStore.fmtTime(d), trace });
    s.updatedAt = SessionStore.fmt(d);
    // 首条用户消息拿来当标题，便于在列表里认出来
    if (s.title === '新的对话' && role === 'user') {
      s.title = text.length > 18 ? `${text.substring(0, 18)}…` : text;
    }
    await this.persist();
  }

  /** 会话列表（按最近更新排序） */
  list(): Session[] {
    const out = this.data.sessions.slice();
    out.sort((a: Session, b: Session) =>
      a.updatedAt < b.updatedAt ? 1 : (a.updatedAt > b.updatedAt ? -1 : 0));
    return out;
  }

  /** 删除会话 */
  async remove(id: string): Promise<void> {
    const kept: Session[] = [];
    for (let i = 0; i < this.data.sessions.length; i++) {
      if (this.data.sessions[i].id !== id) {
        kept.push(this.data.sessions[i]);
      }
    }
    this.data.sessions = kept;
    if (this.data.currentId === id) {
      this.data.currentId = kept.length > 0 ? kept[0].id : '';
    }
    await this.persist();
  }

  /** 清空当前会话的消息 */
  async clearCurrent(): Promise<void> {
    const s = this.current();
    s.messages = [];
    s.title = '新的对话';
    s.updatedAt = SessionStore.fmt(new Date());
    await this.persist();
  }

  /**
   * 取出用于「重放」的历史
   *
   * Agent 的上下文里只放文本问答，不放工具中间消息——见文件头说明。
   */
  replayHistory(): StoredMessage[] {
    const s = this.current();
    return s.messages.slice();
  }

  // ------------------------------------------------------------ 工具

  private static pad(n: number): string {
    return n < 10 ? `0${n}` : `${n}`;
  }

  /** YYYY-MM-DD HH:MM */
  static fmt(d: Date): string {
    return `${d.getFullYear()}-${SessionStore.pad(d.getMonth() + 1)}-` +
           `${SessionStore.pad(d.getDate())} ` +
           `${SessionStore.pad(d.getHours())}:${SessionStore.pad(d.getMinutes())}`;
  }

  /** HH:MM */
  static fmtTime(d: Date): string {
    return `${SessionStore.pad(d.getHours())}:${SessionStore.pad(d.getMinutes())}`;
  }
}

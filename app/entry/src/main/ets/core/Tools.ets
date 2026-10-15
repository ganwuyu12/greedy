/**
 * 工具集：把「贪心」的能力注册成可调用的工具
 *
 * 工具的选择标准是「陪伴」而不是「教练」：
 *   - 记成长、看里程碑、查知识点、整理题解 ✅
 *   - 分析薄弱点、评判水平、下训练指令 ❌
 *
 * 工具分三类：
 *   1. 成长类：get_progress / get_milestones / get_recent_log
 *   2. 知识类：search_wiki（检索 OI Wiki 词条）
 *   3. 记录类：save_note（把想法存下来）
 */

import { http } from '@kit.NetworkKit';
import { ToolDef, ToolRegistry } from './Agent';
import { CFClient, PracticeLog, PracticeDay, ProgressStats, Submission, UserInfo } from './CFClient';
import { AppConfig, AppStorageUtil } from './Config';

/**
 * 陪伴数据服务
 *
 * 把 CF 数据和成长统计包起来，工具只依赖这里，不直接碰网络。
 * 好处：工具可以单独测试，换数据源也不用改工具。
 */
export class CompanionService {
  private client: CFClient;
  private submissions: Submission[] = [];
  private days: PracticeDay[] = [];
  private stats: ProgressStats | null = null;
  private info: UserInfo | null = null;
  private loaded: boolean = false;
  private loadError: string = '';
  private loading: Promise<void> | null = null;
  private metaLoading: Promise<void> | null = null;
  private metaLoaded: boolean = false;

  constructor(handle: string) {
    this.client = new CFClient(handle);
  }

  /**
   * 拉一次数据并算好统计（避免每次问都重新拉）
   *
   * 三个要点：
   *   1. 不拉题库表——成长记录不需要标签，省掉一次 2 MB 的大请求
   *      （之前每次都拉，在移动网络上直接超时）
   *   2. 并发去重——同一轮对话里多个工具都调它，只该拉一次
   *   3. 失败要**记住原因并抛出**，不能静默吞掉
   *      之前吞掉异常，工具返回「还没成长记录」，把真实故障掩盖了，
   *      排查时完全看不到超时信息
   */
  async ensureLoaded(): Promise<void> {
    if (this.loaded) {
      return;
    }
    if (this.loading !== null) {
      return await this.loading;
    }
    this.loading = this.doLoad();
    try {
      await this.loading;
    } finally {
      this.loading = null;
    }
    if (this.loadError.length > 0) {
      throw new Error(this.loadError);
    }
  }

  private async doLoad(): Promise<void> {
    this.loadError = '';
    try {
      // 第一步：只拉提交记录（快，约 2 秒）——成长记录所需的信息够了
      this.submissions = await this.client.submissions(1, false);
      this.days = PracticeLog.build(this.submissions);
      this.stats = PracticeLog.stats(this.days);
      this.loaded = true;
    } catch (e) {
      this.loadError = e instanceof Error ? e.message : String(e);
      return;
    }
    // 用户信息拿不到不影响成长记录，单独兜住
    try {
      this.info = await this.client.userInfo();
    } catch (e) {
      this.info = null;
    }
    // 第二步：后台补难度与标签（要拉全量题库，约 2 MB，慢）
    // 不 await——成长记录不该为它等待
    this.metaLoading = this.loadMeta();
  }

  /**
   * 补全难度与标签
   *
   * 为什么必须补：user.status 里 problem.rating 是 null，
   * 只有题库表才有难度。缺了它「里程碑」和难度分布就没有数据。
   */
  private async loadMeta(): Promise<void> {
    if (this.metaLoaded) {
      return;
    }
    try {
      const full = await this.client.submissions(1, true);
      if (full.length > 0) {
        this.submissions = full;
        this.days = PracticeLog.build(this.submissions);
        this.stats = PracticeLog.stats(this.days);
      }
      this.metaLoaded = true;
    } catch (e) {
      // 补全失败不影响已有数据，只是没有难度
      this.metaLoaded = false;
    }
  }

  /** 等难度数据补全（需要难度的工具调它） */
  async ensureMeta(): Promise<void> {
    if (this.metaLoading !== null) {
      await this.metaLoading;
    }
  }

  /** 强制重新拉取（用户下拉刷新时用） */
  invalidate(): void {
    this.loaded = false;
    this.loadError = '';
  }

  getStats(): ProgressStats | null {
    return this.stats;
  }

  getUserInfo(): UserInfo | null {
    return this.info;
  }

  getDays(): PracticeDay[] {
    return this.days;
  }

  getSubmissions(): Submission[] {
    return this.submissions;
  }
}

/** 把日期字符串转成「几天前」这种更好读的说法 */
function dayLabel(date: string, today: string): string {
  if (date === today) {
    return '今天';
  }
  const d1 = new Date(`${date}T00:00:00`);
  const d2 = new Date(`${today}T00:00:00`);
  const diff = Math.round((d2.getTime() - d1.getTime()) / 86400000);
  if (diff === 1) {
    return '昨天';
  }
  if (diff > 1 && diff < 7) {
    return `${diff} 天前`;
  }
  return date;
}

function todayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** 难度分档（用于里程碑展示） */
const TIERS: number[] = [800, 1000, 1200, 1400, 1600, 1800, 2000, 2200];

/**
 * 注册全部工具
 */
export function buildRegistry(svc: CompanionService, notes: NoteStore): ToolRegistry {
  const reg = new ToolRegistry();

  // ---------------- 成长类 ----------------

  const progressTool: ToolDef = {
    name: 'get_progress',
    description: '查看成长记录：累计做了多少题、活跃多少天、最近一次做了什么。' +
                 '用户问「我最近怎么样」「我做了多少题」时使用',
    params: [],
    run: async (_args: Map<string, Object>): Promise<string> => {
      await svc.ensureLoaded();
      const st = svc.getStats();
      if (st === null) {
        return '还没有成长记录。';
      }
      const days = svc.getDays();
      const lines: string[] = [];
      if (days.length > 0) {
        const last = days[days.length - 1];
        lines.push(`最近一次是${dayLabel(last.date, todayStr())}，解了 ${last.solvedCount} 道`);
        if (last.solvedKeys.length > 0) {
          lines.push(`  ${last.solvedKeys.join('、')}`);
        }
        if (last.maxRating > 0) {
          lines.push(`  当天最难：${last.maxRating}`);
        }
        lines.push('');
      }
      lines.push(`累计解出 ${st.totalSolved} 道，活跃 ${st.activeDays} 天`);
      lines.push(`从 ${st.firstDay} 到 ${st.lastDay}`);
      if (st.currentStreak > 1) {
        lines.push(`连续 ${st.currentStreak} 天有通过`);
      }
      if (st.hardestSolved > 0) {
        lines.push(`最高难度 ${st.hardestSolved}`);
      }
      const info = svc.getUserInfo();
      if (info !== null && info.rating > 0) {
        lines.push('');
        lines.push(`当前 rating ${info.rating}（最高 ${info.maxRating}）`);
      }
      return lines.join('\n');
    }
  };
  reg.register(progressTool);

  const milestoneTool: ToolDef = {
    name: 'get_milestones',
    description: '查看里程碑：首次解出各个难度档位的日期。' +
                 '用户问「我的里程碑」「我什么时候第一次过 X 分」时使用',
    params: [],
    run: async (_args: Map<string, Object>): Promise<string> => {
      await svc.ensureLoaded();
      await svc.ensureMeta();       // 里程碑要难度数据，等它补全
      const subs = svc.getSubmissions();
      const solved = subs.filter((s: Submission) => s.verdict === 'OK');
      solved.sort((a: Submission, b: Submission) =>
        a.creationTimeSeconds - b.creationTimeSeconds);

      const firstByTier = new Map<number, string>();
      for (let i = 0; i < solved.length; i++) {
        const s = solved[i];
        if (s.problemRating <= 0) {
          continue;
        }
        const date = PracticeLog.practiceDate(s.creationTimeSeconds);
        for (let t = 0; t < TIERS.length; t++) {
          const tier = TIERS[t];
          if (s.problemRating >= tier && !firstByTier.has(tier)) {
            firstByTier.set(tier, date);
          }
        }
      }

      if (firstByTier.size === 0) {
        return '还没有难度里程碑记录。';
      }
      const lines: string[] = ['你走过的路：'];
      for (let t = 0; t < TIERS.length; t++) {
        const tier = TIERS[t];
        const d = firstByTier.get(tier);
        if (d !== undefined) {
          lines.push(`  首次解出 ${tier}+   ${d}`);
        }
      }
      const st = svc.getStats();
      if (st !== null && st.hardestSolved > 0) {
        lines.push('');
        lines.push(`目前最高：${st.hardestSolved}`);
      }
      return lines.join('\n');
    }
  };
  reg.register(milestoneTool);

  const recentTool: ToolDef = {
    name: 'get_recent_log',
    description: '查看最近几天的练习详情（解了哪些题、难度、标签）',
    params: [
      { name: 'days', type: 'integer', description: '看最近几天，默认 3', required: false }
    ],
    run: async (args: Map<string, Object>): Promise<string> => {
      await svc.ensureLoaded();
      const raw = args.get('days');
      const n: number = typeof raw === 'number' ? raw : 3;
      const all = svc.getDays();
      if (all.length === 0) {
        return '还没有记录。';
      }
      const take = all.slice(Math.max(0, all.length - n));
      const lines: string[] = [];
      for (let i = take.length - 1; i >= 0; i--) {
        const d = take[i];
        lines.push(`${d.date}（${dayLabel(d.date, todayStr())}）解出 ${d.solvedCount} 道`);
        lines.push(`  ${d.solvedKeys.join('、')}`);
      }
      return lines.join('\n');
    }
  };
  reg.register(recentTool);

  // ---------------- 知识类 ----------------

  const wikiTool: ToolDef = {
    name: 'search_wiki',
    description: '检索算法知识库（OI Wiki），回答算法概念、原理、复杂度等问题时使用',
    params: [
      { name: 'query', type: 'string', description: '检索关键词，如「线段树」「数位DP」',
        required: true }
    ],
    run: async (args: Map<string, Object>): Promise<string> => {
      const q = args.get('query');
      const query: string = typeof q === 'string' ? q : '';
      if (query.length === 0) {
        return JSON.stringify({ error: '缺少 query 参数' });
      }
      // 知识库检索由 Python 侧服务提供（索引约 42 MB，不适合打进 App）
      const base = AppConfig.WIKI_ENDPOINT;
      if (base.length === 0) {
        return '知识库检索未配置：请在 core/Config.ets 里设置 WIKI_ENDPOINT。';
      }
      return await httpGetText(`${base}?q=${encodeURIComponent(query)}`);
    }
  };
  reg.register(wikiTool);

  // ---------------- 记录类 ----------------

  const noteTool: ToolDef = {
    name: 'save_note',
    description: '把一段想法或题解要点存下来，之后可以回看',
    params: [
      { name: 'title', type: 'string', description: '标题', required: true },
      { name: 'content', type: 'string', description: '内容', required: true }
    ],
    run: async (args: Map<string, Object>): Promise<string> => {
      const t = args.get('title');
      const c = args.get('content');
      const title: string = typeof t === 'string' ? t : '';
      const content: string = typeof c === 'string' ? c : '';
      if (title.length === 0 || content.length === 0) {
        return JSON.stringify({ error: 'title 和 content 都不能为空' });
      }
      await notes.add(title, content);
      return `已记下「${title}」`;
    }
  };
  reg.register(noteTool);

  const listNotesTool: ToolDef = {
    name: 'list_notes',
    description: '查看之前记下的笔记标题',
    params: [],
    run: async (_args: Map<string, Object>): Promise<string> => {
      const all = await notes.list();
      if (all.length === 0) {
        return '还没有记过东西。';
      }
      const lines: string[] = [];
      for (let i = 0; i < all.length; i++) {
        lines.push(`${i + 1}. ${all[i].title}（${all[i].createdAt}）`);
      }
      return lines.join('\n');
    }
  };
  reg.register(listNotesTool);

  // ---------------- 辅助类 ----------------

  const dateTool: ToolDef = {
    name: 'get_date',
    description: '获取今天的日期（YYYY-MM-DD）。需要日期时必须调用，不要自己编',
    params: [],
    run: async (_args: Map<string, Object>): Promise<string> => {
      const d = new Date();
      const y = d.getFullYear();
      const m = `${d.getMonth() + 1}`.padStart(2, '0');
      const day = `${d.getDate()}`.padStart(2, '0');
      return `${y}-${m}-${day}`;
    }
  };
  reg.register(dateTool);

  return reg;
}

// ---------------------------------------------------------------- 辅助

export interface Note {
  title: string;
  content: string;
  createdAt: string;
}

/**
 * 笔记存储
 *
 * 长期记忆的落点：跨会话保留用户记下的东西。
 * 用 preferences（键值存储）而不是数据库，因为这个量级不需要。
 */
export class NoteStore {
  private items: Note[] = [];
  private loaded: boolean = false;

  async load(): Promise<void> {
    if (this.loaded) {
      return;
    }
    const raw = await AppStorageUtil.getString(AppConfig.KEY_NOTES);
    if (raw.length > 0) {
      try {
        this.items = JSON.parse(raw) as Note[];
      } catch (e) {
        this.items = [];
      }
    }
    this.loaded = true;
  }

  async add(title: string, content: string): Promise<void> {
    await this.load();
    const d = new Date();
    const createdAt = `${d.getFullYear()}-${`${d.getMonth() + 1}`.padStart(2, '0')}-` +
                      `${`${d.getDate()}`.padStart(2, '0')}`;
    this.items.push({ title, content, createdAt });
    await AppStorageUtil.setString(AppConfig.KEY_NOTES, JSON.stringify(this.items));
  }

  async list(): Promise<Note[]> {
    await this.load();
    return this.items;
  }
}

/** 简单的 HTTP GET（返回文本），失败时返回可读的错误说明 */
export async function httpGetText(url: string): Promise<string> {
  const req = http.createHttp();
  try {
    const resp = await req.request(url, {
      method: http.RequestMethod.GET,
      connectTimeout: 15000,
      readTimeout: 30000
    });
    if (resp.responseCode !== 200) {
      return JSON.stringify({ error: `知识库服务返回 HTTP ${resp.responseCode}` });
    }
    return resp.result as string;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return JSON.stringify({ error: `知识库请求失败：${msg}` });
  } finally {
    req.destroy();
  }
}

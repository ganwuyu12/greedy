/**
 * Codeforces 数据层
 *
 * 对应 Python 侧的 cf_client.py + companion.py，为跨端应用提供数据能力。
 *
 * 三个必须处理的约束（与 Python 版一致）：
 *   1. 限流：官方要求每 2 秒最多 1 次请求，超了会被临时拒绝
 *   2. 容错：网络失败要退避重试，识别 FAILED 状态
 *   3. 缓存：结果落本地，避免重复拉全量数据（题库约 2 MB）
 *
 * 说明：ArkTS 是强类型的 TypeScript 子集，不支持 any/unknown 做任意操作，
 *       所以所有接口数据都用显式 interface 声明。
 */

import { http } from '@kit.NetworkKit';
import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';

const API_BASE = 'https://codeforces.com/api';
const MIN_INTERVAL_MS = 2000;      // 官方限制：每 2 秒最多 1 次
const MAX_TRIES = 3;
const TIMEOUT_MS = 20000;

/** 提交记录 */
export interface Submission {
  id: number;
  creationTimeSeconds: number;
  verdict: string;
  contestId: number;
  index: string;
  problemName: string;
  problemRating: number;
  problemTags: string[];
}

/** 参赛记录 */
export interface RatingChange {
  contestId: number;
  contestName: string;
  rank: number;
  oldRating: number;
  newRating: number;
  ratingUpdateTimeSeconds: number;
}

/** 用户信息 */
export interface UserInfo {
  handle: string;
  rating: number;
  maxRating: number;
  rank: string;
}

/** 一场练习日的聚合 */
export interface PracticeDay {
  date: string;                 // YYYY-MM-DD
  solvedCount: number;
  attemptedCount: number;
  maxRating: number;
  solvedKeys: string[];
}

/** 成长统计 */
export interface ProgressStats {
  totalSolved: number;
  activeDays: number;
  currentStreak: number;
  firstDay: string;
  lastDay: string;
  hardestSolved: number;
}

/** CF 接口原始返回中，我们只关心这几个字段 */
interface RawProblem {
  contestId?: number;
  index?: string;
  name?: string;
  rating?: number;
  tags?: string[];
}

interface RawSubmission {
  id: number;
  creationTimeSeconds: number;
  verdict?: string;
  problem: RawProblem;
}

interface RawProblemEntry {
  contestId?: number;
  index?: string;
  name?: string;
  rating?: number;
  tags?: string[];
}

interface ProblemsetResult {
  problems: RawProblemEntry[];
}

interface CFResponse<T> {
  status: string;
  comment?: string;
  result?: T;
}

/**
 * Codeforces 客户端
 *
 * 为什么做成类：限流需要「上次请求时间」这个状态，
 * 做成模块级全局变量在多处调用时容易打架，而类的实例能明确持有它。
 */
export class CFClient {
  private lastCallMs: number = 0;
  private handle: string;

  constructor(handle: string) {
    this.handle = handle;
  }

  /** 保证两次请求间隔 >= 2 秒 */
  private async throttle(): Promise<void> {
    const now = Date.now();
    const wait = MIN_INTERVAL_MS - (now - this.lastCallMs);
    if (wait > 0) {
      await this.sleep(wait);
    }
    this.lastCallMs = Date.now();
  }

  private sleep(ms: number): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(() => {
        resolve();
      }, ms);
    });
  }

  /** 发一次请求，带重试 */
  private async get<T>(method: string, params: string): Promise<T> {
    const url = params.length > 0 ? `${API_BASE}/${method}?${params}` : `${API_BASE}/${method}`;
    let lastError = '';

    for (let attempt = 1; attempt <= MAX_TRIES; attempt++) {
      await this.throttle();
      try {
        const req = http.createHttp();
        const resp = await req.request(url, {
          method: http.RequestMethod.GET,
          header: { 'User-Agent': 'greedy-companion/0.1' },
          connectTimeout: TIMEOUT_MS,
          readTimeout: TIMEOUT_MS
        });
        req.destroy();

        if (resp.responseCode !== 200) {
          lastError = `HTTP ${resp.responseCode}`;
          await this.sleep(MIN_INTERVAL_MS * attempt);
          continue;
        }

        const body = resp.result as string;
        const parsed: CFResponse<T> = JSON.parse(body) as CFResponse<T>;
        if (parsed.status !== 'OK') {
          const comment: string = parsed.comment ?? '未知原因';
          // 限流是临时的，值得重试；参数错误不值得
          if (comment.toLowerCase().indexOf('limit') >= 0 && attempt < MAX_TRIES) {
            lastError = comment;
            await this.sleep(MIN_INTERVAL_MS * (attempt + 1));
            continue;
          }
          throw new Error(`${method} 失败：${comment}`);
        }
        if (parsed.result === undefined) {
          throw new Error(`${method} 返回为空`);
        }
        return parsed.result;
      } catch (e) {
        lastError = e instanceof Error ? e.message : String(e);
        if (attempt < MAX_TRIES) {
          await this.sleep(MIN_INTERVAL_MS * attempt);
        }
      }
    }
    throw new Error(`${method} 请求失败：${lastError}`);
  }

  // ------------------------------------------------------------ 公开接口

  async userInfo(): Promise<UserInfo | null> {
    const raw = await this.get<UserInfo[]>(
      'user.info', `handles=${encodeURIComponent(this.handle)}`);
    return raw.length > 0 ? raw[0] : null;
  }

  async userRating(): Promise<RatingChange[]> {
    return await this.get<RatingChange[]>(
      'user.rating', `handle=${encodeURIComponent(this.handle)}`);
  }

  /**
   * 拉提交记录，并补上题目名与官方标签
   *
   * CF 的 user.status 只给 contestId + index，不给题目名和标签。
   * 要按标签统计、要显示题名，必须去题库表里查。
   */
  async submissions(maxPages: number = 2): Promise<Submission[]> {
    const pageSize = 1000;
    const all: RawSubmission[] = [];

    for (let page = 0; page < maxPages; page++) {
      const from = page * pageSize + 1;
      const part = await this.get<RawSubmission[]>(
        'user.status',
        `handle=${encodeURIComponent(this.handle)}&from=${from}&count=${pageSize}`);
      if (part.length === 0) {
        break;
      }
      for (let i = 0; i < part.length; i++) {
        all.push(part[i]);
      }
      if (part.length < pageSize) {
        break;
      }
    }

    const problemset = await this.get<ProblemsetResult>('problemset.problems', '');
    const metaMap = new Map<string, RawProblemEntry>();
    for (let i = 0; i < problemset.problems.length; i++) {
      const p = problemset.problems[i];
      if (p.contestId === undefined || p.index === undefined) {
        continue;
      }
      metaMap.set(`${p.contestId}${p.index}`, p);
    }

    const out: Submission[] = [];
    for (let i = 0; i < all.length; i++) {
      const s = all[i];
      const cid = s.problem.contestId ?? 0;
      const idx = s.problem.index ?? '';
      const key = `${cid}${idx}`;
      const meta = metaMap.get(key);
      out.push({
        id: s.id,
        creationTimeSeconds: s.creationTimeSeconds,
        verdict: s.verdict ?? 'UNKNOWN',
        contestId: cid,
        index: idx,
        problemName: meta?.name ?? s.problem.name ?? '',
        problemRating: meta?.rating ?? s.problem.rating ?? 0,
        problemTags: meta?.tags ?? s.problem.tags ?? []
      });
    }
    return out;
  }
}

/**
 * 从提交记录构建练习日志
 *
 * 关键设计：按「练习日」归档，深夜 0–5 点的提交算前一天。
 * 理由：比赛常在深夜开始、跨零点结束，不这样处理会把一场比赛劈成两天，
 *      连续天数也会断掉。
 */
export class PracticeLog {
  private static readonly NIGHT_CUTOFF_HOUR = 5;

  /** 把时间戳归到练习日 */
  static practiceDate(ts: number): string {
    const d = new Date(ts * 1000);
    // 深夜的提交算前一天
    if (d.getHours() < PracticeLog.NIGHT_CUTOFF_HOUR) {
      d.setDate(d.getDate() - 1);
    }
    const y = d.getFullYear();
    const m = `${d.getMonth() + 1}`.padStart(2, '0');
    const day = `${d.getDate()}`.padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  /** 按题目聚合，得到每天的记录 */
  static build(submissions: Submission[]): PracticeDay[] {
    // 以题目为单位去重，记录首次通过
    const solvedFirst = new Map<string, Submission>();
    const attempted = new Set<string>();

    const sorted = submissions.slice().sort(
      (a: Submission, b: Submission) => a.creationTimeSeconds - b.creationTimeSeconds);

    for (let i = 0; i < sorted.length; i++) {
      const s = sorted[i];
      const key = `${s.contestId}${s.index}`;
      if (s.verdict === 'OK') {
        if (!solvedFirst.has(key)) {
          solvedFirst.set(key, s);
        }
      } else {
        attempted.add(key);
      }
    }

    // 按日聚合
    const dayMap = new Map<string, Submission[]>();
    solvedFirst.forEach((s: Submission, key: string) => {
      const date = PracticeLog.practiceDate(s.creationTimeSeconds);
      let list = dayMap.get(date);
      if (list === undefined) {
        list = [];
        dayMap.set(date, list);
      }
      list.push(s);
    });

    const days: PracticeDay[] = [];
    dayMap.forEach((list: Submission[], date: string) => {
      let maxRating = 0;
      const keys: string[] = [];
      for (let i = 0; i < list.length; i++) {
        keys.push(`${list[i].contestId}${list[i].index}`);
        if (list[i].problemRating > maxRating) {
          maxRating = list[i].problemRating;
        }
      }
      let attCount = 0;
      attempted.forEach((k: string) => {
        if (!solvedFirst.has(k)) {
          attCount++;
        }
      });
      days.push({
        date,
        solvedCount: list.length,
        attemptedCount: 0,        // 逐日归属未通过题的日期不可靠，置 0，累计值单独算
        maxRating,
        solvedKeys: keys
      });
    });

    days.sort((a: PracticeDay, b: PracticeDay) => a.date < b.date ? -1 : (a.date > b.date ? 1 : 0));
    return days;
  }

  /** 累计统计 */
  static stats(days: PracticeDay[]): ProgressStats {
    let totalSolved = 0;
    let hardest = 0;
    for (let i = 0; i < days.length; i++) {
      totalSolved += days[i].solvedCount;
      if (days[i].maxRating > hardest) {
        hardest = days[i].maxRating;
      }
    }

    // 连续天数：从最后一天往前数
    let streak = 0;
    if (days.length > 0) {
      const today = PracticeLog.dateStr(new Date());
      const yesterday = PracticeLog.dateStr(new Date(Date.now() - 86400000));
      const last = days[days.length - 1].date;
      if (last === today || last === yesterday) {
        streak = 1;
        const pool = new Set<string>();
        for (let i = 0; i < days.length; i++) {
          pool.add(days[i].date);
        }
        let probe = new Date(last);
        while (true) {
          probe = new Date(probe.getTime() - 86400000);
          if (pool.has(PracticeLog.dateStr(probe))) {
            streak++;
          } else {
            break;
          }
        }
      }
    }

    return {
      totalSolved,
      activeDays: days.length,
      currentStreak: streak,
      firstDay: days.length > 0 ? days[0].date : '',
      lastDay: days.length > 0 ? days[days.length - 1].date : '',
      hardestSolved: hardest
    };
  }

  private static dateStr(d: Date): string {
    const y = d.getFullYear();
    const m = `${d.getMonth() + 1}`.padStart(2, '0');
    const day = `${d.getDate()}`.padStart(2, '0');
    return `${y}-${m}-${day}`;
  }
}

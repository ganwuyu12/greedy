/**
 * 知识检索（轻量关键词版）
 *
 * 为什么不用向量检索：
 *   语义索引（bge-small + reranker）约 42 MB，打进 App 太重。
 *   而检索目标很明确——**把用户说的词映射到一个词条**，
 *   不是做问答理解。关键词匹配对这个任务是够的。
 *
 * 索引来自 build_app_index.py，约 137 KB，随 App 打包进 rawfile。
 *
 * 打分策略（按可靠性从高到低）：
 *   1. 检索键完全等于查询        → 100 分
 *   2. 检索键是查询的子串        → 80 + 长度加权
 *   3. 查询是检索键的子串        → 60 + 长度加权
 *   4. 逐字符交叠（容错错别字）  → 交叠比例 × 40
 *
 * 只保留有意义的分数（>25），避免「什么都匹配一点」。
 */

import { util } from '@kit.ArkTS';
import { resourceManager } from '@kit.LocalizationKit';

/** 索引里的一个词条 */
interface RawEntry {
  path: string;
  name: string;
  keys: string[];
  desc: string;
}

interface RawIndex {
  version: number;
  generated: string;
  count: number;
  entries: RawEntry[];
}

/** 命中结果 */
export interface WikiHit {
  path: string;
  name: string;
  desc: string;
  score: number;
}

/** 检索键的最短长度（太短的键会误匹配一大片） */
const MIN_KEY_LEN = 2;

/** 低于这个分数认为不相关 */
const MIN_SCORE = 25;

export class WikiIndex {
  private entries: RawEntry[] = [];
  private loaded: boolean = false;

  /**
   * 读取索引（resourceManager 读 rawfile）
   *
   * 只读一次并缓存在内存——137 KB 不算大，
   * 但每次提问都读文件没必要。
   */
  async load(mgr: resourceManager.ResourceManager): Promise<void> {
    if (this.loaded) {
      return;
    }
    const bytes: Uint8Array = await mgr.getRawFileContent('kb_index.json');
    const decoder = util.TextDecoder.create('utf-8');
    const text = decoder.decodeToString(bytes);
    const idx = JSON.parse(text) as RawIndex;
    this.entries = idx.entries ?? [];
    this.loaded = true;
  }

  isLoaded(): boolean {
    return this.loaded;
  }

  count(): number {
    return this.entries.length;
  }

  /**
   * 检索
   *
   * topK 默认 3：给模型三四个候选比给一个更稳——
   * 关键词匹配难免有歧义，让模型自己挑。
   */
  search(query: string, topK: number = 3): WikiHit[] {
    const q = query.trim().toLowerCase();
    if (q.length === 0 || this.entries.length === 0) {
      return [];
    }

    const scored: WikiHit[] = [];
    for (let i = 0; i < this.entries.length; i++) {
      const e = this.entries[i];
      let best = 0;
      for (let j = 0; j < e.keys.length; j++) {
        const k = e.keys[j];
        if (k.length < MIN_KEY_LEN) {
          continue;
        }
        const s = WikiIndex.score(q, k);
        if (s > best) {
          best = s;
        }
      }
      if (best >= MIN_SCORE) {
        scored.push({ path: e.path, name: e.name, desc: e.desc, score: best });
      }
    }

    scored.sort((a: WikiHit, b: WikiHit) => b.score - a.score);
    return scored.length > topK ? scored.slice(0, topK) : scored;
  }

  /** 单对「查询 / 检索键」打分 */
  private static score(q: string, k: string): number {
    // 1. 完全相等
    if (q === k) {
      return 100;
    }
    // 2. 键是查询的一部分（用户多说了几个字）
    if (q.indexOf(k) >= 0) {
      // 键越长越可信：「线段树」比「树」可信得多
      return 80 + Math.min(k.length, 6);
    }
    // 3. 查询是键的一部分（用户少说了几个字）
    if (k.indexOf(q) >= 0) {
      return 60 + Math.min(q.length, 6);
    }
    // 4. 逐字符交叠——容错错别字与顺序差异
    const overlap = WikiIndex.overlapRatio(q, k);
    if (overlap >= 0.6) {
      return Math.round(overlap * 40);
    }
    return 0;
  }

  /**
   * 字符交叠比例（不用编辑距离）
   *
   * 编辑距离对中文不合适：一个汉字算一个字符，
   * 「线段树」和「线段树上」距离是 1，但和「树状数组」距离是 3——
   * 而用户更可能打错字，不是打错顺序。
   * 交叠比例对这种场景更稳。
   */
  private static overlapRatio(a: string, b: string): number {
    const setB = new Set<string>();
    for (let i = 0; i < b.length; i++) {
      setB.add(b.charAt(i));
    }
    let hit = 0;
    const setA = new Set<string>();
    for (let i = 0; i < a.length; i++) {
      const c = a.charAt(i);
      if (setA.has(c)) {
        continue;
      }
      setA.add(c);
      if (setB.has(c)) {
        hit++;
      }
    }
    const denom = Math.min(setA.size, setB.size);
    return denom === 0 ? 0 : hit / denom;
  }

  /** 把命中结果格式化成给模型看的文本 */
  static format(hits: WikiHit[]): string {
    if (hits.length === 0) {
      return '知识库里没有找到相关词条。';
    }
    const parts: string[] = [];
    for (let i = 0; i < hits.length; i++) {
      const h = hits[i];
      parts.push(`【${h.name}】(${h.path})\n${h.desc}`);
    }
    return parts.join('\n\n');
  }
}

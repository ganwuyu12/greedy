/**
 * 配置与本地存储
 *
 * 约定：
 *   - 密钥不写进代码，由设置页写入 preferences
 *   - 所有可调项集中在这里，避免散落在各处
 */

import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';

/** 应用配置 */
export class AppConfig {
  /** 大模型接口（DeepSeek 兼容 OpenAI 协议） */
  static readonly LLM_ENDPOINT: string = 'https://api.deepseek.com/chat/completions';
  static readonly LLM_MODEL: string = 'deepseek-chat';

  /** 知识库检索服务（可选。索引约 42 MB，不适合打进 App，留给服务端） */
  static readonly WIKI_ENDPOINT: string = '';

  /** 默认 Codeforces 用户名（可在设置页改） */
  static readonly DEFAULT_HANDLE: string = 'ganwuyu';

  /** 单次任务的最大工具调用轮数 */
  static readonly MAX_ROUNDS: number = 8;

  /** 单次任务的 token 预算 */
  static readonly TOKEN_BUDGET: number = 50000;

  /** 同一工具同参数连续调用超过这个次数就拦截 */
  static readonly MAX_DUPLICATE_CALLS: number = 2;

  // ---- 存储键名 ----
  static readonly KEY_API_KEY: string = 'llm_api_key';
  static readonly KEY_HANDLE: string = 'cf_handle';
  static readonly KEY_NOTES: string = 'notes';
  static readonly KEY_CHAT_HISTORY: string = 'chat_history';
}

/**
 * 本地键值存储的封装
 *
 * 为什么需要封装：preferences 的 API 是异步且需要 context 的，
 * 直接在业务代码里到处调用会重复很多样板。
 */
export class AppStorageUtil {
  private static store: preferences.Preferences | null = null;

  /** 应用启动时初始化一次 */
  static async init(context: common.UIAbilityContext): Promise<void> {
    if (AppStorageUtil.store === null) {
      AppStorageUtil.store = await preferences.getPreferences(context, 'greedy_store');
    }
  }

  static async getString(key: string): Promise<string> {
    if (AppStorageUtil.store === null) {
      return '';
    }
    const v = await AppStorageUtil.store.get(key, '');
    return typeof v === 'string' ? v : '';
  }

  static async setString(key: string, value: string): Promise<void> {
    if (AppStorageUtil.store === null) {
      return;
    }
    await AppStorageUtil.store.put(key, value);
    await AppStorageUtil.store.flush();
  }
}

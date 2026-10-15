/**
 * Agent 核心：工具注册 + 主循环
 *
 * 对应 Python 侧的 my_agent.py，去掉平台相关部分后可在所有端复用。
 *
 * 要示范的七件事（课程要求「多轮任务推进或调用工具」）：
 *   1. 工具注册（声明式，附带参数说明）
 *   2. 主循环（模型要工具 → 执行 → 结果回灌）
 *   3. 状态管理（assistant / tool 消息如何拼接）
 *   4. 循环终止（最大轮数 + 重复调用检测）
 *   5. 失败回灌（工具报错也要结构化返回给模型，让它自己改）
 *   6. Token 预算（防止单次任务烧太多）
 *   7. 追踪日志（每步留下记录，便于排查与演示）
 */

import { http } from '@kit.NetworkKit';

// ---------------------------------------------------------------- 类型

export interface ToolParam {
  name: string;
  type: string;          // 'string' | 'integer'
  description: string;
  required: boolean;
}

export interface ToolDef {
  name: string;
  description: string;
  params: ToolParam[];
  /** 无参数工具也要能调用，所以用 Map 传参 */
  run: (args: Map<string, Object>) => Promise<string>;
}

/** 消息：与各家大模型的 chat 格式对齐 */
export interface ChatMessage {
  role: string;                 // 'system' | 'user' | 'assistant' | 'tool'
  content: string;
  toolCallId?: string;
  toolName?: string;
}

/** 模型返回的一次工具调用请求 */
export interface ToolCall {
  id: string;
  name: string;
  args: Map<string, Object>;
}

/** 模型返回 */
export interface LLMReply {
  content: string;
  toolCalls: ToolCall[];
  promptTokens: number;
  completionTokens: number;
}

/** 追踪记录（第 7 件事） */
export interface TraceStep {
  round: number;
  tool: string;
  args: string;
  ok: boolean;
  resultPreview: string;
}

/** 一次完整运行的轨迹 */
export interface AgentRun {
  answer: string;
  steps: TraceStep[];
  promptTokens: number;
  completionTokens: number;
  stopReason: string;
}

// ---------------------------------------------------------------- 工具注册表

/**
 * 工具注册表
 *
 * 为什么用类而不是模块级全局对象：注册表要能被持有和注入，
 * 全局单例在测试时会互相污染。
 */
export class ToolRegistry {
  private tools: Map<string, ToolDef> = new Map<string, ToolDef>();

  register(def: ToolDef): void {
    this.tools.set(def.name, def);
  }

  get(name: string): ToolDef | undefined {
    return this.tools.get(name);
  }

  names(): string[] {
    const out: string[] = [];
    this.tools.forEach((_v: ToolDef, k: string) => {
      out.push(k);
    });
    return out;
  }

  /** 生成大模型要求的 function-calling schema */
  toSchema(): Object[] {
    const out: Object[] = [];
    this.tools.forEach((def: ToolDef) => {
      const props = new Map<string, Object>();
      const required: string[] = [];
      for (let i = 0; i < def.params.length; i++) {
        const p = def.params[i];
        props.set(p.name, { type: p.type, description: p.description } as Object);
        if (p.required) {
          required.push(p.name);
        }
      }
      out.push({
        type: 'function',
        function: {
          name: def.name,
          description: def.description,
          parameters: {
            type: 'object',
            properties: props,
            required: required
          }
        }
      } as Object);
    });
    return out;
  }

  /**
   * 执行一个工具
   *
   * 第 5 件事：任何失败都要转成结构化信息返回，
   * 而不是抛出去让整个 Agent 崩掉——模型看到错误会自己纠正。
   */
  async execute(name: string, args: Map<string, Object>): Promise<ToolResult> {
    const def = this.tools.get(name);
    if (def === undefined) {
      return {
        ok: false,
        text: JSON.stringify({
          error: `没有这个工具：${name}`,
          available: this.names()
        })
      };
    }
    try {
      const text = await def.run(args);
      return { ok: true, text };
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return {
        ok: false,
        text: JSON.stringify({
          error: `工具执行失败：${msg}`,
          hint: '请检查参数是否符合要求，或换一种方式'
        })
      };
    }
  }
}

export interface ToolResult {
  ok: boolean;
  text: string;
}

// ---------------------------------------------------------------- 主循环

export interface AgentConfig {
  apiKey: string;
  model: string;
  endpoint: string;
  systemPrompt: string;
  maxRounds: number;
  tokenBudget: number;
  maxDuplicateCalls: number;
}

export class Agent {
  private registry: ToolRegistry;
  private config: AgentConfig;
  private history: ChatMessage[] = [];

  constructor(registry: ToolRegistry, config: AgentConfig) {
    this.registry = registry;
    this.config = config;
  }

  clearHistory(): void {
    this.history = [];
  }

  /** 取最近若干条历史，用于 UI 展示 */
  recentHistory(n: number): ChatMessage[] {
    const start = Math.max(0, this.history.length - n);
    return this.history.slice(start);
  }

  /**
   * 跑一次任务
   *
   * 循环流程：模型要工具 → 执行 → 结果回灌 → 再问模型 → 直到给出最终答案
   */
  async run(userInput: string): Promise<AgentRun> {
    const steps: TraceStep[] = [];
    let promptTokens = 0;
    let completionTokens = 0;
    let stopReason = '';

    // 第 3 件事：消息序列。system + 历史 + 本轮输入
    const messages: ChatMessage[] = [];
    messages.push({ role: 'system', content: this.config.systemPrompt });
    for (let i = 0; i < this.history.length; i++) {
      messages.push(this.history[i]);
    }
    messages.push({ role: 'user', content: userInput });

    // 第 4 件事：重复调用检测用「连续」而非「累计」，
    // 否则长对话里合法的重复会被误拦
    let lastSignature = '';
    let repeatCount = 0;

    let answer = '';

    for (let round = 1; round <= this.config.maxRounds; round++) {
      const reply = await this.callModel(messages);
      promptTokens += reply.promptTokens;
      completionTokens += reply.completionTokens;

      // 第 6 件事：token 预算
      if (promptTokens + completionTokens > this.config.tokenBudget) {
        stopReason = `超出 token 预算（${promptTokens + completionTokens}）`;
        answer = reply.content.length > 0 ? reply.content : '（因超出预算中止）';
        break;
      }

      // 没有工具调用 = 最终答案
      if (reply.toolCalls.length === 0) {
        stopReason = '模型给出最终答案';
        answer = reply.content;
        break;
      }

      // assistant 这一轮（含 tool_calls）入列
      messages.push({
        role: 'assistant',
        content: reply.content,
        toolName: reply.toolCalls.map((c: ToolCall) => c.name).join(',')
      });

      for (let i = 0; i < reply.toolCalls.length; i++) {
        const call = reply.toolCalls[i];
        const signature = `${call.name}:${JSON.stringify(Array.from(call.args.entries()))}`;

        if (signature === lastSignature) {
          repeatCount++;
        } else {
          lastSignature = signature;
          repeatCount = 1;
        }

        let result: ToolResult;
        if (repeatCount > this.config.maxDuplicateCalls) {
          // 关键：拦截时**也要**补一条 tool 消息。
          // 只往消息序列里插一条伪造的用户消息，会导致
          // tool_call_id 没有对应响应，下一次请求会被接口拒绝。
          result = {
            ok: false,
            text: JSON.stringify({
              error: `已经用相同参数调用过 ${call.name} ${repeatCount} 次了`,
              hint: '请换关键词或换工具，或者基于已有信息直接回答'
            })
          };
        } else {
          result = await this.registry.execute(call.name, call.args);
        }

        steps.push({
          round,
          tool: call.name,
          args: JSON.stringify(Array.from(call.args.entries())),
          ok: result.ok,
          resultPreview: result.text.substring(0, 200)
        });

        // 结果回灌（成功和失败都回灌）
        messages.push({
          role: 'tool',
          content: result.text,
          toolCallId: call.id,
          toolName: call.name
        });
      }
    }

    if (stopReason.length === 0) {
      stopReason = `达到最大轮数 ${this.config.maxRounds}`;
      answer = '（达到最大轮数，未能给出最终答案）';
    }

    // 历史只保留最终一轮，避免无限增长
    this.history.push({ role: 'user', content: userInput });
    this.history.push({ role: 'assistant', content: answer });

    return { answer, steps, promptTokens, completionTokens, stopReason };
  }

  /** 调一次大模型 */
  private async callModel(messages: ChatMessage[]): Promise<LLMReply> {
    const payload = {
      model: this.config.model,
      messages: messages.map((m: ChatMessage) => this.toWire(m)),
      tools: this.registry.toSchema(),
      tool_choice: 'auto'
    };

    let lastError = '';
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const req = http.createHttp();
        const resp = await req.request(this.config.endpoint, {
          method: http.RequestMethod.POST,
          header: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.config.apiKey}`
          },
          extraData: JSON.stringify(payload),
          connectTimeout: 20000,
          readTimeout: 60000
        });
        req.destroy();

        if (resp.responseCode >= 400 && resp.responseCode < 500 && resp.responseCode !== 429) {
          // 4xx（除限流）重试没意义，直接报出
          throw new Error(`请求被拒绝（${resp.responseCode}）：${resp.result as string}`);
        }
        if (resp.responseCode !== 200) {
          lastError = `HTTP ${resp.responseCode}`;
          await this.sleep(1000 * attempt);
          continue;
        }
        return this.parseReply(resp.result as string);
      } catch (e) {
        lastError = e instanceof Error ? e.message : String(e);
        if (attempt < 3) {
          await this.sleep(1000 * attempt);
        }
      }
    }
    throw new Error(`模型调用失败：${lastError}`);
  }

  private toWire(m: ChatMessage): Object {
    if (m.role === 'tool') {
      return { role: 'tool', tool_call_id: m.toolCallId, content: m.content } as Object;
    }
    return { role: m.role, content: m.content } as Object;
  }

  /** 解析模型返回 */
  private parseReply(body: string): LLMReply {
    const obj = JSON.parse(body) as Record<string, Object>;
    const choices = obj.choices as Object[];
    const first = choices[0] as Record<string, Object>;
    const message = first.message as Record<string, Object>;
    const usage = (obj.usage ?? {}) as Record<string, Object>;

    const content = (message.content ?? '') as string;
    const calls: ToolCall[] = [];
    const rawCalls = message.tool_calls as Object[] | undefined;
    if (rawCalls !== undefined) {
      for (let i = 0; i < rawCalls.length; i++) {
        const c = rawCalls[i] as Record<string, Object>;
        const fn = c.function as Record<string, Object>;
        const argStr = (fn.arguments ?? '{}') as string;
        calls.push({
          id: (c.id ?? '') as string,
          name: (fn.name ?? '') as string,
          args: this.parseArgs(argStr)
        });
      }
    }

    return {
      content,
      toolCalls: calls,
      promptTokens: (usage.prompt_tokens ?? 0) as number,
      completionTokens: (usage.completion_tokens ?? 0) as number
    };
  }

  private parseArgs(s: string): Map<string, Object> {
    const out = new Map<string, Object>();
    try {
      const obj = JSON.parse(s) as Record<string, Object>;
      const keys = Object.keys(obj);
      for (let i = 0; i < keys.length; i++) {
        out.set(keys[i], obj[keys[i]]);
      }
    } catch (e) {
      // 模型偶尔给的不是合法 JSON，交给工具层报错，不在这里崩
    }
    return out;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise<void>((resolve: () => void) => {
      setTimeout(() => {
        resolve();
      }, ms);
    });
  }
}

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
 *
 * ⚠️ ArkTS 语法约束：禁止匿名对象字面量（arkts-no-untyped-obj-literals），
 *    所以下面所有结构都先声明 interface 再用，不能直接写 { a: 1 }。
 */

import { http } from '@kit.NetworkKit';

// ---------------------------------------------------------------- 工具侧类型

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

export interface ToolResult {
  ok: boolean;
  text: string;
}

/** 参数 schema 片段 */
interface PropSchema {
  type: string;
  description: string;
}

interface ParamSchema {
  type: string;
  properties: Record<string, PropSchema>;
  required: string[];
}

interface FunctionSchema {
  name: string;
  description: string;
  parameters: ParamSchema;
}

interface ToolSchema {
  type: string;
  function: FunctionSchema;
}

// ---------------------------------------------------------------- 消息类型

/** 内部消息结构 */
export interface ChatMessage {
  role: string;                 // 'system' | 'user' | 'assistant' | 'tool'
  content: string;
  toolCallId?: string;
  toolName?: string;
}

/** 发给模型时用的消息结构（字段名与接口约定一致） */
interface WireMessage {
  role: string;
  content?: string;
  tool_call_id?: string;
  tool_calls?: WireToolCall[];
}

interface WireToolCallFunction {
  name: string;
  arguments: string;
}

interface WireToolCall {
  id: string;
  type: string;
  function: WireToolCallFunction;
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

/** 请求体 */
interface ChatPayload {
  model: string;
  messages: WireMessage[];
  tools: ToolSchema[];
  tool_choice: string;
}

/** 响应体里我们关心的部分 */
interface RespMessageFunction {
  name?: string;
  arguments?: string;
}

interface RespToolCall {
  id?: string;
  function?: RespMessageFunction;
}

interface RespMessage {
  content?: string;
  tool_calls?: RespToolCall[];
}

interface RespChoice {
  message?: RespMessage;
}

interface RespUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
}

interface ChatResponse {
  choices?: RespChoice[];
  usage?: RespUsage;
}

/** 工具失败时回给模型的结构 */
interface ToolErrorPayload {
  error: string;
  available?: string[];
  hint?: string;
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
  toSchema(): ToolSchema[] {
    const out: ToolSchema[] = [];
    this.tools.forEach((def: ToolDef) => {
      const props: Record<string, PropSchema> = {};
      const required: string[] = [];
      for (let i = 0; i < def.params.length; i++) {
        const p = def.params[i];
        props[p.name] = { type: p.type, description: p.description };
        if (p.required) {
          required.push(p.name);
        }
      }
      out.push({
        type: 'function',
        function: {
          name: def.name,
          description: def.description,
          parameters: { type: 'object', properties: props, required: required }
        }
      });
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
      const payload: ToolErrorPayload = {
        error: `没有这个工具：${name}`,
        available: this.names()
      };
      return { ok: false, text: JSON.stringify(payload) };
    }
    try {
      const text = await def.run(args);
      return { ok: true, text };
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      const payload: ToolErrorPayload = {
        error: `工具执行失败：${msg}`,
        hint: '请检查参数是否符合要求，或换一种方式'
      };
      return { ok: false, text: JSON.stringify(payload) };
    }
  }
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
  /**
   * 对话历史（wire 格式：字段名与接口约定一致）
   *
   * 为什么直接存 wire 格式、而不是内部结构：
   * 接口对消息序列有**结构约束**——role='tool' 的消息必须紧跟一条
   * 带 tool_calls 的 assistant 消息。如果历史里把 tool_calls 丢掉，
   * 下一轮再发就会变成「孤儿 tool 消息」被拒绝（400）。
   * 所以历史里必须保留成对的完整结构，不能只留文本。
   */
  private wireHistory: WireMessage[] = [];

  constructor(registry: ToolRegistry, config: AgentConfig) {
    this.registry = registry;
    this.config = config;
  }

  clearHistory(): void {
    this.wireHistory = [];
  }

  /** 历史条数（UI 可用来判断是否有对话） */
  historyLength(): number {
    return this.wireHistory.length;
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

    // 第 3 件事：消息序列。
    // messages 是本轮的工作副本；wireHistory 跨轮保留，且保留成对结构
    const messages: WireMessage[] = [];
    messages.push({ role: 'system', content: this.config.systemPrompt });
    for (let i = 0; i < this.wireHistory.length; i++) {
      messages.push(this.wireHistory[i]);
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

      // 构造本轮 assistant 消息（必须带 tool_calls，供后面的 tool 消息配对）
      const wireCalls: WireToolCall[] = [];
      for (let i = 0; i < reply.toolCalls.length; i++) {
        const c = reply.toolCalls[i];
        wireCalls.push({
          id: c.id,
          type: 'function',
          function: { name: c.name, arguments: JSON.stringify(this.argsToObj(c.args)) }
        });
      }
      const assistantMsg: WireMessage = {
        role: 'assistant',
        content: reply.content,
        tool_calls: wireCalls
      };
      messages.push(assistantMsg);

      for (let i = 0; i < reply.toolCalls.length; i++) {
        const call = reply.toolCalls[i];
        const signature = `${call.name}:${this.argsKey(call.args)}`;

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
          const payload: ToolErrorPayload = {
            error: `已经用相同参数调用过 ${call.name} ${repeatCount} 次了`,
            hint: '请换关键词或换工具，或者基于已有信息直接回答'
          };
          result = { ok: false, text: JSON.stringify(payload) };
        } else {
          result = await this.registry.execute(call.name, call.args);
        }

        steps.push({
          round,
          tool: call.name,
          args: this.argsKey(call.args),
          ok: result.ok,
          resultPreview: result.text.substring(0, 200)
        });

        // 结果回灌（成功和失败都回灌），必须带 tool_call_id 与上面配对
        messages.push({
          role: 'tool',
          content: result.text,
          tool_call_id: call.id
        });
      }
    }

    if (stopReason.length === 0) {
      stopReason = `达到最大轮数 ${this.config.maxRounds}`;
      answer = '（达到最大轮数，未能给出最终答案）';
    }

    // 跨轮历史：把本轮的完整消息序列（含成对的 tool_calls / tool 结果）
    // 全部保留，最后一轮 assistant 的文本答案补上。
    // 这样下一轮发送时结构依然合法。
    for (let i = 1; i < messages.length; i++) {
      this.wireHistory.push(messages[i]);
    }
    this.wireHistory.push({ role: 'assistant', content: answer });

    return { answer, steps, promptTokens, completionTokens, stopReason };
  }

  /** 把参数 Map 转成普通对象（用于拼 function.arguments） */
  private argsToObj(args: Map<string, Object>): Record<string, Object> {
    const out: Record<string, Object> = {};
    args.forEach((v: Object, k: string) => {
      out[k] = v;
    });
    return out;
  }

  /** 把参数拼成稳定的字符串（用于重复检测与日志） */
  private argsKey(args: Map<string, Object>): string {
    const keys: string[] = [];
    args.forEach((_v: Object, k: string) => {
      keys.push(k);
    });
    keys.sort();
    const parts: string[] = [];
    for (let i = 0; i < keys.length; i++) {
      parts.push(`${keys[i]}=${String(args.get(keys[i]))}`);
    }
    return parts.join('&');
  }

  /** 调一次大模型 */
  private async callModel(messages: WireMessage[]): Promise<LLMReply> {
    const payload: ChatPayload = {
      model: this.config.model,
      messages: messages,
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

        const code = resp.responseCode;
        if (code >= 400 && code < 500 && code !== 429) {
          // 4xx（除限流）重试没意义，直接报出
          throw new Error(`请求被拒绝（${code}）：${resp.result as string}`);
        }
        if (code !== 200) {
          lastError = `HTTP ${code}`;
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

  /** 解析模型返回 */
  private parseReply(body: string): LLMReply {
    const obj = JSON.parse(body) as ChatResponse;
    const choices = obj.choices;
    if (choices === undefined || choices.length === 0) {
      throw new Error('模型返回里没有 choices');
    }
    const message = choices[0].message;
    const content = message?.content ?? '';
    const usage = obj.usage;

    const calls: ToolCall[] = [];
    const rawCalls = message?.tool_calls;
    if (rawCalls !== undefined) {
      for (let i = 0; i < rawCalls.length; i++) {
        const c = rawCalls[i];
        const fn = c.function;
        const argStr = fn?.arguments ?? '{}';
        calls.push({
          id: c.id ?? '',
          name: fn?.name ?? '',
          args: this.parseArgs(argStr)
        });
      }
    }

    return {
      content,
      toolCalls: calls,
      promptTokens: usage?.prompt_tokens ?? 0,
      completionTokens: usage?.completion_tokens ?? 0
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

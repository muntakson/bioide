import * as fs from "fs"
import { providersConfigPath } from "../util"

export interface ProviderCfg {
  apiKey: string
  models?: string[]
}
export type ProvidersCfg = Record<string, ProviderCfg>

export function loadProviders(): ProvidersCfg {
  const p = providersConfigPath()
  if (!fs.existsSync(p)) return {}
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"))
  } catch {
    return {}
  }
}

interface Endpoint {
  url: string
  headers: (key: string) => Record<string, string>
  body: (model: string, system: string, user: string, maxTokens: number) => any
  // returns text delta from one parsed SSE json object, or ""
  delta: (j: any) => string
}

const OPENAI_COMPAT = (url: string, cap = 8000): Endpoint => ({
  url,
  headers: (key) => ({ Authorization: `Bearer ${key}`, "Content-Type": "application/json" }),
  body: (model, system, user, maxTokens) => ({
    model,
    stream: true,
    // Per-provider output cap (DeepSeek hard-caps at 8192; groq/openrouter allow more), so a long
    // paper isn't silently truncated. Prefer Anthropic for the fullest research paper.
    max_tokens: Math.min(maxTokens, cap),
    messages: [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
  }),
  delta: (j) => j?.choices?.[0]?.delta?.content ?? "",
})

const ENDPOINTS: Record<string, Endpoint> = {
  anthropic: {
    url: "https://api.anthropic.com/v1/messages",
    headers: (key) => ({
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
      "Content-Type": "application/json",
    }),
    // Claude 4.x supports large outputs, so honor the caller's request (paper uses ~16000).
    body: (model, system, user, maxTokens) => ({
      model,
      max_tokens: maxTokens,
      stream: true,
      system,
      messages: [{ role: "user", content: user }],
    }),
    delta: (j) => (j?.type === "content_block_delta" ? (j.delta?.text ?? "") : ""),
  },
  groq: OPENAI_COMPAT("https://api.groq.com/openai/v1/chat/completions", 16000),
  openrouter: OPENAI_COMPAT("https://openrouter.ai/api/v1/chat/completions", 16000),
  deepseek: OPENAI_COMPAT("https://api.deepseek.com/chat/completions", 8000),
}

// Single-shot streaming chat. No tools, no agent. Calls onDelta(text) as chunks arrive.
export async function streamChat(opts: {
  provider: string
  model: string
  apiKey: string
  system: string
  user: string
  signal: AbortSignal
  onDelta: (t: string) => void
  maxTokens?: number
  // Anthropic-only: enable the server-side web_search tool. It runs INSIDE this single streaming
  // response (Anthropic performs the search and the model keeps writing) — no client tool loop, so
  // the no-agent design holds. Ignored for OpenAI-compatible providers. Text still streams as
  // content_block_delta, so the existing delta parser is unaffected.
  webSearch?: boolean
}) {
  const ep = ENDPOINTS[opts.provider]
  if (!ep) throw new Error(`Unknown provider: ${opts.provider}`)
  const body = ep.body(opts.model, opts.system, opts.user, opts.maxTokens ?? 8000)
  if (opts.webSearch && opts.provider === "anthropic") {
    body.tools = [{ type: "web_search_20250305", name: "web_search", max_uses: 6 }]
  }
  const res = await fetch(ep.url, {
    method: "POST",
    headers: ep.headers(opts.apiKey),
    body: JSON.stringify(body),
    signal: opts.signal,
  })
  if (!res.ok || !res.body) {
    const txt = await res.text().catch(() => "")
    throw new Error(`${opts.provider} ${res.status}: ${txt.slice(0, 300)}`)
  }
  const reader = (res.body as any).getReader()
  const dec = new TextDecoder()
  let buf = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const lines = buf.split("\n")
    buf = lines.pop() ?? ""
    for (const line of lines) {
      const t = line.trim()
      if (!t.startsWith("data:")) continue
      const data = t.slice(5).trim()
      if (data === "[DONE]") return
      try {
        opts.onDelta(ep.delta(JSON.parse(data)))
      } catch {
        /* ignore keep-alives / partial */
      }
    }
  }
}

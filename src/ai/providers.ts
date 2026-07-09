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
  body: (model: string, system: string, user: string) => any
  // returns text delta from one parsed SSE json object, or ""
  delta: (j: any) => string
}

const OPENAI_COMPAT = (url: string): Endpoint => ({
  url,
  headers: (key) => ({ Authorization: `Bearer ${key}`, "Content-Type": "application/json" }),
  body: (model, system, user) => ({
    model,
    stream: true,
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
    body: (model, system, user) => ({
      model,
      max_tokens: 3000,
      stream: true,
      system,
      messages: [{ role: "user", content: user }],
    }),
    delta: (j) => (j?.type === "content_block_delta" ? (j.delta?.text ?? "") : ""),
  },
  groq: OPENAI_COMPAT("https://api.groq.com/openai/v1/chat/completions"),
  openrouter: OPENAI_COMPAT("https://openrouter.ai/api/v1/chat/completions"),
  deepseek: OPENAI_COMPAT("https://api.deepseek.com/chat/completions"),
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
}) {
  const ep = ENDPOINTS[opts.provider]
  if (!ep) throw new Error(`Unknown provider: ${opts.provider}`)
  const res = await fetch(ep.url, {
    method: "POST",
    headers: ep.headers(opts.apiKey),
    body: JSON.stringify(ep.body(opts.model, opts.system, opts.user)),
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

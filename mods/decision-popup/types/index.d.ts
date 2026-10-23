export type DecisionOption = {
  label: string
  detail?: string
  pros?: string
  cons?: string
  example: string
}

export type DecisionExperiment = {
  name: string
  what: string
  how: string
  why: string
}

export type DecisionItem = {
  id: string
  title: string
  problem?: string
  experiments?: DecisionExperiment[]
  options: DecisionOption[]
}

export type DecisionRequest = {
  title: string
  items: DecisionItem[]
}

declare module 'claude-code' {
  interface PluginState {
    'decision-popup': {
      request: DecisionRequest | null
      answers: Record<string, number>
      texts: Record<string, string>
      page: number
    }
  }
}

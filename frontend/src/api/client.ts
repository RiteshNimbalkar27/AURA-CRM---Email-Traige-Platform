import axios from 'axios'

// ─── Base Instance ───────────────────────────────────────────────────────────
const api = axios.create({
  baseURL: '/',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT from localStorage on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('aura_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ─── TypeScript Interfaces ───────────────────────────────────────────────────
export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface DashboardStats {
  total_open_threads?: number
  open_threads?: number
  total_emails?: number
  open_escalations?: number
  escalations?: number
  open_legal_flags?: number
  legal_flags?: number
  pending_review?: number
  unclassified?: number
  threads_by_queue?: Record<string, number>
  threads_by_urgency?: Record<string, number>
}

export interface Classification {
  id?: number | string
  classification_id?: string
  message_id?: number | string
  category: string
  urgency: string
  sentiment_score: number
  confidence: number
  entities?: Record<string, unknown>
  rationale?: string
  proposed_action?: string
  human_review_required: boolean
  classified_at?: string
  created_at?: string
}

export interface Message {
  id?: number | string
  message_id: string
  thread_id?: number | string
  sender?: string
  sender_email?: string
  recipients?: string[]
  subject?: string
  body?: string
  body_excerpt?: string
  received_at: string
  job_status?: string
  classification?: Classification
  classifications?: Classification[]
  agent_runs?: AgentRun[]
  drafts?: Draft[]
  tickets?: Ticket[]
  escalations?: Escalation[]
  legal_flags?: LegalFlag[]
}

export interface Thread {
  id?: number | string
  thread_id: string
  subject: string
  participants?: string[]
  queue?: string
  status: string
  urgency?: string
  classification?: Classification | null
  created_at: string
  updated_at?: string
  last_message_at?: string | null
  message_count?: number
  messages?: Message[]
  human_review_required?: boolean
}

export interface PaginatedThreads {
  threads: Thread[]
  total: number
  page: number
  page_size: number
  pages?: number
  total_pages?: number
}

export interface AgentStep {
  step: number
  rationale?: string
  action: string
  observation?: string
  result?: string
  timestamp?: string
}

export interface AgentRun {
  id?: number | string
  agent_run_id?: string
  message_id: string
  mode?: string
  run_type?: string
  status?: string
  outcome?: string
  dry_run?: boolean
  tool_calls_count?: number
  result?: Record<string, unknown>
  trace: AgentStep[]
  created_at: string
  completed_at?: string
}

export interface Draft {
  id?: number | string
  draft_id?: string
  message_id?: string
  body?: string
  body_preview?: string
  content?: string
  tone?: string
  status: string
  citations?: unknown[]
  citations_count?: number
  created_at: string
  approved_at?: string
}

export interface Ticket {
  id?: number | string
  ticket_id?: string
  message_id?: string
  ticket_type?: string
  title: string
  description?: string
  assignee_queue?: string
  priority?: string
  status: string
  created_at: string
}

export interface Escalation {
  id?: number | string
  escalation_id?: string
  message_id?: string
  reason: string
  priority?: string
  level?: string
  status: string
  created_at: string
}

export interface LegalFlag {
  id?: number | string
  legal_flag_id?: string
  message_id?: string
  flag_type?: string
  issue_type?: string
  description?: string
  summary?: string
  severity?: string
  status?: string
  legal_status?: string
  created_at: string
}

export interface SentimentTrendPoint {
  date: string
  avg_sentiment: number
  count: number
}

export interface CategoryBreakdownItem {
  category: string
  count: number
  percentage: number
}

export interface AtRiskContact {
  contact_id?: string
  email: string
  name?: string
  sentiment_score?: number
  last_sentiment?: number | null
  message_count?: number
}

export interface AtRiskAccount {
  account_id?: string | null
  account?: string
  account_name?: string | null
  at_risk_count: number
  contacts: AtRiskContact[]
}

export interface ThreadsParams {
  page?: number
  page_size?: number
  queue?: string
  urgency?: string
  status?: string
  search?: string
}

export interface TicketsParams {
  page?: number
  page_size?: number
  status?: string
  priority?: string
}

export interface EscalationsParams {
  page?: number
  page_size?: number
  status?: string
  level?: string
}

export interface LegalFlagsParams {
  page?: number
  page_size?: number
  status?: string
  severity?: string
}

// ─── API Functions ───────────────────────────────────────────────────────────

/** Authenticate and receive a JWT token */
export const login = async (email: string, password: string): Promise<LoginResponse> => {
  const { data } = await api.post<LoginResponse>('/auth/login', {
    email,
    password,
  })
  return data
}

/** Fetch top-level dashboard statistics */
export const getDashboardStats = async (): Promise<DashboardStats> => {
  const { data } = await api.get<DashboardStats>('/api/dashboard/stats')
  return data
}

/** Fetch paginated threads list with optional filters */
export const getThreads = async (params: ThreadsParams = {}): Promise<PaginatedThreads> => {
  const { data } = await api.get<PaginatedThreads>('/api/threads', { params })
  return data
}

/** Fetch a single thread by ID with its messages */
export const getThread = async (id: number | string): Promise<Thread> => {
  const { data } = await api.get<Thread>(`/api/threads/${id}`)
  return data
}

/** Fetch a single message by ID with full details */
export const getMessage = async (id: number | string): Promise<Message> => {
  const { data } = await api.get<Message>(`/api/messages/${id}`)
  return data
}

/** Trigger an agent run on a message */
export const triggerAgentRun = async (
  messageId: number | string,
  dryRun: boolean = false,
): Promise<AgentRun> => {
  const { data } = await api.post<AgentRun>(`/api/messages/${messageId}/agent-runs`, {
    mode: dryRun ? 'dry_run' : 'live',
  })
  return data
}

/** Fetch agent run detail by ID */
export const getAgentRun = async (id: number | string): Promise<AgentRun> => {
  const { data } = await api.get<AgentRun>(`/api/agent-runs/${id}`)
  return data
}

/** Approve a draft reply */
export const approveDraft = async (draftId: number | string): Promise<Draft> => {
  const { data } = await api.post<Draft>(`/api/drafts/${draftId}/approve`)
  return data
}

/** Edit / patch a draft reply */
export const patchDraft = async (
  draftId: number | string,
  body: { content: string },
): Promise<Draft> => {
  const { data } = await api.patch<Draft>(`/api/drafts/${draftId}`, {
    body: body.content,
  })
  return data
}

/** Fetch tickets list */
export const getTickets = async (params: TicketsParams = {}): Promise<Ticket[]> => {
  const { data } = await api.get<Ticket[]>('/api/tickets', { params })
  return data
}

/** Fetch escalations list */
export const getEscalations = async (
  params: EscalationsParams = {},
): Promise<Escalation[]> => {
  const { data } = await api.get<Escalation[]>('/api/escalations', { params })
  return data
}

/** Fetch legal flags list */
export const getLegalFlags = async (
  params: LegalFlagsParams = {},
): Promise<LegalFlag[]> => {
  const { data } = await api.get<LegalFlag[]>('/api/legal-flags', { params })
  return data
}

/** Fetch daily sentiment trend for the last N days */
export const getSentimentTrend = async (
  days: number = 30,
): Promise<SentimentTrendPoint[]> => {
  const { data } = await api.get<{ trend?: SentimentTrendPoint[] } | SentimentTrendPoint[]>(
    '/api/analytics/sentiment-trend',
    { params: { days } },
  )
  if (Array.isArray(data)) return data
  return data?.trend ?? []
}

/** Fetch category breakdown for the last N days */
export const getCategoryBreakdown = async (
  days: number = 30,
): Promise<CategoryBreakdownItem[]> => {
  const { data } = await api.get<{ breakdown?: CategoryBreakdownItem[] } | CategoryBreakdownItem[]>(
    '/api/analytics/category-breakdown',
    { params: { days } },
  )
  if (Array.isArray(data)) return data
  return data?.breakdown ?? []
}

/** Fetch at-risk accounts */
export const getAtRiskAccounts = async (): Promise<AtRiskAccount[]> => {
  const { data } = await api.get<{ at_risk_accounts?: AtRiskAccount[] } | AtRiskAccount[]>(
    '/api/analytics/at-risk-accounts',
  )
  if (Array.isArray(data)) return data
  return data?.at_risk_accounts ?? []
}

export default api

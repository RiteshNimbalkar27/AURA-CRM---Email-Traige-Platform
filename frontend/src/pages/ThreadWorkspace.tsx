import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getThread,
  getMessage,
  triggerAgentRun,
  approveDraft,
  patchDraft,
} from '../api/client'
import type { Message, AgentRun, Draft, Classification } from '../api/client'

// ─── Helpers ─────────────────────────────────────────────────────────────────
function formatDate(dateStr?: string) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function sentimentLabel(score?: number) {
  if (score === undefined || score === null) return { text: '—', cls: 'text-gray-400' }
  if (score < -0.35) return { text: score.toFixed(3), cls: 'text-red-600' }
  if (score < 0) return { text: score.toFixed(3), cls: 'text-amber-600' }
  if (score > 0.35) return { text: score.toFixed(3), cls: 'text-green-700' }
  return { text: score.toFixed(3), cls: 'text-gray-600' }
}

const Spinner = () => (
  <div className="flex items-center justify-center py-12">
    <div className="w-5 h-5 border-2 border-gray-300 border-t-gray-700 rounded-full animate-spin" />
  </div>
)

const SmallSpinner = () => (
  <span className="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
)

// ─── Classification panel ─────────────────────────────────────────────────────
function ClassificationPanel({ cls }: { cls: Classification }) {
  const sm = sentimentLabel(cls.sentiment_score)
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
      <div>
        <dt className="text-xs text-gray-400 mb-0.5">Category</dt>
        <dd className="text-gray-800 font-medium capitalize">
          {cls.category ? cls.category.replace(/_/g, ' ') : '—'}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-gray-400 mb-0.5">Urgency</dt>
        <dd
          className={`font-medium capitalize text-sm ${
            cls.urgency === 'critical'
              ? 'text-red-600'
              : cls.urgency === 'high'
              ? 'text-amber-600'
              : 'text-gray-700'
          }`}
        >
          {cls.urgency ?? '—'}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-gray-400 mb-0.5">Sentiment</dt>
        <dd className={`font-mono text-xs font-medium ${sm.cls}`}>{sm.text}</dd>
      </div>
      <div>
        <dt className="text-xs text-gray-400 mb-0.5">Confidence</dt>
        <dd className="text-gray-700 text-xs font-medium">
          {cls.confidence !== undefined ? `${(cls.confidence * 100).toFixed(0)}%` : '—'}
        </dd>
      </div>
      {cls.rationale && (
        <div className="col-span-2">
          <dt className="text-xs text-gray-400 mb-0.5">Rationale</dt>
          <dd className="text-xs text-gray-600 leading-relaxed">{cls.rationale}</dd>
        </div>
      )}
      {cls.human_review_required && (
        <div className="col-span-2">
          <p className="text-xs text-amber-700 border-l-2 border-amber-400 pl-2">
            Human review required
          </p>
        </div>
      )}
    </dl>
  )
}

// ─── Agent trace panel ────────────────────────────────────────────────────────
function AgentRunPanel({ run }: { run: AgentRun }) {
  const isSuccess =
    run.status === 'completed' || run.outcome === 'completed' || run.outcome === 'success'
  const isDryRun = run.mode === 'dry_run' || run.dry_run || run.outcome === 'dry_run'
  const isFailed = run.status === 'failed' || run.outcome === 'failed'

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">
          {isDryRun ? 'Dry run' : 'Agent run'} &middot;{' '}
          {formatDate(run.created_at)}
        </span>
        <span
          className={`text-xs font-medium ${
            isSuccess || isDryRun
              ? 'text-green-700'
              : isFailed
              ? 'text-red-600'
              : 'text-gray-500'
          }`}
        >
          {run.outcome ?? run.status ?? (isDryRun ? 'dry_run' : 'completed')}
        </span>
      </div>
      {run.trace && run.trace.length > 0 && (
        <ol className="space-y-2 mt-2">
          {run.trace.map((step, i) => {
            const rawObs = step.observation ?? step.result
            const obsText =
              rawObs === null || rawObs === undefined
                ? null
                : typeof rawObs === 'object'
                ? JSON.stringify(rawObs, null, 2)
                : String(rawObs)

            return (
              <li key={i} className="flex gap-2.5 text-xs">
                <span className="w-4 h-4 text-center font-medium text-gray-400 leading-4 flex-shrink-0">
                  {step.step ?? i + 1}.
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-gray-700">{step.action}</p>
                  {step.rationale && (
                    <p className="text-gray-500 mt-0.5">{step.rationale}</p>
                  )}
                  {obsText && (
                    <pre className="text-gray-400 mt-0.5 leading-relaxed font-mono text-[11px] whitespace-pre-wrap break-all bg-gray-50 p-1.5 border border-gray-100">
                      {obsText}
                    </pre>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

// ─── Draft panel ──────────────────────────────────────────────────────────────
function DraftPanel({
  draft,
  onApprove,
  onEdit,
  approving,
  editing,
}: {
  draft: Draft
  onApprove: (id: string | number) => void
  onEdit: (id: string | number, content: string) => void
  approving: boolean
  editing: boolean
}) {
  const [editMode, setEditMode] = useState(false)
  const initialBody = draft.body ?? draft.content ?? draft.body_preview ?? ''
  const [editContent, setEditContent] = useState(initialBody)
  const draftId = draft.draft_id ?? draft.id!

  const handleSave = () => {
    onEdit(draftId, editContent)
    setEditMode(false)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">
          Draft reply {draft.tone ? `(${draft.tone})` : ''}
        </span>
        <span
          className={`text-xs font-medium ${
            draft.status === 'approved' ? 'text-green-700' : 'text-gray-500'
          }`}
        >
          {draft.status === 'approved' ? 'Approved' : 'Pending approval'}
        </span>
      </div>

      {editMode ? (
        <textarea
          className="w-full text-xs border border-gray-300 p-2 resize-none focus:outline-none focus:border-gray-500 font-mono"
          rows={8}
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
        />
      ) : (
        <div className="text-xs text-gray-700 leading-relaxed border border-gray-200 bg-gray-50 p-2.5 whitespace-pre-wrap font-mono">
          {initialBody}
        </div>
      )}

      {draft.status !== 'approved' && (
        <div className="flex gap-2 pt-1">
          {editMode ? (
            <>
              <button
                onClick={handleSave}
                disabled={editing}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-white text-xs font-medium disabled:opacity-50"
              >
                {editing && <SmallSpinner />}
                Save
              </button>
              <button
                onClick={() => setEditMode(false)}
                className="px-3 py-1.5 text-xs text-gray-600 border border-gray-300 hover:bg-gray-50"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => onApprove(draftId)}
                disabled={approving}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-white text-xs font-medium disabled:opacity-50"
              >
                {approving && <SmallSpinner />}
                Approve &amp; send
              </button>
              <button
                onClick={() => {
                  setEditContent(initialBody)
                  setEditMode(true)
                }}
                className="px-3 py-1.5 text-xs text-gray-600 border border-gray-300 hover:bg-gray-50"
              >
                Edit
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-gray-100 px-4 py-4 last:border-0">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">
        {title}
      </h3>
      {children}
    </div>
  )
}

export default function ThreadWorkspace() {
  const { threadId } = useParams<{ threadId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null)
  const [agentRunResult, setAgentRunResult] = useState<AgentRun | null>(null)

  const { data: thread, isLoading, isError } = useQuery({
    queryKey: ['thread', threadId],
    queryFn: () => getThread(threadId!),
    enabled: !!threadId,
  })

  // When a message is selected, fetch its full detail (all drafts, tickets, runs)
  const { data: detailedMessage } = useQuery({
    queryKey: ['message-detail', selectedMessageId],
    queryFn: () => getMessage(selectedMessageId!),
    enabled: !!selectedMessageId,
  })

  const agentRunMutation = useMutation({
    mutationFn: ({ msgId, dryRun }: { msgId: string | number; dryRun: boolean }) =>
      triggerAgentRun(msgId, dryRun),
    onSuccess: (data) => {
      setAgentRunResult(data)
      queryClient.invalidateQueries({ queryKey: ['thread', threadId] })
      queryClient.invalidateQueries({ queryKey: ['message-detail', selectedMessageId] })
    },
  })

  const approveMutation = useMutation({
    mutationFn: (draftId: string | number) => approveDraft(draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['thread', threadId] })
      queryClient.invalidateQueries({ queryKey: ['message-detail', selectedMessageId] })
    },
  })

  const editMutation = useMutation({
    mutationFn: ({ draftId, content }: { draftId: string | number; content: string }) =>
      patchDraft(draftId, { content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['thread', threadId] })
      queryClient.invalidateQueries({ queryKey: ['message-detail', selectedMessageId] })
    },
  })

  const messages: Message[] = thread?.messages ?? []
  const timelineSelectedMessage =
    messages.find((m) => (m.message_id ?? String(m.id)) === selectedMessageId) ?? null

  const activeMessage = detailedMessage ?? timelineSelectedMessage

  const latestRun: AgentRun | null =
    agentRunResult ??
    activeMessage?.agent_runs?.[activeMessage.agent_runs.length - 1] ??
    null

  const latestDraft: Draft | null =
    activeMessage?.drafts?.[activeMessage.drafts.length - 1] ?? null

  const messageClassification =
    activeMessage?.classification ??
    activeMessage?.classifications?.[0] ??
    timelineSelectedMessage?.classification

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-gray-200 px-4 py-2.5 flex items-center gap-3">
        <button
          onClick={() => navigate('/inbox')}
          className="text-gray-400 hover:text-gray-700 text-xs"
        >
          &larr; Inbox
        </button>
        <span className="text-gray-300">/</span>
        <div className="min-w-0">
          <h2 className="text-sm font-medium text-gray-900 truncate">
            {thread?.subject ?? 'Loading…'}
          </h2>
        </div>
        {thread && (
          <div className="flex items-center gap-3 ml-auto text-xs text-gray-400">
            <span
              className={thread.urgency === 'critical' ? 'text-red-600 font-medium' : ''}
            >
              {thread.urgency ?? 'low'}
            </span>
            <span>&middot;</span>
            <span>{(thread.queue ?? '').replace(/_/g, ' ')}</span>
            <span>&middot;</span>
            <span className="capitalize">{thread.status}</span>
          </div>
        )}
      </div>

      {isLoading && <Spinner />}
      {isError && (
        <p className="px-6 py-4 text-sm text-red-600">
          Failed to load thread. Please try again.
        </p>
      )}

      {thread && (
        <div className="flex flex-1 overflow-hidden">
          {/* Left: message timeline (60%) */}
          <div className="flex-[3] overflow-y-auto border-r border-gray-200">
            <div className="px-4 py-2 border-b border-gray-100 text-xs text-gray-400">
              {messages.length} message{messages.length !== 1 ? 's' : ''}
            </div>

            {messages.map((msg) => {
              const msgKey = msg.message_id ?? String(msg.id)
              const cls = msg.classification
              const isSelected = msgKey === selectedMessageId
              const sender = msg.sender_email ?? msg.sender ?? '—'
              const body = msg.body ?? msg.body_excerpt ?? ''

              return (
                <div
                  key={msgKey}
                  onClick={() => {
                    setSelectedMessageId(isSelected ? null : msgKey)
                    setAgentRunResult(null)
                  }}
                  className={`px-4 py-3.5 border-b border-gray-100 cursor-pointer transition-colors ${
                    isSelected
                      ? 'bg-gray-50 border-l-2 border-l-gray-700'
                      : 'hover:bg-gray-50 border-l-2 border-l-transparent'
                  }`}
                >
                  <div className="flex items-baseline justify-between mb-1.5">
                    <div className="flex items-baseline gap-2 min-w-0">
                      <span className="text-sm font-medium text-gray-900 truncate">
                        {sender}
                      </span>
                      {cls?.urgency && (
                        <span
                          className={`text-xs ${
                            cls.urgency === 'critical'
                              ? 'text-red-600 font-medium'
                              : cls.urgency === 'high'
                              ? 'text-amber-600'
                              : 'text-gray-400'
                          }`}
                        >
                          {cls.urgency}
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-400 flex-shrink-0 ml-3">
                      {formatDate(msg.received_at)}
                    </span>
                  </div>

                  {cls?.category && (
                    <div className="text-xs text-gray-400 mb-1.5 capitalize">
                      {cls.category.replace(/_/g, ' ')}
                    </div>
                  )}

                  <p
                    className={`text-sm text-gray-600 leading-relaxed ${
                      isSelected ? '' : 'line-clamp-2'
                    }`}
                  >
                    {body}
                  </p>

                  {isSelected && cls && (
                    <div className="mt-3 pt-3 border-t border-gray-200">
                      <ClassificationPanel cls={cls} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Right: action panel (40%) */}
          <div className="flex-[2] overflow-y-auto">
            {!selectedMessageId ? (
              <div className="flex items-center justify-center h-full text-xs text-gray-400">
                Select a message to view details
              </div>
            ) : (
              <div>
                {/* Agent actions */}
                <Section title="Agent">
                  <div className="flex gap-2 mb-2">
                    <button
                      onClick={() =>
                        agentRunMutation.mutate({
                          msgId: selectedMessageId,
                          dryRun: false,
                        })
                      }
                      disabled={agentRunMutation.isPending}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-white text-xs font-medium disabled:opacity-50"
                    >
                      {agentRunMutation.isPending &&
                        !agentRunMutation.variables?.dryRun && <SmallSpinner />}
                      Run agent
                    </button>
                    <button
                      onClick={() =>
                        agentRunMutation.mutate({
                          msgId: selectedMessageId,
                          dryRun: true,
                        })
                      }
                      disabled={agentRunMutation.isPending}
                      className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 text-gray-700 hover:bg-gray-50 text-xs font-medium disabled:opacity-50"
                    >
                      {agentRunMutation.isPending &&
                        agentRunMutation.variables?.dryRun && <SmallSpinner />}
                      Dry run
                    </button>
                  </div>
                  {agentRunMutation.isError && (
                    <p className="text-xs text-red-600">
                      Agent run failed:{' '}
                      {(agentRunMutation.error as any)?.response?.data?.detail?.message ??
                        (agentRunMutation.error as any)?.response?.data?.detail ??
                        (agentRunMutation.error as any)?.message ??
                        'Please try again.'}
                    </p>
                  )}
                </Section>

                {/* Classification if available */}
                {messageClassification && (
                  <Section title="Classification">
                    <ClassificationPanel cls={messageClassification} />
                  </Section>
                )}

                {/* Agent trace */}
                {latestRun && (
                  <Section title="Agent trace">
                    <AgentRunPanel run={latestRun} />
                  </Section>
                )}

                {/* Draft */}
                {latestDraft && (
                  <Section title="Draft reply">
                    <DraftPanel
                      draft={latestDraft}
                      onApprove={(id) => approveMutation.mutate(id)}
                      onEdit={(id, content) =>
                        editMutation.mutate({ draftId: id, content })
                      }
                      approving={approveMutation.isPending}
                      editing={editMutation.isPending}
                    />
                  </Section>
                )}

                {/* Tickets */}
                {activeMessage?.tickets && activeMessage.tickets.length > 0 && (
                  <Section title={`Tickets (${activeMessage.tickets.length})`}>
                    <div className="space-y-2">
                      {activeMessage.tickets.map((t) => (
                        <div
                          key={t.ticket_id ?? t.id}
                          className="text-xs border-l-2 border-gray-300 pl-2.5 py-0.5"
                        >
                          <p className="font-medium text-gray-700">{t.title}</p>
                          <p className="text-gray-400 capitalize mt-0.5">
                            {t.ticket_type} &middot; {t.priority} &middot; {t.status}
                          </p>
                        </div>
                      ))}
                    </div>
                  </Section>
                )}

                {/* Escalations */}
                {activeMessage?.escalations && activeMessage.escalations.length > 0 && (
                  <Section title={`Escalations (${activeMessage.escalations.length})`}>
                    <div className="space-y-2">
                      {activeMessage.escalations.map((e) => (
                        <div
                          key={e.escalation_id ?? e.id}
                          className="text-xs border-l-2 border-amber-400 pl-2.5 py-0.5"
                        >
                          <p className="font-medium text-gray-700">{e.reason}</p>
                          <p className="text-gray-400 capitalize mt-0.5">
                            Priority: {e.priority ?? e.level ?? 'medium'} &middot;{' '}
                            {e.status}
                          </p>
                        </div>
                      ))}
                    </div>
                  </Section>
                )}

                {/* Legal flags */}
                {activeMessage?.legal_flags && activeMessage.legal_flags.length > 0 && (
                  <Section title={`Legal flags (${activeMessage.legal_flags.length})`}>
                    <div className="space-y-2">
                      {activeMessage.legal_flags.map((f) => (
                        <div
                          key={f.legal_flag_id ?? f.id}
                          className="text-xs border-l-2 border-red-400 pl-2.5 py-0.5"
                        >
                          <p className="font-medium text-gray-700">
                            {f.issue_type ?? f.flag_type}
                          </p>
                          <p className="text-gray-400 mt-0.5">
                            {f.summary ?? f.description} &middot; Status:{' '}
                            {f.legal_status ?? f.status}
                          </p>
                        </div>
                      ))}
                    </div>
                  </Section>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

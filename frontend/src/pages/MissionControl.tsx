import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getDashboardStats, getThreads } from '../api/client'
import type { Thread, DashboardStats } from '../api/client'

// ─── Urgency: critical gets red dot, rest are plain text ─────────────────────
function UrgencyCell({ urgency }: { urgency: string }) {
  if (urgency === 'critical') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-red-700 font-medium">
        <span className="w-1.5 h-1.5 rounded-full bg-red-600 flex-shrink-0" />
        Critical
      </span>
    )
  }
  if (urgency === 'high') {
    return <span className="text-xs text-amber-700 font-medium">High</span>
  }
  return <span className="text-xs text-gray-500 capitalize">{urgency}</span>
}

function queueLabel(q: string) {
  return q.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatRelative(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

const Spinner = () => (
  <div className="flex items-center justify-center py-12">
    <div className="w-5 h-5 border-2 border-gray-300 border-t-gray-700 rounded-full animate-spin" />
  </div>
)

export default function MissionControl() {
  const navigate = useNavigate()

  const [queue, setQueue] = useState('')
  const [urgency, setUrgency] = useState('')
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)

  const { data: stats, isLoading: statsLoading } = useQuery<DashboardStats>({
    queryKey: ['dashboard-stats'],
    queryFn: getDashboardStats,
  })

  const {
    data: threadsData,
    isLoading: threadsLoading,
    isError: threadsError,
  } = useQuery({
    queryKey: ['threads', { queue, urgency, status, search, page }],
    queryFn: () =>
      getThreads({
        page,
        page_size: 20,
        queue: queue || undefined,
        urgency: urgency || undefined,
        status: status || undefined,
        search: search || undefined,
      }),
  })

  const threads: Thread[] = threadsData?.threads ?? []
  const totalPages = threadsData?.pages ?? threadsData?.total_pages ?? 1

  const selectClass =
    'px-2 py-1.5 text-sm border border-gray-300 bg-white text-gray-700 focus:outline-none focus:border-gray-500'

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Inbox</h2>
        </div>

        {!statsLoading && stats && (
          <div className="flex items-center gap-6 text-xs text-gray-500">
            <span>
              <span className="font-medium text-gray-800">
                {stats.total_open_threads ?? stats.open_threads ?? stats.total_emails ?? 0}
              </span>{' '}
              open
            </span>
            {(stats.open_escalations ?? stats.escalations ?? 0) > 0 && (
              <span className="text-amber-700">
                <span className="font-medium">
                  {stats.open_escalations ?? stats.escalations}
                </span>{' '}
                escalation
                {(stats.open_escalations ?? stats.escalations) !== 1 ? 's' : ''}
              </span>
            )}
            {(stats.open_legal_flags ?? stats.legal_flags ?? 0) > 0 && (
              <span className="text-red-700">
                <span className="font-medium">
                  {stats.open_legal_flags ?? stats.legal_flags}
                </span>{' '}
                legal flag
                {(stats.open_legal_flags ?? stats.legal_flags) !== 1 ? 's' : ''}
              </span>
            )}
            {(stats.pending_review ?? 0) > 0 && (
              <span className="text-amber-600">
                <span className="font-medium">{stats.pending_review}</span> review required
              </span>
            )}
          </div>
        )}
      </div>

      {/* Filter bar */}
      <div className="border-b border-gray-200 px-6 py-2 flex items-center gap-2 bg-gray-50">
        <input
          type="text"
          placeholder="Search subject or sender"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
          className="flex-1 min-w-0 max-w-xs px-2 py-1.5 text-sm border border-gray-300 bg-white focus:outline-none focus:border-gray-500 placeholder-gray-400"
        />

        <select
          value={queue}
          onChange={(e) => {
            setQueue(e.target.value)
            setPage(1)
          }}
          className={selectClass}
        >
          <option value="">All queues</option>
          <option value="security">Security</option>
          <option value="legal_compliance">Legal / Compliance</option>
          <option value="reputation">Reputation</option>
          <option value="support_operations">Support</option>
        </select>

        <select
          value={urgency}
          onChange={(e) => {
            setUrgency(e.target.value)
            setPage(1)
          }}
          className={selectClass}
        >
          <option value="">All urgency</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
          className={selectClass}
        >
          <option value="">All status</option>
          <option value="open">Open</option>
          <option value="in_progress">In progress</option>
          <option value="resolved">Resolved</option>
        </select>

        {(queue || urgency || status || search) && (
          <button
            onClick={() => {
              setQueue('')
              setUrgency('')
              setStatus('')
              setSearch('')
              setPage(1)
            }}
            className="px-2 py-1.5 text-xs text-gray-500 hover:text-gray-800 border border-gray-300 bg-white"
          >
            Clear
          </button>
        )}
      </div>

      {/* Thread table */}
      <div className="flex-1 overflow-y-auto">
        {threadsLoading && <Spinner />}

        {threadsError && (
          <p className="px-6 py-4 text-sm text-red-600">
            Failed to load threads. Ensure the backend is running.
          </p>
        )}

        {!threadsLoading && !threadsError && (
          <>
            {threads.length === 0 ? (
              <p className="px-6 py-8 text-sm text-gray-400">
                No threads match the current filters.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 text-left">
                    <th className="px-6 py-2.5 text-xs font-medium text-gray-500 w-24">
                      Urgency
                    </th>
                    <th className="px-3 py-2.5 text-xs font-medium text-gray-500">
                      Subject
                    </th>
                    <th className="px-3 py-2.5 text-xs font-medium text-gray-500">
                      Queue
                    </th>
                    <th className="px-3 py-2.5 text-xs font-medium text-gray-500">
                      Category
                    </th>
                    <th className="px-3 py-2.5 text-xs font-medium text-gray-500">
                      Status
                    </th>
                    <th className="px-3 py-2.5 text-xs font-medium text-gray-500 text-right pr-6">
                      Updated
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {threads.map((thread) => {
                    const tid = thread.thread_id ?? String(thread.id)
                    const urg = thread.classification?.urgency ?? thread.urgency ?? 'low'
                    const category = thread.classification?.category
                    const humanReview =
                      thread.classification?.human_review_required ??
                      thread.human_review_required
                    const timestamp =
                      thread.last_message_at ?? thread.updated_at ?? thread.created_at

                    return (
                      <tr
                        key={tid}
                        onClick={() => navigate(`/threads/${tid}`)}
                        className={`cursor-pointer hover:bg-gray-50 transition-colors ${
                          urg === 'critical' ? 'bg-red-50/40' : ''
                        }`}
                      >
                        <td className="pl-6 pr-2 py-3">
                          <UrgencyCell urgency={urg} />
                        </td>

                        <td className="px-3 py-3">
                          <span className="text-gray-900 font-medium truncate block max-w-md">
                            {thread.subject}
                          </span>
                          {humanReview && (
                            <span className="text-xs text-amber-600">Review required</span>
                          )}
                        </td>

                        <td className="px-3 py-3 text-gray-500 whitespace-nowrap">
                          {queueLabel(thread.queue ?? '')}
                        </td>

                        <td className="px-3 py-3 text-gray-500 capitalize whitespace-nowrap">
                          {category ? category.replace(/_/g, ' ') : '—'}
                        </td>

                        <td className="px-3 py-3">
                          <span
                            className={`text-xs capitalize ${
                              thread.status === 'open'
                                ? 'text-gray-700'
                                : thread.status === 'resolved'
                                ? 'text-gray-400'
                                : 'text-gray-500'
                            }`}
                          >
                            {thread.status}
                          </span>
                        </td>

                        <td className="px-3 py-3 pr-6 text-xs text-gray-400 text-right whitespace-nowrap">
                          {timestamp ? formatRelative(timestamp) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}

            {totalPages > 1 && (
              <div className="flex items-center justify-between px-6 py-2.5 border-t border-gray-200 text-xs text-gray-500 bg-gray-50">
                <span>
                  Page {page} of {totalPages} &middot; {threadsData?.total ?? 0} threads
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}
                    className="px-3 py-1 border border-gray-300 bg-white text-gray-600 disabled:opacity-40 hover:bg-gray-50"
                  >
                    Previous
                  </button>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                    className="px-3 py-1 border border-gray-300 bg-white text-gray-600 disabled:opacity-40 hover:bg-gray-50"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

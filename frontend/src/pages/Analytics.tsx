import { useQuery } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import {
  getSentimentTrend,
  getCategoryBreakdown,
  getAtRiskAccounts,
} from '../api/client'
import type { SentimentTrendPoint, CategoryBreakdownItem, AtRiskAccount } from '../api/client'

// ─── Helpers ──────────────────────────────────────────────────────────────────
const Spinner = () => (
  <div className="flex items-center justify-center py-10">
    <div className="w-5 h-5 border-2 border-gray-300 border-t-gray-700 rounded-full animate-spin" />
  </div>
)

const ErrorMsg = ({ msg }: { msg: string }) => (
  <p className="text-sm text-red-600 py-4">{msg}</p>
)

// Plain tooltip — clean and unflashy
const PlainTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-gray-200 px-2.5 py-1.5 text-xs shadow-none">
      <p className="text-gray-500 mb-0.5">{label}</p>
      {payload.map((p: any, i: number) => (
        <p key={i} className="text-gray-800 font-medium">
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(3) : p.value}
        </p>
      ))}
    </div>
  )
}

// ─── Sentiment Trend ──────────────────────────────────────────────────────────
function SentimentTrendChart() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['sentiment-trend'],
    queryFn: () => getSentimentTrend(30),
  })

  if (isLoading) return <Spinner />
  if (isError) return <ErrorMsg msg="Failed to load sentiment trend." />

  const points: SentimentTrendPoint[] = Array.isArray(data)
    ? data
    : ((data as any)?.trend ?? [])

  if (!points || points.length === 0)
    return <p className="text-sm text-gray-400 py-4">No data for the last 30 days.</p>

  const chartData = points.map((d) => ({
    date: d.date
      ? new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : '—',
    sentiment: typeof d.avg_sentiment === 'number' ? parseFloat(d.avg_sentiment.toFixed(3)) : 0,
  }))

  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 10, fill: '#9ca3af' }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          domain={[-1, 1]}
          tick={{ fontSize: 10, fill: '#9ca3af' }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip content={<PlainTooltip />} />
        <ReferenceLine y={0} stroke="#d1d5db" strokeDasharray="4 2" />
        <ReferenceLine
          y={-0.35}
          stroke="#fca5a5"
          strokeDasharray="4 2"
          label={{
            value: 'at-risk',
            fontSize: 9,
            fill: '#f87171',
            position: 'insideBottomRight',
          }}
        />
        <Line
          type="monotone"
          dataKey="sentiment"
          name="Avg sentiment"
          stroke="#374151"
          strokeWidth={1.5}
          dot={{ r: 2, fill: '#374151' }}
          activeDot={{ r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ─── Category Breakdown ───────────────────────────────────────────────────────
function CategoryBreakdownChart() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['category-breakdown'],
    queryFn: () => getCategoryBreakdown(30),
  })

  if (isLoading) return <Spinner />
  if (isError) return <ErrorMsg msg="Failed to load category breakdown." />

  const items: CategoryBreakdownItem[] = Array.isArray(data)
    ? data
    : ((data as any)?.breakdown ?? [])

  if (!items || items.length === 0)
    return <p className="text-sm text-gray-400 py-4">No data for the last 30 days.</p>

  const chartData = items.map((d) => ({
    name: d.category ? d.category.replace(/_/g, ' ') : '—',
    count: d.count ?? 0,
  }))

  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 36 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 10, fill: '#9ca3af' }}
          tickLine={false}
          axisLine={false}
          angle={-30}
          textAnchor="end"
        />
        <YAxis
          tick={{ fontSize: 10, fill: '#9ca3af' }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip content={<PlainTooltip />} cursor={{ fill: '#f9fafb' }} />
        <Bar dataKey="count" name="Emails" fill="#374151" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// ─── At-Risk Accounts ─────────────────────────────────────────────────────────
function AtRiskAccountsTable() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['at-risk-accounts'],
    queryFn: getAtRiskAccounts,
  })

  if (isLoading) return <Spinner />
  if (isError) return <ErrorMsg msg="Failed to load at-risk accounts." />

  const accounts: AtRiskAccount[] = Array.isArray(data)
    ? data
    : ((data as any)?.at_risk_accounts ?? [])

  if (!accounts || accounts.length === 0)
    return <p className="text-sm text-gray-400 py-4">No at-risk accounts.</p>

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-gray-200">
          <th className="text-left py-2 pr-6 text-xs font-medium text-gray-400">Account</th>
          <th className="text-left py-2 pr-6 text-xs font-medium text-gray-400">
            At-risk contacts
          </th>
          <th className="text-left py-2 text-xs font-medium text-gray-400">Contacts</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {accounts.map((account, i) => (
          <tr
            key={account.account_id ?? i}
            className={account.at_risk_count > 0 ? 'bg-red-50/30' : ''}
          >
            <td className="py-2.5 pr-6 font-medium text-gray-900">
              {account.account_name ?? account.account ?? 'Unnamed Account'}
            </td>
            <td className="py-2.5 pr-6">
              <span
                className={`text-sm font-medium ${
                  account.at_risk_count > 0 ? 'text-red-600' : 'text-gray-400'
                }`}
              >
                {account.at_risk_count}
              </span>
            </td>
            <td className="py-2.5 text-xs text-gray-500">
              {(account.contacts ?? []).slice(0, 4).map((c, j) => {
                const sScore = c.last_sentiment ?? c.sentiment_score
                return (
                  <span
                    key={j}
                    className="mr-2"
                    title={
                      sScore !== undefined && sScore !== null
                        ? `Sentiment: ${sScore.toFixed(2)}`
                        : undefined
                    }
                  >
                    {c.name ?? c.email}
                    {j < Math.min((account.contacts ?? []).length, 4) - 1 ? ',' : ''}
                  </span>
                )
              })}
              {(account.contacts ?? []).length > 4 && (
                <span className="text-gray-400">
                  +{(account.contacts ?? []).length - 4} more
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────
function Section({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-3">
        <h3 className="text-sm font-medium text-gray-900">{title}</h3>
        {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function Analytics() {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 py-3">
        <h2 className="text-sm font-semibold text-gray-900">Analytics</h2>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        {/* Charts row */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-8 mb-8">
          <Section
            title="Sentiment trend"
            subtitle="Daily average sentiment score — last 30 days"
          >
            <SentimentTrendChart />
          </Section>

          <Section
            title="Category breakdown"
            subtitle="Email volume by category — last 30 days"
          >
            <CategoryBreakdownChart />
          </Section>
        </div>

        {/* At-risk table */}
        <Section
          title="At-risk accounts"
          subtitle="Accounts with contacts showing sustained negative sentiment (below −0.35)"
        >
          <AtRiskAccountsTable />
        </Section>
      </div>
    </div>
  )
}

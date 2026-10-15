import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

interface NavItemProps {
  to: string
  label: string
}

function NavItem({ to, label }: NavItemProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `block px-4 py-2 text-sm border-l-2 transition-colors ${
          isActive
            ? 'border-white text-white font-medium'
            : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-500'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex h-screen bg-gray-100 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-52 flex-shrink-0 bg-slate-900 flex flex-col select-none">
        {/* Product name */}
        <div className="px-4 py-4 border-b border-slate-800">
          <span className="text-white font-semibold text-sm tracking-wide">AURA</span>
          <span className="text-slate-500 text-xs block mt-0.5">Email Triage</span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-3 space-y-0.5">
          <p className="px-4 pt-1 pb-2 text-xs text-slate-600 uppercase tracking-wider">
            Workspace
          </p>
          <NavItem to="/inbox" label="Inbox" />
          <NavItem to="/analytics" label="Analytics" />
        </nav>

        {/* Session */}
        <div className="px-4 py-3 border-t border-slate-800">
          <p className="text-slate-400 text-xs truncate mb-2">
            {user?.email ?? user?.sub ?? 'Operator'}
          </p>
          <button
            onClick={handleLogout}
            className="text-slate-500 hover:text-slate-300 text-xs transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-y-auto bg-white">{children}</main>
    </div>
  )
}

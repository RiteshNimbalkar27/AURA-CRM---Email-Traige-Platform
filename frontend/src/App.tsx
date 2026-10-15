import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import MissionControl from './pages/MissionControl'
import ThreadWorkspace from './pages/ThreadWorkspace'
import Analytics from './pages/Analytics'
import ProtectedRoute from './components/ProtectedRoute'

export default function App() {
  return (
    <Routes>
      {/* Public route */}
      <Route path="/login" element={<Login />} />

      {/* Protected routes — wrapped in Layout shell */}
      <Route element={<ProtectedRoute />}>
        <Route path="/inbox" element={<MissionControl />} />
        <Route path="/threads/:threadId" element={<ThreadWorkspace />} />
        <Route path="/analytics" element={<Analytics />} />
      </Route>

      {/* Root redirect */}
      <Route path="/" element={<Navigate to="/inbox" replace />} />

      {/* Catch-all */}
      <Route path="*" element={<Navigate to="/inbox" replace />} />
    </Routes>
  )
}

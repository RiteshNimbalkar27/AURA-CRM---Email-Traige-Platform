import { Routes, Route, Navigate } from 'react-router-dom'

// Placeholder pages — will be implemented in Phase 3
const MissionControl = () => (
  <div className="min-h-screen bg-gray-50 flex items-center justify-center">
    <div className="text-center">
      <h1 className="text-3xl font-bold text-gray-900">AURA</h1>
      <p className="text-gray-500 mt-2">Mission Control — coming in Phase 3</p>
    </div>
  </div>
)

const ThreadWorkspace = () => (
  <div className="min-h-screen bg-gray-50 flex items-center justify-center">
    <h1 className="text-2xl font-bold text-gray-900">Thread Workspace — Phase 3</h1>
  </div>
)

const Analytics = () => (
  <div className="min-h-screen bg-gray-50 flex items-center justify-center">
    <h1 className="text-2xl font-bold text-gray-900">Analytics — Phase 3</h1>
  </div>
)

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/inbox" replace />} />
      <Route path="/inbox" element={<MissionControl />} />
      <Route path="/threads/:threadId" element={<ThreadWorkspace />} />
      <Route path="/analytics" element={<Analytics />} />
    </Routes>
  )
}

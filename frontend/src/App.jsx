import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import Chat from './pages/Chat';
import Inbox from './pages/Inbox';
import Sessions from './pages/Sessions';
import Config from './pages/Config';
import Dashboard from './pages/Dashboard';
import Skills from './pages/Skills';
import Memory from './pages/Memory';
import Security from './pages/Security';
import Cron from './pages/Cron';
import Pairing from './pages/Pairing';
import Subagents from './pages/Subagents';
import Nodes from './pages/Nodes';
import Webhooks from './pages/Webhooks';
import Plugins from './pages/Plugins';
import Agents from './pages/Agents';
import Usage from './pages/Usage';

function AppRoutes() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<Login />} />

      {/* Protected */}
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <Layout>
              <Routes>
                {/* Chat */}
                <Route path="/" element={<Chat />} />

                {/* Channels */}
                <Route path="/inbox" element={<Inbox />} />
                <Route path="/sessions" element={<Sessions />} />
                <Route path="/pairing" element={<Pairing />} />

                {/* System */}
                <Route path="/memory" element={<Memory />} />
                <Route path="/subagents" element={<Subagents />} />
                <Route path="/cron" element={<Cron />} />
                <Route path="/security" element={<Security />} />
                <Route path="/nodes" element={<Nodes />} />
                <Route path="/webhooks" element={<Webhooks />} />

                {/* Settings */}
                <Route path="/skills" element={<Skills />} />
                <Route path="/plugins" element={<Plugins />} />
                <Route path="/agents" element={<Agents />} />
                <Route path="/config" element={<Config />} />
                <Route path="/usage" element={<Usage />} />
                <Route path="/dashboard" element={<Dashboard />} />

                {/* Catch all */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}

import { useEffect } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { auth } from '../api';

export default function ProtectedRoute({ children }) {
  const navigate = useNavigate();

  useEffect(() => {
    const handler = () => navigate('/login', { replace: true });
    window.addEventListener('ungula:auth-required', handler);
    return () => window.removeEventListener('ungula:auth-required', handler);
  }, [navigate]);

  if (!auth.isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

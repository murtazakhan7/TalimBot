import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { loginUser, registerUser } from '../api/client';

export default function LoginPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('login');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Login form state
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');

  // Register form state
  const [regName, setRegName] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regPassword, setRegPassword] = useState('');

  // Redirect if already logged in
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      navigate('/upload');
    }
  }, [navigate]);

  async function handleLogin(e) {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const data = await loginUser(loginEmail, loginPassword);
      localStorage.setItem('access_token', data.access_token);
      navigate('/upload');
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccessMsg('');

    try {
      await registerUser(regEmail, regPassword, regName);
      setSuccessMsg('Registration successful! You can now log in.');
      setActiveTab('login');
      // Clear register fields
      setRegName('');
      setRegEmail('');
      setRegPassword('');
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <h1 style={styles.title}>TaleemBot</h1>

        {/* Tab switcher */}
        <div style={styles.tabs}>
          <button
            style={{ ...styles.tab, ...(activeTab === 'login' ? styles.tabActive : {}) }}
            onClick={() => {
              setActiveTab('login');
              setError('');
              setSuccessMsg('');
            }}
          >
            Login
          </button>
          <button
            style={{ ...styles.tab, ...(activeTab === 'register' ? styles.tabActive : {}) }}
            onClick={() => {
              setActiveTab('register');
              setError('');
              setSuccessMsg('');
            }}
          >
            Register
          </button>
        </div>

        {/* Error message */}
        {error && <div style={styles.error}>{error}</div>}

        {/* Success message */}
        {successMsg && <div style={styles.success}>{successMsg}</div>}

        {/* Login form */}
        {activeTab === 'login' && (
          <div style={styles.form}>
            <input
              type="email"
              placeholder="Email"
              value={loginEmail}
              onChange={(e) => setLoginEmail(e.target.value)}
              style={styles.input}
              required
            />
            <input
              type="password"
              placeholder="Password"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              style={styles.input}
              required
            />
            <button
              onClick={handleLogin}
              disabled={loading || !loginEmail || !loginPassword}
              style={styles.button}
            >
              {loading ? 'Logging in...' : 'Login'}
            </button>
          </div>
        )}

        {/* Register form */}
        {activeTab === 'register' && (
          <div style={styles.form}>
            <input
              type="text"
              placeholder="Full Name"
              value={regName}
              onChange={(e) => setRegName(e.target.value)}
              style={styles.input}
              required
            />
            <input
              type="email"
              placeholder="Email"
              value={regEmail}
              onChange={(e) => setRegEmail(e.target.value)}
              style={styles.input}
              required
            />
            <input
              type="password"
              placeholder="Password"
              value={regPassword}
              onChange={(e) => setRegPassword(e.target.value)}
              style={styles.input}
              required
            />
            <button
              onClick={handleRegister}
              disabled={loading || !regName || !regEmail || !regPassword}
              style={styles.button}
            >
              {loading ? 'Creating account...' : 'Create Account'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    backgroundColor: '#0f0f0f',
    color: '#f0f0f0',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '20px',
    fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  card: {
    maxWidth: '400px',
    width: '100%',
    backgroundColor: '#1a1a1a',
    borderRadius: '12px',
    padding: '32px',
    boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
  },
  title: {
    fontSize: '32px',
    fontWeight: '600',
    textAlign: 'center',
    margin: '0 0 24px 0',
    color: '#c084fc',
  },
  tabs: {
    display: 'flex',
    gap: '8px',
    marginBottom: '24px',
  },
  tab: {
    flex: 1,
    padding: '10px',
    border: 'none',
    borderRadius: '6px',
    backgroundColor: '#2a2a2a',
    color: '#9ca3af',
    cursor: 'pointer',
    fontSize: '14px',
    fontWeight: '500',
    transition: 'all 0.2s',
  },
  tabActive: {
    backgroundColor: '#c084fc',
    color: '#fff',
  },
  error: {
    backgroundColor: '#7f1d1d',
    color: '#fecaca',
    padding: '12px',
    borderRadius: '6px',
    marginBottom: '16px',
    fontSize: '14px',
  },
  success: {
    backgroundColor: '#14532d',
    color: '#bbf7d0',
    padding: '12px',
    borderRadius: '6px',
    marginBottom: '16px',
    fontSize: '14px',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  input: {
    padding: '12px',
    borderRadius: '6px',
    border: '1px solid #3a3a3a',
    backgroundColor: '#2a2a2a',
    color: '#f0f0f0',
    fontSize: '14px',
    outline: 'none',
  },
  button: {
    padding: '12px',
    borderRadius: '6px',
    border: 'none',
    backgroundColor: '#c084fc',
    color: '#fff',
    fontSize: '14px',
    fontWeight: '600',
    cursor: 'pointer',
    opacity: 1,
    transition: 'opacity 0.2s',
  },
};

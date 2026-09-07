import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { parseCV, parseJD, parseJDText, startInterview } from '../api/client';
import Logo from '../components/Logo';

export default function UploadPage() {
  const navigate = useNavigate();

  const [cvText, setCvText] = useState('');
  const [jdText, setJdText] = useState('');
  const [jdRawText, setJdRawText] = useState('');
  const [cvCharCount, setCvCharCount] = useState(0);
  const [jdCharCount, setJdCharCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [loadingMessage, setLoadingMessage] = useState('Reading your CV...');
  const [jdMode, setJdMode] = useState('text');
  

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) navigate('/login');
  }, [navigate]);

  useEffect(() => {
    if (!loading) return;
    const messages = [
      'Reading your CV...',
      'Analysing the job description...',
      'Identifying key skill domains...',
      'Preparing your first question...',
      'Almost ready...',
    ];
    let index = 0;
    const interval = setInterval(() => {
      index = (index + 1) % messages.length;
      setLoadingMessage(messages[index]);
    }, 3000);
    return () => clearInterval(interval);
  }, [loading]);

  async function handleCVUpload(file) {
    setLoading(true); setError('');
    try {
      const data = await parseCV(file);
      setCvText(data.text);
      setCvCharCount(data.char_count || data.text.length);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to parse CV. Please upload a valid PDF.');
      setCvText(''); setCvCharCount(0);
    } finally { setLoading(false); }
  }

  async function handleJDUpload(file) {
    setLoading(true); setError('');
    try {
      const data = await parseJD(file);
      setJdText(data.text);
      setJdCharCount(data.char_count || data.text.length);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to parse JD. Please upload a valid PDF.');
      setJdText(''); setJdCharCount(0);
    } finally { setLoading(false); }
  }

  async function handleJDTextSubmit(text) {
    setLoading(true); setError('');
    try {
      const data = await parseJDText(text);
      setJdText(data.text);
      setJdCharCount(data.char_count || data.text.length);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to parse JD text.');
      setJdText(''); setJdCharCount(0);
    } finally { setLoading(false); }
  }

  async function handleStartInterview() {
    const parentInterviewId = sessionStorage.getItem('parent_interview_id') || null;
    sessionStorage.clear();
    const candidateName = getNameFromToken();
    if (!cvText || !jdText) {
      setError('Please complete both steps before starting the interview.');
      return;
    }
    setLoading(true); setError(''); setLoadingMessage('Reading your CV...');
    try {
      const data = await startInterview(candidateName, cvText, jdText, parentInterviewId);
      sessionStorage.setItem('session_id', data.session_id);
      sessionStorage.setItem('question_text', data.question_text);
      sessionStorage.setItem('audio_base64', data.audio_base64 || '');
      sessionStorage.removeItem('parent_interview_id');
      navigate('/interview');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start interview. Please try again.');
    } finally { setLoading(false); }
  }

  function getNameFromToken() {
    try {
      const token = localStorage.getItem('access_token');
      if (!token) return 'Candidate';
      const payload = JSON.parse(atob(token.split('.')[1]));
      const fullName = payload.full_name || payload.name || '';
      return fullName.split(' ')[0] || payload.email?.split('@')[0] || 'Candidate';
    } catch { return 'Candidate'; }
  }

  function handleLogout() {
    if (!window.confirm('Are you sure you want to logout?')) return;
    localStorage.removeItem('access_token');
    navigate('/login');
  }

  if (loading && cvText && jdText) {
    return (
      <div style={styles.loadingContainer}>
        <Logo size={60} />
        <div style={styles.spinner} />
        <h2 style={styles.loadingMessage}>{loadingMessage}</h2>
        <p style={styles.loadingNote}>This usually takes 15–30 seconds</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        {/* Logo (clickable home) + explicit Home button at a distance */}
        <div style={styles.topBarLeft}>
          <div onClick={() => navigate('/dashboard')} title="Back to dashboard" style={styles.logoLink}>
            <Logo size={40} />
          </div>
          <button onClick={() => navigate('/dashboard')} style={styles.homeBtn}>
            🏠 Home
          </button>
        </div>

        <div style={styles.topBarRight}>
          <button onClick={() => navigate('/history')} style={styles.historyBtn}>
            My Interviews
          </button>
          <button onClick={handleLogout} style={styles.logoutBtn}>
            Logout
          </button>
        </div>
      </div>

      <div style={styles.content}>
        <h1 style={styles.title}>Setup Your Interview</h1>

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.step}>
          <div style={styles.stepHeader}>
            <span style={styles.stepNumber}>Step 1</span>
            <h3 style={styles.stepTitle}>Upload Your CV (PDF)</h3>
          </div>
          <input
            type="file" accept=".pdf"
            onChange={(e) => { const f = e.target.files[0]; if (f) handleCVUpload(f); }}
            style={styles.fileInput}
          />
          {loading && cvCharCount === 0 && <div style={styles.inlineLoading}>Parsing CV...</div>}
          {cvCharCount > 0 && (
            <div style={styles.success}>CV parsed successfully ({cvCharCount} characters extracted)</div>
          )}
        </div>

        <div style={styles.step}>
          <div style={styles.stepHeader}>
            <span style={styles.stepNumber}>Step 2</span>
            <h3 style={styles.stepTitle}>Job Description</h3>
          </div>

          <div style={styles.modeToggle}>
            <button
              style={{ ...styles.modeBtn, ...(jdMode === 'text' ? styles.modeBtnActive : {}) }}
              onClick={() => setJdMode('text')}
            >Paste Text</button>
            <button
              style={{ ...styles.modeBtn, ...(jdMode === 'file' ? styles.modeBtnActive : {}) }}
              onClick={() => setJdMode('file')}
            >Upload PDF</button>
          </div>

          {jdMode === 'text' ? (
            <div>
              <textarea
                placeholder="Paste the job description here..."
                rows={8}
                value={jdRawText}
                onChange={(e) => setJdRawText(e.target.value)}
                style={styles.textarea}
              />
              <button
                onClick={() => handleJDTextSubmit(jdRawText)}
                disabled={loading || !jdRawText.trim()}
                style={{ ...styles.confirmJdBtn, opacity: loading || !jdRawText.trim() ? 0.5 : 1 }}
              >
                {loading ? 'Parsing...' : 'Confirm Job Description'}
              </button>
            </div>
          ) : (
            <div>
              <input
                type="file" accept=".pdf"
                onChange={(e) => { const f = e.target.files[0]; if (f) handleJDUpload(f); }}
                style={styles.fileInput}
              />
              {loading && jdCharCount === 0 && jdMode === 'file' && (
                <div style={styles.inlineLoading}>Parsing JD...</div>
              )}
            </div>
          )}

          {jdCharCount > 0 && (
            <div style={styles.success}>JD parsed successfully ({jdCharCount} characters extracted)</div>
          )}
        </div>

        <button
          onClick={handleStartInterview}
          disabled={loading || !cvText || !jdText}
          style={{ ...styles.startBtn, opacity: loading || !cvText || !jdText ? 0.5 : 1 }}
        >
          {loading && cvText && jdText ? 'Starting...' : 'Start Interview'}
        </button>
      </div>
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #0a0a0f 0%, #0f0f1a 100%)',
    color: '#f1f5f9',
    fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  topBar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '16px 32px',
    borderBottom: '1px solid #1e1e35',
  },
  topBarLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '20px',
  },
  topBarRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  logoLink: {
    cursor: 'pointer',
  },
  homeBtn: {
    padding: '7px 16px',
    borderRadius: '6px',
    border: 'none',
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    color: '#fff',
    fontSize: '13px',
    fontWeight: '600',
    cursor: 'pointer',
    letterSpacing: '0.2px',
  },
  historyBtn: {
    padding: '10px 20px',
    borderRadius: '6px',
    border: '1px solid #6366f1',
    backgroundColor: 'transparent',
    color: '#6366f1',
    cursor: 'pointer',
    fontSize: '14px',
    fontWeight: '500',
  },
  logoutBtn: {
    padding: '4px 8px',
    borderRadius: '4px',
    border: 'none',
    backgroundColor: 'transparent',
    color: '#64748b',
    cursor: 'pointer',
    fontSize: '13px',
  },
  content: { maxWidth: '600px', margin: '0 auto', padding: '32px 20px' },
  title: { fontSize: '28px', fontWeight: '600', textAlign: 'center', margin: '0 0 32px 0' },
  error: {
    backgroundColor: '#450a0a', color: '#fecaca', padding: '12px',
    borderRadius: '6px', marginBottom: '24px', fontSize: '14px',
  },
  success: {
    backgroundColor: '#052e16', color: '#bbf7d0', padding: '12px',
    borderRadius: '6px', marginTop: '12px', fontSize: '14px',
  },
  step: {
    marginBottom: '32px', padding: '24px', backgroundColor: '#13131f',
    borderRadius: '12px', border: '1px solid #1e1e35',
    boxShadow: '0 4px 24px rgba(99, 102, 241, 0.08)',
  },
  stepHeader: { display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' },
  stepNumber: {
    backgroundColor: '#6366f1', color: '#fff', padding: '4px 12px',
    borderRadius: '12px', fontSize: '12px', fontWeight: '600',
  },
  stepTitle: { fontSize: '18px', fontWeight: '500', margin: 0 },
  textarea: {
    width: '100%', padding: '12px', borderRadius: '6px', border: '1px solid #1e1e35',
    backgroundColor: '#1e1e35', color: '#f1f5f9', fontSize: '14px',
    outline: 'none', resize: 'vertical', boxSizing: 'border-box',
  },
  fileInput: {
    width: '100%', padding: '12px', borderRadius: '6px', border: '1px solid #1e1e35',
    backgroundColor: '#1e1e35', color: '#f1f5f9', fontSize: '14px', boxSizing: 'border-box',
  },
  modeToggle: { display: 'flex', gap: '8px', marginBottom: '16px' },
  modeBtn: {
    flex: 1, padding: '10px', borderRadius: '6px', border: '1px solid #1e1e35',
    backgroundColor: '#1e1e35', color: '#64748b', cursor: 'pointer',
    fontSize: '14px', fontWeight: '500',
  },
  modeBtnActive: { backgroundColor: '#6366f1', color: '#fff', border: '1px solid #6366f1' },
  confirmJdBtn: {
    width: '100%', padding: '10px', borderRadius: '6px', border: '1px solid #6366f1',
    backgroundColor: 'transparent', color: '#6366f1', fontSize: '14px',
    fontWeight: '500', cursor: 'pointer', marginTop: '12px', transition: 'all 0.2s',
  },
  inlineLoading: { fontSize: '13px', color: '#8b5cf6', marginTop: '8px', fontStyle: 'italic' },
  startBtn: {
    width: '100%', padding: '16px', borderRadius: '8px', border: 'none',
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    color: '#fff', fontSize: '16px', fontWeight: '600', cursor: 'pointer', marginTop: '16px',
  },
  loadingContainer: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #0a0a0f 0%, #0f0f1a 100%)',
    color: '#f1f5f9', display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center', gap: '32px',
    fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  spinner: {
    width: '48px', height: '48px', border: '4px solid #1e1e35',
    borderTop: '4px solid #6366f1', borderRadius: '50%', animation: 'spin 1s linear infinite',
  },
  loadingMessage: { fontSize: '20px', fontWeight: '500', color: '#f1f5f9', margin: 0 },
  loadingNote: { fontSize: '14px', color: '#64748b', margin: 0 },
};

if (typeof document !== 'undefined') {
  const existing = document.getElementById('upload-animations');
  if (!existing) {
    const style = document.createElement('style');
    style.id = 'upload-animations';
    style.textContent = `@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }`;
    document.head.appendChild(style);
  }
}
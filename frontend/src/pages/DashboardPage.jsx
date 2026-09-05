import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCurrentUser } from '../api/client';
import Logo from '../components/Logo';

const CARDS = [
  {
    id: 'practice',
    emoji: '🎯',
    title: 'Practice for an Interview',
    description: 'Upload your CV and a job description to start a tailored AI interview',
    cta: 'Start Practice',
    to: '/upload',
  },
  {
    id: 'history',
    emoji: '📊',
    title: 'My Interviews',
    description: 'Review your past interviews, scores, and track your improvement',
    cta: 'View History',
    to: '/history',
  },
  {
    id: 'premium',
    emoji: '⭐',
    title: 'Premium Features',
    description: 'Unlock advanced coaching, detailed analytics, and unlimited sessions',
    cta: 'Coming Soon',
    to: null,
  },
];

// The JWT is base64url, which atob cannot read as-is
function readTokenPayload(token) {
  const segment = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
  return JSON.parse(atob(segment));
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [userName, setUserName] = useState('');
  const [hoveredCard, setHoveredCard] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    let fullName = '';
    let email = '';

    if (token) {
      try {
        const payload = readTokenPayload(token);
        fullName = payload.full_name || '';
        email = payload.sub || payload.email || '';
      } catch {
        // Unreadable token — /auth/me below is the fallback
      }
    }

    setUserName((fullName || email).split(' ')[0]);

    if (!fullName) {
      getCurrentUser()
        .then((me) => setUserName(((me.full_name || me.email || email) + '').split(' ')[0]))
        .catch(() => {});
    }
  }, []);

  function handleLogout() {
    if (!window.confirm('Are you sure you want to logout?')) return;
    localStorage.removeItem('access_token');
    navigate('/login');
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <Logo size={40} />
        <div style={styles.topBarRight}>
          <span style={styles.welcomeText}>
            Welcome back{userName ? `, ${userName}` : ''}
          </span>
          <button onClick={handleLogout} style={styles.logoutBtn}>Logout</button>
        </div>
      </div>

      <div style={styles.hero}>
        <h1 style={styles.heroTitle}>Ready to practice?</h1>
        <p style={styles.heroSubtitle}>
          AI-powered mock interviews tailored to your CV and target role
        </p>
      </div>

      <div style={styles.cardGrid}>
        {CARDS.map((card) => {
          const isDisabled = card.to === null;
          const isHovered = hoveredCard === card.id && !isDisabled;

          return (
            <div
              key={card.id}
              onMouseEnter={() => setHoveredCard(card.id)}
              onMouseLeave={() => setHoveredCard(null)}
              style={{
                ...styles.card,
                ...(isHovered ? styles.cardHover : {}),
              }}
            >
              <div style={styles.cardEmoji}>{card.emoji}</div>
              <h2 style={styles.cardTitle}>{card.title}</h2>
              <p style={styles.cardDescription}>{card.description}</p>
              <button
                onClick={() => { if (card.to) navigate(card.to); }}
                disabled={isDisabled}
                style={{
                  ...styles.cardBtn,
                  ...(isDisabled ? styles.cardBtnDisabled : {}),
                }}
              >
                {card.cta}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    backgroundColor: '#0a0a0f',
    backgroundImage: 'linear-gradient(135deg, #0a0a0f 0%, #0f0f1a 100%)',
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
  topBarRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
  },
  welcomeText: {
    fontSize: '14px',
    color: '#94a3b8',
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
  hero: {
    textAlign: 'center',
    padding: '60px 20px 40px',
  },
  heroTitle: {
    fontSize: '48px',
    fontWeight: '700',
    margin: '0 0 16px',
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
  },
  heroSubtitle: {
    fontSize: '18px',
    color: '#64748b',
    margin: 0,
  },
  cardGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: '24px',
    maxWidth: '1000px',
    margin: '0 auto',
    padding: '0 20px 60px',
  },
  card: {
    backgroundColor: '#13131f',
    // Longhand on purpose: cardHover overrides borderColor, and React clearing a
    // longhand that was set via the `border` shorthand falls back to currentColor.
    borderWidth: '1px',
    borderStyle: 'solid',
    borderColor: '#1e1e35',
    borderRadius: '16px',
    padding: '40px 32px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '16px',
    textAlign: 'center',
    boxShadow: '0 4px 24px rgba(99, 102, 241, 0.08)',
    transition: 'border-color 0.2s, box-shadow 0.2s',
  },
  cardHover: {
    borderColor: '#6366f1',
    boxShadow: '0 8px 32px rgba(99, 102, 241, 0.2)',
  },
  cardEmoji: {
    fontSize: '64px',
    lineHeight: 1,
  },
  cardTitle: {
    fontSize: '20px',
    fontWeight: '600',
    color: '#f1f5f9',
    margin: 0,
  },
  cardDescription: {
    fontSize: '14px',
    color: '#64748b',
    lineHeight: '1.6',
    margin: 0,
  },
  cardBtn: {
    marginTop: 'auto',
    padding: '12px 24px',
    borderRadius: '8px',
    border: 'none',
    backgroundColor: '#6366f1',
    color: '#fff',
    fontSize: '14px',
    fontWeight: '600',
    cursor: 'pointer',
    width: '100%',
  },
  cardBtnDisabled: {
    backgroundColor: '#1e1e35',
    color: '#64748b',
    cursor: 'not-allowed',
  },
};

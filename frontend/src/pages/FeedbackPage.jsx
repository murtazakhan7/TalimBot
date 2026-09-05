import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Logo from '../components/Logo';

export default function FeedbackPage() {
  const navigate = useNavigate();
  const [scores, setScores] = useState(null);
  const [copyStatus, setCopyStatus] = useState('');

  useEffect(() => {
    const raw = sessionStorage.getItem('interview_scores');
    if (!raw) { navigate('/upload'); return; }
    try {
      setScores(JSON.parse(raw));
    } catch {
      navigate('/upload');
    }
  }, [navigate]);

  if (!scores) return null;

  // Reframe hire_recommendation as readiness level
  function getReadinessLabel(recommendation) {
    const map = {
      'Strong hire': { label: 'Interview Ready', color: '#10b981' },
      'Hire': { label: 'Almost Ready', color: '#10b981' },
      'Lean hire': { label: 'Getting There', color: '#f59e0b' },
      'No hire': { label: 'Needs Practice', color: '#ef4444' },
    };
    return map[recommendation] || { label: 'Practice Complete', color: '#6366f1' };
  }

  const readiness = getReadinessLabel(scores.hire_recommendation);

  // Backend emits {domain: number} scores plus top-level strengths/improvements/summary
  const domainScore = (data) => (typeof data === 'number' ? data : (data?.score || 0));
  const strengths = scores.detailed_feedback?.strengths || scores.strengths || [];
  const improvements = scores.detailed_feedback?.improvements || scores.improvements || [];
  const summaryText = scores.summary_feedback || scores.summary || '';

  // Motivational message based on score
  function getMotivationalMessage(score) {
    if (score >= 8) return "Excellent work! You're well prepared for real interviews.";
    if (score >= 7) return "Great progress! A bit more practice and you'll be interview-ready.";
    if (score >= 6) return "You're on the right track. Keep practising — you're making great progress!";
    if (score >= 5) return "Good effort! Focus on the areas below and you'll see improvement.";
    return "Keep going! Every practice session brings you closer to success.";
  }

  function handlePracticeAgain() {
    // Keep a link to this attempt so the next one can show improvement
    const currentInterviewId = sessionStorage.getItem('session_id');
    sessionStorage.clear();
    if (currentInterviewId) {
      sessionStorage.setItem('parent_interview_id', currentInterviewId);
    }
    navigate('/upload');
  }

  async function handleCopySummary() {
    const domainLines = scores.domain_scores
      ? Object.entries(scores.domain_scores)
          .map(([domain, data]) => `- ${domain}: ${domainScore(data).toFixed(1)}/10`)
          .join('\n')
      : 'No domain data available';

    const text = `TalimBot Interview Results
Overall Score: ${(scores.overall_score || 0).toFixed(1)}/10
Readiness: ${readiness.label}

Domain Scores:
${domainLines}

${summaryText}`;

    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus('Copied!');
      setTimeout(() => setCopyStatus(''), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  }

  return (
    <div style={styles.container}>
      {/* Top bar */}
      <div style={styles.topBar}>
        <Logo size={40} />
        <div style={{ display: 'flex', gap: '12px' }}>
          <button onClick={handleCopySummary} style={styles.copyBtn}>
            {copyStatus || 'Copy Summary'}
          </button>
          <button onClick={handlePracticeAgain} style={styles.practiceBtn}>
            Practice Again
          </button>
        </div>
      </div>

      <div style={styles.content}>
        {/* Hero section */}
        <div style={styles.hero}>
          <div style={styles.scoreCircle}>
            <span style={styles.scoreValue}>{scores.overall_score?.toFixed(1) || 'N/A'}</span>
            <span style={styles.scoreMax}>/ 10</span>
          </div>
          <div
            style={{
              ...styles.readinessBadge,
              backgroundColor: readiness.color + '20',
              border: `2px solid ${readiness.color}`,
              color: readiness.color,
            }}
          >
            {readiness.label}
          </div>
          <p style={styles.motivational}>{getMotivationalMessage(scores.overall_score)}</p>
        </div>

        {/* Domain breakdown */}
        {scores.domain_scores && Object.keys(scores.domain_scores).length > 0 && (
          <div style={styles.section}>
            <h2 style={styles.sectionTitle}>Domain Breakdown</h2>
            {Object.entries(scores.domain_scores).map(([domain, data]) => {
              const score = domainScore(data);
              const barColor = score >= 7 ? '#10b981' : score >= 5 ? '#f59e0b' : '#ef4444';
              
              return (
                <div key={domain} style={styles.domainCard}>
                  <div style={styles.domainHeader}>
                    <h3 style={styles.domainName}>{domain}</h3>
                    <span style={styles.domainScore}>{score.toFixed(1)} / 10</span>
                  </div>
                  
                  {/* Score bar */}
                  <div style={styles.scoreBarContainer}>
                    <div
                      style={{
                        ...styles.scoreBarFill,
                        width: `${(score / 10) * 100}%`,
                        backgroundColor: barColor,
                      }}
                    />
                  </div>

                  {/* Reasoning */}
                  {data.reasoning && (
                    <p style={styles.reasoning}>{data.reasoning}</p>
                  )}

                  {/* Strength and gap */}
                  {(data.strength || data.gap) && (
                  <div style={styles.domainDetails}>
                    {data.strength && (
                      <div style={styles.detailItem}>
                        <span style={styles.detailLabel}>What you did well:</span>
                        <p style={styles.detailText}>{data.strength}</p>
                      </div>
                    )}
                    {data.gap && (
                      <div style={styles.detailItem}>
                        <span style={styles.detailLabel}>Focus on this:</span>
                        <p style={styles.detailText}>{data.gap}</p>
                      </div>
                    )}
                  </div>
                  )}

                  {data.expected_highlights && data.expected_highlights.length > 0 && (
                    <div style={styles.highlightsSection}>
                      <span style={styles.detailLabel}>What a strong answer covers:</span>
                      {data.expected_highlights.map((h, i) => (
                        <div key={i} style={styles.highlightItem}>
                          <span style={styles.highlightDot}>◆</span>
                          <span>{h}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Overall assessment */}
        {summaryText && (
          <div style={styles.section}>
            <h2 style={styles.sectionTitle}>Overall Assessment</h2>
            <p style={styles.summaryText}>{summaryText}</p>
          </div>
        )}

        {/* Coaching section */}
        {(strengths.length > 0 || improvements.length > 0) && (
          <div style={styles.coachingSection}>
            <div style={styles.coachingColumn}>
              <h3 style={styles.coachingTitle}>Your Strengths</h3>
              {strengths.map((item, idx) => (
                <div key={idx} style={styles.bulletPoint}>
                  <span style={styles.bulletIcon}>✓</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>

            <div style={styles.coachingColumn}>
              <h3 style={styles.coachingTitle}>Work On These</h3>
              {improvements.map((item, idx) => (
                <div key={idx} style={styles.bulletPointOrange}>
                  <span style={styles.bulletIconOrange}>→</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Interview tips */}
        {scores.detailed_feedback?.interview_tips && (
          <div style={styles.tipsSection}>
            <h2 style={styles.sectionTitle}>💡 Interview Tips</h2>
            {scores.detailed_feedback.interview_tips.map((tip, idx) => (
              <div key={idx} style={styles.tipItem}>
                <span style={styles.tipIcon}>💡</span>
                <span>{tip}</span>
              </div>
            ))}
          </div>
        )}
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
  copyBtn: {
    padding: '10px 20px',
    borderRadius: '6px',
    border: '1px solid #6366f1',
    backgroundColor: 'transparent',
    color: '#6366f1',
    cursor: 'pointer',
    fontSize: '14px',
    fontWeight: '500',
  },
  practiceBtn: {
    padding: '10px 20px',
    borderRadius: '6px',
    border: '1px solid #6366f1',
    backgroundColor: 'transparent',
    color: '#6366f1',
    cursor: 'pointer',
    fontSize: '14px',
    fontWeight: '500',
  },
  content: {
    maxWidth: '800px',
    margin: '0 auto',
    padding: '40px 20px',
  },
  hero: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '24px',
    marginBottom: '48px',
  },
  scoreCircle: {
    width: '160px',
    height: '160px',
    borderRadius: '50%',
    border: '4px solid #6366f1',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#13131f',
    boxShadow: '0 0 0 8px rgba(99, 102, 241, 0.2)',
  },
  scoreValue: {
    fontSize: '48px',
    fontWeight: '700',
    color: '#6366f1',
  },
  scoreMax: {
    fontSize: '16px',
    color: '#64748b',
  },
  readinessBadge: {
    padding: '8px 24px',
    borderRadius: '20px',
    fontSize: '16px',
    fontWeight: '600',
  },
  motivational: {
    fontSize: '18px',
    color: '#64748b',
    textAlign: 'center',
    maxWidth: '600px',
    lineHeight: '1.6',
  },
  section: {
    marginBottom: '40px',
  },
  sectionTitle: {
    fontSize: '24px',
    fontWeight: '600',
    marginBottom: '20px',
    color: '#f1f5f9',
  },
  domainCard: {
    backgroundColor: '#13131f',
    borderRadius: '12px',
    padding: '24px',
    marginBottom: '16px',
    border: '1px solid #1e1e35',
    boxShadow: '0 4px 24px rgba(99, 102, 241, 0.08)',
  },
  domainHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '12px',
  },
  domainName: {
    fontSize: '18px',
    fontWeight: '600',
    margin: 0,
  },
  domainScore: {
    fontSize: '16px',
    fontWeight: '600',
    color: '#6366f1',
  },
  scoreBarContainer: {
    width: '100%',
    height: '8px',
    backgroundColor: '#1e1e35',
    borderRadius: '4px',
    overflow: 'hidden',
    marginBottom: '16px',
  },
  scoreBarFill: {
    height: '100%',
    transition: 'width 0.3s ease',
  },
  reasoning: {
    fontSize: '14px',
    color: '#64748b',
    lineHeight: '1.6',
    marginBottom: '16px',
  },
  domainDetails: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  detailItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  detailLabel: {
    fontSize: '12px',
    fontWeight: '600',
    color: '#6366f1',
    textTransform: 'uppercase',
  },
  detailText: {
    fontSize: '14px',
    color: '#d1d5db',
    lineHeight: '1.5',
    margin: 0,
  },
  highlightsSection: {
    marginTop: '12px',
    padding: '12px',
    backgroundColor: '#0f0f1a',
    borderRadius: '8px',
    border: '1px solid #1e1e35',
  },
  highlightItem: {
    display: 'flex',
    gap: '8px',
    alignItems: 'flex-start',
    marginTop: '6px',
    fontSize: '13px',
    color: '#94a3b8',
    lineHeight: '1.5',
  },
  highlightDot: {
    color: '#6366f1',
    fontSize: '10px',
    flexShrink: 0,
    marginTop: '3px',
  },
  coachingSection: {
    display: 'grid',
    gridTemplateColumns: '1fr',
    gap: '24px',
    marginBottom: '40px',
  },
  coachingColumn: {
    backgroundColor: '#13131f',
    borderRadius: '12px',
    padding: '24px',
    border: '1px solid #1e1e35',
    boxShadow: '0 4px 24px rgba(99, 102, 241, 0.08)',
  },
  coachingTitle: {
    fontSize: '18px',
    fontWeight: '600',
    marginBottom: '16px',
    marginTop: 0,
  },
  bulletPoint: {
    display: 'flex',
    gap: '12px',
    alignItems: 'flex-start',
    marginBottom: '12px',
    fontSize: '14px',
    color: '#bbf7d0',
    lineHeight: '1.5',
  },
  bulletIcon: {
    color: '#10b981',
    fontWeight: '700',
    flexShrink: 0,
  },
  bulletPointOrange: {
    display: 'flex',
    gap: '12px',
    alignItems: 'flex-start',
    marginBottom: '12px',
    fontSize: '14px',
    color: '#fed7aa',
    lineHeight: '1.5',
  },
  bulletIconOrange: {
    color: '#f59e0b',
    fontWeight: '700',
    flexShrink: 0,
  },
  tipsSection: {
    backgroundColor: '#13131f',
    borderRadius: '12px',
    padding: '24px',
    border: '1px solid #1e1e35',
    boxShadow: '0 4px 24px rgba(99, 102, 241, 0.08)',
  },
  tipItem: {
    display: 'flex',
    gap: '12px',
    alignItems: 'flex-start',
    marginBottom: '16px',
    fontSize: '14px',
    color: '#d1d5db',
    lineHeight: '1.5',
  },
  tipIcon: {
    flexShrink: 0,
  },
  summaryText: {
    fontSize: '16px',
    lineHeight: '1.7',
    color: '#d1d5db',
  },
};

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getInterviewHistory, getInterviewFeedback, restartInterview } from '../api/client';
import Logo from '../components/Logo';

// Same readiness framing and colours as FeedbackPage
const READINESS_COLORS = {
  'Strong hire': '#10b981',
  'Hire': '#10b981',
  'Lean hire': '#f59e0b',
  'No hire': '#ef4444',
};

function readinessColor(recommendation) {
  return READINESS_COLORS[recommendation] || '#6366f1';
}

function scoreColor(score) {
  if (score >= 7) return '#10b981';
  if (score >= 5) return '#f59e0b';
  return '#ef4444';
}

function formatDate(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// Scores arrive either as a number or as a rich object per domain
const domainScore = (data) => (typeof data === 'number' ? data : (data?.score || 0));

export default function HistoryPage() {
  const navigate = useNavigate();
  const [history, setHistory] = useState([]);
  const [expandedId, setExpandedId] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackError, setFeedbackError] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [practicingId, setPracticingId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getInterviewHistory()
      .then((data) => { if (!cancelled) setHistory(Array.isArray(data) ? data : []); })
      .catch((err) => {
        if (!cancelled) setError(err.response?.data?.detail || 'Could not load your interviews.');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  async function handleCardClick(interviewId) {
    // Clicking the open card collapses it
    if (expandedId === interviewId) {
      setExpandedId(null);
      setFeedback(null);
      setFeedbackError('');
      return;
    }

    setExpandedId(interviewId);
    setFeedback(null);
    setFeedbackError('');
    setFeedbackLoading(true);

    try {
      const data = await getInterviewFeedback(interviewId);
      setFeedback(data);
    } catch (err) {
      setFeedbackError(err.response?.data?.detail || 'Could not load this feedback.');
    } finally {
      setFeedbackLoading(false);
    }
  }

async function handlePracticeAgain(interviewId) {
  setPracticingId(interviewId);
  try {
    const data = await restartInterview(interviewId);
    sessionStorage.clear();
    sessionStorage.setItem('session_id', data.session_id);
    sessionStorage.setItem('question_text', data.question_text);
    sessionStorage.setItem('audio_base64', data.audio_base64 || '');
    navigate('/interview');
  } catch {
    alert('Could not restart interview. Please try again.');
  } finally {
    setPracticingId(null);
  }
}

  return (
    <div style={styles.container}>
      {/* Top bar */}
      <div style={styles.topBar}>
        <Logo size={40} />
        <button onClick={() => navigate('/upload')} style={styles.newPracticeBtn}>
          New Practice
        </button>
      </div>

      <div style={styles.content}>
        <h1 style={styles.title}>My Interviews</h1>
        <p style={styles.subtitle}>Every practice session you have completed, newest first.</p>

        {error && <div style={styles.error}>{error}</div>}

        {loading && (
          <div style={styles.emptyState}>
            <div style={styles.spinner} />
            <p style={styles.emptyText}>Loading your interviews...</p>
          </div>
        )}

        {!loading && !error && history.length === 0 && (
          <div style={styles.emptyState}>
            <p style={styles.emptyText}>
              No practice interviews yet. Your completed sessions will show up here so you can
              track how you improve.
            </p>
            <button onClick={() => navigate('/upload')} style={styles.startBtn}>
              Start Your First Practice
            </button>
          </div>
        )}

        {!loading && history.map((item) => {
          const score = typeof item.overall_score === 'number' ? item.overall_score : null;
          const improved =
            score !== null &&
            typeof item.parent_score === 'number' &&
            score > item.parent_score;
          const isOpen = expandedId === item.id;
          const color = readinessColor(item.hire_recommendation);

          return (
            <div key={item.id} style={styles.cardWrap}>
              <div
                onClick={() => handleCardClick(item.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleCardClick(item.id); }}
                style={{ ...styles.card, ...(isOpen ? styles.cardOpen : {}) }}
              >
                <div style={styles.cardLeft}>
                  <div style={styles.jobTitle}>{item.job_title || 'Practice Interview'}</div>
                  <div style={styles.date}>{formatDate(item.created_at)}</div>
                  {improved && (
                    <div style={styles.improved}>
                      ↑ +{(score - item.parent_score).toFixed(1)} from last attempt
                    </div>
                  )}
                </div>

                <div style={styles.cardRight}>
                  {score !== null ? (
                    <>
                      <div style={{ ...styles.scoreCircle, borderColor: scoreColor(score) }}>
                        <span style={{ ...styles.scoreValue, color: scoreColor(score) }}>
                          {score.toFixed(1)}
                        </span>
                        <span style={styles.scoreMax}>/ 10</span>
                      </div>
                      <div
                        style={{
                          ...styles.readinessBadge,
                          backgroundColor: color + '20',
                          border: `2px solid ${color}`,
                          color,
                        }}
                      >
                        {item.readiness || 'Practice Complete'}
                      </div>
                    </>
                  ) : (
                    <div style={styles.inProgress}>Not scored yet</div>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handlePracticeAgain(item.id);
                    }}
                    disabled={practicingId === item.id}
                    style={{
                      ...styles.practiceAgainBtn,
                      opacity: practicingId === item.id ? 0.5 : 1,
                    }}
                  >
                    {practicingId === item.id ? 'Starting...' : '🔄 Practice Again'}
                  </button>
                  <div style={styles.chevron}>{isOpen ? '▾' : '▸'}</div>
                </div>
              </div>

              {isOpen && (
                <div style={styles.expanded}>
                  {feedbackLoading && (
                    <div style={styles.expandedNote}>Loading feedback...</div>
                  )}

                  {feedbackError && (
                    <div style={styles.expandedNote}>{feedbackError}</div>
                  )}

                  {feedback && (
                    <>
                      {feedback.summary_feedback && (
                        <div style={styles.block}>
                          <h3 style={styles.blockTitle}>Overall Assessment</h3>
                          <p style={styles.summaryText}>{feedback.summary_feedback}</p>
                        </div>
                      )}

                      {feedback.domain_scores && Object.keys(feedback.domain_scores).length > 0 && (
                        <div style={styles.block}>
                          <h3 style={styles.blockTitle}>Domain Breakdown</h3>
                          {Object.entries(feedback.domain_scores).map(([domain, data]) => {
                            const value = domainScore(data);
                            const barColor = scoreColor(value);
                            return (
                              <div key={domain} style={styles.domainCard}>
                                <div style={styles.domainHeader}>
                                  <span style={styles.domainName}>{domain}</span>
                                  <span style={styles.domainScore}>{value.toFixed(1)} / 10</span>
                                </div>
                                <div style={styles.scoreBarContainer}>
                                  <div
                                    style={{
                                      ...styles.scoreBarFill,
                                      width: `${(value / 10) * 100}%`,
                                      backgroundColor: barColor,
                                    }}
                                  />
                                </div>
                                {data?.reasoning && <p style={styles.reasoning}>{data.reasoning}</p>}
                                {(data?.strength || data?.gap) && (
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
                                {data?.expected_highlights?.length > 0 && (
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

                      {(feedback.strengths?.length > 0 || feedback.improvements?.length > 0) && (
                        <div style={styles.coachingSection}>
                          {feedback.strengths?.length > 0 && (
                            <div style={styles.coachingColumn}>
                              <h3 style={styles.blockTitle}>Your Strengths</h3>
                              {feedback.strengths.map((s, i) => (
                                <div key={i} style={styles.bulletPoint}>
                                  <span style={styles.bulletIcon}>✓</span>
                                  <span>{s}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          {feedback.improvements?.length > 0 && (
                            <div style={styles.coachingColumn}>
                              <h3 style={styles.blockTitle}>Work On These</h3>
                              {feedback.improvements.map((s, i) => (
                                <div key={i} style={styles.bulletPointOrange}>
                                  <span style={styles.bulletIconOrange}>→</span>
                                  <span>{s}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {feedback.detailed_feedback?.interview_tips?.length > 0 && (
                        <div style={styles.block}>
                          <h3 style={styles.blockTitle}>💡 Interview Tips</h3>
                          {feedback.detailed_feedback.interview_tips.map((tip, i) => (
                            <div key={i} style={styles.tipItem}>
                              <span>💡</span>
                              <span>{tip}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
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
  newPracticeBtn: {
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
  title: {
    fontSize: '28px',
    fontWeight: '600',
    margin: '0 0 8px 0',
  },
  subtitle: {
    fontSize: '14px',
    color: '#64748b',
    margin: '0 0 32px 0',
  },
  error: {
    backgroundColor: '#450a0a',
    color: '#fecaca',
    padding: '12px',
    borderRadius: '6px',
    marginBottom: '24px',
    fontSize: '14px',
  },
  emptyState: {
    backgroundColor: '#13131f',
    border: '1px solid #1e1e35',
    borderRadius: '12px',
    padding: '40px 24px',
    textAlign: 'center',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '20px',
  },
  emptyText: {
    fontSize: '15px',
    color: '#94a3b8',
    lineHeight: '1.6',
    margin: 0,
    maxWidth: '460px',
  },
  spinner: {
    width: '36px',
    height: '36px',
    border: '3px solid #1e1e35',
    borderTop: '3px solid #6366f1',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
  },
  startBtn: {
    padding: '12px 24px',
    borderRadius: '8px',
    border: 'none',
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    color: '#fff',
    fontSize: '15px',
    fontWeight: '600',
    cursor: 'pointer',
  },
  cardWrap: {
    marginBottom: '16px',
  },
  card: {
    backgroundColor: '#13131f',
    border: '1px solid #1e1e35',
    borderRadius: '12px',
    padding: '20px 24px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '16px',
    cursor: 'pointer',
    boxShadow: '0 4px 24px rgba(99, 102, 241, 0.08)',
  },
  cardOpen: {
    borderBottomLeftRadius: '0px',
    borderBottomRightRadius: '0px',
    borderColor: '#6366f1',
  },
  cardLeft: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    minWidth: 0,
  },
  jobTitle: {
    fontSize: '17px',
    fontWeight: '600',
    color: '#f1f5f9',
  },
  date: {
    fontSize: '13px',
    color: '#64748b',
  },
  improved: {
    fontSize: '13px',
    fontWeight: '600',
    color: '#10b981',
  },
  cardRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    flexShrink: 0,
  },
  scoreCircle: {
    width: '64px',
    height: '64px',
    borderRadius: '50%',
    border: '3px solid #6366f1',
    backgroundColor: '#0f0f1a',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
  },
  scoreValue: {
    fontSize: '18px',
    fontWeight: '700',
    color: '#6366f1',
    lineHeight: 1,
  },
  scoreMax: {
    fontSize: '10px',
    color: '#64748b',
    marginTop: '2px',
  },
  readinessBadge: {
    padding: '6px 14px',
    borderRadius: '16px',
    fontSize: '13px',
    fontWeight: '600',
    whiteSpace: 'nowrap',
  },
  inProgress: {
    fontSize: '13px',
    color: '#64748b',
    fontStyle: 'italic',
  },
  practiceAgainBtn: {
    padding: '6px 14px',
    borderRadius: '6px',
    border: '1px solid #6366f1',
    backgroundColor: 'transparent',
    color: '#6366f1',
    fontSize: '12px',
    cursor: 'pointer',
    fontWeight: '500',
  },
  chevron: {
    color: '#475569',
    fontSize: '14px',
  },
  expanded: {
    backgroundColor: '#0f0f1a',
    border: '1px solid #6366f1',
    borderTop: 'none',
    borderBottomLeftRadius: '12px',
    borderBottomRightRadius: '12px',
    padding: '24px',
  },
  expandedNote: {
    fontSize: '14px',
    color: '#94a3b8',
    fontStyle: 'italic',
  },
  block: {
    marginBottom: '28px',
  },
  blockTitle: {
    fontSize: '16px',
    fontWeight: '600',
    color: '#f1f5f9',
    margin: '0 0 14px 0',
  },
  summaryText: {
    fontSize: '15px',
    lineHeight: '1.7',
    color: '#d1d5db',
    margin: 0,
  },
  domainCard: {
    backgroundColor: '#13131f',
    borderRadius: '12px',
    padding: '20px',
    marginBottom: '12px',
    border: '1px solid #1e1e35',
  },
  domainHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '10px',
  },
  domainName: {
    fontSize: '16px',
    fontWeight: '600',
  },
  domainScore: {
    fontSize: '15px',
    fontWeight: '600',
    color: '#6366f1',
  },
  scoreBarContainer: {
    width: '100%',
    height: '8px',
    backgroundColor: '#1e1e35',
    borderRadius: '4px',
    overflow: 'hidden',
    marginBottom: '14px',
  },
  scoreBarFill: {
    height: '100%',
    transition: 'width 0.3s ease',
  },
  reasoning: {
    fontSize: '14px',
    color: '#64748b',
    lineHeight: '1.6',
    marginBottom: '14px',
  },
  domainDetails: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
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
    gap: '16px',
    marginBottom: '28px',
  },
  coachingColumn: {
    backgroundColor: '#13131f',
    borderRadius: '12px',
    padding: '20px',
    border: '1px solid #1e1e35',
  },
  bulletPoint: {
    display: 'flex',
    gap: '12px',
    alignItems: 'flex-start',
    marginBottom: '10px',
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
    marginBottom: '10px',
    fontSize: '14px',
    color: '#fed7aa',
    lineHeight: '1.5',
  },
  bulletIconOrange: {
    color: '#f59e0b',
    fontWeight: '700',
    flexShrink: 0,
  },
  tipItem: {
    display: 'flex',
    gap: '12px',
    alignItems: 'flex-start',
    marginBottom: '14px',
    fontSize: '14px',
    color: '#d1d5db',
    lineHeight: '1.5',
  },
};

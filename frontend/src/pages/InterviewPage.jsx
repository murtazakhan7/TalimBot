import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import useVoiceRecorder from '../hooks/useVoiceRecorder';
import { logProctorEvent } from '../api/client';
import Logo from '../components/Logo';

export default function InterviewPage() {
  const navigate = useNavigate();
  const audioRef = useRef(null);
  const interviewStartRef = useRef(Date.now());
  const proctorTimerRef = useRef(null);
  const domainsSeenRef = useRef(new Set());

  // Read session data
  const sessionId = sessionStorage.getItem('session_id');
  const initialQuestionText = sessionStorage.getItem('question_text') || '';
  const initialAudioBase64 = sessionStorage.getItem('audio_base64') || '';

  // State for readiness check
  const [isReady, setIsReady] = useState(false);

  // State
  const [currentQuestion, setCurrentQuestion] = useState(initialQuestionText);
  const [currentDomain, setCurrentDomain] = useState(sessionStorage.getItem('current_domain') || 'General');
  const [questionNumber, setQuestionNumber] = useState(parseInt(sessionStorage.getItem('question_number') || '1'));
  const [totalDomains, setTotalDomains] = useState(parseInt(sessionStorage.getItem('total_domains') || '4'));
  const [domainsCovered, setDomainsCovered] = useState(parseInt(sessionStorage.getItem('domains_covered') || '0'));
  const [isPlaying, setIsPlaying] = useState(false);
  const [lastTranscript, setLastTranscript] = useState('');
  const [timeRemaining, setTimeRemaining] = useState(60);

  // Check session validity on mount
  useEffect(() => {
    if (!sessionId) {
      navigate('/upload');
    } else {
      setIsReady(true);
    }
  }, [navigate, sessionId]);

  // Voice recorder hook
  const { isRecording, isProcessing, startRecording, stopRecording, error: recorderError } = useVoiceRecorder({
    sessionId,
    onQuestionReceived: (audioUrl, questionText, domain) => {
      setCurrentQuestion(questionText);
      
      // Increment question counter
      setQuestionNumber(prev => prev + 1);
      
      if (domain) {
        setCurrentDomain(domain);
        sessionStorage.setItem('current_domain', domain);
        
        // Track unique domains seen
        domainsSeenRef.current.add(domain);
        setDomainsCovered(domainsSeenRef.current.size);
      }

      // Play the audio
      if (audioUrl && audioRef.current) {
        audioRef.current.src = audioUrl;
        audioRef.current.play().catch((err) => console.warn('Audio play failed:', err));
      }
    },
    onInterviewComplete: (scores) => {
      sessionStorage.setItem('interview_scores', JSON.stringify(scores));
      navigate('/feedback');
    },
    onTranscriptCaptured: (transcript) => {
      setLastTranscript(transcript);
    },
  });

  // Handle first question audio playback on mount
  useEffect(() => {
    if (initialAudioBase64 && initialAudioBase64.length > 10) {
      const audioBlob = base64ToBlob(initialAudioBase64, 'audio/mpeg');
      const audioUrl = URL.createObjectURL(audioBlob);
      if (audioRef.current) {
        audioRef.current.src = audioUrl;
        audioRef.current.play().catch((err) => console.warn('Audio play failed:', err));
      }
    }
    // If no audio, candidate's turn starts immediately
  }, []);

  // Timer countdown during recording
  useEffect(() => {
    if (isRecording) {
      setTimeRemaining(60);
      const interval = setInterval(() => {
        setTimeRemaining(prev => {
          if (prev <= 1) {
            clearInterval(interval);
            stopRecording();
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
      return () => clearInterval(interval);
    } else {
      setTimeRemaining(60);
    }
  }, [isRecording, stopRecording]);

  // Proctoring: track tab switches
  useEffect(() => {
    if (!isReady) return;

    function handleVisibilityChange() {
      const elapsed = Math.floor((Date.now() - interviewStartRef.current) / 1000);
      if (document.hidden) {
        logProctorEvent(sessionId, 'tab_switch', elapsed).catch(console.error);
      } else {
        logProctorEvent(sessionId, 'tab_returned', elapsed).catch(console.error);
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange);

    // Start proctor timer
    proctorTimerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - interviewStartRef.current) / 1000);
      // Could log periodic heartbeat here if needed
    }, 30000);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (proctorTimerRef.current) {
        clearInterval(proctorTimerRef.current);
      }
    };
  }, [sessionId, isReady]);

  function handleRecordClick() {
    if (isRecording) {
      stopRecording();
    } else {
      setLastTranscript(''); // Clear transcript when starting new recording
      startRecording();
    }
  }

  function handleAudioEnded() {
    setIsPlaying(false);
  }

  function handleAudioPlay() {
    setIsPlaying(true);
  }

  // Helper: convert base64 to Blob
  function base64ToBlob(base64, mimeType) {
    const byteCharacters = atob(base64);
    const byteArrays = [];
    for (let offset = 0; offset < byteCharacters.length; offset += 512) {
      const slice = byteCharacters.slice(offset, offset + 512);
      const byteNumbers = new Array(slice.length);
      for (let i = 0; i < slice.length; i++) {
        byteNumbers[i] = slice.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      byteArrays.push(byteArray);
    }
    return new Blob(byteArrays, { type: mimeType });
  }

  // Determine turn state
  const isCandidateTurn = !isPlaying && !isRecording && !isProcessing;

  // Timer color
  const getTimerColor = () => {
    if (timeRemaining > 30) return '#22c55e';
    if (timeRemaining >= 10) return '#eab308';
    return '#ef4444';
  };

  // Don't render until session is validated
  if (!isReady) {
    return null;
  }

  return (
    <div style={styles.container}>
      {/* Top bar */}
      <div style={styles.topBar}>
        <Logo size={40} />
        <div style={styles.badge}>{currentDomain}</div>
        <div style={styles.counter}>Q {questionNumber}/{totalDomains * 4}</div>
      </div>

      {/* Main area */}
      <div style={styles.main}>
        {/* Question display */}
        <div style={styles.questionBox}>
          <h2 style={styles.questionText}>{currentQuestion}</h2>
        </div>

        {/* Turn indicator banner */}
        {isPlaying && (
          <div style={styles.turnBannerInterviewer}>
            <div style={styles.turnBannerIcon}>🎙️</div>
            <div>
              <div style={styles.turnBannerTitle}>Interviewer is speaking...</div>
              <div style={styles.turnBannerSubtitle}>Listen carefully to the question</div>
            </div>
          </div>
        )}

        {isCandidateTurn && !recorderError && (
          <div style={styles.turnBannerCandidate}>
            <div style={styles.turnBannerIcon}>⏺</div>
            <div>
              <div style={styles.turnBannerTitle}>Your Turn — Click the mic to answer</div>
              <div style={styles.turnBannerSubtitle}>Take your time, click Stop when done</div>
            </div>
          </div>
        )}

        {isRecording && (
          <div style={styles.turnBannerRecording}>
            <div style={styles.turnBannerIcon}>🔴</div>
            <div>
              <div style={styles.turnBannerTitle}>Recording... speak your answer</div>
              <div style={styles.turnBannerSubtitle}>Click Stop when you're done</div>
            </div>
          </div>
        )}

        {isProcessing && (
          <div style={styles.turnBannerProcessing}>
            <div style={styles.turnBannerIcon}>⏳</div>
            <div>
              <div style={styles.turnBannerTitle}>Processing your answer...</div>
              <div style={styles.turnBannerSubtitle}>Preparing next question</div>
            </div>
          </div>
        )}

        {/* Audio element (hidden, controlled programmatically) */}
        <audio
          ref={audioRef}
          onEnded={handleAudioEnded}
          onPlay={handleAudioPlay}
          onPause={() => setIsPlaying(false)}
          style={{ display: 'none' }}
        />

        {/* Record button and timer area */}
        <div style={styles.recordArea}>
          <button
            onClick={handleRecordClick}
            disabled={!isCandidateTurn && !isRecording}
            style={{
              ...styles.recordBtn,
              ...(isRecording ? styles.recordBtnActive : {}),
              ...(!isCandidateTurn && !isRecording ? styles.recordBtnDisabled : {}),
            }}
          >
            {isRecording ? '■' : '🎙️'}
          </button>

          {/* Timer */}
          {isRecording && (
            <div style={{ ...styles.timer, color: getTimerColor() }}>
              {timeRemaining}s
            </div>
          )}

          {/* Button label */}
          <div style={styles.buttonLabel}>
            {isRecording ? 'Click to Stop' : isCandidateTurn ? 'Click to Answer' : 'Please Wait'}
          </div>
        </div>

        {/* Transcript card */}
        {lastTranscript && !isRecording && (
          <div style={styles.transcriptCard}>
            <div style={styles.transcriptLabel}>Your answer:</div>
            <div style={styles.transcriptText}>"{lastTranscript}"</div>
          </div>
        )}

        {/* Recorder error */}
        {recorderError && (
          <div style={styles.error}>{recorderError}</div>
        )}

        {/* Progress bar */}
        <div style={styles.progressBarContainer}>
          <div
            style={{
              ...styles.progressBarFill,
              width: `${(domainsCovered / totalDomains) * 100}%`,
            }}
          />
        </div>
        <div style={styles.progressText}>
          Domains covered: {domainsCovered}/{totalDomains}
        </div>
      </div>
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    backgroundColor: '#0f0f0f',
    color: '#f0f0f0',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    display: 'flex',
    flexDirection: 'column',
  },
  topBar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '16px 32px',
    borderBottom: '1px solid #2a2a2a',
  },
  badge: {
    backgroundColor: '#c084fc',
    color: '#fff',
    padding: '6px 16px',
    borderRadius: '16px',
    fontSize: '14px',
    fontWeight: '500',
  },
  counter: {
    fontSize: '14px',
    color: '#9ca3af',
  },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'flex-start',
    padding: '40px 20px',
    gap: '24px',
  },
  questionBox: {
    maxWidth: '700px',
    width: '100%',
    padding: '32px',
    backgroundColor: '#1a1a1a',
    borderRadius: '12px',
    border: '1px solid #2a2a2a',
  },
  questionText: {
    fontSize: '24px',
    fontWeight: '500',
    lineHeight: '1.5',
    margin: 0,
    textAlign: 'center',
  },
  turnBannerInterviewer: {
    maxWidth: '700px',
    width: '100%',
    padding: '20px 24px',
    backgroundColor: '#4c1d95',
    borderRadius: '12px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    color: '#fff',
  },
  turnBannerCandidate: {
    maxWidth: '700px',
    width: '100%',
    padding: '20px 24px',
    backgroundColor: '#14532d',
    borderRadius: '12px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    color: '#fff',
  },
  turnBannerRecording: {
    maxWidth: '700px',
    width: '100%',
    padding: '20px 24px',
    backgroundColor: '#7f1d1d',
    borderRadius: '12px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    color: '#fff',
    animation: 'pulse-red 2s ease-in-out infinite',
  },
  turnBannerProcessing: {
    maxWidth: '700px',
    width: '100%',
    padding: '20px 24px',
    backgroundColor: '#1c1917',
    borderRadius: '12px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    color: '#9ca3af',
  },
  turnBannerIcon: {
    fontSize: '28px',
    flexShrink: 0,
  },
  turnBannerTitle: {
    fontSize: '16px',
    fontWeight: '600',
  },
  turnBannerSubtitle: {
    fontSize: '13px',
    opacity: 0.8,
    marginTop: '4px',
  },
  recordArea: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '16px',
  },
  recordBtn: {
    width: '100px',
    height: '100px',
    borderRadius: '50%',
    border: '3px solid #22c55e',
    backgroundColor: 'transparent',
    color: '#22c55e',
    fontSize: '36px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.2s',
    animation: 'pulse-green 2s ease-in-out infinite',
  },
  recordBtnActive: {
    backgroundColor: '#ef4444',
    borderColor: '#ef4444',
    color: '#fff',
    transform: 'scale(1.1)',
    animation: 'pulse-red 1.5s ease-in-out infinite',
  },
  recordBtnDisabled: {
    backgroundColor: '#2a2a2a',
    borderColor: '#3a3a3a',
    color: '#6b7280',
    cursor: 'not-allowed',
    animation: 'none',
  },
  timer: {
    fontSize: '32px',
    fontWeight: '700',
    fontVariantNumeric: 'tabular-nums',
  },
  buttonLabel: {
    fontSize: '14px',
    color: '#9ca3af',
    fontWeight: '500',
  },
  transcriptCard: {
    maxWidth: '600px',
    width: '100%',
    padding: '16px 20px',
    backgroundColor: '#1a1a1a',
    borderRadius: '8px',
    border: '1px solid #2a2a2a',
  },
  transcriptLabel: {
    fontSize: '12px',
    fontWeight: '600',
    color: '#9ca3af',
    textTransform: 'uppercase',
    marginBottom: '8px',
  },
  transcriptText: {
    fontSize: '14px',
    color: '#d1d5db',
    fontStyle: 'italic',
    lineHeight: '1.5',
  },
  error: {
    backgroundColor: '#7f1d1d',
    color: '#fecaca',
    padding: '12px',
    borderRadius: '6px',
    fontSize: '14px',
    maxWidth: '500px',
    textAlign: 'center',
  },
  progressBarContainer: {
    width: '100%',
    maxWidth: '500px',
    height: '8px',
    backgroundColor: '#2a2a2a',
    borderRadius: '4px',
    overflow: 'hidden',
    marginTop: '16px',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#c084fc',
    transition: 'width 0.3s ease',
  },
  progressText: {
    fontSize: '14px',
    color: '#9ca3af',
  },
};

// Add keyframe animations
if (typeof document !== 'undefined') {
  const existingStyle = document.getElementById('interview-animations');
  if (!existingStyle) {
    const style = document.createElement('style');
    style.id = 'interview-animations';
    style.textContent = `
      @keyframes pulse-green {
        0%, 100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.4); }
        50% { box-shadow: 0 0 0 12px rgba(34, 197, 94, 0); }
      }
      @keyframes pulse-red {
        0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
        50% { box-shadow: 0 0 0 12px rgba(239, 68, 68, 0); }
      }
    `;
    document.head.appendChild(style);
  }
}

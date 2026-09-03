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
  const [statusText, setStatusText] = useState('Interviewer speaking...');

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
      } else {
        // No audio — just enable recording immediately
        setStatusText('Your turn');
      }
    },
    onInterviewComplete: (scores) => {
      sessionStorage.setItem('interview_scores', JSON.stringify(scores));
      navigate('/feedback');
    },
  });

  // Handle audio playback
  useEffect(() => {
    if (initialAudioBase64 && initialAudioBase64.length > 0) {
      const audioBlob = base64ToBlob(initialAudioBase64, 'audio/mpeg');
      const audioUrl = URL.createObjectURL(audioBlob);
      if (audioRef.current) {
        audioRef.current.src = audioUrl;
        audioRef.current.play().catch((err) => console.warn('Audio play failed:', err));
      }
    } else if (initialQuestionText) {
      // No audio but question text exists
      setStatusText('Your turn');
    }
  }, []);

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

  // Update status based on state
  useEffect(() => {
    if (isProcessing) {
      setStatusText('Processing...');
    } else if (isRecording) {
      setStatusText('Recording...');
    } else if (isPlaying) {
      setStatusText('Interviewer speaking...');
    } else {
      setStatusText('Your turn');
    }
  }, [isRecording, isProcessing, isPlaying]);

  function handleRecordClick() {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  }

  function handleAudioEnded() {
    setIsPlaying(false);
    setStatusText('Your turn');
  }

  function handleAudioPlay() {
    setIsPlaying(true);
    setStatusText('Interviewer speaking...');
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

        {/* Status indicator */}
        <div style={styles.statusIndicator}>
          {statusText}
        </div>

        {/* Audio element (hidden, controlled programmatically) */}
        <audio
          ref={audioRef}
          onEnded={handleAudioEnded}
          onPlay={handleAudioPlay}
          onPause={() => setIsPlaying(false)}
          style={{ display: 'none' }}
        />

        {/* Record button */}
        <button
          onClick={handleRecordClick}
          disabled={isProcessing || isPlaying}
          style={{
            ...styles.recordBtn,
            ...(isRecording ? styles.recordBtnActive : {}),
            opacity: isProcessing || isPlaying ? 0.5 : 1,
          }}
        >
          {isRecording ? '■' : '●'}
        </button>

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
    justifyContent: 'center',
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
  statusIndicator: {
    fontSize: '16px',
    color: '#9ca3af',
    fontStyle: 'italic',
  },
  recordBtn: {
    width: '80px',
    height: '80px',
    borderRadius: '50%',
    border: '3px solid #c084fc',
    backgroundColor: 'transparent',
    color: '#c084fc',
    fontSize: '32px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.2s',
  },
  recordBtnActive: {
    backgroundColor: '#c084fc',
    color: '#fff',
    transform: 'scale(1.1)',
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

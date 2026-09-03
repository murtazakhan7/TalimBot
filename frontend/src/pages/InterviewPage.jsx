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
  const micLevelRef = useRef(null);
  const animFrameRef = useRef(null);

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
  const [isPlaying, setIsPlaying] = useState(false);
  const [canReplay, setCanReplay] = useState(false);
  const [timeRemaining, setTimeRemaining] = useState(120);

  // Check session validity on mount
  useEffect(() => {
    if (!sessionId) {
      navigate('/upload');
    } else {
      setIsReady(true);
    }
  }, [navigate, sessionId]);

  // Voice recorder hook
  const { isRecording, isProcessing, startRecording, stopRecording, error: recorderError, liveTranscript } = useVoiceRecorder({
    sessionId,
    onQuestionReceived: (audioUrl, questionText, domain) => {
      setCurrentQuestion(questionText);
      
      // Increment question counter
      setQuestionNumber(prev => prev + 1);
      
      if (domain) {
        setCurrentDomain(domain);
        sessionStorage.setItem('current_domain', domain);
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
      setTimeRemaining(120);
      const interval = setInterval(() => {
        setTimeRemaining(prev => {
          if (prev <= 1) {
            clearInterval(interval);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
      return () => clearInterval(interval);
    } else {
      setTimeRemaining(120);
    }
  }, [isRecording]);

  // Mic level meter while recording
  useEffect(() => {
    if (!isRecording) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (micLevelRef.current) micLevelRef.current.style.width = '0%';
      return;
    }

    let stream, audioContext, analyser, source;

    navigator.mediaDevices.getUserMedia({ audio: true }).then(s => {
      stream = s;
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source = audioContext.createMediaStreamSource(stream);
      source.connect(analyser);

      const data = new Uint8Array(analyser.frequencyBinCount);
      function tick() {
        analyser.getByteFrequencyData(data);
        const avg = data.reduce((a, b) => a + b, 0) / data.length;
        const pct = Math.min(100, (avg / 128) * 100);
        if (micLevelRef.current) micLevelRef.current.style.width = pct + '%';
        animFrameRef.current = requestAnimationFrame(tick);
      }
      tick();
    }).catch(() => {});

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (stream) stream.getTracks().forEach(t => t.stop());
      if (audioContext) audioContext.close();
    };
  }, [isRecording]);

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
      startRecording();
    }
  }

  function handleAudioEnded() {
    setIsPlaying(false);
    setCanReplay(true);
  }

  function handleAudioPlay() {
    setIsPlaying(true);
    setCanReplay(false);
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

  // Format time as M:SS
  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // Timer color
  const getTimerColor = () => {
    if (timeRemaining > 60) return '#22c55e';
    if (timeRemaining >= 30) return '#eab308';
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
        <div style={styles.counter}>Q {questionNumber} / 5</div>
      </div>

      {/* Main area */}
      <div style={styles.main}>
        {/* AI Interviewer Avatar */}
        {isPlaying && (
          <div style={styles.avatarContainer}>
            <div style={styles.avatarGlow}>
              <div style={styles.avatarCircle}>
                <span style={styles.avatarEmoji}>🤖</span>
              </div>
            </div>
          </div>
        )}

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

        {/* Question display */}
        <div style={styles.questionCard}>
          <div style={styles.questionLabel}>Interviewer's Question</div>
          <h2 style={styles.questionText}>{currentQuestion}</h2>
        </div>

        {canReplay && !isRecording && !isProcessing && (
          <button
            onClick={() => {
              if (audioRef.current) {
                audioRef.current.currentTime = 0;
                audioRef.current.play().catch(() => {});
                setCanReplay(false);
              }
            }}
            style={styles.replayBtn}
          >
            ↩ Replay Question
          </button>
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
              {formatTime(timeRemaining)}
            </div>
          )}

          {/* Button label */}
          <div style={styles.buttonLabel}>
            {isRecording ? 'Tap to Stop' : isCandidateTurn ? 'Tap to Answer' : 'Please Wait'}
          </div>

          {/* Mic level meter */}
          {isRecording && (
            <div style={styles.micMeterContainer}>
              <div style={styles.micMeterLabel}>Mic level</div>
              <div style={styles.micMeterTrack}>
                <div ref={micLevelRef} style={styles.micMeterFill} />
              </div>
            </div>
          )}

          {/* Live transcript while recording */}
          {isRecording && liveTranscript && (
            <div style={styles.liveTranscript}>
              <span style={styles.liveTranscriptLabel}>Hearing:</span> {liveTranscript}
            </div>
          )}
        </div>

        {/* Recorder error */}
        {recorderError && (
          <div style={styles.errorContainer}>
            <div style={styles.error}>{recorderError}</div>
            {!isProcessing && (
              <button onClick={() => { startRecording(); }} style={styles.retryBtn}>
                Try Again
              </button>
            )}
          </div>
        )}

        {/* Progress bar */}
        <div style={styles.progressBarContainer}>
          <div
            style={{
              ...styles.progressBarFill,
              width: `${((questionNumber - 1) / 5) * 100}%`,
            }}
          />
        </div>
        <div style={styles.progressText}>
          Questions answered: {questionNumber - 1}/5
        </div>
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
    display: 'flex',
    flexDirection: 'column',
  },
  topBar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '16px 32px',
    borderBottom: '1px solid #1e1e35',
  },
  badge: {
    backgroundColor: '#8b5cf6',
    color: '#fff',
    padding: '6px 16px',
    borderRadius: '16px',
    fontSize: '14px',
    fontWeight: '500',
  },
  counter: {
    fontSize: '14px',
    color: '#64748b',
  },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'flex-start',
    padding: '32px 20px',
    gap: '20px',
  },
  avatarContainer: {
    marginTop: '16px',
  },
  avatarGlow: {
    animation: 'pulse-avatar 2s ease-in-out infinite',
  },
  avatarCircle: {
    width: '120px',
    height: '120px',
    borderRadius: '50%',
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 4px 24px rgba(99, 102, 241, 0.08)',
  },
  avatarEmoji: {
    fontSize: '48px',
  },
  turnBannerInterviewer: {
    width: '100%',
    maxWidth: '700px',
    padding: '12px 32px',
    backgroundColor: '#1e1b4b',
    borderRadius: '8px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    color: '#fff',
  },
  turnBannerCandidate: {
    width: '100%',
    maxWidth: '700px',
    padding: '12px 32px',
    backgroundColor: '#052e16',
    borderRadius: '8px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    color: '#fff',
  },
  turnBannerRecording: {
    width: '100%',
    maxWidth: '700px',
    padding: '12px 32px',
    backgroundColor: '#450a0a',
    borderRadius: '8px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    color: '#fff',
    animation: 'pulse-red 2s ease-in-out infinite',
  },
  turnBannerProcessing: {
    width: '100%',
    maxWidth: '700px',
    padding: '12px 32px',
    backgroundColor: '#0f0f1a',
    borderRadius: '8px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    color: '#64748b',
  },
  turnBannerIcon: {
    fontSize: '24px',
    flexShrink: 0,
  },
  turnBannerTitle: {
    fontSize: '15px',
    fontWeight: '600',
  },
  turnBannerSubtitle: {
    fontSize: '12px',
    opacity: 0.8,
    marginTop: '2px',
  },
  questionCard: {
    maxWidth: '700px',
    width: '100%',
    padding: '28px 32px',
    backgroundColor: '#13131f',
    borderRadius: '12px',
    border: '1px solid #1e1e35',
    boxShadow: '0 4px 24px rgba(99, 102, 241, 0.08)',
  },
  questionLabel: {
    fontSize: '12px',
    fontWeight: '600',
    color: '#6366f1',
    textTransform: 'uppercase',
    marginBottom: '12px',
    letterSpacing: '0.5px',
  },
  questionText: {
    fontSize: '22px',
    fontWeight: '500',
    lineHeight: '1.6',
    margin: 0,
    textAlign: 'center',
    color: '#f1f5f9',
  },
  recordArea: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '12px',
  },
  recordBtn: {
    width: '100px',
    height: '100px',
    borderRadius: '50%',
    border: '3px solid #6366f1',
    backgroundColor: 'transparent',
    color: '#6366f1',
    fontSize: '36px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.2s',
    boxShadow: '0 0 0 0 rgba(99, 102, 241, 0.4)',
    animation: 'pulse-indigo 2s ease-in-out infinite',
  },
  recordBtnActive: {
    backgroundColor: '#ef4444',
    borderColor: '#ef4444',
    color: '#fff',
    transform: 'scale(1.1)',
    animation: 'pulse-red 1.5s ease-in-out infinite',
  },
  recordBtnDisabled: {
    backgroundColor: '#1e1e35',
    borderColor: '#2a2a45',
    color: '#64748b',
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
    color: '#64748b',
    fontWeight: '500',
  },
  micMeterContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '4px',
    width: '200px',
  },
  micMeterLabel: {
    fontSize: '11px',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  micMeterTrack: {
    width: '100%',
    height: '6px',
    backgroundColor: '#1e1e35',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  micMeterFill: {
    height: '100%',
    width: '0%',
    backgroundColor: '#10b981',
    borderRadius: '3px',
    transition: 'width 0.1s ease',
  },
  replayBtn: {
    padding: '6px 16px',
    borderRadius: '6px',
    border: '1px solid #1e1e35',
    backgroundColor: 'transparent',
    color: '#64748b',
    fontSize: '13px',
    cursor: 'pointer',
  },
  liveTranscript: {
    maxWidth: '600px',
    width: '100%',
    padding: '12px 16px',
    backgroundColor: '#13131f',
    borderRadius: '8px',
    border: '1px solid #1e1e35',
    fontSize: '13px',
    color: '#64748b',
    fontStyle: 'italic',
    lineHeight: '1.5',
    maxHeight: '3em',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  liveTranscriptLabel: {
    fontWeight: '600',
    color: '#475569',
  },
  error: {
    backgroundColor: '#450a0a',
    color: '#fecaca',
    padding: '12px',
    borderRadius: '6px',
    fontSize: '14px',
    maxWidth: '500px',
    textAlign: 'center',
  },
  errorContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '12px',
  },
  retryBtn: {
    padding: '8px 20px',
    borderRadius: '6px',
    border: '1px solid #6366f1',
    backgroundColor: 'transparent',
    color: '#6366f1',
    cursor: 'pointer',
    fontSize: '14px',
    fontWeight: '500',
  },
  progressBarContainer: {
    width: '100%',
    maxWidth: '500px',
    height: '8px',
    backgroundColor: '#1e1e35',
    borderRadius: '4px',
    overflow: 'hidden',
    marginTop: '16px',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#6366f1',
    transition: 'width 0.3s ease',
  },
  progressText: {
    fontSize: '14px',
    color: '#64748b',
    marginTop: '8px',
  },
};

// Add keyframe animations
if (typeof document !== 'undefined') {
  const existingStyle = document.getElementById('interview-animations');
  if (!existingStyle) {
    const style = document.createElement('style');
    style.id = 'interview-animations';
    style.textContent = `
      @keyframes pulse-indigo {
        0%, 100% { box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.4); }
        50% { box-shadow: 0 0 0 12px rgba(99, 102, 241, 0); }
      }
      @keyframes pulse-red {
        0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
        50% { box-shadow: 0 0 0 12px rgba(239, 68, 68, 0); }
      }
      @keyframes pulse-avatar {
        0%, 100% { box-shadow: 0 0 0 8px rgba(99, 102, 241, 0.2); }
        50% { box-shadow: 0 0 0 16px rgba(99, 102, 241, 0); }
      }
    `;
    document.head.appendChild(style);
  }
}

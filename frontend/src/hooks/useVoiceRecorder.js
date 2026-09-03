import { useCallback, useRef, useState } from 'react';
import { submitAnswerText } from '../api/client';

// ── OLD MEDIARECORDER CODE (commented out for quick revert) ──────────────────
// import { submitAnswer } from '../api/client';
//
// const SILENCE_THRESHOLD = 10;
// const SILENCE_DURATION_MS = 2000;
// const MIN_RECORDING_MS = 1500;
// const CHUNK_INTERVAL_MS = 100;
//
// export default function useVoiceRecorder({ sessionId, onQuestionReceived, onInterviewComplete }) {
//   const [isRecording, setIsRecording] = useState(false);
//   const [isProcessing, setIsProcessing] = useState(false);
//   const [error, setError] = useState(null);
//
//   const mediaRecorderRef = useRef(null);
//   const streamRef = useRef(null);
//   const analyserRef = useRef(null);
//   const audioContextRef = useRef(null);
//   const chunksRef = useRef([]);
//   const silenceTimerRef = useRef(null);
//   const animFrameRef = useRef(null);
//   const recordingStartRef = useRef(0);
//   const silenceStartRef = useRef(0);
//   const isSilentRef = useRef(true);
//
//   const cleanup = useCallback(() => {
//     if (animFrameRef.current) {
//       cancelAnimationFrame(animFrameRef.current);
//       animFrameRef.current = null;
//     }
//     if (silenceTimerRef.current) {
//       clearTimeout(silenceTimerRef.current);
//       silenceTimerRef.current = null;
//     }
//     if (streamRef.current) {
//       streamRef.current.getTracks().forEach((track) => track.stop());
//       streamRef.current = null;
//     }
//     if (audioContextRef.current) {
//       audioContextRef.current.close();
//       audioContextRef.current = null;
//     }
//     analyserRef.current = null;
//     mediaRecorderRef.current = null;
//   }, []);
//
//   const checkSilence = useCallback(() => {
//     const analyser = analyserRef.current;
//     if (!analyser) return;
//
//     const dataArray = new Uint8Array(analyser.fftSize);
//     analyser.getByteTimeDomainData(dataArray);
//
//     let sumSquares = 0;
//     for (let i = 0; i < dataArray.length; i++) {
//       const val = (dataArray[i] - 128) / 128.0;
//       sumSquares += val * val;
//     }
//     const rms = Math.sqrt(sumSquares / dataArray.length) * 100;
//
//     const now = Date.now();
//     const elapsed = now - recordingStartRef.current;
//
//     if (rms < SILENCE_THRESHOLD) {
//       if (isSilentRef.current === false) {
//         isSilentRef.current = true;
//         silenceStartRef.current = now;
//       }
//       const silentDuration = now - silenceStartRef.current;
//       if (silentDuration >= SILENCE_DURATION_MS && elapsed >= MIN_RECORDING_MS) {
//         stopRecording();
//         return;
//       }
//     } else {
//       isSilentRef.current = false;
//       silenceStartRef.current = 0;
//     }
//
//     animFrameRef.current = requestAnimationFrame(checkSilence);
//   }, []);
//
//   const startRecording = useCallback(async () => {
//     setError(null);
//     try {
//       const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
//       streamRef.current = stream;
//
//       const audioContext = new (window.AudioContext || window.webkitAudioContext)();
//       audioContextRef.current = audioContext;
//
//       const source = audioContext.createMediaStreamSource(stream);
//       const analyser = audioContext.createAnalyser();
//       analyser.fftSize = 2048;
//       source.connect(analyser);
//       analyserRef.current = analyser;
//
//       const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
//       mediaRecorderRef.current = recorder;
//       chunksRef.current = [];
//
//       recorder.ondataavailable = (e) => {
//         if (e.data.size > 0) {
//           chunksRef.current.push(e.data);
//         }
//       };
//
//       recorder.onstop = async () => {
//         const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
//         chunksRef.current = [];
//         cleanup();
//
//         if (blob.size < 100) {
//           setError('Recording too short — please speak clearly');
//           setIsProcessing(false);
//           return;
//         }
//
//         setIsProcessing(true);
//         try {
//           const response = await submitAnswer(sessionId, blob);
//           const doneHeader = response.headers['x-interview-done'];
//           const questionText = response.headers['x-question-text'] || '';
//
//           // Check if interview is complete
//           if (doneHeader === 'true' || response.data?.done === true) {
//             // Response body is JSON with scores, but comes as Blob due to responseType
//             let json;
//             try {
//               const text = await response.data.text();  // Blob → string
//               json = JSON.parse(text);
//             } catch {
//               json = { done: true, scores: null };
//             }
//             onInterviewComplete(json.scores || {});
//           } else {
//             // Audio response — create blob URL and notify parent
//             const audioBlob = new Blob([response.data], { type: 'audio/mpeg' });
//             const audioUrl = URL.createObjectURL(audioBlob);
//             onQuestionReceived(audioUrl, questionText);
//           }
//         } catch (err) {
//           setError(err.response?.data?.detail || err.message || 'Failed to submit answer');
//         } finally {
//           setIsProcessing(false);
//         }
//       };
//
//       recorder.start(CHUNK_INTERVAL_MS);
//       recordingStartRef.current = Date.now();
//       silenceStartRef.current = Date.now();
//       isSilentRef.current = false;
//       setIsRecording(true);
//
//       animFrameRef.current = requestAnimationFrame(checkSilence);
//     } catch (err) {
//       if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
//         setError('Microphone access denied. Please allow microphone permissions and try again.');
//       } else {
//         setError(err.message || 'Failed to start recording');
//       }
//     }
//   }, [sessionId, onQuestionReceived, onInterviewComplete, checkSilence, cleanup]);
//
//   const stopRecording = useCallback(() => {
//     if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
//       mediaRecorderRef.current.stop();
//     }
//     setIsRecording(false);
//   }, []);
//
//   return { isRecording, isProcessing, startRecording, stopRecording, error };
// }

export default function useVoiceRecorder({ sessionId, onQuestionReceived, onInterviewComplete, onTranscriptCaptured }) {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState(null);
  const [liveTranscript, setLiveTranscript] = useState('');

  const recognitionRef = useRef(null);
  const accumulatedTranscriptRef = useRef('');
  const isRecordingRef = useRef(false);
  const timerFiredRef = useRef(false);
  const maxTimeTimerRef = useRef(null);

  // Check browser support on init
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    setError('Web Speech API not supported in this browser. Please use Chrome or Edge.');
  }

  const submitTranscript = useCallback(async (transcript) => {
    const trimmed = transcript.trim();
    if (!trimmed) {
      setError('No speech detected. Please try again.');
      setIsProcessing(false);
      return;
    }

    // Notify parent about captured transcript
    if (onTranscriptCaptured) {
      onTranscriptCaptured(trimmed);
    }

    try {
      const response = await submitAnswerText(sessionId, trimmed);
      const doneHeader = response.headers['x-interview-done'];
      const questionText = response.headers['x-question-text'] || '';

      // Check if interview is complete
      if (doneHeader === 'true') {
        // Response body is JSON with scores, but comes as Blob due to responseType
        let json;
        try {
          const text = await response.data.text();  // Blob → string
          json = JSON.parse(text);
        } catch {
          json = { done: true, scores: null };
        }
        onInterviewComplete(json.scores || {});
      } else {
        // Audio response — create blob URL and notify parent
        const audioBlob = new Blob([response.data], { type: 'audio/mpeg' });
        const audioUrl = URL.createObjectURL(audioBlob);
        onQuestionReceived(audioUrl, questionText);
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to submit answer');
    } finally {
      setIsProcessing(false);
    }
  }, [sessionId, onQuestionReceived, onInterviewComplete, onTranscriptCaptured]);

  const startRecording = useCallback(() => {
    if (!SpeechRecognition) {
      setError('Web Speech API not supported in this browser. Please use Chrome or Edge.');
      return;
    }

    setError(null);
    accumulatedTranscriptRef.current = '';
    setLiveTranscript('');
    isRecordingRef.current = true;
    timerFiredRef.current = false;

    const recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    // Maximum recording time of 2 minutes
    maxTimeTimerRef.current = setTimeout(() => {
      timerFiredRef.current = true;
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    }, 120000);

    recognition.onstart = () => {
      setIsRecording(true);
      setIsProcessing(false);
    };

    recognition.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          accumulatedTranscriptRef.current += t + ' ';
        } else {
          interim = t;
        }
      }
      // Show live interim transcript to user
      setLiveTranscript(accumulatedTranscriptRef.current + interim);
    };

    recognition.onend = () => {
      // Browser stopped — restart if user hasn't clicked stop and timer hasn't fired
      if (isRecordingRef.current && !timerFiredRef.current) {
        try {
          recognition.start(); // restart to continue
        } catch (err) {
          // Recognition already started or other error — just proceed to submit
          submitTranscript(accumulatedTranscriptRef.current);
        }
      } else {
        // Submit what we have
        submitTranscript(accumulatedTranscriptRef.current);
      }
    };

    recognition.onerror = (event) => {
      // Clear the max time timer
      if (maxTimeTimerRef.current) {
        clearTimeout(maxTimeTimerRef.current);
        maxTimeTimerRef.current = null;
      }

      if (event.error === 'no-speech') {
        // Ignore no-speech errors during continuous recording
        return;
      }

      isRecordingRef.current = false;
      setIsRecording(false);
      setIsProcessing(false);

      switch (event.error) {
        case 'audio-capture':
          setError('No microphone found. Please check your microphone.');
          break;
        case 'not-allowed':
          setError('Microphone permission denied. Please allow microphone access.');
          break;
        default:
          setError(`Speech recognition error: ${event.error}`);
      }
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, [submitTranscript]);

  const stopRecording = useCallback(() => {
    isRecordingRef.current = false;
    if (maxTimeTimerRef.current) {
      clearTimeout(maxTimeTimerRef.current);
      maxTimeTimerRef.current = null;
    }
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    setIsRecording(false);
    setIsProcessing(true);
  }, []);

  return { isRecording, isProcessing, startRecording, stopRecording, error, liveTranscript };
}

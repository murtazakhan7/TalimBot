import { useCallback, useRef, useState } from 'react';
import { submitAnswerText } from '../api/client';

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
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setError('Web Speech API not supported. Please use Chrome or Edge.');
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

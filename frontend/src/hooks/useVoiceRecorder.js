import { useCallback, useRef, useState } from 'react';
import { submitAnswer } from '../api/client';

const MIN_RECORDING_MS = 1500;
const CHUNK_INTERVAL_MS = 100;
const MAX_RECORDING_MS = 120000;

export default function useVoiceRecorder({ sessionId, onQuestionReceived, onInterviewComplete }) {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState(null);

  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const recordingStartRef = useRef(0);
  const maxTimeTimerRef = useRef(null);

  const cleanup = useCallback(() => {
    if (maxTimeTimerRef.current) {
      clearTimeout(maxTimeTimerRef.current);
      maxTimeTimerRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    mediaRecorderRef.current = null;
  }, []);

  const stopRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
    }
    setIsRecording(false);
  }, []);

  const startRecording = useCallback(async () => {
    setError(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        chunksRef.current = [];
        const elapsed = Date.now() - recordingStartRef.current;
        cleanup();

        setIsProcessing(true);

        if (blob.size < 100 || elapsed < MIN_RECORDING_MS) {
          setError('Recording too short — please speak clearly');
          setIsProcessing(false);
          return;
        }

        try {
          const response = await submitAnswer(sessionId, blob);
          const doneHeader = response.headers['x-interview-done'];
          const questionText = response.headers['x-question-text'] || '';
          const domainText = response.headers['x-current-domain'] || '';

          if (doneHeader === 'true') {
            // Scores arrive as JSON but the axios client reads every answer as a Blob
            let json;
            try {
              const text = await response.data.text();
              json = JSON.parse(text);
            } catch {
              json = { done: true, scores: null };
            }
            onInterviewComplete(json.scores || {});
          } else {
            const audioBlob = new Blob([response.data], { type: 'audio/mpeg' });
            const audioUrl = URL.createObjectURL(audioBlob);
            onQuestionReceived(audioUrl, questionText, domainText);
          }
        } catch (err) {
          if (err.response?.status === 400) {
            // No speech detected server-side — no LangGraph turn was run,
            // so the next question must come from a fresh recording.
            setError('No speech detected. Please try again.');
          } else {
            setError(err.response?.data?.detail || err.message || 'Failed to submit answer');
          }
        } finally {
          setIsProcessing(false);
        }
      };

      // Hard 2-minute cap — the candidate controls every other stop
      maxTimeTimerRef.current = setTimeout(() => stopRecording(), MAX_RECORDING_MS);

      recorder.start(CHUNK_INTERVAL_MS);
      recordingStartRef.current = Date.now();
      setIsRecording(true);
      setIsProcessing(false);
    } catch (err) {
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setError('Microphone access denied. Please allow microphone permissions and try again.');
      } else {
        setError(err.message || 'Failed to start recording');
      }
      cleanup();
    }
  }, [sessionId, onQuestionReceived, onInterviewComplete, stopRecording, cleanup]);

  return { isRecording, isProcessing, setIsProcessing, startRecording, stopRecording, error, setError };
}

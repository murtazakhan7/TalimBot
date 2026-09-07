import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

const client = axios.create({
  baseURL: API_BASE,
});

// ── Request interceptor: attach Bearer token ────────────────────────────────
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor: handle 401 globally ───────────────────────────────
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// ─ Auth ────────────────────────────────────────────────────────────────────
export async function loginUser(email, password) {
  const form = new FormData();
  form.append('username', email);
  form.append('password', password);
  const res = await client.post('/auth/login', form);
  return res.data; // { access_token, token_type }
}

export async function restartInterview(interviewId) {
  const res = await client.post(`/interview/${interviewId}/restart`);
  return res.data; // { session_id, question_text, audio_base64 }
}

export async function registerUser(email, password, fullName) {
  const res = await client.post('/auth/register', {
    email,
    password,
    full_name: fullName,
  });
  return res.data; // { id, email }
}

export async function getCurrentUser() {
  const res = await client.get('/auth/me');
  return res.data; // { email, full_name }
}

// ── Document parsing ────────────────────────────────────────────────────────
export async function parseCV(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await client.post('/docs/parse-cv', form);
  return res.data; // { text, page_count, char_count }
}

export async function parseJD(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await client.post('/docs/parse-jd', form);
  return res.data; // { text, page_count, char_count }
}

export async function parseJDText(text) {
  const res = await client.post('/docs/parse-jd-text', { text });
  return res.data; // { text, page_count, char_count }
}

// ─ Interview orchestration ─────────────────────────────────────────────────
export async function startInterview(candidateName, cvText, jdText, parentInterviewId = null) {
  const res = await client.post('/interview/start', {
    candidate_name: candidateName,
    cv_text: cvText,
    jd_text: jdText,
    parent_interview_id: parentInterviewId,
  });
  return res.data; // { session_id, question_text, audio_base64 }
}

/**
 * Submit a .webm audio blob as the candidate's answer.
 * Returns the FULL axios response so the caller can inspect headers
 * (X-Question-Text, X-Interview-Done) and the body (audio bytes or JSON).
 */
export async function submitAnswer(sessionId, audioBlob) {
  const form = new FormData();
  form.append('file', audioBlob, 'answer.webm');
  return client.post(`/interview/${sessionId}/answer`, form, {
    responseType: 'blob',
  });
}

/**
 * Submit transcript text directly as the candidate's answer.
 * Used by Web Speech API frontend. Returns full axios response with blob.
 */
export async function submitAnswerText(sessionId, transcript) {
  return client.post(`/interview/${sessionId}/answer-text`,
    { transcript },
    { responseType: 'blob' }
  );
}

/**
 * Ask for the current question in simpler wording. Does not consume an interview
 * turn — returns { rephrased_question }.
 */
export async function paraphraseQuestion(sessionId, questionText) {
  const res = await client.post(`/interview/${sessionId}/paraphrase`, { question_text: questionText });
  return res.data; // { rephrased_question }
}

/**
 * Move on without recording an answer. Returns the FULL axios response so the
 * caller can inspect X-Interview-Done / X-Question-Text and the audio blob.
 */
export async function skipQuestion(sessionId) {
  return client.post(`/interview/${sessionId}/skip`, {}, { responseType: 'blob' });
}

export async function getInterviewStatus(sessionId) {
  const res = await client.get(`/interview/${sessionId}/status`);
  return res.data;
}

// ─ Interview history (/interviews router, not the /interview session routes) ──
export async function getInterviewHistory() {
  const res = await client.get('/interviews/history');
  return res.data;
}

export async function getInterviewFeedback(interviewId) {
  const res = await client.get(`/interviews/${interviewId}/feedback`);
  return res.data;
}

// ─ Proctoring ──────────────────────────────────────────────────────────────
export async function logProctorEvent(sessionId, eventType, timestampSeconds) {
  await client.post(`/proctor/${sessionId}/event`, {
    event_type: eventType,
    timestamp_seconds: timestampSeconds,
  });
}

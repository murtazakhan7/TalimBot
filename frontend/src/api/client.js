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

export async function registerUser(email, password, fullName) {
  const res = await client.post('/auth/register', {
    email,
    password,
    full_name: fullName,
  });
  return res.data; // { id, email }
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
export async function startInterview(candidateName, cvText, jdText) {
  const res = await client.post('/interview/start', {
    candidate_name: candidateName,
    cv_text: cvText,
    jd_text: jdText,
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

export async function getInterviewStatus(sessionId) {
  const res = await client.get(`/interview/${sessionId}/status`);
  return res.data;
}

// ─ Proctoring ──────────────────────────────────────────────────────────────
export async function logProctorEvent(sessionId, eventType, timestampSeconds) {
  await client.post(`/proctor/${sessionId}/event`, {
    event_type: eventType,
    timestamp_seconds: timestampSeconds,
  });
}

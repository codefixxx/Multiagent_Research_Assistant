/**
 * Ephemeral session utility for "Search and Forget" research isolation.
 *
 * Sessions are strictly scoped to sessionStorage so that when the browser tab or window
 * closes, the session ID and all temporary research history are erased from the client.
 */

const SESSION_STORAGE_KEY = 'multiagent_ephemeral_session_id';

export function getSessionId(): string {
  let sessionId = sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!sessionId) {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      sessionId = crypto.randomUUID();
    } else {
      sessionId = 'sess_' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
    }
    sessionStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  }
  return sessionId;
}

export function resetSessionId(): string {
  let newId: string;
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    newId = crypto.randomUUID();
  } else {
    newId = 'sess_' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
  }
  sessionStorage.setItem(SESSION_STORAGE_KEY, newId);
  return newId;
}

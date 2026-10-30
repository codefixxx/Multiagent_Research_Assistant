/**
 * Ephemeral session utility for "Search and Forget" research isolation.
 *
 * Sessions are strictly scoped to sessionStorage so that when the browser tab or window
 * closes, the session ID and all temporary research history are erased from the client.
 */

const SESSION_STORAGE_KEY = 'multiagent_ephemeral_session_id';
const AUTO_PURGE_ON_EXPORT_KEY = 'multiagent_auto_purge_on_export';
const PURGE_ON_CLOSE_KEY = 'multiagent_purge_on_close';

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

export function isAutoPurgeOnExport(): boolean {
  return sessionStorage.getItem(AUTO_PURGE_ON_EXPORT_KEY) === 'true';
}

export function setAutoPurgeOnExport(enabled: boolean): void {
  sessionStorage.setItem(AUTO_PURGE_ON_EXPORT_KEY, enabled ? 'true' : 'false');
}

export function isPurgeOnClose(): boolean {
  return sessionStorage.getItem(PURGE_ON_CLOSE_KEY) === 'true';
}

export function setPurgeOnClose(enabled: boolean): void {
  sessionStorage.setItem(PURGE_ON_CLOSE_KEY, enabled ? 'true' : 'false');
}

/**
 * Triggers complete server-side and client-side purge of all research artifacts for the session.
 */
export async function purgeEntireSession(apiBaseUrl: string = ''): Promise<boolean> {
  const sessionId = getSessionId();
  try {
    const res = await fetch(`${apiBaseUrl}/research/session/clear?session_id=${sessionId}`, {
      method: 'DELETE',
      headers: {
        'X-Session-ID': sessionId,
      },
    });
    // Wipe local ephemeral keys and state
    sessionStorage.removeItem('multiagent_last_run_id');
    sessionStorage.removeItem('multiagent_byok_keys');
    resetSessionId();
    return res.ok;
  } catch (err) {
    console.warn('Failed to purge session on server:', err);
    resetSessionId();
    return false;
  }
}

/**
 * Register unload listener that purges session on tab/browser close if opted-in.
 */
export function registerSessionUnloadHandler(apiBaseUrl: string = ''): () => void {
  const onUnload = () => {
    if (isPurgeOnClose()) {
      const sessionId = getSessionId();
      try {
        fetch(`${apiBaseUrl}/research/session/clear?session_id=${sessionId}`, {
          method: 'DELETE',
          headers: { 'X-Session-ID': sessionId },
          keepalive: true,
        }).catch(() => {});
      } catch {}
    }
  };

  window.addEventListener('pagehide', onUnload);
  return () => window.removeEventListener('pagehide', onUnload);
}

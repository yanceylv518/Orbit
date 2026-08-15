const STREAM_URL = "wss://fstream.binance.com/market/stream?streams=!ticker@arr/!markPrice@arr@1s";

export function createCurrentMarketStream({ onTicker, onMarkPrice, onStatus }) {
  let socket = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let stopped = false;

  function setStatus(status) {
    onStatus?.(status);
  }

  function connect() {
    if (stopped || socket) return;
    setStatus(reconnectAttempt ? "reconnecting" : "connecting");
    socket = new WebSocket(STREAM_URL);
    socket.addEventListener("open", () => {
      reconnectAttempt = 0;
      setStatus("live");
    });
    socket.addEventListener("message", (event) => {
      try {
        const envelope = JSON.parse(event.data);
        const rows = Array.isArray(envelope?.data) ? envelope.data : [];
        if (!rows.length) return;
        if (rows[0]?.e === "24hrTicker") onTicker?.(rows);
        if (rows[0]?.e === "markPriceUpdate") onMarkPrice?.(rows);
      } catch {
        // Ignore malformed third-party frames; the next update is a full snapshot.
      }
    });
    socket.addEventListener("close", () => {
      socket = null;
      if (stopped) return;
      setStatus("reconnecting");
      const delay = Math.min(30_000, 1000 * 2 ** reconnectAttempt++);
      reconnectTimer = setTimeout(connect, delay);
    });
    socket.addEventListener("error", () => socket?.close());
  }

  function stop() {
    stopped = true;
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (socket) socket.close();
    socket = null;
    setStatus("offline");
  }

  connect();
  return { stop };
}

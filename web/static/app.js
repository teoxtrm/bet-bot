/**
 * BetBot — WebSocket client with auto-reconnect + exponential backoff
 * Cookie bb_session is sent automatically by the browser (same-origin).
 */

let _ws       = null;
let _handlers = [];
let _delay    = 5000;
const _maxDelay = 30000;

function connectWS(onMessage) {
  if (onMessage) _handlers.push(onMessage);
  if (_ws && (_ws.readyState === WebSocket.OPEN ||
              _ws.readyState === WebSocket.CONNECTING)) return;

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _ws = new WebSocket(`${proto}://${location.host}/ws`);

  _ws.onopen = () => {
    console.log('[WS] connected');
    _delay = 5000;
    _ws._ping = setInterval(() => {
      if (_ws.readyState === WebSocket.OPEN) _ws.send('ping');
    }, 20000);
  };

  _ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    _handlers.forEach(h => { try { h(msg); } catch (err) { console.warn('[WS handler]', err); }});
  };

  _ws.onclose = () => {
    console.log(`[WS] closed — retry in ${_delay/1000}s`);
    clearInterval(_ws?._ping);
    setTimeout(() => {
      _delay = Math.min(_delay * 2, _maxDelay);
      connectWS(null);
    }, _delay);
  };

  _ws.onerror = () => _ws.close();
}

connectWS(null);

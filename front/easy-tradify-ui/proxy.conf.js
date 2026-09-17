/**
 * Dev-server proxy: forwards /api/** to the EasyTradify gateway.
 *
 * WHY THIS IS .js AND NOT .json
 * -----------------------------
 * The gateway's configured port is 8080, but that port is not always ours on a
 * developer machine — an unrelated Spring gateway from another project runs on
 * it here and is restarted by a supervisor, so hardcoding 8080 means the UI
 * silently proxies to a foreign service that answers 404 for every route. That
 * failure reads as "the backend is broken" and is genuinely hard to spot,
 * because something IS listening and IS replying.
 *
 * So the port is overridable:
 *
 *   EASYTRADIFY_GATEWAY_PORT=8088 npm start
 *
 * and the default stays 8080, which is what the gateway's own application.yml
 * declares and what production uses.
 */
const port = process.env.EASYTRADIFY_GATEWAY_PORT || '8080';
const target = `http://localhost:${port}`;

console.log(`[proxy] /api -> ${target}`);

module.exports = {
  '/api': {
    target,
    secure: false,
    changeOrigin: true,
    logLevel: 'debug',

    // Generous, and deliberately so. The AI research endpoints run walk-forward
    // folds and a permutation null before they answer; a 30s default would cut
    // off a scan that was going to succeed and report it as a network error.
    timeout: 120000,
    proxyTimeout: 120000,
  },
};

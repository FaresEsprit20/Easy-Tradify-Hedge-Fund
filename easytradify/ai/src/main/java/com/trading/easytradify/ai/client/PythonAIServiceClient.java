package com.trading.easytradify.ai.client;

import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;

import java.util.List;

/**
 * <h1>Python AI Service Client</h1>
 * <p>
 * Complete abstraction for the Python-based AI service (port 5002).
 * Provides access to GNN (Graph Neural Network) and Adversarial Training capabilities.
 * </p>
 *
 * <h2>Architecture Overview</h2>
 * <p>
 * This client provides a comprehensive set of methods that map directly
 * to the REST endpoints exposed by the Python AI controller on port 5002.
 * </p>
 *
 * <h2>GNN Features (14 endpoints)</h2>
 * <ul>
 *   <li><b>Status:</b> Get GNN health and configuration</li>
 *   <li><b>Context:</b> Get GNN context for analysis (dxy_strength, risk_sentiment, etc.)</li>
 *   <li><b>Insights:</b> Complete trading insights with correlations, divergences, suggestions</li>
 *   <li><b>Correlations:</b> Dynamic correlation matrix with confidence scores</li>
 *   <li><b>Divergences:</b> GNN vs price direction divergence detection</li>
 *   <li><b>Suggestions:</b> Correlated symbols with BUY/SELL actions</li>
 *   <li><b>Conflict:</b> Contradiction detection between your analysis and GNN</li>
 *   <li><b>A/B Test:</b> GNN A/B test results and statistics</li>
 *   <li><b>Heatmap:</b> Correlation heatmap for multiple symbols</li>
 *   <li><b>Correlation Changes:</b> Detect significant correlation shifts (regime changes)</li>
 *   <li><b>Refresh:</b> Force GNN cache refresh</li>
 *   <li><b>Reset:</b> Reset GNN state</li>
 *   <li><b>Rollout:</b> Set A/B test rollout percentage</li>
 *   <li><b>Track Result:</b> Track trade outcome for A/B testing</li>
 * </ul>
 *
 * <h2>Adversarial Features (6 endpoints)</h2>
 * <ul>
 *   <li><b>Status:</b> Get adversarial training status</li>
 *   <li><b>Generate:</b> Generate attacked trades for training</li>
 *   <li><b>Train:</b> Apply adversarial attacks to training</li>
 *   <li><b>Metrics:</b> Attack metrics and statistics</li>
 *   <li><b>Intensity:</b> Set attack intensity (0.0 - 1.0)</li>
 *   <li><b>Enable:</b> Enable or disable adversarial training</li>
 * </ul>
 *
 * <h2>Base URL</h2>
 * <p>
 * The Python AI service runs on port 5002
 * </p>
 *
 * <h2>Error Handling</h2>
 * <p>
 * All errors are propagated to the caller via
 * {@link com.trading.easytradify.common.exception.TradingException}.
 * </p>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @see DefaultPythonAIServiceClient
 * @see com.trading.easytradify.common.exception.TradingException
 */
public interface PythonAIServiceClient {

    // ============================================================
    // HEALTH
    // ============================================================

    /**
     * <h3>GET /health</h3>
     * <p>
     * Performs a health check on the Python AI service.
     * </p>
     *
     * @return {@link AIHealthResponse} containing the service health status
     */
    AIHealthResponse healthCheck();

    // ============================================================
    // GNN ENDPOINTS (14)
    // ============================================================

    /**
     * <h3>GET /gnn/status</h3>
     * <p>
     * Retrieves the current status of the GNN including configuration,
     * asset count, update interval, and A/B test status.
     * </p>
     *
     * @return {@link GnnStatusResponse} containing GNN status information
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnStatusResponse getGnnStatus();

    /**
     * <h3>GET /gnn/context/{symbol}</h3>
     * <p>
     * Retrieves GNN context for a symbol used in AI Asset Analyzer feature extraction.
     * </p>
     *
     * <h4>Context Includes</h4>
     * <ul>
     *   <li><b>dxy_strength:</b> Dollar index strength</li>
     *   <li><b>risk_sentiment:</b> Risk-on/risk-off sentiment</li>
     *   <li><b>commodity_impact:</b> Commodity price impact</li>
     *   <li><b>sector_sentiment:</b> Sector sentiment</li>
     *   <li><b>global_confidence:</b> Global market confidence</li>
     *   <li><b>trend_alignment:</b> Trend alignment score</li>
     *   <li><b>market_regime:</b> Current market regime</li>
     *   <li><b>correlation_shift:</b> Correlation changes</li>
     *   <li><b>gnn_influence:</b> GNN influence score</li>
     *   <li><b>gnn_connections:</b> Connected assets and weights</li>
     * </ul>
     *
     * @param symbol  The trading symbol (e.g., "EURUSD")
     * @param tradeId Optional trade ID for tracking (can be null)
     * @return {@link GnnContextResponse} containing the GNN context
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized, symbol is invalid, or the request fails
     */
    GnnContextResponse getGnnContext(String symbol, Integer tradeId);

    /**
     * <h3>GET /gnn/insights/{symbol}</h3>
     * <p>
     * Retrieves complete trading insights for a symbol including correlations,
     * divergences, suggestions, and conflict detection.
     * </p>
     *
     * @param symbol             The trading symbol (e.g., "EURUSD")
     * @param analysisDirection  Your analysis direction (BUY, SELL, or HOLD)
     * @return {@link GnnInsightsResponse} containing complete trading insights
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnInsightsResponse getGnnInsights(String symbol, String analysisDirection);

    /**
     * <h3>GET /gnn/correlations/{symbol}</h3>
     * <p>
     * Retrieves correlation information for a symbol.
     * Returns dynamic correlation matrix with confidence scores.
     * </p>
     *
     * @param symbol The trading symbol (e.g., "EURUSD")
     * @return {@link GnnCorrelationsResponse} containing correlation information
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnCorrelationsResponse getGnnCorrelations(String symbol);

    /**
     * <h3>GET /gnn/divergences/{symbol}</h3>
     * <p>
     * Checks for divergences between GNN and price direction.
     * </p>
     *
     * <h4>Divergence Types</h4>
     * <ul>
     *   <li><b>BULLISH:</b> Price making lower lows, GNN making higher lows</li>
     *   <li><b>BEARISH:</b> Price making higher highs, GNN making lower highs</li>
     * </ul>
     *
     * @param symbol The trading symbol (e.g., "EURUSD")
     * @return {@link GnnDivergencesResponse} containing divergence information
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnDivergencesResponse getGnnDivergences(String symbol);

    /**
     * <h3>GET /gnn/suggestions/{symbol}</h3>
     * <p>
     * Retrieves trade suggestions for correlated symbols.
     * Returns BUY/SELL actions with confidence scores.
     * </p>
     *
     * @param symbol The trading symbol (e.g., "EURUSD")
     * @return {@link GnnSuggestionsResponse} containing trade suggestions
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnSuggestionsResponse getGnnSuggestions(String symbol);

    /**
     * <h3>GET /gnn/conflict/{symbol}</h3>
     * <p>
     * Detects contradiction between your analysis and GNN predictions.
     * </p>
     *
     * <h4>Conflict Severity</h4>
     * <ul>
     *   <li><b>NONE:</b> Your analysis aligns with GNN</li>
     *   <li><b>LOW:</b> Minor disagreement</li>
     *   <li><b>MEDIUM:</b> Significant disagreement</li>
     *   <li><b>HIGH:</b> Strong contradiction</li>
     * </ul>
     *
     * @param symbol            The trading symbol (e.g., "EURUSD")
     * @param analysisDirection Your analysis direction (BUY or SELL)
     * @return {@link GnnConflictResponse} containing conflict detection results
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized, direction is invalid, or the request fails
     */
    GnnConflictResponse getGnnConflict(String symbol, String analysisDirection);

    /**
     * <h3>GET /gnn/ab_test</h3>
     * <p>
     * Retrieves GNN A/B test results and statistics.
     * </p>
     *
     * <h4>Statistics Include</h4>
     * <ul>
     *   <li>Total trades with GNN</li>
     *   <li>Total trades without GNN</li>
     *   <li>Win rates for both groups</li>
     *   <li>Profit/loss comparison</li>
     *   <li>Statistical significance</li>
     * </ul>
     *
     * @return {@link GnnAbTestResponse} containing A/B test results
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnAbTestResponse getGnnAbTest();

    /**
     * <h3>GET /gnn/heatmap</h3>
     * <p>
     * Retrieves a correlation heatmap for symbols.
     * </p>
     *
     * @param symbols Optional list of symbols (if null, returns all symbols)
     * @return {@link GnnHeatmapResponse} containing the correlation heatmap
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnHeatmapResponse getGnnHeatmap(List<String> symbols);

    /**
     * <h3>GET /gnn/correlation_changes/{symbol}</h3>
     * <p>
     * Detects significant changes in correlations (regime shifts).
     * </p>
     *
     * @param symbol   The trading symbol (e.g., "EURUSD")
     * @param lookback The lookback period in bars (default: 10)
     * @return {@link GnnCorrelationChangesResponse} containing correlation changes
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnCorrelationChangesResponse getGnnCorrelationChanges(String symbol, int lookback);

    /**
     * <h3>POST /gnn/refresh</h3>
     * <p>
     * Forces a refresh of the GNN cache.
     * </p>
     *
     * @return {@link GnnRefreshResponse} indicating the refresh result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the refresh fails
     */
    GnnRefreshResponse refreshGnn();

    /**
     * <h3>POST /gnn/reset</h3>
     * <p>
     * Resets the GNN state.
     * </p>
     *
     * @return {@link GnnResetResponse} indicating the reset result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the reset fails
     */
    GnnResetResponse resetGnn();

    /**
     * <h3>POST /gnn/ab_test/rollout</h3>
     * <p>
     * Sets the A/B test rollout percentage.
     * </p>
     *
     * @param rollout The rollout percentage (0.0 - 1.0)
     * @return {@link GnnRolloutResponse} indicating the rollout update result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the rollout value is invalid
     */
    GnnRolloutResponse setGnnAbTestRollout(double rollout);

    /**
     * <h3>POST /gnn/track_result</h3>
     * <p>
     * Tracks a trade outcome for A/B testing.
     * </p>
     *
     * @param request The track result request containing trade ID, profit, and outcome
     * @return {@link GnnTrackResultResponse} indicating the tracking result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request is invalid
     */
    GnnTrackResultResponse trackGnnResult(GnnTrackResultRequest request);

    // ============================================================
    // ADVERSARIAL ENDPOINTS (6)
    // ============================================================

    /**
     * <h3>GET /adversarial/status</h3>
     * <p>
     * Retrieves the current status of adversarial training.
     * </p>
     *
     * @return {@link AdversarialStatusResponse} containing adversarial training status
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or the request fails
     */
    AdversarialStatusResponse getAdversarialStatus();

    /**
     * <h3>POST /adversarial/generate</h3>
     * <p>
     * Generates attacked trade variations for adversarial training.
     * Creates multiple variations of a trade with different attack patterns.
     * </p>
     *
     * <h4>Attack Types</h4>
     * <ul>
     *   <li><b>PRICE_SHIFT:</b> Shift entry/stop/take profit levels</li>
     *   <li><b>VOLUME_SPIKE:</b> Add fake volume spikes</li>
     *   <li><b>MOMENTUM_FLIP:</b> Reverse momentum indicators</li>
     *   <li><b>STRUCTURE_BREAK:</b> Break structural levels</li>
     *   <li><b>COMBINED:</b> Combine multiple attack types</li>
     * </ul>
     *
     * @param request The adversarial generate request containing trade data
     * @return {@link AdversarialGenerateResponse} containing generated attacked trades
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or the request is invalid
     */
    AdversarialGenerateResponse generateAdversarialAttacks(AdversarialGenerateRequest request);

    /**
     * <h3>POST /adversarial/train</h3>
     * <p>
     * Applies adversarial attacks to training data.
     * Trains models on attacked versions of trades.
     * </p>
     *
     * @param request The adversarial train request containing trades and outcomes
     * @return {@link AdversarialTrainResponse} containing training results
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or the request is invalid
     */
    AdversarialTrainResponse trainAdversarial(AdversarialTrainRequest request);

    /**
     * <h3>GET /adversarial/metrics</h3>
     * <p>
     * Retrieves adversarial attack metrics and statistics.
     * </p>
     *
     * <h4>Metrics Include</h4>
     * <ul>
     *   <li>Total attacks generated</li>
     *   <li>Attacks applied</li>
     *   <li>Attack success rate</li>
     *   <li>Diversity score</li>
     *   <li>Components attacked</li>
     *   <li>Attack types used</li>
     * </ul>
     *
     * @return {@link AdversarialMetricsResponse} containing attack metrics
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or the request fails
     */
    AdversarialMetricsResponse getAdversarialMetrics();

    /**
     * <h3>POST /adversarial/intensity</h3>
     * <p>
     * Sets the attack intensity level.
     * </p>
     *
     * <h4>Intensity Levels</h4>
     * <ul>
     *   <li><b>0.0 - 0.3:</b> Low intensity - minimal perturbations</li>
     *   <li><b>0.3 - 0.7:</b> Medium intensity - moderate perturbations</li>
     *   <li><b>0.7 - 1.0:</b> High intensity - aggressive perturbations</li>
     * </ul>
     *
     * @param intensity The intensity value (0.0 - 1.0)
     * @return {@link AdversarialIntensityResponse} indicating the update result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or intensity is invalid
     */
    AdversarialIntensityResponse setAdversarialIntensity(double intensity);

    /**
     * <h3>POST /adversarial/enable</h3>
     * <p>
     * Enables or disables adversarial training.
     * </p>
     *
     * @param enabled Whether adversarial training should be enabled
     * @return {@link AdversarialEnableResponse} indicating the enable/disable result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or the request fails
     */
    AdversarialEnableResponse enableAdversarial(boolean enabled);
}
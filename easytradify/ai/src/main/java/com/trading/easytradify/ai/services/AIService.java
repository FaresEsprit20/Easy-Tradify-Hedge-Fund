package com.trading.easytradify.ai.services;

import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;

import java.util.List;
import java.util.Map;

/**
 * <h1>AI Service</h1>
 * <p>
 * Core service for AI-powered trading intelligence including GNN (Graph Neural Network)
 * and Adversarial Training capabilities.
 * </p>
 *
 * <h2>Architecture Overview</h2>
 * <p>
 * This service acts as a bridge between the application layer and the
 * Python AI service (port 5002). It provides:
 * </p>
 * <ul>
 *   <li><b>GNN:</b> Graph Neural Network for cross-asset learning and correlation analysis</li>
 *   <li><b>Adversarial:</b> Adversarial training for robust model development</li>
 *   <li><b>Insights:</b> Trading insights, divergences, and conflict detection</li>
 *   <li><b>A/B Testing:</b> Rollout management and performance tracking</li>
 * </ul>
 *
 * <h2>GNN Features</h2>
 * <ul>
 *   <li><b>Context:</b> Market context for feature extraction (dxy_strength, risk_sentiment, etc.)</li>
 *   <li><b>Insights:</b> Complete trading insights with correlations, divergences, suggestions</li>
 *   <li><b>Correlations:</b> Dynamic correlation matrix with confidence scores</li>
 *   <li><b>Divergences:</b> GNN vs price direction divergence detection</li>
 *   <li><b>Conflict:</b> Contradiction detection between your analysis and GNN</li>
 *   <li><b>A/B Test:</b> A/B test results and rollout management</li>
 * </ul>
 *
 * <h2>Adversarial Features</h2>
 * <ul>
 *   <li><b>Generation:</b> Generate attacked trade variations for training</li>
 *   <li><b>Training:</b> Apply adversarial attacks to training data</li>
 *   <li><b>Metrics:</b> Attack metrics and statistics</li>
 *   <li><b>Control:</b> Intensity and enable/disable controls</li>
 * </ul>
 *
 * <h2>Design Principles</h2>
 * <ul>
 *   <li><b>Thin Service:</b> All business logic is delegated to the Python client</li>
 *   <li><b>Zero Try-Catch:</b> All exceptions bubble up to GlobalExceptionHandler</li>
 *   <li><b>Declarative Validation:</b> Input validation is explicit and throws domain exceptions</li>
 *   <li><b>Stateless:</b> No instance state is maintained between requests</li>
 * </ul>
 *
 * <h2>Error Handling Strategy</h2>
 * <ol>
 *   <li>Validate inputs → throws {@link com.trading.easytradify.common.exception.TradingException} if invalid</li>
 *   <li>Delegate to client → returns a response object</li>
 *   <li>Check response success flag → throws {@link com.trading.easytradify.common.exception.TradingException} if {@code false}</li>
 *   <li>Return successful response to caller</li>
 * </ol>
 *
 * <h2>Usage Example</h2>
 * <pre>
 * {@code
 * @Autowired
 * private AIService aiService;
 *
 * public void analyzeTrade() {
 *     var context = aiService.getGnnContext("EURUSD", null);
 *     var insights = aiService.getGnnInsights("EURUSD", "BUY");
 *     var conflict = aiService.getGnnConflict("EURUSD", "BUY");
 *     // Use insights for trading decisions
 * }
 * }
 * </pre>
 *
 * @author Trading Platform Team
 * @version 1.0
 * @since 1.0.0
 * @see com.trading.easytradify.ai.client.PythonAIServiceClient
 * @see com.trading.easytradify.common.exception.TradingException
 * @see com.trading.easytradify.common.exception.ErrorCodes
 */
public interface AIService {

    // ============================================================
    // HEALTH
    // ============================================================

    /**
     * <h3>Health Check</h3>
     * <p>
     * Performs a health check on the AI service.
     * </p>
     *
     * @return {@link AIHealthResponse} containing the service health status
     */
    AIHealthResponse healthCheck();

    // ============================================================
    // GNN ENDPOINTS
    // ============================================================

    /**
     * <h3>Get GNN Status</h3>
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
     * <h3>Get GNN Context</h3>
     * <p>
     * Retrieves GNN context for a symbol used in AI Asset Analyzer feature extraction.
     * </p>
     *
     * <h4>Context Includes</h4>
     * <ul>
     *   <li><b>dxy_strength:</b> Dollar index strength (-1.0 to 1.0)</li>
     *   <li><b>risk_sentiment:</b> Risk-on/risk-off sentiment (-1.0 to 1.0)</li>
     *   <li><b>commodity_impact:</b> Commodity price impact (-1.0 to 1.0)</li>
     *   <li><b>sector_sentiment:</b> Sector sentiment (-1.0 to 1.0)</li>
     *   <li><b>global_confidence:</b> Global market confidence (0.0 to 1.0)</li>
     *   <li><b>trend_alignment:</b> Trend alignment score (0.0 to 1.0)</li>
     *   <li><b>market_regime:</b> Current market regime (TRENDING/RANGING/VOLATILE)</li>
     *   <li><b>correlation_shift:</b> Correlation changes (0.0 to 1.0)</li>
     *   <li><b>gnn_influence:</b> GNN influence score (0.0 to 1.0)</li>
     *   <li><b>gnn_connections:</b> Connected assets and weights</li>
     * </ul>
     *
     * @param symbol  The trading symbol (e.g., "EURUSD")
     *                Must not be {@code null} or empty
     * @param tradeId Optional trade ID for tracking (can be null)
     * @return {@link GnnContextResponse} containing the GNN context
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized, symbol is invalid, or the request fails
     */
    GnnContextResponse getGnnContext(String symbol, Integer tradeId);

    /**
     * <h3>Get GNN Insights</h3>
     * <p>
     * Retrieves complete trading insights for a symbol including correlations,
     * divergences, suggestions, and conflict detection.
     * </p>
     *
     * <h4>Insights Include</h4>
     * <ul>
     *   <li><b>correlations:</b> Dynamic correlation matrix</li>
     *   <li><b>divergences:</b> GNN vs price direction divergence</li>
     *   <li><b>suggestions:</b> Correlated symbols with BUY/SELL actions</li>
     *   <li><b>risk_warnings:</b> Risk warnings and alerts</li>
     *   <li><b>conflict:</b> Contradiction detection (if analysis direction provided)</li>
     * </ul>
     *
     * @param symbol             The trading symbol (e.g., "EURUSD")
     *                           Must not be {@code null} or empty
     * @param analysisDirection  Your analysis direction (BUY, SELL, or HOLD)
     *                           Can be {@code null} for no conflict detection
     * @return {@link GnnInsightsResponse} containing complete trading insights
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnInsightsResponse getGnnInsights(String symbol, String analysisDirection);

    /**
     * <h3>Get GNN Correlations</h3>
     * <p>
     * Retrieves correlation information for a symbol.
     * Returns dynamic correlation matrix with confidence scores.
     * </p>
     *
     * @param symbol The trading symbol (e.g., "EURUSD")
     *               Must not be {@code null} or empty
     * @return {@link GnnCorrelationsResponse} containing correlation information
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnCorrelationsResponse getGnnCorrelations(String symbol);

    /**
     * <h3>Get GNN Divergences</h3>
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
     *               Must not be {@code null} or empty
     * @return {@link GnnDivergencesResponse} containing divergence information
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnDivergencesResponse getGnnDivergences(String symbol);

    /**
     * <h3>Get GNN Suggestions</h3>
     * <p>
     * Retrieves trade suggestions for correlated symbols.
     * Returns BUY/SELL actions with confidence scores.
     * </p>
     *
     * @param symbol The trading symbol (e.g., "EURUSD")
     *               Must not be {@code null} or empty
     * @return {@link GnnSuggestionsResponse} containing trade suggestions
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnSuggestionsResponse getGnnSuggestions(String symbol);

    /**
     * <h3>Get GNN Conflict</h3>
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
     *                          Must not be {@code null} or empty
     * @param analysisDirection Your analysis direction (BUY or SELL)
     *                          Must not be {@code null}
     * @return {@link GnnConflictResponse} containing conflict detection results
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized, direction is invalid, or the request fails
     */
    GnnConflictResponse getGnnConflict(String symbol, String analysisDirection);

    /**
     * <h3>Get GNN A/B Test Results</h3>
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
     * <h3>Get GNN Heatmap</h3>
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
     * <h3>Get GNN Correlation Changes</h3>
     * <p>
     * Detects significant changes in correlations (regime shifts).
     * </p>
     *
     * @param symbol   The trading symbol (e.g., "EURUSD")
     *                 Must not be {@code null} or empty
     * @param lookback The lookback period in bars (default: 10)
     *                 Must be positive
     * @return {@link GnnCorrelationChangesResponse} containing correlation changes
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request fails
     */
    GnnCorrelationChangesResponse getGnnCorrelationChanges(String symbol, int lookback);

    /**
     * <h3>Refresh GNN</h3>
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
     * <h3>Reset GNN</h3>
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
     * <h3>Set GNN A/B Test Rollout</h3>
     * <p>
     * Sets the A/B test rollout percentage.
     * </p>
     *
     * @param rollout The rollout percentage (0.0 - 1.0)
     *                Must be between 0.0 and 1.0
     * @return {@link GnnRolloutResponse} indicating the rollout update result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the rollout value is invalid
     */
    GnnRolloutResponse setGnnAbTestRollout(double rollout);

    /**
     * <h3>Track GNN Result</h3>
     * <p>
     * Tracks a trade outcome for A/B testing.
     * </p>
     *
     * @param request The track result request containing trade ID, profit, and outcome
     *                Must not be {@code null}
     * @return {@link GnnTrackResultResponse} indicating the tracking result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If the GNN is not initialized or the request is invalid
     */
    GnnTrackResultResponse trackGnnResult(GnnTrackResultRequest request);

    // ============================================================
    // ADVERSARIAL ENDPOINTS
    // ============================================================

    /**
     * <h3>Get Adversarial Status</h3>
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
     * <h3>Generate Adversarial Attacks</h3>
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
     *                Must not be {@code null}
     * @return {@link AdversarialGenerateResponse} containing generated attacked trades
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or the request is invalid
     */
    AdversarialGenerateResponse generateAdversarialAttacks(AdversarialGenerateRequest request);

    /**
     * <h3>Train Adversarial</h3>
     * <p>
     * Applies adversarial attacks to training data.
     * Trains models on attacked versions of trades.
     * </p>
     *
     * @param request The adversarial train request containing trades and outcomes
     *                Must not be {@code null}
     * @return {@link AdversarialTrainResponse} containing training results
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or the request is invalid
     */
    AdversarialTrainResponse trainAdversarial(AdversarialTrainRequest request);

    /**
     * <h3>Get Adversarial Metrics</h3>
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
     * <h3>Set Adversarial Intensity</h3>
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
     *                  Must be between 0.0 and 1.0
     * @return {@link AdversarialIntensityResponse} indicating the update result
     * @throws com.trading.easytradify.common.exception.TradingException
     *         If adversarial training is not initialized or intensity is invalid
     */
    AdversarialIntensityResponse setAdversarialIntensity(double intensity);

    /**
     * <h3>Enable/Disable Adversarial</h3>
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
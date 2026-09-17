package com.trading.easytradify.ai.unit;

import com.trading.easytradify.ai.client.PythonAIServiceClient;
import com.trading.easytradify.ai.models.*;
import com.trading.easytradify.ai.models.adverserial.*;
import com.trading.easytradify.ai.models.gnn.*;
import java.util.List;

/**
 * Mock implementation of PythonAIServiceClient for unit testing.
 * Provides configurable success/failure responses.
 */
public class PythonAIServiceClientMock implements PythonAIServiceClient {

    private boolean shouldSucceed = true;
    private String errorMessage = "Mock error";
    private boolean shouldThrowException = false;

    public PythonAIServiceClientMock withSuccess() {
        this.shouldSucceed = true;
        this.shouldThrowException = false;
        return this;
    }

    public PythonAIServiceClientMock withFailure(String errorMessage) {
        this.shouldSucceed = false;
        this.errorMessage = errorMessage;
        this.shouldThrowException = false;
        return this;
    }

    public PythonAIServiceClientMock withException() {
        this.shouldThrowException = true;
        return this;
    }

    // ============================================================
    // HEALTH
    // ============================================================

    @Override
    public AIHealthResponse healthCheck() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validHealthResponse();
        }
        return AIServiceTestDataFactory.errorHealthResponse();
    }

    // ============================================================
    // GNN ENDPOINTS (14)
    // ============================================================

    @Override
    public GnnStatusResponse getGnnStatus() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnStatusResponse();
        }
        return AIServiceTestDataFactory.errorGnnStatusResponse(errorMessage);
    }

    @Override
    public GnnContextResponse getGnnContext(String symbol, Integer tradeId) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnContextResponse();
        }
        return AIServiceTestDataFactory.errorGnnContextResponse(errorMessage);
    }

    @Override
    public GnnInsightsResponse getGnnInsights(String symbol, String analysisDirection) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnInsightsResponse();
        }
        return AIServiceTestDataFactory.errorGnnInsightsResponse(errorMessage);
    }

    @Override
    public GnnCorrelationsResponse getGnnCorrelations(String symbol) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnCorrelationsResponse();
        }
        return AIServiceTestDataFactory.errorGnnCorrelationsResponse(errorMessage);
    }

    @Override
    public GnnDivergencesResponse getGnnDivergences(String symbol) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnDivergencesResponse();
        }
        return AIServiceTestDataFactory.errorGnnDivergencesResponse(errorMessage);
    }

    @Override
    public GnnSuggestionsResponse getGnnSuggestions(String symbol) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnSuggestionsResponse();
        }
        return AIServiceTestDataFactory.errorGnnSuggestionsResponse(errorMessage);
    }

    @Override
    public GnnConflictResponse getGnnConflict(String symbol, String analysisDirection) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnConflictResponse();
        }
        return AIServiceTestDataFactory.errorGnnConflictResponse(errorMessage);
    }

    @Override
    public GnnAbTestResponse getGnnAbTest() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnAbTestResponse();
        }
        return AIServiceTestDataFactory.errorGnnAbTestResponse(errorMessage);
    }

    @Override
    public GnnHeatmapResponse getGnnHeatmap(List<String> symbols) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnHeatmapResponse();
        }
        return AIServiceTestDataFactory.errorGnnHeatmapResponse(errorMessage);
    }

    @Override
    public GnnCorrelationChangesResponse getGnnCorrelationChanges(String symbol, int lookback) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnCorrelationChangesResponse();
        }
        return AIServiceTestDataFactory.errorGnnCorrelationChangesResponse(errorMessage);
    }

    @Override
    public GnnRefreshResponse refreshGnn() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnRefreshResponse();
        }
        return AIServiceTestDataFactory.errorGnnRefreshResponse(errorMessage);
    }

    @Override
    public GnnResetResponse resetGnn() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnResetResponse();
        }
        return AIServiceTestDataFactory.errorGnnResetResponse(errorMessage);
    }

    @Override
    public GnnRolloutResponse setGnnAbTestRollout(double rollout) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnRolloutResponse();
        }
        return AIServiceTestDataFactory.errorGnnRolloutResponse(errorMessage);
    }

    @Override
    public GnnTrackResultResponse trackGnnResult(GnnTrackResultRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validGnnTrackResultResponse();
        }
        return AIServiceTestDataFactory.errorGnnTrackResultResponse(errorMessage);
    }

    // ============================================================
    // ADVERSARIAL ENDPOINTS (6)
    // ============================================================

    @Override
    public AdversarialStatusResponse getAdversarialStatus() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validAdversarialStatusResponse();
        }
        return AIServiceTestDataFactory.errorAdversarialStatusResponse(errorMessage);
    }

    @Override
    public AdversarialGenerateResponse generateAdversarialAttacks(AdversarialGenerateRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validAdversarialGenerateResponse();
        }
        return AIServiceTestDataFactory.errorAdversarialGenerateResponse(errorMessage);
    }

    @Override
    public AdversarialTrainResponse trainAdversarial(AdversarialTrainRequest request) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validAdversarialTrainResponse();
        }
        return AIServiceTestDataFactory.errorAdversarialTrainResponse(errorMessage);
    }

    @Override
    public AdversarialMetricsResponse getAdversarialMetrics() {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validAdversarialMetricsResponse();
        }
        return AIServiceTestDataFactory.errorAdversarialMetricsResponse(errorMessage);
    }

    @Override
    public AdversarialIntensityResponse setAdversarialIntensity(double intensity) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validAdversarialIntensityResponse();
        }
        return AIServiceTestDataFactory.errorAdversarialIntensityResponse(errorMessage);
    }

    @Override
    public AdversarialEnableResponse enableAdversarial(boolean enabled) {
        if (shouldThrowException) {
            throw new RuntimeException("Simulated client exception");
        }
        if (shouldSucceed) {
            return AIServiceTestDataFactory.validAdversarialEnableResponse();
        }
        return AIServiceTestDataFactory.errorAdversarialEnableResponse(errorMessage);
    }


}
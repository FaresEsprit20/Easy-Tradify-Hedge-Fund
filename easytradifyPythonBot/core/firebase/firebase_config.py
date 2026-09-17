# ============================================================
# FIREBASE CONFIGURATION - COMPLETE WITH SELF-CORRECTION
# ============================================================

import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class FirebaseConfig:
    """Firebase configuration management with complete AI collections."""
    
    # Default credentials path
    DEFAULT_CREDENTIALS_PATH = "firebase-credentials.json"
    
    # ============================================================
    # MAIN TRADE COLLECTIONS
    # ============================================================
    
    COLLECTION_TRADES = "trades"                    # Full trade data
    COLLECTION_TRADES_OPEN = "trades_open"          # Open trades only
    COLLECTION_TRADES_CLOSED = "trades_closed"      # Closed trades only
    
    # ============================================================
    # AI TRAINING COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_TRAINING = "ai_training"          # Raw training data (features + target)
    COLLECTION_AI_FEATURES = "ai_features"          # Extracted features per trade
    COLLECTION_AI_TARGETS = "ai_targets"            # Win/Loss targets
    COLLECTION_AI_COMPONENTS = "ai_components"      # Component performance data
    
    # ============================================================
    # AI MODEL COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_MODELS = "ai_models"              # All model versions
    COLLECTION_AI_MODEL_COMPONENTS = "ai_model_components"  # Component-specific models
    COLLECTION_AI_MODEL_ENSEMBLE = "ai_model_ensemble"      # Ensemble models
    COLLECTION_AI_MODEL_META = "ai_model_meta"              # Meta-learner models
    COLLECTION_AI_MODEL_RL = "ai_model_rl"                  # Reinforcement Learning models
    COLLECTION_AI_MODEL_CLUSTER = "ai_model_cluster"        # Clustering models
    COLLECTION_AI_MODEL_PHASE = "ai_model_phase"            # Market phase models
    
    # ============================================================
    # AI PREDICTION COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_PREDICTIONS = "ai_predictions"            # All predictions
    COLLECTION_AI_PREDICTIONS_LIVE = "ai_predictions_live"  # Current live predictions
    COLLECTION_AI_PREDICTIONS_HISTORY = "ai_predictions_history"  # Historical predictions
    
    # ============================================================
    # AI SCORING COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_SCORES = "ai_scores"                      # All scores
    COLLECTION_AI_SCORES_OVERALL = "ai_scores_overall"      # Overall confidence scores
    COLLECTION_AI_SCORES_ENTRY = "ai_scores_entry"          # Entry confidence scores
    COLLECTION_AI_SCORES_COMPONENT = "ai_scores_component"  # Component-level scores
    
    # ============================================================
    # AI PATTERN COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_PATTERNS = "ai_patterns"                  # All patterns
    COLLECTION_AI_PATTERNS_WINNING = "ai_patterns_winning"  # Winning patterns
    COLLECTION_AI_PATTERNS_LOSING = "ai_patterns_losing"    # Losing patterns
    COLLECTION_AI_PATTERNS_SIMILAR = "ai_patterns_similar"  # Similar pattern matches
    
    # ============================================================
    # AI INSIGHT COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_INSIGHTS = "ai_insights"                  # All insights
    COLLECTION_AI_INSIGHTS_DAILY = "ai_insights_daily"      # Daily insights
    COLLECTION_AI_INSIGHTS_WEEKLY = "ai_insights_weekly"    # Weekly insights
    COLLECTION_AI_INSIGHTS_MONTHLY = "ai_insights_monthly"  # Monthly insights
    
    # ============================================================
    # AI PERFORMANCE COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_PERFORMANCE = "ai_performance"            # Performance metrics
    COLLECTION_AI_PERFORMANCE_COMPONENT = "ai_performance_component"  # Component performance
    COLLECTION_AI_PERFORMANCE_MODEL = "ai_performance_model"        # Model performance
    COLLECTION_AI_PERFORMANCE_CALIBRATION = "ai_performance_calibration"  # Confidence calibration
    
    # ============================================================
    # AI ADAPTATION COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_ADAPTATION = "ai_adaptation"              # Adaptation history
    COLLECTION_AI_ADAPTATION_THRESHOLDS = "ai_adaptation_thresholds"  # Dynamic thresholds
    COLLECTION_AI_ADAPTATION_WEIGHTS = "ai_adaptation_weights"        # Component weights
    COLLECTION_AI_ADAPTATION_MARKET = "ai_adaptation_market"          # Market adaptation
    
    # ============================================================
    # AI RL COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_RL = "ai_rl"                              # RL data
    COLLECTION_AI_RL_QTABLE = "ai_rl_qtable"                # Q-table
    COLLECTION_AI_RL_MEMORY = "ai_rl_memory"                # Experience replay memory
    COLLECTION_AI_RL_REWARDS = "ai_rl_rewards"              # Reward history
    
    # ============================================================
    # AI DRIFT COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_DRIFT = "ai_drift"                        # Drift detection
    COLLECTION_AI_DRIFT_SCORES = "ai_drift_scores"          # Drift scores history
    COLLECTION_AI_DRIFT_ALERTS = "ai_drift_alerts"          # Drift alerts
    
    # ============================================================
    # AI RISK COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_RISK = "ai_risk"                          # Risk assessment
    COLLECTION_AI_RISK_SCORES = "ai_risk_scores"            # Risk scores
    COLLECTION_AI_RISK_HISTORY = "ai_risk_history"          # Risk history
    
    # ============================================================
    # AI ATTRIBUTION COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_ATTRIBUTION = "ai_attribution"            # Attribution analysis
    COLLECTION_AI_ATTRIBUTION_COMPONENT = "ai_attribution_component"  # Component attribution
    COLLECTION_AI_ATTRIBUTION_TRADE = "ai_attribution_trade"          # Trade-level attribution
    
    # ============================================================
    # AI COUNTERFACTUAL COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_COUNTERFACTUAL = "ai_counterfactual"      # Counterfactual analysis
    COLLECTION_AI_COUNTERFACTUAL_SCENARIOS = "ai_counterfactual_scenarios"  # Scenarios
    
    # ============================================================
    # AI ANOMALY COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_ANOMALY = "ai_anomaly"                    # Anomaly detection
    COLLECTION_AI_ANOMALY_DETECTED = "ai_anomaly_detected"  # Detected anomalies
    
    # ============================================================
    # AI MARKET PHASE COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_PHASE = "ai_phase"                        # Market phase
    COLLECTION_AI_PHASE_HISTORY = "ai_phase_history"        # Phase history
    COLLECTION_AI_PHASE_TRANSITIONS = "ai_phase_transitions"  # Phase transitions
    
    # ============================================================
    # AI CLUSTER COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_CLUSTER = "ai_cluster"                    # Clustering
    COLLECTION_AI_CLUSTER_RESULTS = "ai_cluster_results"    # Cluster results
    COLLECTION_AI_CLUSTER_ASSIGNMENTS = "ai_cluster_assignments"  # Trade assignments
    
    # ============================================================
    # AI DISTILLATION COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_DISTILLATION = "ai_distillation"          # Knowledge distillation
    COLLECTION_AI_DISTILLATION_STUDENT = "ai_distillation_student"  # Student models
    
    # ============================================================
    # AI CAUSAL COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_CAUSAL = "ai_causal"                      # Causal inference
    COLLECTION_AI_CAUSAL_EDGES = "ai_causal_edges"          # Causal edges
    
    # ============================================================
    # AI FEEDBACK COLLECTIONS
    # ============================================================
    
    COLLECTION_AI_FEEDBACK = "ai_feedback"                  # Feedback loop
    COLLECTION_AI_FEEDBACK_CORRECTIONS = "ai_feedback_corrections"  # Corrections
    COLLECTION_AI_FEEDBACK_LEARNINGS = "ai_feedback_learnings"      # Learnings
    
    # ============================================================
    # AI SELF-CORRECTION COLLECTIONS (NEW!)
    # ============================================================
    
    COLLECTION_AI_ROOT_CAUSES = "ai_root_causes"            # Root cause analysis
    COLLECTION_AI_CORRECTIONS = "ai_corrections"            # Applied corrections
    COLLECTION_AI_EVOLUTIONS = "ai_evolutions"              # AI evolution history
    COLLECTION_AI_COMPONENT_PERFORMANCE = "ai_component_performance"  # Component performance tracking
    COLLECTION_AI_RULE_EVOLUTION = "ai_rule_evolution"      # Evolved rules history
    
    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path or self.DEFAULT_CREDENTIALS_PATH
        self._credentials_exist = os.path.exists(self.credentials_path)
        
        if not self._credentials_exist:
            logger.warning(f"Firebase credentials file not found: {self.credentials_path}")
            logger.warning("Firebase will run in offline mode - writes will be queued")
    
    def get_credentials_path(self) -> str:
        return self.credentials_path
    
    def has_credentials(self) -> bool:
        return self._credentials_exist
    
    @classmethod
    def from_env(cls) -> 'FirebaseConfig':
        cred_path = os.environ.get('FIREBASE_CREDENTIALS_PATH', cls.DEFAULT_CREDENTIALS_PATH)
        return cls(cred_path)
    
    def get_collection(self, name: str) -> str:
        return name
    
    def get_document_id(self, trade_id: str) -> str:
        return f"trade_{trade_id}"
    
    def get_ai_training_id(self, trade_id: str) -> str:
        return f"trade_{trade_id}"
    
    # ============================================================
    # COLLECTION HELPERS
    # ============================================================
    
    @property
    def collections(self) -> dict:
        """Get all collection names grouped by category."""
        return {
            # Main trades
            "trades": {
                "all": self.COLLECTION_TRADES,
                "open": self.COLLECTION_TRADES_OPEN,
                "closed": self.COLLECTION_TRADES_CLOSED
            },
            # AI Training
            "ai_training": {
                "training": self.COLLECTION_AI_TRAINING,
                "features": self.COLLECTION_AI_FEATURES,
                "targets": self.COLLECTION_AI_TARGETS,
                "components": self.COLLECTION_AI_COMPONENTS
            },
            # AI Models
            "ai_models": {
                "all": self.COLLECTION_AI_MODELS,
                "components": self.COLLECTION_AI_MODEL_COMPONENTS,
                "ensemble": self.COLLECTION_AI_MODEL_ENSEMBLE,
                "meta": self.COLLECTION_AI_MODEL_META,
                "rl": self.COLLECTION_AI_MODEL_RL,
                "cluster": self.COLLECTION_AI_MODEL_CLUSTER,
                "phase": self.COLLECTION_AI_MODEL_PHASE
            },
            # AI Predictions
            "ai_predictions": {
                "all": self.COLLECTION_AI_PREDICTIONS,
                "live": self.COLLECTION_AI_PREDICTIONS_LIVE,
                "history": self.COLLECTION_AI_PREDICTIONS_HISTORY
            },
            # AI Scores
            "ai_scores": {
                "all": self.COLLECTION_AI_SCORES,
                "overall": self.COLLECTION_AI_SCORES_OVERALL,
                "entry": self.COLLECTION_AI_SCORES_ENTRY,
                "component": self.COLLECTION_AI_SCORES_COMPONENT
            },
            # AI Patterns
            "ai_patterns": {
                "all": self.COLLECTION_AI_PATTERNS,
                "winning": self.COLLECTION_AI_PATTERNS_WINNING,
                "losing": self.COLLECTION_AI_PATTERNS_LOSING,
                "similar": self.COLLECTION_AI_PATTERNS_SIMILAR
            },
            # AI Insights
            "ai_insights": {
                "all": self.COLLECTION_AI_INSIGHTS,
                "daily": self.COLLECTION_AI_INSIGHTS_DAILY,
                "weekly": self.COLLECTION_AI_INSIGHTS_WEEKLY,
                "monthly": self.COLLECTION_AI_INSIGHTS_MONTHLY
            },
            # AI Performance
            "ai_performance": {
                "all": self.COLLECTION_AI_PERFORMANCE,
                "component": self.COLLECTION_AI_PERFORMANCE_COMPONENT,
                "model": self.COLLECTION_AI_PERFORMANCE_MODEL,
                "calibration": self.COLLECTION_AI_PERFORMANCE_CALIBRATION
            },
            # AI Adaptation
            "ai_adaptation": {
                "all": self.COLLECTION_AI_ADAPTATION,
                "thresholds": self.COLLECTION_AI_ADAPTATION_THRESHOLDS,
                "weights": self.COLLECTION_AI_ADAPTATION_WEIGHTS,
                "market": self.COLLECTION_AI_ADAPTATION_MARKET
            },
            # AI RL
            "ai_rl": {
                "all": self.COLLECTION_AI_RL,
                "qtable": self.COLLECTION_AI_RL_QTABLE,
                "memory": self.COLLECTION_AI_RL_MEMORY,
                "rewards": self.COLLECTION_AI_RL_REWARDS
            },
            # AI Drift
            "ai_drift": {
                "all": self.COLLECTION_AI_DRIFT,
                "scores": self.COLLECTION_AI_DRIFT_SCORES,
                "alerts": self.COLLECTION_AI_DRIFT_ALERTS
            },
            # AI Risk
            "ai_risk": {
                "all": self.COLLECTION_AI_RISK,
                "scores": self.COLLECTION_AI_RISK_SCORES,
                "history": self.COLLECTION_AI_RISK_HISTORY
            },
            # AI Attribution
            "ai_attribution": {
                "all": self.COLLECTION_AI_ATTRIBUTION,
                "component": self.COLLECTION_AI_ATTRIBUTION_COMPONENT,
                "trade": self.COLLECTION_AI_ATTRIBUTION_TRADE
            },
            # AI Counterfactual
            "ai_counterfactual": {
                "all": self.COLLECTION_AI_COUNTERFACTUAL,
                "scenarios": self.COLLECTION_AI_COUNTERFACTUAL_SCENARIOS
            },
            # AI Anomaly
            "ai_anomaly": {
                "all": self.COLLECTION_AI_ANOMALY,
                "detected": self.COLLECTION_AI_ANOMALY_DETECTED
            },
            # AI Phase
            "ai_phase": {
                "all": self.COLLECTION_AI_PHASE,
                "history": self.COLLECTION_AI_PHASE_HISTORY,
                "transitions": self.COLLECTION_AI_PHASE_TRANSITIONS
            },
            # AI Cluster
            "ai_cluster": {
                "all": self.COLLECTION_AI_CLUSTER,
                "results": self.COLLECTION_AI_CLUSTER_RESULTS,
                "assignments": self.COLLECTION_AI_CLUSTER_ASSIGNMENTS
            },
            # AI Distillation
            "ai_distillation": {
                "all": self.COLLECTION_AI_DISTILLATION,
                "student": self.COLLECTION_AI_DISTILLATION_STUDENT
            },
            # AI Causal
            "ai_causal": {
                "all": self.COLLECTION_AI_CAUSAL,
                "edges": self.COLLECTION_AI_CAUSAL_EDGES
            },
            # AI Feedback
            "ai_feedback": {
                "all": self.COLLECTION_AI_FEEDBACK,
                "corrections": self.COLLECTION_AI_FEEDBACK_CORRECTIONS,
                "learnings": self.COLLECTION_AI_FEEDBACK_LEARNINGS
            },
            # ============================================================
            # AI SELF-CORRECTION (NEW!)
            # ============================================================
            "ai_self_correction": {
                "root_causes": self.COLLECTION_AI_ROOT_CAUSES,
                "corrections": self.COLLECTION_AI_CORRECTIONS,
                "evolutions": self.COLLECTION_AI_EVOLUTIONS,
                "component_performance": self.COLLECTION_AI_COMPONENT_PERFORMANCE,
                "rule_evolution": self.COLLECTION_AI_RULE_EVOLUTION
            }
        }
    
    @property
    def all_collections(self) -> list:
        """Get flat list of all collection names."""
        return [
            self.COLLECTION_TRADES,
            self.COLLECTION_TRADES_OPEN,
            self.COLLECTION_TRADES_CLOSED,
            self.COLLECTION_AI_TRAINING,
            self.COLLECTION_AI_FEATURES,
            self.COLLECTION_AI_TARGETS,
            self.COLLECTION_AI_COMPONENTS,
            self.COLLECTION_AI_MODELS,
            self.COLLECTION_AI_MODEL_COMPONENTS,
            self.COLLECTION_AI_MODEL_ENSEMBLE,
            self.COLLECTION_AI_MODEL_META,
            self.COLLECTION_AI_MODEL_RL,
            self.COLLECTION_AI_MODEL_CLUSTER,
            self.COLLECTION_AI_MODEL_PHASE,
            self.COLLECTION_AI_PREDICTIONS,
            self.COLLECTION_AI_PREDICTIONS_LIVE,
            self.COLLECTION_AI_PREDICTIONS_HISTORY,
            self.COLLECTION_AI_SCORES,
            self.COLLECTION_AI_SCORES_OVERALL,
            self.COLLECTION_AI_SCORES_ENTRY,
            self.COLLECTION_AI_SCORES_COMPONENT,
            self.COLLECTION_AI_PATTERNS,
            self.COLLECTION_AI_PATTERNS_WINNING,
            self.COLLECTION_AI_PATTERNS_LOSING,
            self.COLLECTION_AI_PATTERNS_SIMILAR,
            self.COLLECTION_AI_INSIGHTS,
            self.COLLECTION_AI_INSIGHTS_DAILY,
            self.COLLECTION_AI_INSIGHTS_WEEKLY,
            self.COLLECTION_AI_INSIGHTS_MONTHLY,
            self.COLLECTION_AI_PERFORMANCE,
            self.COLLECTION_AI_PERFORMANCE_COMPONENT,
            self.COLLECTION_AI_PERFORMANCE_MODEL,
            self.COLLECTION_AI_PERFORMANCE_CALIBRATION,
            self.COLLECTION_AI_ADAPTATION,
            self.COLLECTION_AI_ADAPTATION_THRESHOLDS,
            self.COLLECTION_AI_ADAPTATION_WEIGHTS,
            self.COLLECTION_AI_ADAPTATION_MARKET,
            self.COLLECTION_AI_RL,
            self.COLLECTION_AI_RL_QTABLE,
            self.COLLECTION_AI_RL_MEMORY,
            self.COLLECTION_AI_RL_REWARDS,
            self.COLLECTION_AI_DRIFT,
            self.COLLECTION_AI_DRIFT_SCORES,
            self.COLLECTION_AI_DRIFT_ALERTS,
            self.COLLECTION_AI_RISK,
            self.COLLECTION_AI_RISK_SCORES,
            self.COLLECTION_AI_RISK_HISTORY,
            self.COLLECTION_AI_ATTRIBUTION,
            self.COLLECTION_AI_ATTRIBUTION_COMPONENT,
            self.COLLECTION_AI_ATTRIBUTION_TRADE,
            self.COLLECTION_AI_COUNTERFACTUAL,
            self.COLLECTION_AI_COUNTERFACTUAL_SCENARIOS,
            self.COLLECTION_AI_ANOMALY,
            self.COLLECTION_AI_ANOMALY_DETECTED,
            self.COLLECTION_AI_PHASE,
            self.COLLECTION_AI_PHASE_HISTORY,
            self.COLLECTION_AI_PHASE_TRANSITIONS,
            self.COLLECTION_AI_CLUSTER,
            self.COLLECTION_AI_CLUSTER_RESULTS,
            self.COLLECTION_AI_CLUSTER_ASSIGNMENTS,
            self.COLLECTION_AI_DISTILLATION,
            self.COLLECTION_AI_DISTILLATION_STUDENT,
            self.COLLECTION_AI_CAUSAL,
            self.COLLECTION_AI_CAUSAL_EDGES,
            self.COLLECTION_AI_FEEDBACK,
            self.COLLECTION_AI_FEEDBACK_CORRECTIONS,
            self.COLLECTION_AI_FEEDBACK_LEARNINGS,
            # Self-Correction Collections
            self.COLLECTION_AI_ROOT_CAUSES,
            self.COLLECTION_AI_CORRECTIONS,
            self.COLLECTION_AI_EVOLUTIONS,
            self.COLLECTION_AI_COMPONENT_PERFORMANCE,
            self.COLLECTION_AI_RULE_EVOLUTION
        ]
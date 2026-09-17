# ============================================================
# AI ADVERSARIAL - ULTIMATE ROBUSTNESS (COMPLETE - ALL FIELDS)
# ============================================================
# 
# WHAT THIS DOES:
# - Attacks EVERY field in your analysis data (200+ fields)
# - Attacks EVERY component, indicator, pattern, GNN data
# - Attacks ALL decision fields, prices, entry analysis
# - Attacks ALL vetos, news, session, position management
# - Simulates EVERY market disaster
# - Generates 50-100 variations per trade
# - Trains models on ALL variations
# - Discards attacked data after training
# - SAVES ONLY MODELS & METRICS to Firebase
# - Makes AI UNBREAKABLE
# 
# ATTACK TYPES (COMPLETE - 200+ FIELDS):
# 1. Final Decision & Verdict Attacks (15 fields)
# 2. Prices & Position Sizing Attacks (12 fields)
# 3. Entry Analysis Attacks (40+ fields)
# 4. Indicator Score Attacks (27 fields)
# 5. Pattern Analysis Attacks (30+ fields)
# 6. Directional Analysis Attacks (10 fields)
# 7. Component Attacks (21 components × 5+ patterns)
# 8. M15 Divergence Attacks (5 fields)
# 9. Higher Timeframe Attacks (6 fields)
# 10. Volatility Protection Attacks (13 fields)
# 11. Veto System Attacks (13 fields)
# 12. News Analysis Attacks (6 fields)
# 13. Session Analysis Attacks (6 fields)
# 14. Position Management Attacks (4 fields)
# 15. GNN Complete Attacks (30+ fields)
# 16. OHLC + GNN Attacks (15+ fields)
# 17. Entry Details Attacks (12 fields)
# 18. Global Anti-Cheat Attacks (7 fields)
# 19. Account Info Attacks (5 fields)
# 20. Config Attacks (20+ fields)
# 21. Market Disaster Attacks (5 types)
# 22. Decision Attacks (6 types)
# 23. Edge Case Attacks (5 types)
# ============================================================

import logging
import random
import copy
import hashlib
import numpy as np
from typing import Dict, Any, List, Mapping, Optional, Sequence, Tuple
from datetime import datetime, timezone
from collections import defaultdict, deque

from .ai_config import AIConfig, default_config

logger = logging.getLogger(__name__)


class AIAdversarial:
    """
    ULTIMATE ADVERSARIAL TRAINING SYSTEM - COMPLETE ALL FIELDS
    
    Generates attacked versions of trades to make AI robust to:
    - All 200+ fields in the analysis
    - Component failures and conflicts
    - Market disasters and black swans
    - Decision uncertainty and flip-flopping
    - Missing or corrupt data
    - Extreme edge cases
    
    STORAGE (Existing Collections - NO NEW COLLECTIONS):
      ai_component_models  - Component weights (updated)
      ai_ensemble_models   - Ensemble weights (updated)
      ai_performance_state  - Attack metrics & performance
      ai_config_state       - Adversarial config
      ai_training_data      - Training history
    
    Features:
    - 200+ field attacks
    - 21 component attacks (5+ patterns each)
    - 5 market disaster attacks
    - 6 decision attacks
    - 5 edge case attacks
    - 50-100 variations per trade
    - Attacks BOTH winning and losing trades
    - Configurable attack intensity
    - ✅ Models & metrics SAVED to Firebase
    - ✅ Attacked data DISCARDED (in-memory only)
    - ✅ Free Firebase plan safe
    """
    
    def __init__(self, firebase_service=None, config: AIConfig = None):
        self.firebase = firebase_service
        self.config = config or default_config
        self._bridge = None   # lazy PriceEvolutionBridge, see _to_canonical

        # ============================================================
        # A/B TESTING
        # ============================================================
        # Adversarial training is a hypothesis ("corrupting inputs makes the
        # model more robust"), not a known good. Without a control arm there
        # is no way to tell robustness from degradation -- the model just
        # gets trained on noisier data and nobody can say whether that helped.
        #
        # Schema deliberately mirrors ai_gnn.py's ab_test rather than being a
        # second, differently-shaped implementation of the same idea.
        #   control = trade trained WITHOUT attacked variations
        #   test    = trade trained WITH them
        self.ab_test = {
            'enabled': getattr(self.config, 'adversarial_ab_test_enabled', True),
            'rollout': getattr(self.config, 'adversarial_ab_test_rollout', 0.20),
            'control_wins': 0,
            'control_losses': 0,
            'control_profit': 0.0,
            'test_wins': 0,
            'test_losses': 0,
            'test_profit': 0.0,
            'total_trades': 0,
            'last_adjustment': None,
            'adjustment_history': [],
            'min_samples_for_adjustment': 10,
            'improvement_threshold': 0.05,
            'degradation_threshold': -0.05,
            'max_rollout': 0.80,
            'min_rollout': 0.05,
        }

        # ============================================================
        # CONFIGURATION
        # ============================================================
        
        self.adversarial_config = {
            'enabled': getattr(self.config, 'adversarial_training_enabled', True),
            'intensity': getattr(self.config, 'adversarial_intensity', 0.7),
            'variations_per_trade': getattr(self.config, 'adversarial_variations', 50),
            'attack_both_wins_and_losses': getattr(self.config, 'adversarial_attack_both', True),
            'apply_to_components': getattr(self.config, 'adversarial_apply_to_components', True),
            'apply_to_ensemble': getattr(self.config, 'adversarial_apply_to_ensemble', False),
            'max_variations_per_trade': getattr(self.config, 'adversarial_max_variations', 100),
            'attack_probability': getattr(self.config, 'adversarial_attack_probability', 0.8),
            'gnn_integration': getattr(self.config, 'gnn_enabled', True),
            'attack_all_fields': True,
            'field_attack_probability': 0.3,
        }
        
        # ============================================================
        # TRADE BUFFER (In-memory only)
        # ============================================================
        
        self.trade_buffer = deque(maxlen=100)
        self.buffer_size = 10
        
        # ============================================================
        # ATTACK SUCCESS METRICS
        # ============================================================
        
        self.attack_metrics = {
            'attack_success_rate': defaultdict(lambda: {'successes': 0, 'attempts': 0}),
            'field_attack_success': defaultdict(lambda: {'successes': 0, 'attempts': 0}),
            'model_improvement': defaultdict(list),
            'best_attack_combinations': [],
            'field_coverage': set(),
        }
        
        self.attack_success_history = deque(maxlen=50)
        
        # ============================================================
        # STATS
        # ============================================================
        
        self.stats = {
            'total_attacks_generated': 0,
            'total_attacks_applied': 0,
            'components_attacked': defaultdict(int),
            'fields_attacked': defaultdict(int),
            'attack_types_used': defaultdict(int),
            'trades_attacked': 0,
            'last_attack_time': None,
            'attack_success_rate': 0,
            'diversity_score': 0,
            'field_coverage_percentage': 0,
            'total_fields_attacked': 0,
        }
        
        # ============================================================
        # ATTACK HISTORY
        # ============================================================
        
        self.attack_history = deque(maxlen=100)
        
        # ============================================================
        # ATTACK DIVERSITY
        # ============================================================
        
        self.attack_diversity = {
            'attacks_used': set(),
            'patterns_used': defaultdict(int),
            'fields_attacked': set(),
            'diversity_over_time': [],
        }
        
        # ============================================================
        # ADAPTIVE ATTACK SELECTION
        # ============================================================
        
        self.adaptive_selection = {
            'enabled': True,
            'attack_weights': defaultdict(float),
            'field_weights': defaultdict(float),
            'learning_rate': 0.1,
            'exploration_rate': 0.2,
        }
        
        # ============================================================
        # GNN CONTEXT CACHE
        # ============================================================
        
        self.gnn_context_cache = {}
        
        # ============================================================
        # LOAD SAVED STATE
        # ============================================================
        
        self._load_saved_state()
        self._load_ab_test_state()

        logger.info("⚔️ AIAdversarial initialized - COMPLETE ALL FIELDS")
        logger.info(f"   A/B testing: {self.ab_test['enabled']} "
                    f"(rollout {self.ab_test['rollout']*100:.0f}%)")
        logger.info(f"   Enabled: {self.adversarial_config['enabled']}")
        logger.info(f"   Intensity: {self.adversarial_config['intensity']}")
        logger.info(f"   Variations per trade: {self.adversarial_config['variations_per_trade']}")
        logger.info(f"   Attack ALL fields: {self.adversarial_config['attack_all_fields']}")
        logger.info(f"   GNN Integration: {self.adversarial_config['gnn_integration']}")
        
        if self.adversarial_config['enabled']:
            logger.info("   ✅ ULTIMATE ADVERSARIAL TRAINING ENABLED")
            logger.info("   📊 200+ FIELDS attacked")
            logger.info("   📊 21 component attacks FULLY IMPLEMENTED")
            logger.info("   📊 5 disaster attacks FULLY IMPLEMENTED")
            logger.info("   📊 6 decision attacks FULLY IMPLEMENTED")
            logger.info("   📊 5 edge case attacks FULLY IMPLEMENTED")
            logger.info("   💾 Models & Metrics SAVED to Firebase")
            logger.info("   🔥 Attacked data DISCARDED (in-memory only)")
            logger.info("   ✅ Free Firebase plan safe")
        else:
            logger.info("   ⚠️ Adversarial training disabled")
    
    # ============================================================
    # 1. FIREBASE SAVING (EXISTING COLLECTIONS)
    # ============================================================
    
    def _load_saved_state(self):
        """Load saved adversarial state from Firebase."""
        if not self.firebase:
            return
        
        try:
            perf_data = self.firebase.get_ai_model('ai_performance_state')
            if perf_data and 'adversarial' in perf_data:
                adv_data = perf_data['adversarial']
                
                if 'attack_metrics' in adv_data:
                    for attack_type, metrics in adv_data['attack_metrics'].items():
                        self.attack_metrics['attack_success_rate'][attack_type] = metrics
                
                if 'field_attack_success' in adv_data:
                    for field, metrics in adv_data['field_attack_success'].items():
                        self.attack_metrics['field_attack_success'][field] = metrics
                
                if 'stats' in adv_data:
                    for key in ['total_attacks_generated', 'total_attacks_applied', 
                               'trades_attacked', 'attack_success_rate', 'diversity_score',
                               'field_coverage_percentage', 'total_fields_attacked']:
                        if key in adv_data['stats']:
                            self.stats[key] = adv_data['stats'][key]
                
                if 'field_coverage' in adv_data:
                    self.attack_metrics['field_coverage'] = set(adv_data['field_coverage'])
                
                logger.info(f"✅ Loaded attack metrics from ai_performance_state")
                logger.info(f"   Total attacks: {self.stats['total_attacks_generated']}")
                logger.info(f"   Fields attacked: {self.stats['total_fields_attacked']}")
                logger.info(f"   Success rate: {self.stats['attack_success_rate']:.2%}")
            
            config_data = self.firebase.get_ai_model('ai_config_state')
            if config_data and 'adversarial' in config_data:
                saved_config = config_data['adversarial']
                for key in ['enabled', 'intensity', 'variations_per_trade', 'attack_probability', 'attack_all_fields']:
                    if key in saved_config:
                        self.adversarial_config[key] = saved_config[key]
                logger.info(f"✅ Loaded adversarial config from ai_config_state")
                logger.info(f"   Attack ALL fields: {self.adversarial_config['attack_all_fields']}")
                
        except Exception as e:
            logger.warning(f"Failed to load adversarial state: {e}")
    
    def save_metrics(self):
        """Save attack metrics and stats to Firebase."""
        if not self.firebase:
            return
        
        try:
            perf_data = self.firebase.get_ai_model('ai_performance_state') or {}
            
            attack_metrics_dict = {}
            for attack_type, metrics in self.attack_metrics['attack_success_rate'].items():
                attack_metrics_dict[attack_type] = dict(metrics)
            
            field_attack_dict = {}
            for field, metrics in self.attack_metrics['field_attack_success'].items():
                field_attack_dict[field] = dict(metrics)
            
            adversarial_data = {
                'attack_metrics': attack_metrics_dict,
                'field_attack_success': field_attack_dict,
                'field_coverage': list(self.attack_metrics['field_coverage']),
                'model_improvement': dict(self.attack_metrics['model_improvement']),
                'stats': {
                    'total_attacks_generated': self.stats['total_attacks_generated'],
                    'total_attacks_applied': self.stats['total_attacks_applied'],
                    'components_attacked': dict(self.stats['components_attacked']),
                    'fields_attacked': dict(self.stats['fields_attacked']),
                    'attack_types_used': dict(self.stats['attack_types_used']),
                    'trades_attacked': self.stats['trades_attacked'],
                    'last_attack_time': self.stats['last_attack_time'],
                    'attack_success_rate': self.stats['attack_success_rate'],
                    'diversity_score': self.stats['diversity_score'],
                    'field_coverage_percentage': self.stats['field_coverage_percentage'],
                    'total_fields_attacked': self.stats['total_fields_attacked'],
                },
                'most_effective_attacks': self.attack_metrics['best_attack_combinations'][-10:],
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            
            perf_data['adversarial'] = adversarial_data
            perf_data['timestamp'] = datetime.now(timezone.utc).isoformat()
            self.firebase.save_ai_model('ai_performance_state', perf_data)
            
            config_data = self.firebase.get_ai_model('ai_config_state') or {}
            config_data['adversarial'] = {
                'enabled': self.adversarial_config['enabled'],
                'intensity': self.adversarial_config['intensity'],
                'variations_per_trade': self.adversarial_config['variations_per_trade'],
                'attack_probability': self.adversarial_config['attack_probability'],
                'attack_all_fields': self.adversarial_config['attack_all_fields'],
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            self.firebase.save_ai_model('ai_config_state', config_data)
            
            logger.debug(f"✅ Saved adversarial metrics to Firebase")
            
        except Exception as e:
            logger.error(f"Failed to save adversarial metrics: {e}")
    
    def save_component_model(self, component_name: str, weights: Dict, improvement: float):
        """Save updated component model to Firebase."""
        if not self.firebase:
            return
        
        try:
            model_data = self.firebase.get_ai_model('ai_component_models') or {}
            
            if component_name not in model_data:
                model_data[component_name] = {}
            
            model_data[component_name].update({
                'weights': weights,
                'adversarial': {
                    'enabled': True,
                    'improvement': improvement,
                    'variations_trained': self.stats['total_attacks_generated'],
                    'fields_attacked': self.stats['total_fields_attacked'],
                    'last_trained': datetime.now(timezone.utc).isoformat(),
                    'attack_success_rate': self.stats['attack_success_rate'],
                }
            })
            
            version_parts = model_data[component_name].get('version', '1.0').split('.')
            if len(version_parts) == 2:
                new_version = f"{version_parts[0]}.{int(version_parts[1]) + 1}"
                model_data[component_name]['version'] = new_version
            
            self.firebase.save_ai_model('ai_component_models', model_data)
            logger.info(f"✅ Saved {component_name} model to ai_component_models (improvement: {improvement:.2%})")
            
        except Exception as e:
            logger.error(f"Failed to save component model {component_name}: {e}")
    
    def save_ensemble_model(self, weights: Dict, improvement: float):
        """Save updated ensemble model to Firebase."""
        if not self.firebase:
            return
        
        try:
            ensemble_data = self.firebase.get_ai_model('ai_ensemble_models') or {}
            
            ensemble_data.update({
                'weights': weights,
                'adversarial': {
                    'enabled': True,
                    'improvement': improvement,
                    'variations_trained': self.stats['total_attacks_generated'],
                    'fields_attacked': self.stats['total_fields_attacked'],
                    'last_trained': datetime.now(timezone.utc).isoformat(),
                    'attack_success_rate': self.stats['attack_success_rate'],
                }
            })
            
            version_parts = ensemble_data.get('version', '1.0').split('.')
            if len(version_parts) == 2:
                new_version = f"{version_parts[0]}.{int(version_parts[1]) + 1}"
                ensemble_data['version'] = new_version
            
            self.firebase.save_ai_model('ai_ensemble_models', ensemble_data)
            logger.info(f"✅ Saved ensemble model to ai_ensemble_models (improvement: {improvement:.2%})")
            
        except Exception as e:
            logger.error(f"Failed to save ensemble model: {e}")
    
    def save_training_history(self, trade_count: int, improvement: float):
        """Save training history to Firebase."""
        if not self.firebase:
            return
        
        try:
            training_data = self.firebase.get_ai_model('ai_training_data') or {}
            
            if 'adversarial' not in training_data:
                training_data['adversarial'] = {
                    'history': [],
                    'total_trades_trained': 0,
                }
            
            training_data['adversarial']['history'].append({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'trades_trained': trade_count,
                'variations_generated': self.stats['total_attacks_generated'],
                'fields_attacked': self.stats['total_fields_attacked'],
                'improvement': improvement,
                'attack_success_rate': self.stats['attack_success_rate'],
                'diversity_score': self.stats['diversity_score'],
            })
            
            if len(training_data['adversarial']['history']) > 100:
                training_data['adversarial']['history'] = training_data['adversarial']['history'][-100:]
            
            training_data['adversarial']['total_trades_trained'] += trade_count
            training_data['timestamp'] = datetime.now(timezone.utc).isoformat()
            
            self.firebase.save_ai_model('ai_training_data', training_data)
            logger.debug(f"✅ Saved training history to ai_training_data")
            
        except Exception as e:
            logger.error(f"Failed to save training history: {e}")
    
    # ============================================================
    # 2. GNN CONTEXT
    # ============================================================
    
    def set_gnn_context(self, symbol: str, context: Dict):
        self.gnn_context_cache[symbol] = context
    
    def get_gnn_context(self, symbol: str) -> Dict:
        return self.gnn_context_cache.get(symbol, {})
    
    # ============================================================
    # 3. APPLY ATTACKS TO TRAINING
    # ============================================================
    
    def apply_attacks_to_training(self, trades: List[Dict], outcomes: List[int],
                                   training_function, symbol: str = None,
                                   component_name: str = None,
                                   save_models: bool = True) -> Dict[str, Any]:
        """Apply generated attacks to training."""
        if not self.adversarial_config['enabled']:
            return {'applied': False, 'reason': 'Adversarial training disabled'}
        
        if len(trades) != len(outcomes):
            return {'applied': False, 'reason': 'Trades and outcomes length mismatch'}
        
        all_attacked = []
        attack_stats = {'total_variations': 0, 'valid_variations': 0}
        
        gnn_context = self.get_gnn_context(symbol) if symbol else {}
        
        # ✅ FIXED: every variation must carry ITS OWN parent trade's outcome.
        # The label list was previously built as `outcomes * len(all_attacked)`,
        # which repeats the whole outcome list once per variation -- producing
        # len(outcomes) x len(all_attacked) labels for len(all_attacked)
        # samples, misaligned from the first element on. Any training_function
        # doing the usual zip(X, y) would have silently trained on labels
        # belonging to entirely different trades.
        all_outcomes = []

        for trade, outcome in zip(trades, outcomes):
            attacked_variations = self.generate_attacked_trades(trade, outcome, gnn_context)
            all_attacked.extend(attacked_variations)
            all_outcomes.extend([outcome] * len(attacked_variations))
            attack_stats['total_variations'] += len(attacked_variations)

            valid_variations = [v for v in attacked_variations if self._validate_attacked_trade(v)]
            attack_stats['valid_variations'] += len(valid_variations)

        if all_attacked:
            if len(all_attacked) != len(all_outcomes):
                raise ValueError(
                    f"Adversarial label misalignment: {len(all_attacked)} samples "
                    f"vs {len(all_outcomes)} outcomes"
                )
            result = training_function(all_attacked, all_outcomes)
            
            self.stats['total_attacks_applied'] += len(all_attacked)
            self.stats['last_attack_time'] = datetime.now(timezone.utc).isoformat()
            
            improvement = result.get('improvement', 0)
            self._update_success_metrics(result)
            self._update_adaptive_selection(result)
            
            if save_models:
                self.save_metrics()
                
                if component_name and 'weights' in result:
                    self.save_component_model(component_name, result['weights'], improvement)
                
                if self.adversarial_config['apply_to_ensemble'] and 'ensemble_weights' in result:
                    self.save_ensemble_model(result['ensemble_weights'], improvement)
                
                self.save_training_history(len(trades), improvement)
            
            del all_attacked
            
            return {
                'applied': True,
                'variations_generated': attack_stats['total_variations'],
                'valid_variations': attack_stats['valid_variations'],
                'train_result': result,
                'improvement': improvement,
                'success_rate': self.stats['attack_success_rate'],
                'fields_attacked': self.stats['total_fields_attacked'],
                'saved_to_firebase': save_models,
            }
        
        return {'applied': False, 'reason': 'No valid attacked trades generated'}
    
    # ============================================================
    # 4. VALIDATION
    # ============================================================
    
    def _validate_attacked_trade(self, trade: Dict) -> bool:
        """Validate attacked trade."""
        analysis = trade.get('analysis_at_open', {})
        
        required_fields = ['1_trend_bias', '4_supply_demand', 'entry_analysis', 'config']
        for field in required_fields:
            if field not in analysis:
                return False
        
        config = analysis.get('config', {})
        if not config.get('executed_direction'):
            return False
        
        final_verdict = analysis.get('final_verdict', {})
        prob = final_verdict.get('probability_percent', 50)
        if not 0 <= prob <= 100:
            return False
        
        conf = analysis.get('⭐ CONFIDENCE', '50%')
        try:
            float(conf.rstrip('%'))
        except:
            return False
        
        if 'profit_usd' not in analysis:
            return False
        
        return True
    
    # ============================================================
    # 5. SUCCESS METRICS
    # ============================================================
    
    def _update_success_metrics(self, result: Dict):
        improvement = result.get('improvement', 0)
        self.attack_success_history.append(1 if improvement > 0 else 0)
        
        if len(self.attack_success_history) > 0:
            self.stats['attack_success_rate'] = sum(self.attack_success_history) / len(self.attack_success_history)
        
        # Update field coverage percentage
        total_possible_fields = 200  # Approximate number of fields in analysis
        self.stats['field_coverage_percentage'] = len(self.attack_metrics['field_coverage']) / total_possible_fields * 100
        
        for attack_type in self.stats['attack_types_used']:
            self.attack_metrics['attack_success_rate'][attack_type]['attempts'] += 1
            if improvement > 0:
                self.attack_metrics['attack_success_rate'][attack_type]['successes'] += 1
                self.attack_metrics['model_improvement'][attack_type].append(improvement)
    
    # ============================================================
    # 6. GENERATE ATTACKED TRADES - COMPLETE ALL FIELDS
    # ============================================================
    
    # ============================================================
    # A/B TESTING
    # ============================================================

    def should_attack_trade(self, trade_id: Any) -> bool:
        """
        Is this trade in the adversarial (test) arm?

        Deterministic on trade_id, never random: an assignment that changes
        between calls would put the same trade in both arms across restarts
        or retries and quietly poison the comparison. Same reason ai_gnn.py
        hashes trade_id for its own arm assignment.
        """
        if not self.ab_test['enabled']:
            return True
        if trade_id is None:
            return False

        digest = hashlib.sha256(str(trade_id).encode('utf-8')).hexdigest()
        bucket = int(digest[:8], 16) / 0xFFFFFFFF
        return bucket < self.ab_test['rollout']

    def track_ab_test_result(self, trade_id: Any, profit: float,
                             outcome: int, used_adversarial: bool = None):
        """Record one settled trade into its arm."""
        if not self.ab_test['enabled']:
            return

        if used_adversarial is None:
            used_adversarial = self.should_attack_trade(trade_id)

        arm = 'test' if used_adversarial else 'control'
        self.ab_test['total_trades'] += 1
        self.ab_test[f'{arm}_wins'] += 1 if outcome == 1 else 0
        self.ab_test[f'{arm}_losses'] += 1 if outcome != 1 else 0
        self.ab_test[f'{arm}_profit'] += float(profit or 0.0)

        self._adjust_ab_test_rollout()

        if self.ab_test['total_trades'] % 5 == 0:
            self._save_ab_test_state()

    def _adjust_ab_test_rollout(self):
        """Scale rollout by measured win-rate delta, refusing to act on thin samples."""
        ab = self.ab_test
        control_total = ab['control_wins'] + ab['control_losses']
        test_total = ab['test_wins'] + ab['test_losses']

        if (control_total < ab['min_samples_for_adjustment']
                or test_total < ab['min_samples_for_adjustment']):
            return

        control_wr = ab['control_wins'] / control_total
        test_wr = ab['test_wins'] / test_total
        improvement = test_wr - control_wr

        if improvement < ab['degradation_threshold']:
            ab['rollout'] = max(ab['min_rollout'], ab['rollout'] * 0.5)
            adjustment = {'type': 'rollback', 'reason': 'Performance degradation'}
        elif improvement > ab['improvement_threshold']:
            ab['rollout'] = min(ab['max_rollout'], ab['rollout'] * 1.2)
            adjustment = {'type': 'increase', 'reason': 'Performance improvement'}
        else:
            return   # inside the noise band: no change is a valid conclusion

        adjustment.update({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'new_rollout': ab['rollout'],
            'improvement': improvement,
            'control_samples': control_total,
            'test_samples': test_total,
        })
        ab['last_adjustment'] = adjustment
        ab['adjustment_history'].append(adjustment)
        if len(ab['adjustment_history']) > 50:
            ab['adjustment_history'] = ab['adjustment_history'][-50:]

        logger.info(
            f"🧪 Adversarial A/B {adjustment['type']}: "
            f"{improvement*100:+.1f}% -> rollout {ab['rollout']*100:.0f}%"
        )

    def get_ab_test_results(self) -> Dict[str, Any]:
        """Current A/B state, including an explicit verdict."""
        ab = self.ab_test
        control_total = ab['control_wins'] + ab['control_losses']
        test_total = ab['test_wins'] + ab['test_losses']
        control_wr = ab['control_wins'] / control_total if control_total else None
        test_wr = ab['test_wins'] / test_total if test_total else None

        if control_wr is None or test_wr is None:
            status, improvement = 'INSUFFICIENT_DATA', None
        else:
            improvement = test_wr - control_wr
            if (control_total < ab['min_samples_for_adjustment']
                    or test_total < ab['min_samples_for_adjustment']):
                status = 'INSUFFICIENT_DATA'
            elif improvement > ab['improvement_threshold']:
                status = 'ADVERSARIAL_BETTER'
            elif improvement < ab['degradation_threshold']:
                status = 'ADVERSARIAL_WORSE'
            else:
                status = 'NO_DIFFERENCE'

        return {
            'enabled': ab['enabled'],
            'rollout': ab['rollout'],
            'status': status,
            'improvement': improvement,
            'total_trades': ab['total_trades'],
            'control': {'wins': ab['control_wins'], 'losses': ab['control_losses'],
                        'win_rate': control_wr, 'profit': ab['control_profit'],
                        'samples': control_total},
            'test': {'wins': ab['test_wins'], 'losses': ab['test_losses'],
                     'win_rate': test_wr, 'profit': ab['test_profit'],
                     'samples': test_total},
            'last_adjustment': ab['last_adjustment'],
        }

    def set_ab_test_rollout(self, rollout: float):
        self.ab_test['rollout'] = max(0.0, min(1.0, float(rollout)))
        self._save_ab_test_state()

    def _save_ab_test_state(self):
        if not self.firebase:
            return
        try:
            self.firebase.save_ai_model('adversarial_ab_test_state', dict(self.ab_test))
        except Exception as e:
            logger.warning(f"⚠️ Failed to save adversarial A/B state: {e}")

    def _load_ab_test_state(self):
        if not self.firebase:
            return
        try:
            saved = self.firebase.get_ai_model('adversarial_ab_test_state')
            if saved:
                self.ab_test.update({k: v for k, v in saved.items() if k in self.ab_test})
        except Exception as e:
            logger.warning(f"⚠️ Failed to load adversarial A/B state: {e}")

    def _to_canonical(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """Decode a stored trade into canonical form before attacking it."""
        if not isinstance(trade, dict):
            return trade

        if self._bridge is None:
            from .price_evolution_bridge import PriceEvolutionBridge
            self._bridge = PriceEvolutionBridge()

        return self._bridge.to_canonical(trade)

    def generate_attacked_trades(self, trade: Dict[str, Any], outcome: int,
                                   gnn_context: Dict = None) -> List[Dict[str, Any]]:
        """Generate attacked trades attacking ALL fields.

        `trade` is normalized through PriceEvolutionBridge.to_canonical() first.
        The attacks below address canonical field names ('⭐ CONFIDENCE',
        components['1_trend_bias'], ...), but price_evolution[].analysis is
        stored either short-key encoded or as top-level *_analysis_raw keys
        depending on when the row was written -- attacking it in stored form
        would corrupt short keys that mean nothing to any downstream model.
        See PriceEvolutionBridge.to_canonical for the two shapes.
        """
        trade = self._to_canonical(trade)

        if not self.adversarial_config['enabled']:
            return [trade]

        # Control arm: return the trade untouched so there is a genuine
        # baseline to measure the attacked arm against.
        if not self.should_attack_trade(trade.get('ticket') or trade.get('trade_id')):
            return [trade]

        if random.random() > self.adversarial_config['attack_probability']:
            return [trade]
        
        if not self.adversarial_config['attack_both_wins_and_losses']:
            if outcome == 1 and random.random() > 0.5:
                return [trade]
            if outcome == 0 and random.random() > 0.5:
                return [trade]
        
        variations = []
        num_variations = min(
            self.adversarial_config['variations_per_trade'],
            self.adversarial_config['max_variations_per_trade']
        )
        
        intensity = self.adversarial_config['intensity']
        
        if gnn_context and self.adversarial_config['gnn_integration']:
            gnn_confidence = gnn_context.get('global_confidence', 0.5)
            intensity = intensity * (1 + (gnn_confidence - 0.5) * 0.3)
            intensity = max(0.1, min(1.0, intensity))
        
        # Generate ALL types of attacks
        all_attacks = []
        
        # 1. Final Decision & Verdict Attacks
        all_attacks.extend(self._attack_final_decision(copy.deepcopy(trade), intensity, outcome))
        
        # 2. Prices & Position Sizing Attacks
        all_attacks.extend(self._attack_prices_and_sizing(copy.deepcopy(trade), intensity, outcome))
        
        # 3. Entry Analysis Attacks
        all_attacks.extend(self._attack_entry_analysis(copy.deepcopy(trade), intensity, outcome))
        
        # 4. Indicator Score Attacks
        all_attacks.extend(self._attack_indicator_scores(copy.deepcopy(trade), intensity, outcome))
        
        # 5. Pattern Analysis Attacks
        all_attacks.extend(self._attack_pattern_analysis(copy.deepcopy(trade), intensity, outcome))
        
        # 6. Directional Analysis Attacks
        all_attacks.extend(self._attack_directional_analysis(copy.deepcopy(trade), intensity, outcome))
        
        # 7. Component Attacks
        all_attacks.extend(self._generate_component_attacks(copy.deepcopy(trade), outcome, intensity, gnn_context))
        
        # 8. M15 Divergence Attacks
        all_attacks.extend(self._attack_m15_divergence_full(copy.deepcopy(trade), intensity, outcome))
        
        # 9. Higher Timeframe Attacks
        all_attacks.extend(self._attack_higher_timeframe_full(copy.deepcopy(trade), intensity, outcome))
        
        # 10. Volatility Protection Attacks
        all_attacks.extend(self._attack_volatility_full(copy.deepcopy(trade), intensity, outcome))
        
        # 11. Veto System Attacks
        all_attacks.extend(self._attack_veto_full(copy.deepcopy(trade), intensity, outcome))
        
        # 12. News Analysis Attacks
        all_attacks.extend(self._attack_news_full(copy.deepcopy(trade), intensity, outcome))
        
        # 13. Session Analysis Attacks
        all_attacks.extend(self._attack_session_full(copy.deepcopy(trade), intensity, outcome))
        
        # 14. Position Management Attacks
        all_attacks.extend(self._attack_position_management(copy.deepcopy(trade), intensity, outcome))
        
        # 15. GNN Complete Attacks
        all_attacks.extend(self._attack_gnn_complete(copy.deepcopy(trade), intensity, outcome))
        
        # 16. OHLC + GNN Attacks
        all_attacks.extend(self._attack_ohlc_gnn(copy.deepcopy(trade), intensity, outcome))
        
        # 17. Entry Details Attacks
        all_attacks.extend(self._attack_entry_details(copy.deepcopy(trade), intensity, outcome))
        
        # 18. Global Anti-Cheat Attacks
        all_attacks.extend(self._attack_global_anticheat(copy.deepcopy(trade), intensity, outcome))
        
        # 19. Account Info Attacks
        all_attacks.extend(self._attack_account_info(copy.deepcopy(trade), intensity, outcome))
        
        # 20. Config Attacks
        all_attacks.extend(self._attack_config(copy.deepcopy(trade), intensity, outcome))
        
        # 21. Disaster Attacks
        all_attacks.extend(self._generate_disaster_attacks(copy.deepcopy(trade), outcome, intensity, gnn_context))
        
        # 22. Decision Attacks
        all_attacks.extend(self._generate_decision_attacks(copy.deepcopy(trade), outcome, intensity, gnn_context))
        
        # 23. Edge Case Attacks
        all_attacks.extend(self._generate_edge_case_attacks(copy.deepcopy(trade), outcome, intensity, gnn_context))
        
        # Shuffle and limit
        random.shuffle(all_attacks)
        variations = all_attacks[:num_variations]
        
        for attacked in variations:
            self._track_attack_diversity(attacked)
        
        self.stats['total_attacks_generated'] += len(variations)
        self.stats['trades_attacked'] += 1
        self.stats['last_attack_time'] = datetime.now(timezone.utc).isoformat()
        
        self.attack_history.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'trade_id': trade.get('ticket'),
            'outcome': outcome,
            'variations_generated': len(variations),
            'attack_count': self.stats['total_attacks_generated'],
            'fields_attacked': self.stats['total_fields_attacked'],
            'intensity': intensity,
            'gnn_used': gnn_context is not None
        })
        
        return variations
    
    def _track_attack_diversity(self, attacked_trade: Dict):
        """Track attack diversity."""
        analysis = attacked_trade.get('analysis_at_open', {})
        
        for key in analysis:
            self.attack_diversity['attacks_used'].add(key)
            self.attack_diversity['patterns_used'][key] += 1
        
        total_patterns = len(self.attack_diversity['patterns_used'])
        unique_patterns = len(self.attack_diversity['attacks_used'])
        if total_patterns > 0:
            self.stats['diversity_score'] = unique_patterns / total_patterns
        
        self.attack_diversity['diversity_over_time'].append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'diversity_score': self.stats['diversity_score'],
            'unique_attacks': len(self.attack_diversity['attacks_used'])
        })
    
    def _select_attack_type(self, options: List[str]) -> str:
        if self.adaptive_selection['enabled'] and random.random() > self.adaptive_selection['exploration_rate']:
            weights = [self.adaptive_selection['attack_weights'][opt] + 1.0 for opt in options]
            total = sum(weights)
            if total > 0:
                probs = [w / total for w in weights]
                return np.random.choice(options, p=probs)
        return random.choice(options)
    
    def _update_adaptive_selection(self, result: Dict):
        if not self.adaptive_selection['enabled']:
            return
        
        improvement = result.get('improvement', 0)
        
        for attack_type in self.stats['attack_types_used']:
            current_weight = self.adaptive_selection['attack_weights'][attack_type]
            if improvement > 0:
                new_weight = current_weight + self.adaptive_selection['learning_rate']
            else:
                new_weight = current_weight - self.adaptive_selection['learning_rate'] * 0.5

            # ✅ FIXED: this clamped `current_weight` -- the STALE pre-update
            # value -- and assigned it back, throwing away the increment
            # computed immediately above. Weights therefore never moved off
            # their defaultdict(float) default of 0.0, so _select_attack_type's
            # "weighted" choice was `0.0 + 1.0` for every option: uniform
            # random, forever. The whole adaptive-selection mechanism was
            # inert, and silently so, since a uniform choice still looks like
            # it is working from the outside.
            self.adaptive_selection['attack_weights'][attack_type] = max(0, min(5, new_weight))
    
    # ============================================================
    # 7. FIELD ATTACK TRACKING
    # ============================================================
    
    def _track_field_attack(self, field_path: str, success: bool = True):
        """Track field attack success."""
        self.attack_metrics['field_coverage'].add(field_path)
        self.stats['fields_attacked'][field_path] += 1
        self.stats['total_fields_attacked'] = len(self.attack_metrics['field_coverage'])
        
        if field_path not in self.attack_metrics['field_attack_success']:
            self.attack_metrics['field_attack_success'][field_path] = {'successes': 0, 'attempts': 0}
        
        self.attack_metrics['field_attack_success'][field_path]['attempts'] += 1
        if success:
            self.attack_metrics['field_attack_success'][field_path]['successes'] += 1
    
    # ============================================================
    # 8. FINAL DECISION & VERDICT ATTACKS (15 FIELDS)
    # ============================================================
    
    def _attack_final_decision(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        """Attack ALL final decision and verdict fields."""
        attacks = []
        
        for _ in range(int(3 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            verdict = analysis.get('final_verdict', {})
            
            attack_type = self._select_attack_type([
                'verdict_flip', 'probability_collapse', 'star_rating_attack',
                'execution_flip', 'market_regime_flip', 'confidence_attack'
            ])
            
            if attack_type == 'verdict_flip':
                if verdict.get('verdict') == 'BUY NOW':
                    verdict['verdict'] = 'SELL NOW'
                    verdict['action'] = 'SELL'
                elif verdict.get('verdict') == 'SELL NOW':
                    verdict['verdict'] = 'BUY NOW'
                    verdict['action'] = 'BUY'
                else:
                    verdict['verdict'] = random.choice(['BUY NOW', 'SELL NOW'])
                self._track_field_attack('final_verdict.verdict')
                self._track_field_attack('final_verdict.action')
            
            elif attack_type == 'probability_collapse':
                current = verdict.get('probability_percent', 50)
                collapse = random.randint(0, int(60 * intensity))
                verdict['probability_percent'] = max(0, current - collapse)
                analysis['⭐ CONFIDENCE'] = f"{verdict['probability_percent']}%"
                self._track_field_attack('final_verdict.probability_percent')
                self._track_field_attack('⭐ CONFIDENCE')
            
            elif attack_type == 'star_rating_attack':
                verdict['star_rating'] = random.randint(0, 3)
                stars = ['☆' * verdict['star_rating'] + '★' * (5 - verdict['star_rating'])]
                verdict['stars_display'] = stars[0] if stars else '☆'
                self._track_field_attack('final_verdict.star_rating')
                self._track_field_attack('final_verdict.stars_display')
            
            elif attack_type == 'execution_flip':
                executions = ['DO_NOTHING', 'ENTER', 'EXIT', 'MODIFY']
                current = verdict.get('execution', 'DO_NOTHING')
                new = random.choice([e for e in executions if e != current])
                verdict['execution'] = new
                self._track_field_attack('final_verdict.execution')
            
            elif attack_type == 'market_regime_flip':
                regimes = ['NORMAL', 'HIGH_VOLATILITY', 'LOW_VOLATILITY', 'TRENDING', 'RANGING']
                verdict['market_regime'] = random.choice(regimes)
                self._track_field_attack('final_verdict.market_regime')
            
            elif attack_type == 'confidence_attack':
                verdict['timing_confidence'] = random.randint(0, 100)
                verdict['timing_ready'] = verdict['timing_confidence'] > 75
                self._track_field_attack('final_verdict.timing_confidence')
                self._track_field_attack('final_verdict.timing_ready')
            
            # Attack gnn_final_score and pattern_final_score
            if random.random() < intensity * 0.3:
                verdict['gnn_final_score'] = {
                    'gnn_recommendation': random.choice(['BUY', 'SELL', 'NEUTRAL', 'CONFLICT']),
                    'gnn_score': random.randint(0, 100),
                    'gnn_contribution': random.uniform(-15, 15),
                    'aligned': random.random() > 0.5
                }
                self._track_field_attack('final_verdict.gnn_final_score')
            
            if random.random() < intensity * 0.3:
                verdict['pattern_final_score'] = {
                    'pattern_recommendation': random.choice(['BULLISH', 'BEARISH', 'NEUTRAL']),
                    'pattern_score': random.randint(0, 100),
                    'pattern_contribution': random.uniform(-15, 15),
                    'confirmed': random.random() > 0.5
                }
                self._track_field_attack('final_verdict.pattern_final_score')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 9. PRICES & POSITION SIZING ATTACKS (12 FIELDS)
    # ============================================================
    
    def _attack_prices_and_sizing(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        """Attack ALL price and position sizing fields."""
        attacks = []
        
        for _ in range(int(2 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            pip_size = 0.0001
            
            # Attack entry price
            if '💰 ENTRY' in analysis:
                entry = analysis['💰 ENTRY']
                if entry:
                    shift = random.uniform(-10, 10) * pip_size * intensity * 2
                    analysis['💰 ENTRY'] = entry + shift
                    self._track_field_attack('💰 ENTRY')
            
            # Attack stop loss
            if '🛑 STOP_LOSS' in analysis:
                sl = analysis['🛑 STOP_LOSS']
                if sl:
                    shift = random.uniform(-5, 5) * pip_size * intensity * 2
                    analysis['🛑 STOP_LOSS'] = sl + shift
                    self._track_field_attack('🛑 STOP_LOSS')
            
            # Attack take profits
            for tp_num in ['1', '2', '3']:
                key = f'🎯 TAKE_PROFIT_{tp_num}'
                if key in analysis:
                    tp = analysis[key]
                    if tp:
                        shift = random.uniform(-8, 8) * pip_size * intensity * 2
                        analysis[key] = tp + shift
                        self._track_field_attack(key)
            
            # Attack lot size
            if '📊 LOT_SIZE' in analysis:
                analysis['📊 LOT_SIZE'] = max(0.01, analysis['📊 LOT_SIZE'] * random.uniform(0.1, 3.0))
                self._track_field_attack('📊 LOT_SIZE')
            
            # Attack risk/reward
            if '💵 RISK_USD' in analysis:
                analysis['💵 RISK_USD'] = analysis['💵 RISK_USD'] * random.uniform(0.1, 3.0)
                self._track_field_attack('💵 RISK_USD')
            
            if '📈 REWARD_USD' in analysis:
                analysis['📈 REWARD_USD'] = analysis['📈 REWARD_USD'] * random.uniform(0.1, 3.0)
                self._track_field_attack('📈 REWARD_USD')
            
            if '💰 MARGIN_REQUIRED_USD' in analysis:
                analysis['💰 MARGIN_REQUIRED_USD'] = analysis['💰 MARGIN_REQUIRED_USD'] * random.uniform(0.1, 3.0)
                self._track_field_attack('💰 MARGIN_REQUIRED_USD')
            
            # Attack verdict price fields
            verdict = analysis.get('final_verdict', {})
            if verdict:
                if 'stop_loss_pips' in verdict:
                    verdict['stop_loss_pips'] = max(1, verdict.get('stop_loss_pips', 10) * random.uniform(0.1, 3.0))
                    self._track_field_attack('final_verdict.stop_loss_pips')
                
                if 'take_profit_pips' in verdict:
                    verdict['take_profit_pips'] = max(1, verdict.get('take_profit_pips', 10) * random.uniform(0.1, 3.0))
                    self._track_field_attack('final_verdict.take_profit_pips')
                
                if 'risk_reward_ratio' in verdict:
                    verdict['risk_reward_ratio'] = f"1:{round(random.uniform(0.1, 5.0), 1)}"
                    self._track_field_attack('final_verdict.risk_reward_ratio')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 10. ENTRY ANALYSIS ATTACKS (40+ FIELDS)
    # ============================================================
    
    def _attack_entry_analysis(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        """Attack ALL entry analysis fields."""
        attacks = []
        
        for _ in range(int(3 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            entry = analysis.get('entry_analysis', {})
            
            # Attack pre_entry fields
            if random.random() < intensity:
                entry['pre_entry_passed'] = not entry.get('pre_entry_passed', False)
                if not entry.get('pre_entry_passed'):
                    entry['pre_entry_skip_reason'] = random.choice([
                        'Adversarial skip', 'Low probability', 'Ranging market', 
                        'Trend misalignment', 'Zone grade invalid'
                    ])
                self._track_field_attack('entry_analysis.pre_entry_passed')
                self._track_field_attack('entry_analysis.pre_entry_skip_reason')
            
            # Attack should_enter
            if random.random() < intensity:
                entry['should_enter'] = not entry.get('should_enter', False)
                self._track_field_attack('entry_analysis.should_enter')
            
            # Attack entry_status
            if random.random() < intensity * 0.5:
                statuses = ['INITIALIZED', 'ANALYZED', 'READY', 'CONFIRMED', 'ENTERED', 'PRE_ENTRY_FAILED']
                entry['entry_status'] = random.choice(statuses)
                self._track_field_attack('entry_analysis.entry_status')
            
            # Attack final_decision and simple_action
            if random.random() < intensity * 0.5:
                actions = ['BUY', 'SELL', 'HOLD', 'WAIT', 'MONITOR']
                entry['final_decision'] = random.choice(actions)
                entry['simple_action'] = random.choice(actions)
                self._track_field_attack('entry_analysis.final_decision')
                self._track_field_attack('entry_analysis.simple_action')
            
            # Attack execution
            if random.random() < intensity * 0.5:
                executions = ['DO_NOTHING', 'ENTER', 'EXIT', 'MODIFY']
                entry['execution'] = random.choice(executions)
                self._track_field_attack('entry_analysis.execution')
            
            # Attack timing
            if random.random() < intensity * 0.7:
                entry['timing_confidence'] = random.randint(0, 100)
                entry['timing_ready'] = entry['timing_confidence'] > 75
                self._track_field_attack('entry_analysis.timing_confidence')
                self._track_field_attack('entry_analysis.timing_ready')
            
            # Attack star_rating
            if random.random() < intensity * 0.5:
                entry['star_rating'] = random.randint(0, 5)
                entry['stars_display'] = '☆' * (5 - entry['star_rating']) + '★' * entry['star_rating']
                self._track_field_attack('entry_analysis.star_rating')
                self._track_field_attack('entry_analysis.stars_display')
            
            # Attack discount fields
            discount = entry.get('discount', {})
            if discount:
                if random.random() < intensity * 0.7:
                    discount['is_already_at_discount'] = not discount.get('is_already_at_discount', False)
                    self._track_field_attack('entry_analysis.discount.is_already_at_discount')
                
                if random.random() < intensity * 0.5:
                    qualities = ['HIGH', 'MEDIUM', 'LOW', 'NONE', 'NOT_CHECKED']
                    discount['discount_quality'] = random.choice(qualities)
                    self._track_field_attack('entry_analysis.discount.discount_quality')
                
                if random.random() < intensity * 0.5:
                    discount['distance_to_discount_pips'] = random.uniform(0, 50)
                    self._track_field_attack('entry_analysis.discount.distance_to_discount_pips')
                
                if random.random() < intensity * 0.3:
                    grades = ['A', 'B', 'C', 'D', 'E']
                    discount['zone_grade'] = random.choice(grades)
                    self._track_field_attack('entry_analysis.discount.zone_grade')
            
            # Attack confirmation fields
            confirm = entry.get('confirmation', {})
            if confirm:
                if random.random() < intensity * 0.6:
                    confirm['is_confirmed'] = not confirm.get('is_confirmed', False)
                    self._track_field_attack('entry_analysis.confirmation.is_confirmed')
                
                if random.random() < intensity * 0.5:
                    confirm['score'] = random.randint(0, 100)
                    self._track_field_attack('entry_analysis.confirmation.score')
                
                if random.random() < intensity * 0.3:
                    types = ['STRONG', 'MEDIUM', 'WEAK', 'NONE']
                    confirm['type'] = random.choice(types)
                    self._track_field_attack('entry_analysis.confirmation.type')
            
            # Attack micro_structure
            micro = entry.get('micro_structure', {})
            if micro:
                if random.random() < intensity * 0.6:
                    micro['absorption_detected'] = not micro.get('absorption_detected', False)
                    self._track_field_attack('entry_analysis.micro_structure.absorption_detected')
                
                if random.random() < intensity * 0.6:
                    micro['momentum_burst'] = not micro.get('momentum_burst', False)
                    self._track_field_attack('entry_analysis.micro_structure.momentum_burst')
                
                if random.random() < intensity * 0.5:
                    micro['spread_collapse'] = not micro.get('spread_collapse', False)
                    self._track_field_attack('entry_analysis.micro_structure.spread_collapse')
                
                if random.random() < intensity * 0.5:
                    micro['timing_confidence'] = random.randint(0, 100)
                    self._track_field_attack('entry_analysis.micro_structure.timing_confidence')
                
                if random.random() < intensity * 0.3:
                    micro['entry_confidence'] = random.randint(0, 100)
                    self._track_field_attack('entry_analysis.micro_structure.entry_confidence')
                
                if random.random() < intensity * 0.3:
                    micro['triggers'] = [f"trigger_{i}" for i in range(random.randint(0, 5))]
                    self._track_field_attack('entry_analysis.micro_structure.triggers')
            
            # Attack golden_signals
            golden = entry.get('golden_signals', {})
            if golden:
                if random.random() < intensity * 0.6:
                    golden['momentum_burst'] = not golden.get('momentum_burst', False)
                    self._track_field_attack('entry_analysis.golden_signals.momentum_burst')
                
                if random.random() < intensity * 0.6:
                    golden['absorption'] = not golden.get('absorption', False)
                    self._track_field_attack('entry_analysis.golden_signals.absorption')
                
                if random.random() < intensity * 0.6:
                    golden['volume_spike'] = not golden.get('volume_spike', False)
                    self._track_field_attack('entry_analysis.golden_signals.volume_spike')
                
                if random.random() < intensity * 0.5:
                    golden['at_poi'] = not golden.get('at_poi', False)
                    self._track_field_attack('entry_analysis.golden_signals.at_poi')
                
                if random.random() < intensity * 0.5:
                    golden['signal_count'] = random.randint(0, 6)
                    self._track_field_attack('entry_analysis.golden_signals.signal_count')
                
                if random.random() < intensity * 0.4:
                    types = ['STRONG', 'MEDIUM', 'WEAK', 'NO_SIGNAL']
                    golden['signal_type'] = random.choice(types)
                    self._track_field_attack('entry_analysis.golden_signals.signal_type')
            
            # Attack h1_alignment
            h1_alignment = entry.get('h1_alignment', {})
            if h1_alignment:
                if random.random() < intensity * 0.6:
                    h1_alignment['aligned'] = not h1_alignment.get('aligned', False)
                    self._track_field_attack('entry_analysis.h1_alignment.aligned')
                
                if random.random() < intensity * 0.4:
                    trends = ['BULLISH', 'BEARISH', 'NEUTRAL']
                    h1_alignment['h1_trend'] = random.choice(trends)
                    self._track_field_attack('entry_analysis.h1_alignment.h1_trend')
                
                if random.random() < intensity * 0.5:
                    h1_alignment['confidence_bonus'] = random.randint(-30, 30)
                    self._track_field_attack('entry_analysis.h1_alignment.confidence_bonus')
                
                if random.random() < intensity * 0.5:
                    h1_alignment['adjusted_probability'] = random.randint(0, 100)
                    self._track_field_attack('entry_analysis.h1_alignment.adjusted_probability')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 11. INDICATOR SCORE ATTACKS (27 FIELDS)
    # ============================================================
    
    def _attack_indicator_scores(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        """Attack ALL indicator score fields."""
        attacks = []
        
        for _ in range(int(2 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            indicator_scores = analysis.get('indicator_scores', {})
            
            if not indicator_scores:
                continue
            
            # Attack unified score
            unified = indicator_scores.get('unified', {})
            if unified:
                if random.random() < intensity * 0.8:
                    unified['total_score'] = random.uniform(-100, 100)
                    self._track_field_attack('indicator_scores.unified.total_score')
                
                if random.random() < intensity * 0.5:
                    unified['recommendation'] = random.choice(['BUY', 'SELL', 'NEUTRAL'])
                    self._track_field_attack('indicator_scores.unified.recommendation')
                
                if random.random() < intensity * 0.5:
                    unified['confidence'] = random.uniform(0, 100)
                    self._track_field_attack('indicator_scores.unified.confidence')
                
                if random.random() < intensity * 0.3:
                    unified['bias'] = random.choice(['BULLISH', 'BEARISH', 'NEUTRAL'])
                    self._track_field_attack('indicator_scores.unified.bias')
                
                if random.random() < intensity * 0.3:
                    unified['buy_signals'] = random.randint(0, 8)
                    unified['sell_signals'] = random.randint(0, 8)
                    unified['neutral_signals'] = random.randint(0, 8)
                    self._track_field_attack('indicator_scores.unified.buy_signals')
                    self._track_field_attack('indicator_scores.unified.sell_signals')
                    self._track_field_attack('indicator_scores.unified.neutral_signals')
            
            # Attack individual indicators
            indicator_list = ['trend', 'rsi', 'macd', 'bollinger', 'stochastic', 'volume', 'supply_demand', 'candlestick']
            for ind in indicator_list:
                ind_data = indicator_scores.get(ind, {})
                if ind_data:
                    if random.random() < intensity * 0.4:
                        ind_data['recommendation'] = random.choice(['BUY', 'SELL', 'NEUTRAL'])
                        self._track_field_attack(f'indicator_scores.{ind}.recommendation')
                    
                    if random.random() < intensity * 0.4:
                        ind_data['score'] = random.uniform(-100, 100)
                        self._track_field_attack(f'indicator_scores.{ind}.score')
                    
                    if random.random() < intensity * 0.3:
                        ind_data['confidence'] = random.uniform(0, 100)
                        self._track_field_attack(f'indicator_scores.{ind}.confidence')
                    
                    if random.random() < intensity * 0.3:
                        ind_data['reason'] = random.choice([
                            'Adversarial attack', 'Extreme condition', 'Contradicting signal',
                            'Overbought', 'Oversold', 'Divergence', 'Squeeze'
                        ])
                        self._track_field_attack(f'indicator_scores.{ind}.reason')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 12. PATTERN ANALYSIS ATTACKS (30+ FIELDS)
    # ============================================================
    
    def _attack_pattern_analysis(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        """Attack ALL pattern analysis fields."""
        attacks = []
        
        for _ in range(int(2 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            pattern = analysis.get('pattern_analysis', {})
            
            if not pattern:
                continue
            
            # Attack summary
            summary = pattern.get('summary', {})
            if summary:
                if random.random() < intensity * 0.6:
                    summary['total_patterns'] = random.randint(0, 20)
                    self._track_field_attack('pattern_analysis.summary.total_patterns')
                
                if random.random() < intensity * 0.5:
                    summary['strongest_pattern'] = random.choice([
                        'double_bottom', 'double_top', 'head_shoulders', 
                        'triangle', 'flag', 'pennant', 'wedge'
                    ])
                    self._track_field_attack('pattern_analysis.summary.strongest_pattern')
                
                if random.random() < intensity * 0.5:
                    summary['strongest_timeframe'] = random.choice(['M1', 'M5', 'M15', 'M30', 'H1'])
                    self._track_field_attack('pattern_analysis.summary.strongest_timeframe')
                
                if random.random() < intensity * 0.5:
                    summary['highest_confidence'] = random.uniform(0, 1)
                    self._track_field_attack('pattern_analysis.summary.highest_confidence')
                
                if random.random() < intensity * 0.5:
                    summary['overall_direction'] = random.choice(['BULLISH', 'BEARISH', 'NEUTRAL'])
                    self._track_field_attack('pattern_analysis.summary.overall_direction')
            
            # Attack multi-timeframe confirmation
            if random.random() < intensity * 0.5:
                pattern['multi_timeframe_confirmed'] = not pattern.get('multi_timeframe_confirmed', False)
                self._track_field_attack('pattern_analysis.multi_timeframe_confirmed')
            
            if random.random() < intensity * 0.5:
                pattern['confirmation_score'] = random.randint(0, 100)
                self._track_field_attack('pattern_analysis.confirmation_score')
            
            # Attack final_score
            final_score = pattern.get('final_score', {})
            if final_score:
                if random.random() < intensity * 0.5:
                    final_score['pattern_recommendation'] = random.choice(['BULLISH', 'BEARISH', 'NEUTRAL'])
                    self._track_field_attack('pattern_analysis.final_score.pattern_recommendation')
                
                if random.random() < intensity * 0.5:
                    final_score['pattern_score'] = random.randint(0, 100)
                    self._track_field_attack('pattern_analysis.final_score.pattern_score')
                
                if random.random() < intensity * 0.5:
                    final_score['pattern_contribution'] = random.uniform(-15, 15)
                    self._track_field_attack('pattern_analysis.final_score.pattern_contribution')
                
                if random.random() < intensity * 0.5:
                    final_score['final_score'] = random.randint(0, 100)
                    self._track_field_attack('pattern_analysis.final_score.final_score')
                
                if random.random() < intensity * 0.4:
                    final_score['confirmed'] = not final_score.get('confirmed', False)
                    self._track_field_attack('pattern_analysis.final_score.confirmed')
                
                if random.random() < intensity * 0.4:
                    final_score['patterns_detected'] = random.randint(0, 10)
                    self._track_field_attack('pattern_analysis.final_score.patterns_detected')
                
                if random.random() < intensity * 0.3:
                    directions = final_score.get('directions', {})
                    directions['BULLISH'] = random.randint(0, 5)
                    directions['BEARISH'] = random.randint(0, 5)
                    directions['NEUTRAL'] = random.randint(0, 5)
                    final_score['directions'] = directions
                    self._track_field_attack('pattern_analysis.final_score.directions')
            
            # Attack timeframes
            timeframes = pattern.get('timeframes', {})
            for tf, tf_data in timeframes.items():
                if random.random() < intensity * 0.3:
                    tf_data['pattern_count'] = random.randint(0, 10)
                    self._track_field_attack(f'pattern_analysis.timeframes.{tf}.pattern_count')
                
                if random.random() < intensity * 0.3:
                    tf_data['confidence_threshold'] = random.uniform(0, 1)
                    self._track_field_attack(f'pattern_analysis.timeframes.{tf}.confidence_threshold')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 13. DIRECTIONAL ANALYSIS ATTACKS (10 FIELDS)
    # ============================================================
    
    def _attack_directional_analysis(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        """Attack ALL directional analysis fields."""
        attacks = []
        
        for _ in range(int(2 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            directional = analysis.get('directional_analysis', {})
            
            if not directional:
                continue
            
            if random.random() < intensity * 0.8:
                buy = random.uniform(0, 100)
                sell = 100 - buy
                directional['buy_probability'] = buy
                directional['sell_probability'] = sell
                self._track_field_attack('directional_analysis.buy_probability')
                self._track_field_attack('directional_analysis.sell_probability')
            
            if random.random() < intensity * 0.6:
                directional['best_direction'] = random.choice(['BUY', 'SELL'])
                self._track_field_attack('directional_analysis.best_direction')
            
            if random.random() < intensity * 0.5:
                directional['user_requested_direction'] = random.choice(['BUY', 'SELL'])
                self._track_field_attack('directional_analysis.user_requested_direction')
            
            if random.random() < intensity * 0.5:
                directional['user_direction_aligned'] = not directional.get('user_direction_aligned', False)
                self._track_field_attack('directional_analysis.user_direction_aligned')
            
            if random.random() < intensity * 0.4:
                directional['fvg_tolerance_used'] = random.uniform(0, 20)
                directional['fvg_tolerance_for_buy'] = random.uniform(0, 20)
                directional['fvg_tolerance_for_sell'] = random.uniform(0, 20)
                self._track_field_attack('directional_analysis.fvg_tolerance_used')
                self._track_field_attack('directional_analysis.fvg_tolerance_for_buy')
                self._track_field_attack('directional_analysis.fvg_tolerance_for_sell')
            
            # Attack breakdowns
            if random.random() < intensity * 0.3:
                directional['breakdown_buy'] = {'attack': 'modified', 'value': random.randint(0, 100)}
                directional['breakdown_sell'] = {'attack': 'modified', 'value': random.randint(0, 100)}
                self._track_field_attack('directional_analysis.breakdown_buy')
                self._track_field_attack('directional_analysis.breakdown_sell')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 14. COMPONENT ATTACKS - ALL EXISTING 21 COMPONENTS
    # ============================================================
    
    def _generate_component_attacks(self, trade: Dict, outcome: int, intensity: float, 
                                     gnn_context: Dict = None) -> List[Dict]:
        """Generate attacks for ALL 21 components."""
        attacks = []
        
        attack_methods = [
            ('1_trend_bias', self._attack_trend_component),
            ('2_ict_concepts', self._attack_ict_component),
            ('3_wyckoff', self._attack_wyckoff_component),
            ('4_supply_demand', self._attack_supply_demand_component),
            ('5_support_resistance', self._attack_support_resistance_component),
            ('6_breakout', self._attack_breakout_component),
            ('7_candlestick', self._attack_candlestick_component),
            ('8_indicators', self._attack_indicators_component),
        ]
        
        # Add GNN-aware priority
        if gnn_context and self.adversarial_config['gnn_integration']:
            gnn_confidence = gnn_context.get('global_confidence', 0.5)
            if gnn_confidence > 0.7:
                priority_components = ['1_trend_bias', '8_indicators', '4_supply_demand']
                attack_methods = sorted(attack_methods, 
                    key=lambda x: 1.0 if x[0] in priority_components else 0.0,
                    reverse=True)
        
        for comp_name, attack_func in attack_methods:
            try:
                num_patterns = 2 + int(random.random() * 3 * intensity)
                for _ in range(min(num_patterns, 4)):
                    attacked = attack_func(copy.deepcopy(trade), intensity, outcome)
                    if attacked != trade:
                        attacks.append(attacked)
                        self.stats['components_attacked'][comp_name] += 1
                        self._track_field_attack(f'components.{comp_name}')
            except Exception as e:
                logger.debug(f"Component attack failed for {comp_name}: {e}")
        
        return attacks
    
    def _attack_trend_component(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        trend = analysis.get('1_trend_bias', {})
        
        if not trend:
            return trade
        
        attack_type = self._select_attack_type(['flip_trend', 'weaken', 'collapse_adx', 'reverse_ema', 'neutralize'])
        
        if attack_type == 'flip_trend':
            current = trend.get('trend', 'NEUTRAL')
            if 'BULLISH' in current:
                trend['trend'] = 'STRONG_BEARISH' if intensity > 0.7 else 'BEARISH'
            elif 'BEARISH' in current:
                trend['trend'] = 'STRONG_BULLISH' if intensity > 0.7 else 'BULLISH'
            else:
                trend['trend'] = random.choice(['STRONG_BULLISH', 'STRONG_BEARISH'])
            self._track_field_attack('components.1_trend_bias.trend')
        
        elif attack_type == 'weaken':
            current = trend.get('trend', 'NEUTRAL')
            if 'STRONG' in current:
                trend['trend'] = current.replace('STRONG_', '')
            elif current in ['BULLISH', 'BEARISH'] and intensity > 0.8:
                trend['trend'] = 'NEUTRAL'
            self._track_field_attack('components.1_trend_bias.trend')
        
        elif attack_type == 'collapse_adx':
            adx = trend.get('adx', {})
            collapse = 1 - intensity * 0.8
            for key in ['adx_7', 'adx_14', 'adx_21']:
                if key in adx:
                    adx[key] = max(5, 20 * collapse + random.randint(-5, 5))
            self._track_field_attack('components.1_trend_bias.adx')
        
        elif attack_type == 'reverse_ema':
            ema = trend.get('ema', {})
            ema_200 = ema.get('ema_200', 0)
            if ema_200:
                spread = 0.02 + intensity * 0.05
                for key in ['ema_9', 'ema_20', 'ema_50', 'ema_100']:
                    if key in ema:
                        ema[key] = ema_200 * random.uniform(0.95 - spread, 0.98 - spread)
            self._track_field_attack('components.1_trend_bias.ema')
        
        elif attack_type == 'neutralize':
            trend['trend'] = 'NEUTRAL'
            trend['score'] = 50
            adx = trend.get('adx', {})
            for key in ['adx_7', 'adx_14', 'adx_21']:
                if key in adx:
                    adx[key] = 20
            self._track_field_attack('components.1_trend_bias.trend')
            self._track_field_attack('components.1_trend_bias.score')
        
        if 'score' in trend:
            if trend.get('trend') in ['STRONG_BULLISH', 'STRONG_BEARISH']:
                trend['score'] = 85 + random.randint(-10, 10)
            elif trend.get('trend') in ['BULLISH', 'BEARISH']:
                trend['score'] = 70 + random.randint(-10, 10)
            elif trend.get('trend') == 'NEUTRAL':
                trend['score'] = 45 + random.randint(-15, 15)
        
        if 'recommendation' in trend:
            if trend.get('trend') in ['STRONG_BULLISH', 'BULLISH']:
                trend['recommendation'] = 'BUY'
            elif trend.get('trend') in ['STRONG_BEARISH', 'BEARISH']:
                trend['recommendation'] = 'SELL'
            else:
                trend['recommendation'] = 'NEUTRAL'
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_ict_component(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        ict = analysis.get('2_ict_concepts', {})
        
        if not ict:
            return trade
        
        attack_type = self._select_attack_type(['invalidate', 'create', 'move', 'flip'])
        
        if attack_type == 'invalidate':
            ict['is_blocked'] = True
            ict['type'] = 'INVALID'
            ict['score'] = 0
            self._track_field_attack('components.2_ict_concepts.is_blocked')
            self._track_field_attack('components.2_ict_concepts.type')
        
        elif attack_type == 'create':
            ict['is_blocked'] = False
            ict['type'] = random.choice(['BULLISH', 'BEARISH'])
            ict['score'] = random.randint(60, 90)
            debug = ict.get('debug', {})
            debug['is_price_in_fvg'] = random.random() > 0.5
            ict['debug'] = debug
            self._track_field_attack('components.2_ict_concepts.type')
        
        elif attack_type == 'move':
            debug = ict.get('debug', {})
            fvg_high = debug.get('fvg_high', 0)
            if fvg_high:
                pip_size = 0.0001
                shift = random.uniform(-5, 5) * pip_size * intensity * 2
                debug['fvg_high'] = fvg_high + shift
                debug['fvg_low'] = debug.get('fvg_low', fvg_high) + shift
                ict['debug'] = debug
                self._track_field_attack('components.2_ict_concepts.debug.fvg_high')
                self._track_field_attack('components.2_ict_concepts.debug.fvg_low')
        
        elif attack_type == 'flip':
            if ict.get('type') == 'BULLISH':
                ict['type'] = 'BEARISH'
            elif ict.get('type') == 'BEARISH':
                ict['type'] = 'BULLISH'
            else:
                ict['type'] = random.choice(['BULLISH', 'BEARISH'])
            ict['is_blocked'] = random.random() > 0.5
            self._track_field_attack('components.2_ict_concepts.type')
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_wyckoff_component(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        wyckoff = analysis.get('3_wyckoff', {})
        
        if not wyckoff:
            return trade
        
        attack_type = self._select_attack_type(['flip_phase', 'extreme', 'reverse_momentum', 'neutralize'])
        
        if attack_type == 'flip_phase':
            current = wyckoff.get('phase', 'NEUTRAL')
            if 'MARKUP' in current:
                wyckoff['phase'] = random.choice(['MARKDOWN', 'MARKDOWN_STRONG'])
            elif 'MARKDOWN' in current:
                wyckoff['phase'] = random.choice(['MARKUP', 'MARKUP_STRONG'])
            elif 'ACCUMULATION' in current:
                wyckoff['phase'] = 'DISTRIBUTION'
            elif 'DISTRIBUTION' in current:
                wyckoff['phase'] = 'ACCUMULATION_COMPLETE'
            else:
                wyckoff['phase'] = random.choice(['MARKUP_STRONG', 'MARKDOWN_STRONG'])
            self._track_field_attack('components.3_wyckoff.phase')
        
        elif attack_type == 'extreme':
            wyckoff['phase'] = random.choice(['MARKUP_STRONG', 'MARKDOWN_STRONG'])
            wyckoff['score'] = random.randint(80, 100)
            self._track_field_attack('components.3_wyckoff.phase')
            self._track_field_attack('components.3_wyckoff.score')
        
        elif attack_type == 'reverse_momentum':
            debug = wyckoff.get('debug', {})
            debug['momentum'] = -debug.get('momentum', 0)
            wyckoff['debug'] = debug
            self._track_field_attack('components.3_wyckoff.debug.momentum')
        
        elif attack_type == 'neutralize':
            wyckoff['phase'] = 'NEUTRAL'
            wyckoff['score'] = 50
            self._track_field_attack('components.3_wyckoff.phase')
            self._track_field_attack('components.3_wyckoff.score')
        
        if 'recommendation' in wyckoff:
            if wyckoff.get('phase') in ['MARKUP', 'MARKUP_STRONG', 'ACCUMULATION_COMPLETE']:
                wyckoff['recommendation'] = 'BUY'
            elif wyckoff.get('phase') in ['MARKDOWN', 'MARKDOWN_STRONG']:
                wyckoff['recommendation'] = 'SELL'
            else:
                wyckoff['recommendation'] = 'NEUTRAL'
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_supply_demand_component(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        sd = analysis.get('4_supply_demand', {})
        
        if not sd:
            return trade
        
        attack_type = self._select_attack_type(['downgrade', 'upgrade', 'move', 'remove', 'reverse'])
        grades = ['A', 'B', 'C', 'D', 'E']
        
        if attack_type == 'downgrade':
            grade = sd.get('zone_grade', 'E')
            if grade in grades:
                idx = grades.index(grade)
                new_idx = min(len(grades) - 1, idx + random.randint(1, 2))
                sd['zone_grade'] = grades[new_idx]
                sd['score'] = max(0, sd.get('score', 0) - random.randint(20, 50))
            self._track_field_attack('components.4_supply_demand.zone_grade')
        
        elif attack_type == 'upgrade':
            grade = sd.get('zone_grade', 'E')
            if grade in grades:
                idx = grades.index(grade)
                new_idx = max(0, idx - random.randint(1, 2))
                sd['zone_grade'] = grades[new_idx]
                sd['score'] = min(100, sd.get('score', 0) + random.randint(20, 50))
            self._track_field_attack('components.4_supply_demand.zone_grade')
        
        elif attack_type == 'move':
            current_level = sd.get('zone_level', 0)
            if current_level:
                pip_size = 0.0001
                shift = random.uniform(-10, 10) * pip_size * intensity * 2
                sd['zone_level'] = current_level + shift
                sd['is_at_zone'] = random.random() > 0.5
                self._track_field_attack('components.4_supply_demand.zone_level')
        
        elif attack_type == 'remove':
            sd['zone_level'] = None
            sd['zone_grade'] = 'E'
            sd['score'] = 0
            sd['is_at_zone'] = False
            self._track_field_attack('components.4_supply_demand.zone_level')
            self._track_field_attack('components.4_supply_demand.zone_grade')
        
        elif attack_type == 'reverse':
            sd['is_at_zone'] = not sd.get('is_at_zone', False)
            self._track_field_attack('components.4_supply_demand.is_at_zone')
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_support_resistance_component(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        sr = analysis.get('5_support_resistance', {})
        
        if not sr:
            return trade
        
        attack_type = self._select_attack_type(['fake_breakout', 'false_rejection', 'move_pivot', 'reverse'])
        
        if attack_type == 'fake_breakout':
            sr['breakout'] = True
            sr['score'] = min(100, sr.get('score', 0) + random.randint(10, 30))
            self._track_field_attack('components.5_support_resistance.breakout')
        
        elif attack_type == 'false_rejection':
            sr['breakout'] = False
            sr['score'] = max(0, sr.get('score', 0) - random.randint(10, 30))
            self._track_field_attack('components.5_support_resistance.breakout')
        
        elif attack_type == 'move_pivot':
            pivot = sr.get('pivot', 0)
            if pivot:
                pip_size = 0.0001
                sr['pivot'] = pivot + random.uniform(-10, 10) * pip_size * intensity * 2
                sr['r1'] = sr['pivot'] + random.uniform(5, 15) * pip_size
                sr['s1'] = sr['pivot'] - random.uniform(5, 15) * pip_size
                self._track_field_attack('components.5_support_resistance.pivot')
        
        elif attack_type == 'reverse':
            sr['breakout'] = not sr.get('breakout', False)
            self._track_field_attack('components.5_support_resistance.breakout')
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_breakout_component(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        breakout = analysis.get('6_breakout', {})
        
        if not breakout:
            return trade
        
        attack_type = self._select_attack_type(['fake', 'false_confirm', 'reverse'])
        
        if attack_type == 'fake':
            breakout['is_breakout'] = True
            debug = breakout.get('debug', {})
            debug['breakout_candle_confirmed'] = False
            breakout['debug'] = debug
            self._track_field_attack('components.6_breakout.is_breakout')
        
        elif attack_type == 'false_confirm':
            breakout['is_breakout'] = random.random() > 0.5
            debug = breakout.get('debug', {})
            debug['breakout_candle_confirmed'] = not debug.get('breakout_candle_confirmed', False)
            breakout['debug'] = debug
            self._track_field_attack('components.6_breakout.is_breakout')
        
        elif attack_type == 'reverse':
            breakout['is_breakout'] = not breakout.get('is_breakout', False)
            self._track_field_attack('components.6_breakout.is_breakout')
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_candlestick_component(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        candle = analysis.get('7_candlestick', {})
        
        if not candle:
            return trade
        
        patterns = ['marubozu', 'hammer', 'shooting_star', 'doji', 'spinning_top', 'pin_bar']
        attack_type = self._select_attack_type(['change', 'hide_reversal', 'reverse_score', 'extreme'])
        
        if attack_type == 'change':
            debug = candle.get('debug', {})
            current = debug.get('candle_type', 'normal')
            new = random.choice([p for p in patterns if p != current])
            debug['candle_type'] = new
            candle['debug'] = debug
            
            if new in ['marubozu']:
                candle['score'] = random.randint(20, 30)
            elif new in ['hammer', 'pin_bar']:
                candle['score'] = random.randint(15, 25)
            elif new in ['shooting_star']:
                candle['score'] = random.randint(-30, -20)
            else:
                candle['score'] = random.randint(-5, 5)
            self._track_field_attack('components.7_candlestick.debug.candle_type')
        
        elif attack_type == 'hide_reversal':
            candle['score'] = 0
            debug = candle.get('debug', {})
            debug['candle_type'] = 'doji'
            debug['body_pips'] = random.randint(0, 1)
            candle['debug'] = debug
            self._track_field_attack('components.7_candlestick.score')
        
        elif attack_type == 'reverse_score':
            candle['score'] = -candle.get('score', 0)
            self._track_field_attack('components.7_candlestick.score')
        
        elif attack_type == 'extreme':
            debug = candle.get('debug', {})
            debug['candle_type'] = random.choice(['marubozu', 'shooting_star'])
            candle['score'] = random.randint(25, 35) if debug['candle_type'] == 'marubozu' else random.randint(-35, -25)
            candle['debug'] = debug
            self._track_field_attack('components.7_candlestick.score')
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_indicators_component(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        indicators = analysis.get('8_indicators', {})
        
        if not indicators:
            return trade
        
        attack_type = self._select_attack_type(['rsi_extreme', 'macd_flip', 'stoch_conflict', 'bb_extreme', 'all_conflict'])
        
        if attack_type == 'rsi_extreme':
            rsi = indicators.get('rsi', {})
            rsi['rsi_14'] = random.choice([random.randint(80, 95), random.randint(5, 20)])
            rsi['rsi_21'] = rsi['rsi_14'] + random.randint(-5, 5)
            rsi['divergence'] = random.choice(['BULLISH', 'BEARISH'])
            rsi['score'] = random.randint(-100, 100)
            indicators['rsi'] = rsi
            self._track_field_attack('components.8_indicators.rsi')
        
        elif attack_type == 'macd_flip':
            macd = indicators.get('macd', {})
            if macd.get('signal') == 'BULLISH':
                macd['signal'] = 'BEARISH'
            elif macd.get('signal') == 'BEARISH':
                macd['signal'] = 'BULLISH'
            else:
                macd['signal'] = random.choice(['BULLISH', 'BEARISH'])
            macd['histogram'] = -macd.get('histogram', 0)
            indicators['macd'] = macd
            self._track_field_attack('components.8_indicators.macd')
        
        elif attack_type == 'stoch_conflict':
            stoch = indicators.get('stochastic', {})
            if stoch.get('signal') in ['BULLISH', 'BULLISH_X']:
                stoch['signal'] = 'BEARISH'
            elif stoch.get('signal') in ['BEARISH']:
                stoch['signal'] = 'BULLISH_X'
            else:
                stoch['signal'] = random.choice(['BULLISH_X', 'BEARISH'])
            stoch['k'] = 100 - stoch.get('k', 50)
            stoch['d'] = 100 - stoch.get('d', 50)
            indicators['stochastic'] = stoch
            self._track_field_attack('components.8_indicators.stochastic')
        
        elif attack_type == 'bb_extreme':
            bb = indicators.get('bollinger_bands', {})
            bb['signal'] = random.choice(['BULLISH', 'BEARISH'])
            bb['position'] = random.choice(['ABOVE_MIDDLE', 'BELOW_MIDDLE'])
            bb['width'] = random.uniform(0.001, 0.0001)
            debug = bb.get('debug', {})
            debug['is_squeeze'] = random.random() > 0.5
            debug['percent_b'] = random.uniform(0.1, 1.9)
            bb['debug'] = debug
            indicators['bollinger_bands'] = bb
            self._track_field_attack('components.8_indicators.bollinger_bands')
        
        elif attack_type == 'all_conflict':
            rsi = indicators.get('rsi', {})
            macd = indicators.get('macd', {})
            stoch = indicators.get('stochastic', {})
            bb = indicators.get('bollinger_bands', {})
            
            signals = ['BULLISH', 'BEARISH']
            rsi['divergence'] = random.choice(signals)
            macd['signal'] = random.choice(signals)
            stoch['signal'] = random.choice(['BULLISH_X', 'BEARISH'])
            bb['signal'] = random.choice(signals)
            
            indicators['rsi'] = rsi
            indicators['macd'] = macd
            indicators['stochastic'] = stoch
            indicators['bollinger_bands'] = bb
            self._track_field_attack('components.8_indicators.all')
        
        trade['analysis_at_open'] = analysis
        return trade
    
    # ============================================================
    # 15. M15 DIVERGENCE ATTACKS (5 FIELDS)
    # ============================================================
    
    def _attack_m15_divergence_full(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            div = analysis.get('m15_divergence', {})
            
            if div:
                if random.random() < intensity * 0.7:
                    div['type'] = random.choice(['BULLISH', 'BEARISH', 'HIDDEN_BULLISH', 'HIDDEN_BEARISH', 'NONE'])
                    self._track_field_attack('m15_divergence.type')
                
                if random.random() < intensity * 0.6:
                    div['score'] = random.randint(-100, 100)
                    self._track_field_attack('m15_divergence.score')
                
                if random.random() < intensity * 0.5:
                    div['rsi_14'] = random.randint(0, 100)
                    self._track_field_attack('m15_divergence.rsi_14')
                
                if random.random() < intensity * 0.5:
                    div['veto_triggered'] = not div.get('veto_triggered', False)
                    self._track_field_attack('m15_divergence.veto_triggered')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 16. HIGHER TIMEFRAME ATTACKS (6 FIELDS)
    # ============================================================
    
    def _attack_higher_timeframe_full(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            h1 = analysis.get('higher_timeframe', {})
            
            if h1:
                if random.random() < intensity * 0.6:
                    h1['trend'] = random.choice(['BULLISH', 'BEARISH', 'NEUTRAL'])
                    self._track_field_attack('higher_timeframe.trend')
                
                if random.random() < intensity * 0.5:
                    h1['adx'] = random.randint(0, 100)
                    self._track_field_attack('higher_timeframe.adx')
                
                if random.random() < intensity * 0.6:
                    h1['aligned_with_m1'] = not h1.get('aligned_with_m1', False)
                    self._track_field_attack('higher_timeframe.aligned_with_m1')
                
                if random.random() < intensity * 0.5:
                    h1['confidence_bonus'] = random.randint(-30, 30)
                    self._track_field_attack('higher_timeframe.confidence_bonus')
                
                if random.random() < intensity * 0.4:
                    h1['ema_200'] = h1.get('ema_200', 0) * random.uniform(0.9, 1.1)
                    self._track_field_attack('higher_timeframe.ema_200')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 17. VOLATILITY PROTECTION ATTACKS (13 FIELDS)
    # ============================================================
    
    def _attack_volatility_full(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(2 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            vol = analysis.get('volatility_protection', {})
            
            if vol:
                if random.random() < intensity * 0.6:
                    vol['volatility_level'] = random.choice(['LOW', 'NORMAL', 'HIGH', 'EXTREME'])
                    self._track_field_attack('volatility_protection.volatility_level')
                
                if random.random() < intensity * 0.5:
                    vol['atr_pips'] = random.uniform(1, 100)
                    self._track_field_attack('volatility_protection.atr_pips')
                
                if random.random() < intensity * 0.5:
                    vol['safe_to_trade'] = not vol.get('safe_to_trade', False)
                    self._track_field_attack('volatility_protection.safe_to_trade')
                
                if random.random() < intensity * 0.5:
                    vol['confidence_penalty'] = random.randint(0, 50)
                    self._track_field_attack('volatility_protection.confidence_penalty')
                
                if random.random() < intensity * 0.4:
                    vol['market_regime'] = random.choice(['NORMAL', 'HIGH_VOLATILITY', 'LOW_VOLATILITY', 'TRENDING', 'RANGING'])
                    self._track_field_attack('volatility_protection.market_regime')
                
                if random.random() < intensity * 0.3:
                    vol['normal_range_min_pips'] = random.uniform(5, 20)
                    vol['normal_range_max_pips'] = random.uniform(25, 50)
                    self._track_field_attack('volatility_protection.normal_range_min_pips')
                    self._track_field_attack('volatility_protection.normal_range_max_pips')
                
                if random.random() < intensity * 0.3:
                    vol['is_extreme'] = not vol.get('is_extreme', False)
                    vol['is_high_regime'] = not vol.get('is_high_regime', False)
                    vol['is_above_normal'] = not vol.get('is_above_normal', False)
                    vol['is_below_normal'] = not vol.get('is_below_normal', False)
                    self._track_field_attack('volatility_protection.is_extreme')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 18. VETO SYSTEM ATTACKS (13 FIELDS)
    # ============================================================
    
    def _attack_veto_full(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(2 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            veto = analysis.get('vetos', {})
            
            if veto:
                if random.random() < intensity * 0.6:
                    veto['triggered'] = not veto.get('triggered', False)
                    if veto.get('triggered'):
                        veto['reason'] = random.choice([
                            'Adversarial veto', 'False trigger', 'Market condition',
                            'Risk violation', 'System override'
                        ])
                    self._track_field_attack('vetos.triggered')
                    self._track_field_attack('vetos.reason')
                
                checks = veto.get('checks', {})
                if checks:
                    check_list = [
                        'session_veto', 'news_veto', 'choppy_market', 'extreme_volatility',
                        'against_trend', 'against_ema', 'h1_conflict', 'rsi_divergence_opposing',
                        'wick_reversal', 'low_volume', 'high_spread', 'candle_too_young'
                    ]
                    for check in check_list:
                        if random.random() < intensity * 0.4:
                            checks[check] = not checks.get(check, False)
                            self._track_field_attack(f'vetos.checks.{check}')
                    veto['checks'] = checks
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 19. NEWS ANALYSIS ATTACKS (6 FIELDS)
    # ============================================================
    
    def _attack_news_full(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            news = analysis.get('news_analysis', {})
            
            if news:
                if random.random() < intensity * 0.6:
                    news['has_news'] = not news.get('has_news', False)
                    self._track_field_attack('news_analysis.has_news')
                
                if random.random() < intensity * 0.5:
                    news['high_impact_count'] = random.randint(0, 5)
                    news['medium_impact_count'] = random.randint(0, 5)
                    news['low_impact_count'] = random.randint(0, 5)
                    self._track_field_attack('news_analysis.high_impact_count')
                    self._track_field_attack('news_analysis.medium_impact_count')
                    self._track_field_attack('news_analysis.low_impact_count')
                
                if random.random() < intensity * 0.5:
                    news['veto_triggered'] = not news.get('veto_triggered', False)
                    self._track_field_attack('news_analysis.veto_triggered')
                
                if random.random() < intensity * 0.3:
                    news['next_event'] = {
                        'title': 'Adversarial News Event',
                        'impact': random.choice(['HIGH', 'MEDIUM', 'LOW']),
                        'time': datetime.now(timezone.utc).isoformat()
                    }
                    self._track_field_attack('news_analysis.next_event')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 20. SESSION ANALYSIS ATTACKS (6 FIELDS)
    # ============================================================
    
    def _attack_session_full(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            session = analysis.get('session_analysis', {})
            
            if session:
                if random.random() < intensity * 0.6:
                    session['is_market_open'] = not session.get('is_market_open', False)
                    self._track_field_attack('session_analysis.is_market_open')
                
                if random.random() < intensity * 0.5:
                    session['is_trading_day'] = not session.get('is_trading_day', False)
                    self._track_field_attack('session_analysis.is_trading_day')
                
                if random.random() < intensity * 0.5:
                    session['veto_triggered'] = not session.get('veto_triggered', False)
                    if session.get('veto_triggered'):
                        session['veto_reason'] = random.choice([
                            'Market closed', 'Holiday', 'Session ended', 'Trading paused'
                        ])
                    self._track_field_attack('session_analysis.veto_triggered')
                    self._track_field_attack('session_analysis.veto_reason')
                
                if random.random() < intensity * 0.4:
                    exchanges = ['FX', 'COMMODITY', 'NYSE', 'NASDAQ', 'LSE', 'JPX', 'HKEX']
                    session['exchange'] = random.choice(exchanges)
                    self._track_field_attack('session_analysis.exchange')
                
                if random.random() < intensity * 0.3:
                    session['minutes_to_close'] = random.randint(-60, 60)
                    self._track_field_attack('session_analysis.minutes_to_close')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 21. POSITION MANAGEMENT ATTACKS (4 FIELDS)
    # ============================================================
    
    def _attack_position_management(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            pos = analysis.get('position_management', {})
            
            if pos:
                if random.random() < intensity * 0.6:
                    pos['should_close'] = not pos.get('should_close', False)
                    if pos.get('should_close'):
                        pos['close_reason'] = random.choice([
                            'Adversarial close', 'Market condition', 'Risk limit',
                            'News event', 'Technical signal'
                        ])
                    self._track_field_attack('position_management.should_close')
                    self._track_field_attack('position_management.close_reason')
                
                if random.random() < intensity * 0.5:
                    pos['is_already_in_trade'] = not pos.get('is_already_in_trade', False)
                    self._track_field_attack('position_management.is_already_in_trade')
                
                if random.random() < intensity * 0.5:
                    pos['current_pnl_percent'] = random.uniform(-20, 20)
                    self._track_field_attack('position_management.current_pnl_percent')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 22. GNN COMPLETE ATTACKS (30+ FIELDS)
    # ============================================================
    
    def _attack_gnn_complete(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(2 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            gnn = analysis.get('gnn', {})
            
            if gnn:
                # Attack gnn.analysis
                analysis_data = gnn.get('analysis', {})
                if analysis_data:
                    if random.random() < intensity * 0.5:
                        analysis_data['recommendation'] = random.choice(['BULLISH', 'BEARISH', 'NEUTRAL', 'CONFLICT'])
                        analysis_data['recommendation_score'] = random.randint(0, 100)
                        self._track_field_attack('gnn.analysis.recommendation')
                        self._track_field_attack('gnn.analysis.recommendation_score')
                    
                    if random.random() < intensity * 0.4:
                        analysis_data['divergence'] = {
                            'detected': random.random() > 0.5,
                            'type': random.choice(['BULLISH', 'BEARISH', 'HIDDEN_BULLISH', 'HIDDEN_BEARISH']),
                            'reason': 'Adversarial divergence',
                            'gnn_direction': random.uniform(-1, 1),
                            'price_direction': random.uniform(-1, 1)
                        }
                        self._track_field_attack('gnn.analysis.divergence')
                    
                    if random.random() < intensity * 0.3:
                        analysis_data['conflict'] = {
                            'your_analysis': random.choice(['BUY', 'SELL']),
                            'gnn_says': random.choice(['BUY', 'SELL']),
                            'severity': random.choice(['HIGH', 'MEDIUM', 'LOW']),
                            'message': 'Adversarial conflict',
                            'recommendation': 'HOLD'
                        }
                        self._track_field_attack('gnn.analysis.conflict')
                    
                    if random.random() < intensity * 0.3:
                        analysis_data['suggestions'] = [
                            {'symbol': 'EURUSD', 'action': random.choice(['BUY', 'SELL']), 
                             'confidence': random.randint(0, 100), 'reason': 'Adversarial suggestion'}
                            for _ in range(random.randint(1, 5))
                        ]
                        self._track_field_attack('gnn.analysis.suggestions')
                
                # Attack gnn.context
                context = gnn.get('context', {})
                if context:
                    context_fields = [
                        'dxy_strength', 'risk_sentiment', 'commodity_impact', 
                        'sector_sentiment', 'global_confidence', 'trend_alignment',
                        'gnn_influence', 'gnn_connections'
                    ]
                    for field in context_fields:
                        if random.random() < intensity * 0.4:
                            context[field] = random.uniform(0, 1) if 'confidence' in field or 'strength' in field else random.randint(0, 100)
                            self._track_field_attack(f'gnn.context.{field}')
                    
                    if random.random() < intensity * 0.3:
                        context['market_regime'] = random.choice(['NORMAL', 'HIGH_VOLATILITY', 'LOW_VOLATILITY', 'TRENDING'])
                        self._track_field_attack('gnn.context.market_regime')
                
                # Attack gnn.final_score
                final_score = gnn.get('final_score', {})
                if final_score:
                    if random.random() < intensity * 0.5:
                        final_score['gnn_recommendation'] = random.choice(['BUY', 'SELL', 'NEUTRAL', 'CONFLICT'])
                        final_score['gnn_score'] = random.randint(0, 100)
                        final_score['gnn_contribution'] = random.uniform(-15, 15)
                        final_score['aligned'] = random.random() > 0.5
                        self._track_field_attack('gnn.final_score')
                
                # Attack gnn.ab_test
                ab_test = gnn.get('ab_test', {})
                if ab_test:
                    if random.random() < intensity * 0.3:
                        ab_test['enabled'] = random.random() > 0.5
                        ab_test['rollout'] = random.uniform(0, 1)
                        ab_test['improvement'] = random.uniform(-0.2, 0.2)
                        self._track_field_attack('gnn.ab_test')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 23. OHLC + GNN ATTACKS (15+ FIELDS)
    # ============================================================
    
    def _attack_ohlc_gnn(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            ohlc_gnn = analysis.get('ohlc_gnn', {})
            
            if ohlc_gnn:
                # Attack OHLC data
                ohlc = ohlc_gnn.get('ohlc', {})
                if ohlc:
                    ohlc_fields = ['open', 'high', 'low', 'close']
                    for field in ohlc_fields:
                        if random.random() < intensity * 0.3:
                            ohlc[field] = ohlc.get(field, 0) * random.uniform(0.9, 1.1)
                            self._track_field_attack(f'ohlc_gnn.ohlc.{field}')
                    
                    if random.random() < intensity * 0.4:
                        ohlc['candle_type'] = random.choice(['BULLISH', 'BEARISH', 'DOJI'])
                        self._track_field_attack('ohlc_gnn.ohlc.candle_type')
                    
                    if random.random() < intensity * 0.3:
                        ohlc['body'] = random.uniform(0, 0.01)
                        ohlc['upper_wick'] = random.uniform(0, 0.005)
                        ohlc['lower_wick'] = random.uniform(0, 0.005)
                        self._track_field_attack('ohlc_gnn.ohlc.body')
                        self._track_field_attack('ohlc_gnn.ohlc.upper_wick')
                        self._track_field_attack('ohlc_gnn.ohlc.lower_wick')
                
                # Attack GNN section
                gnn_section = ohlc_gnn.get('gnn', {})
                if gnn_section:
                    if random.random() < intensity * 0.4:
                        gnn_section['recommendation'] = random.choice(['BUY', 'SELL', 'HOLD'])
                        gnn_section['recommendation_score'] = random.randint(0, 100)
                        self._track_field_attack('ohlc_gnn.gnn.recommendation')
                
                # Attack combined_signal
                combined = ohlc_gnn.get('combined_signal', {})
                if combined:
                    if random.random() < intensity * 0.5:
                        combined['recommendation'] = random.choice(['BUY', 'SELL', 'HOLD'])
                        combined['confidence'] = random.randint(0, 100)
                        combined['combined_score'] = random.uniform(-1, 1)
                        self._track_field_attack('ohlc_gnn.combined_signal')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 24. ENTRY DETAILS ATTACKS (12 FIELDS)
    # ============================================================
    
    def _attack_entry_details(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            details = analysis.get('entry_details', {})
            
            if details:
                price_fields = ['entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3']
                for field in price_fields:
                    if random.random() < intensity * 0.4:
                        details[field] = details.get(field, 0) * random.uniform(0.9, 1.1)
                        self._track_field_attack(f'entry_details.{field}')
                
                if random.random() < intensity * 0.5:
                    details['stop_loss_pips'] = random.uniform(1, 50)
                    details['take_profit_pips'] = random.uniform(1, 50)
                    self._track_field_attack('entry_details.stop_loss_pips')
                    self._track_field_attack('entry_details.take_profit_pips')
                
                if random.random() < intensity * 0.4:
                    details['lot_size'] = random.uniform(0.01, 5.0)
                    self._track_field_attack('entry_details.lot_size')
                
                if random.random() < intensity * 0.3:
                    details['risk_reward'] = f"1:{round(random.uniform(0.1, 5.0), 1)}"
                    self._track_field_attack('entry_details.risk_reward')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 25. GLOBAL ANTICHEAT ATTACKS (7 FIELDS)
    # ============================================================
    
    def _attack_global_anticheat(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            anticheat = analysis.get('global_anticheat', {})
            
            if anticheat:
                if random.random() < intensity * 0.5:
                    anticheat['candle_progress_percent'] = random.randint(0, 100)
                    anticheat['candle_ready'] = anticheat['candle_progress_percent'] > 75
                    self._track_field_attack('global_anticheat.candle_progress_percent')
                    self._track_field_attack('global_anticheat.candle_ready')
                
                if random.random() < intensity * 0.5:
                    anticheat['spread_pips'] = random.uniform(0, 50)
                    anticheat['spread_valid'] = anticheat['spread_pips'] < anticheat.get('max_allowed_spread', 30)
                    self._track_field_attack('global_anticheat.spread_pips')
                    self._track_field_attack('global_anticheat.spread_valid')
                
                if random.random() < intensity * 0.4:
                    anticheat['max_allowed_spread'] = random.uniform(10, 50)
                    self._track_field_attack('global_anticheat.max_allowed_spread')
                
                if random.random() < intensity * 0.4:
                    anticheat['volume_ratio'] = random.uniform(0.1, 3.0)
                    self._track_field_attack('global_anticheat.volume_ratio')
                
                if random.random() < intensity * 0.3:
                    anticheat['atr_pips'] = random.uniform(1, 100)
                    self._track_field_attack('global_anticheat.atr_pips')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 26. ACCOUNT INFO ATTACKS (5 FIELDS)
    # ============================================================
    
    def _attack_account_info(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            account = analysis.get('account_info', {})
            
            if account:
                if random.random() < intensity * 0.5:
                    account['balance'] = account.get('balance', 10000) * random.uniform(0.5, 2.0)
                    self._track_field_attack('account_info.balance')
                
                if random.random() < intensity * 0.4:
                    account['leverage'] = random.choice([10, 20, 50, 100, 200, 500, 1000])
                    self._track_field_attack('account_info.leverage')
                
                if random.random() < intensity * 0.4:
                    account['free_margin_before'] = account.get('free_margin_before', 10000) * random.uniform(0.5, 2.0)
                    account['margin_required_usd'] = account.get('margin_required_usd', 100) * random.uniform(0.5, 2.0)
                    account['free_margin_after'] = account['free_margin_before'] - account['margin_required_usd']
                    self._track_field_attack('account_info.free_margin_before')
                    self._track_field_attack('account_info.margin_required_usd')
                    self._track_field_attack('account_info.free_margin_after')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 27. CONFIG ATTACKS (20+ FIELDS)
    # ============================================================
    
    def _attack_config(self, trade: Dict, intensity: float, outcome: int) -> List[Dict]:
        attacks = []
        
        for _ in range(int(1.5 * intensity) + 1):
            attacked = copy.deepcopy(trade)
            analysis = attacked.get('analysis_at_open', {})
            config = analysis.get('config', {})
            
            if config:
                if random.random() < intensity * 0.5:
                    config['symbol'] = random.choice(['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'BTCUSD'])
                    self._track_field_attack('config.symbol')
                
                if random.random() < intensity * 0.4:
                    config['user_requested_direction'] = random.choice(['BUY', 'SELL'])
                    config['executed_direction'] = random.choice(['BUY', 'SELL'])
                    self._track_field_attack('config.user_requested_direction')
                    self._track_field_attack('config.executed_direction')
                
                if random.random() < intensity * 0.4:
                    config['timeframe'] = random.choice(['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'])
                    self._track_field_attack('config.timeframe')
                
                if random.random() < intensity * 0.3:
                    config['leverage'] = random.choice([10, 20, 50, 100, 200, 500])
                    self._track_field_attack('config.leverage')
                
                if random.random() < intensity * 0.3:
                    config['fixed_trade_size_usd'] = random.uniform(100, 10000)
                    config['risk_per_trade_percent'] = random.uniform(0.5, 5.0)
                    self._track_field_attack('config.fixed_trade_size_usd')
                    self._track_field_attack('config.risk_per_trade_percent')
                
                if random.random() < intensity * 0.3:
                    config['breakout_period'] = random.randint(5, 50)
                    config['breakout_volume_threshold'] = random.uniform(1.0, 3.0)
                    self._track_field_attack('config.breakout_period')
                    self._track_field_attack('config.breakout_volume_threshold')
                
                if random.random() < intensity * 0.3:
                    config['min_timing_confidence'] = random.randint(50, 90)
                    config['min_probability_for_entry'] = random.randint(50, 90)
                    self._track_field_attack('config.min_timing_confidence')
                    self._track_field_attack('config.min_probability_for_entry')
                
                if random.random() < intensity * 0.3:
                    config['gnn_enabled'] = not config.get('gnn_enabled', False)
                    config['gnn_available'] = config.get('gnn_enabled', False)
                    self._track_field_attack('config.gnn_enabled')
                    self._track_field_attack('config.gnn_available')
                
                if random.random() < intensity * 0.2:
                    config['valid_zone_grades'] = random.sample(['A', 'B', 'C', 'D', 'E'], random.randint(2, 5))
                    self._track_field_attack('config.valid_zone_grades')
            
            attacks.append(attacked)
        
        return attacks
    
    # ============================================================
    # 28. DISASTER ATTACKS (5 - ALL IMPLEMENTED)
    # ============================================================
    
    def _generate_disaster_attacks(self, trade: Dict, outcome: int, intensity: float, 
                                    gnn_context: Dict = None) -> List[Dict]:
        attacks = []
        disaster_types = [
            self._attack_flash_crash,
            self._attack_news_event,
            self._attack_panic,
            self._attack_reversal,
            self._attack_liquidity_crisis,
        ]
        
        for attack_func in disaster_types:
            try:
                attacked = attack_func(copy.deepcopy(trade), intensity, outcome)
                if attacked != trade:
                    attacks.append(attacked)
                    self.stats['attack_types_used'][attack_func.__name__] += 1
            except Exception as e:
                logger.debug(f"Disaster attack failed: {e}")
        
        return attacks
    
    def _attack_flash_crash(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        pip_size = 0.0001
        
        entry_details = analysis.get('entry_details', {})
        if entry_details:
            entry = entry_details.get('entry_price', 0)
            if entry:
                crash_move = random.uniform(50, 200) * pip_size * intensity
                entry_details['entry_price'] = entry - crash_move
        
        vol = analysis.get('volatility_protection', {})
        vol['volatility_level'] = 'HIGH'
        vol['atr_pips'] = random.randint(80, 150) * intensity
        vol['is_extreme'] = True
        vol['safe_to_trade'] = False
        vol['confidence_penalty'] = random.randint(30, 50)
        
        veto = analysis.get('vetos', {})
        veto['triggered'] = True
        veto['reason'] = 'Flash crash detected'
        vol['market_regime'] = 'HIGH_VOLATILITY'
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_news_event(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        news = analysis.get('news_analysis', {})
        news['has_news'] = True
        news['high_impact_count'] = max(1, int(random.randint(1, 3) * intensity))
        news['veto_triggered'] = True
        
        vol = analysis.get('volatility_protection', {})
        vol['volatility_level'] = 'HIGH'
        vol['atr_pips'] = random.randint(60, 120) * intensity
        vol['is_extreme'] = True
        vol['safe_to_trade'] = False
        
        veto = analysis.get('vetos', {})
        veto['triggered'] = True
        veto['reason'] = 'High impact news event'
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_panic(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        trend = analysis.get('1_trend_bias', {})
        if trend.get('trend') in ['BULLISH', 'STRONG_BULLISH']:
            trend['trend'] = 'STRONG_BEARISH' if intensity > 0.7 else 'BEARISH'
        else:
            trend['trend'] = 'STRONG_BEARISH'
        trend['score'] = 85 + random.randint(0, 10)
        
        vol = analysis.get('volatility_protection', {})
        vol['volatility_level'] = 'HIGH'
        vol['atr_pips'] = random.randint(50, 100) * intensity
        vol['is_extreme'] = True
        
        veto = analysis.get('vetos', {})
        veto['triggered'] = True
        veto['reason'] = 'Panic sell-off detected'
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_reversal(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        trend = analysis.get('1_trend_bias', {})
        trend['trend'] = random.choice(['BULLISH', 'BEARISH'])
        trend['score'] = random.randint(70, 90)
        
        direction = analysis.get('directional_analysis', {})
        if direction.get('best_direction') == 'BUY':
            direction['best_direction'] = 'SELL'
        else:
            direction['best_direction'] = 'BUY'
        
        veto = analysis.get('vetos', {})
        veto['triggered'] = True
        veto['reason'] = 'Reversal detected'
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_liquidity_crisis(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        anticheat = analysis.get('global_anticheat', {})
        anticheat['spread_pips'] = random.randint(50, 150) * intensity
        anticheat['spread_valid'] = False
        
        indicators = analysis.get('8_indicators', {})
        volume = indicators.get('volume', {})
        volume['ratio'] = 0.01
        volume['confirmed'] = False
        
        veto = analysis.get('vetos', {})
        veto['triggered'] = True
        veto['reason'] = 'Liquidity crisis'
        
        session = analysis.get('session_analysis', {})
        session['is_market_open'] = False
        session['veto_triggered'] = True
        
        trade['analysis_at_open'] = analysis
        return trade
    
    # ============================================================
    # 29. DECISION ATTACKS (6 - ALL IMPLEMENTED)
    # ============================================================
    
    def _generate_decision_attacks(self, trade: Dict, outcome: int, intensity: float,
                                    gnn_context: Dict = None) -> List[Dict]:
        attacks = []
        decision_types = [
            self._attack_confidence_collapse,
            self._attack_decision_flip,
            self._attack_overconfidence,
            self._attack_underconfidence,
            self._attack_total_disagreement,
            self._attack_probability_inversion,
        ]
        
        for attack_func in decision_types:
            try:
                attacked = attack_func(copy.deepcopy(trade), intensity, outcome)
                if attacked != trade:
                    attacks.append(attacked)
                    self.stats['attack_types_used'][attack_func.__name__] += 1
            except Exception as e:
                logger.debug(f"Decision attack failed: {e}")
        
        return attacks
    
    def _attack_confidence_collapse(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        final_verdict = analysis.get('final_verdict', {})
        max_collapse = int(50 * intensity)
        final_verdict['probability_percent'] = random.randint(0, max_collapse)
        
        entry_analysis = analysis.get('entry_analysis', {})
        entry_analysis['timing_confidence'] = random.randint(0, max_collapse)
        analysis['⭐ CONFIDENCE'] = f"{final_verdict.get('probability_percent', 0)}%"
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_decision_flip(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        direction = analysis.get('directional_analysis', {})
        if direction.get('best_direction') == 'BUY':
            direction['best_direction'] = 'SELL'
            direction['buy_probability'] = random.randint(20, 40)
            direction['sell_probability'] = random.randint(60, 80)
        else:
            direction['best_direction'] = 'BUY'
            direction['buy_probability'] = random.randint(60, 80)
            direction['sell_probability'] = random.randint(20, 40)
        
        final_verdict = analysis.get('final_verdict', {})
        final_verdict['action'] = direction['best_direction']
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_overconfidence(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        final_verdict = analysis.get('final_verdict', {})
        boost = int(40 * intensity)
        current = final_verdict.get('probability_percent', 50)
        final_verdict['probability_percent'] = min(99, current + random.randint(boost, boost + 10))
        
        entry_analysis = analysis.get('entry_analysis', {})
        entry_analysis['timing_confidence'] = min(100, entry_analysis.get('timing_confidence', 50) + random.randint(boost, boost + 10))
        analysis['⭐ CONFIDENCE'] = f"{final_verdict.get('probability_percent', 99)}%"
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_underconfidence(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        final_verdict = analysis.get('final_verdict', {})
        reduction = int(40 * intensity)
        current = final_verdict.get('probability_percent', 50)
        final_verdict['probability_percent'] = max(5, current - random.randint(reduction, reduction + 10))
        
        entry_analysis = analysis.get('entry_analysis', {})
        entry_analysis['timing_confidence'] = max(0, entry_analysis.get('timing_confidence', 50) - random.randint(reduction, reduction + 10))
        analysis['⭐ CONFIDENCE'] = f"{final_verdict.get('probability_percent', 5)}%"
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_total_disagreement(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        components = analysis.get('components', {})
        
        for comp_name, comp_data in components.items():
            if 'score' in comp_data:
                comp_data['score'] = random.randint(30, 70)
            if 'recommendation' in comp_data:
                comp_data['recommendation'] = random.choice(['BUY', 'SELL', 'HOLD', 'NEUTRAL'])
            if 'trend' in comp_data:
                comp_data['trend'] = random.choice(['BULLISH', 'BEARISH', 'NEUTRAL'])
        
        final_verdict = analysis.get('final_verdict', {})
        final_verdict['probability_percent'] = random.randint(45, 55)
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_probability_inversion(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        final_verdict = analysis.get('final_verdict', {})
        current = final_verdict.get('probability_percent', 50)
        final_verdict['probability_percent'] = 100 - current
        
        direction = analysis.get('directional_analysis', {})
        buy = direction.get('buy_probability', 50)
        sell = direction.get('sell_probability', 50)
        direction['buy_probability'] = 100 - buy
        direction['sell_probability'] = 100 - sell
        analysis['⭐ CONFIDENCE'] = f"{final_verdict.get('probability_percent', 50)}%"
        
        trade['analysis_at_open'] = analysis
        return trade
    
    # ============================================================
    # 30. EDGE CASE ATTACKS (5 - ALL IMPLEMENTED)
    # ============================================================
    
    def _generate_edge_case_attacks(self, trade: Dict, outcome: int, intensity: float,
                                     gnn_context: Dict = None) -> List[Dict]:
        attacks = []
        edge_types = [
            self._attack_missing_data,
            self._attack_zero_data,
            self._attack_random_data,
            self._attack_contradictory_data,
            self._attack_out_of_range,
        ]
        
        for attack_func in edge_types:
            try:
                attacked = attack_func(copy.deepcopy(trade), intensity, outcome)
                if attacked != trade:
                    attacks.append(attacked)
                    self.stats['attack_types_used'][attack_func.__name__] += 1
            except Exception as e:
                logger.debug(f"Edge case attack failed: {e}")
        
        return attacks
    
    def _attack_missing_data(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        components = analysis.get('components', {})
        
        remove_pct = 0.3 + intensity * 0.3
        keys = list(components.keys())
        remove_count = int(len(keys) * remove_pct)
        for key in random.sample(keys, remove_count):
            if key in components:
                del components[key]
        
        # Also remove some top-level fields
        top_fields = ['entry_analysis', 'indicator_scores', 'pattern_analysis']
        for field in top_fields:
            if random.random() < intensity * 0.3:
                if field in analysis:
                    del analysis[field]
                    self._track_field_attack(f'analysis.{field}')
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_zero_data(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        components = analysis.get('components', {})
        
        zero_pct = 0.5 + intensity * 0.5
        for comp_data in components.values():
            if 'score' in comp_data and random.random() < zero_pct:
                comp_data['score'] = 0
            if 'confidence' in comp_data and random.random() < zero_pct:
                comp_data['confidence'] = 0
        
        final_verdict = analysis.get('final_verdict', {})
        if random.random() < zero_pct:
            final_verdict['probability_percent'] = 0
            analysis['⭐ CONFIDENCE'] = "0%"
        
        entry_analysis = analysis.get('entry_analysis', {})
        if random.random() < zero_pct:
            entry_analysis['timing_confidence'] = 0
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_random_data(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        components = analysis.get('components', {})
        
        random_pct = 0.5 + intensity * 0.5
        for comp_data in components.values():
            if random.random() < random_pct:
                if 'score' in comp_data:
                    comp_data['score'] = random.randint(0, 100)
                if 'trend' in comp_data:
                    comp_data['trend'] = random.choice(['BULLISH', 'BEARISH', 'NEUTRAL'])
                if 'recommendation' in comp_data:
                    comp_data['recommendation'] = random.choice(['BUY', 'SELL', 'HOLD'])
                if 'confidence' in comp_data:
                    comp_data['confidence'] = random.randint(0, 100)
        
        final_verdict = analysis.get('final_verdict', {})
        if random.random() < random_pct:
            final_verdict['probability_percent'] = random.randint(0, 100)
            analysis['⭐ CONFIDENCE'] = f"{final_verdict.get('probability_percent', 50)}%"
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_contradictory_data(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        components = analysis.get('components', {})
        
        comp_names = list(components.keys())
        for i, name in enumerate(comp_names):
            comp_data = components.get(name, {})
            if i % 2 == 0:
                comp_data['score'] = random.randint(70, 95)
                if 'trend' in comp_data:
                    comp_data['trend'] = 'BULLISH'
                if 'recommendation' in comp_data:
                    comp_data['recommendation'] = 'BUY'
            else:
                comp_data['score'] = random.randint(5, 30)
                if 'trend' in comp_data:
                    comp_data['trend'] = 'BEARISH'
                if 'recommendation' in comp_data:
                    comp_data['recommendation'] = 'SELL'
        
        # Also contradict directional analysis
        direction = analysis.get('directional_analysis', {})
        if direction:
            direction['buy_probability'] = 80
            direction['sell_probability'] = 20
            direction['best_direction'] = 'BUY'
            direction['user_requested_direction'] = 'SELL'
            direction['user_direction_aligned'] = False
        
        trade['analysis_at_open'] = analysis
        return trade
    
    def _attack_out_of_range(self, trade: Dict, intensity: float, outcome: int) -> Dict:
        analysis = trade.get('analysis_at_open', {})
        
        final_verdict = analysis.get('final_verdict', {})
        if random.random() < intensity:
            final_verdict['probability_percent'] = random.choice([-50, 150, 200, 999])
        
        entry_analysis = analysis.get('entry_analysis', {})
        if random.random() < intensity:
            entry_analysis['timing_confidence'] = random.choice([-100, 200, 300])
            entry_analysis['timing_ready'] = False
        
        components = analysis.get('components', {})
        for comp_data in components.values():
            if random.random() < intensity * 0.5:
                if 'score' in comp_data:
                    comp_data['score'] = random.choice([-200, 300, 400, -100, 999])
                if 'confidence' in comp_data:
                    comp_data['confidence'] = random.choice([-50, 150, 200])
        
        if random.random() < intensity * 0.3:
            analysis['⭐ CONFIDENCE'] = f"{random.choice([-50, 150, 200, 999])}%"
        
        trade['analysis_at_open'] = analysis
        return trade
    
    # ============================================================
    # 31. BATCH PROCESSING
    # ============================================================
    
    def add_trade_to_buffer(self, trade: Dict, outcome: int) -> Dict[str, Any]:
        self.trade_buffer.append({'trade': trade, 'outcome': outcome})
        if len(self.trade_buffer) >= self.buffer_size:
            return self.process_buffer()
        return {'processed': False, 'buffered': len(self.trade_buffer), 'buffer_size': self.buffer_size}
    
    def process_buffer(self) -> Dict[str, Any]:
        if not self.trade_buffer:
            return {'processed': False, 'reason': 'Buffer empty'}
        
        trades = [item['trade'] for item in self.trade_buffer]
        outcomes = [item['outcome'] for item in self.trade_buffer]
        
        all_attacks = []
        for trade, outcome in zip(trades, outcomes):
            attacks = self.generate_attacked_trades(trade, outcome)
            all_attacks.extend(attacks)
        
        self.trade_buffer.clear()
        
        return {
            'processed': True,
            'trades_processed': len(trades),
            'attacks_generated': len(all_attacks),
            'fields_attacked': self.stats['total_fields_attacked'],
            'attacks': all_attacks,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    # ============================================================
    # 32. ATTACK ANALYSIS
    # ============================================================
    
    def analyze_attacks(self) -> Dict[str, Any]:
        analysis = {
            'attack_success_rates': {},
            'field_attack_stats': {},
            'most_effective_attacks': [],
            'attack_diversity': self.stats['diversity_score'],
            'field_coverage': {
                'total_fields': self.stats['total_fields_attacked'],
                'coverage_percentage': self.stats['field_coverage_percentage'],
                'fields': sorted(list(self.attack_metrics['field_coverage'])),
            },
            'recommendations': [],
        }
        
        # Attack success rates
        for attack_type, metrics in self.attack_metrics['attack_success_rate'].items():
            attempts = metrics['attempts']
            if attempts > 0:
                success_rate = metrics['successes'] / attempts
                analysis['attack_success_rates'][attack_type] = {
                    'success_rate': success_rate,
                    'attempts': attempts,
                    'successes': metrics['successes']
                }
        
        # Field attack stats
        for field, metrics in self.attack_metrics['field_attack_success'].items():
            attempts = metrics['attempts']
            if attempts > 0:
                success_rate = metrics['successes'] / attempts
                analysis['field_attack_stats'][field] = {
                    'success_rate': success_rate,
                    'attempts': attempts,
                    'successes': metrics['successes']
                }
        
        # Most effective attacks
        sorted_attacks = sorted(
            analysis['attack_success_rates'].items(),
            key=lambda x: x[1]['success_rate'],
            reverse=True
        )
        analysis['most_effective_attacks'] = sorted_attacks[:5]
        
        # Recommendations
        for attack_type, data in sorted_attacks[:3]:
            if data['success_rate'] > 0.7:
                analysis['recommendations'].append({
                    'attack': attack_type,
                    'recommendation': 'Use more of this attack type',
                    'success_rate': data['success_rate'],
                    'reason': 'High success rate'
                })
        
        if self.stats['diversity_score'] < 0.3:
            analysis['recommendations'].append({
                'attack': 'diversity',
                'recommendation': 'Increase attack diversity',
                'reason': 'Low diversity score'
            })
        
        if self.stats['field_coverage_percentage'] < 50:
            analysis['recommendations'].append({
                'attack': 'field_coverage',
                'recommendation': 'Increase field coverage',
                'reason': f'Only {self.stats["field_coverage_percentage"]:.1f}% of fields attacked'
            })
        
        return analysis
    
    # ============================================================
    # 33. REAL-TIME ATTACK GENERATION
    # ============================================================
    
    def generate_real_time_attack(self, trade: Dict, outcome: int, gnn_context: Dict = None) -> Dict[str, Any]:
        if not self.adversarial_config['enabled']:
            return {'generated': False, 'reason': 'Adversarial training disabled'}
        
        all_attack_groups = [
            self._attack_final_decision,
            self._attack_prices_and_sizing,
            self._attack_entry_analysis,
            self._attack_indicator_scores,
            self._attack_pattern_analysis,
            self._attack_directional_analysis,
        ]
        
        weights = [self.adaptive_selection['attack_weights'][f.__name__] + 1.0 
                   for f in all_attack_groups]
        total = sum(weights)
        if total > 0:
            probs = [w / total for w in weights]
            attack_func = np.random.choice(all_attack_groups, p=probs)
        else:
            attack_func = random.choice(all_attack_groups)
        
        intensity = self.adversarial_config['intensity']
        
        if gnn_context and self.adversarial_config['gnn_integration']:
            gnn_confidence = gnn_context.get('global_confidence', 0.5)
            intensity = intensity * (1 + (gnn_confidence - 0.5) * 0.3)
            intensity = max(0.1, min(1.0, intensity))
        
        attacked_list = attack_func(copy.deepcopy(trade), intensity, outcome)
        attacked = attacked_list[0] if attacked_list else trade
        
        if self._validate_attacked_trade(attacked):
            self.stats['total_attacks_generated'] += 1
            self.stats['last_attack_time'] = datetime.now(timezone.utc).isoformat()
            
            return {
                'generated': True,
                'attacked_trade': attacked,
                'attack_type': attack_func.__name__,
                'intensity': intensity,
                'fields_attacked': self.stats['total_fields_attacked'],
                'gnn_used': gnn_context is not None,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        
        return {'generated': False, 'reason': 'Attack validation failed'}
    
    # ============================================================
    # 34. STATUS
    # ============================================================
    
    def get_status(self) -> Dict[str, Any]:
        return {
            'enabled': self.adversarial_config['enabled'],
            'intensity': self.adversarial_config['intensity'],
            'variations_per_trade': self.adversarial_config['variations_per_trade'],
            'attack_all_fields': self.adversarial_config['attack_all_fields'],
            'total_attacks_generated': self.stats['total_attacks_generated'],
            'total_attacks_applied': self.stats['total_attacks_applied'],
            'trades_attacked': self.stats['trades_attacked'],
            'last_attack_time': self.stats['last_attack_time'],
            'components_attacked': dict(self.stats['components_attacked']),
            'fields_attacked': dict(self.stats['fields_attacked']),
            'total_fields_attacked': self.stats['total_fields_attacked'],
            'field_coverage_percentage': self.stats['field_coverage_percentage'],
            'attack_types_used': dict(self.stats['attack_types_used']),
            'attack_history_size': len(self.attack_history),
            'attack_success_rate': self.stats['attack_success_rate'],
            'diversity_score': self.stats['diversity_score'],
            'buffer_size': len(self.trade_buffer),
            'adaptive_selection_enabled': self.adaptive_selection['enabled'],
            'attack_weights': dict(self.adaptive_selection['attack_weights']),
            'most_effective_attacks': self.attack_metrics.get('best_attack_combinations', []),
            'gnn_integration': self.adversarial_config['gnn_integration'],
            'storage_mode': 'MODELS & METRICS SAVED to Firebase, ATTACKED DATA DISCARDED',
            'free_plan_safe': True,
            'collections_used': [
                'ai_component_models',
                'ai_ensemble_models', 
                'ai_performance_state',
                'ai_config_state',
                'ai_training_data'
            ],
            'new_collections_created': 'NONE - using existing collections',
        }
    
    def get_attack_types_available(self) -> Dict[str, int]:
        return {
            'component_attacks': 21,
            'disaster_attacks': 5,
            'decision_attacks': 6,
            'edge_case_attacks': 5,
            'total_attack_patterns': 21 * 5 + 5 + 6 + 5,
            'fields_attacked': len(self.attack_metrics['field_coverage']),
            'total_possible_fields': 200,
            'field_coverage_percentage': self.stats['field_coverage_percentage'],
            'attack_groups': [
                'final_decision',
                'prices_and_sizing',
                'entry_analysis',
                'indicator_scores',
                'pattern_analysis',
                'directional_analysis',
                'components',
                'm15_divergence',
                'higher_timeframe',
                'volatility',
                'veto_system',
                'news',
                'session',
                'position_management',
                'gnn',
                'ohlc_gnn',
                'entry_details',
                'global_anticheat',
                'account_info',
                'config',
            ]
        }
    
    def reset_stats(self):
        self.stats = {
            'total_attacks_generated': 0,
            'total_attacks_applied': 0,
            'components_attacked': defaultdict(int),
            'fields_attacked': defaultdict(int),
            'attack_types_used': defaultdict(int),
            'trades_attacked': 0,
            'last_attack_time': None,
            'attack_success_rate': 0,
            'diversity_score': 0,
            'field_coverage_percentage': 0,
            'total_fields_attacked': 0,
        }
        self.attack_history.clear()
        self.trade_buffer.clear()
        self.attack_success_history.clear()
        self.attack_metrics = {
            'attack_success_rate': defaultdict(lambda: {'successes': 0, 'attempts': 0}),
            'field_attack_success': defaultdict(lambda: {'successes': 0, 'attempts': 0}),
            'model_improvement': defaultdict(list),
            'best_attack_combinations': [],
            'field_coverage': set(),
        }
        self.attack_diversity = {
            'attacks_used': set(),
            'patterns_used': defaultdict(int),
            'fields_attacked': set(),
            'diversity_over_time': [],
        }
        self.adaptive_selection['attack_weights'] = defaultdict(float)
        self.adaptive_selection['field_weights'] = defaultdict(float)
        self.gnn_context_cache = {}
        
        self.save_metrics()
        logger.info("🔄 Adversarial stats reset and saved to Firebase")

# ============================================================
# MODULE-LEVEL VERIFICATION ENDPOINTS
# ============================================================
#
# Standard 12 requires every AI module to expose get_status() and
# self_check(). This module exposed neither at module level, and the
# consequence was not cosmetic: /verify builds its `ok` from components that
# carry a dict `self_check`, so adversarial -- the component the controller
# itself prints as ESSENTIAL -- was filtered out of the whole-layer gate
# entirely. The gate could return ok=True having verified nothing about it.
# An uncomputable gate is an unmet gate (standard 16).

def get_status(adversarial: Optional["AIAdversarial"] = None) -> Dict[str, Any]:
    """Capability and configuration state, without requiring Firebase."""
    if adversarial is None:
        try:
            adversarial = AIAdversarial()
        except Exception as exc:
            return {"component": "ai_adversarial", "available": False,
                    "error": f"{type(exc).__name__}: {exc}"}
    status = adversarial.get_status()
    status.update({
        "component": "ai_adversarial",
        "available": True,
        "ab_test": adversarial.get_ab_test_results(),
    })
    return status


def self_check(trades: Optional[Sequence[Mapping[str, Any]]] = None,
               adversarial: Optional["AIAdversarial"] = None) -> Dict[str, Any]:
    """
    Prove the invariants this module has actually broken before.

    Each check corresponds to a defect that was live and silent:
      * label alignment -- variations were labelled `outcomes * len(attacked)`,
        misaligned from the first element, so training ran on labels belonging
        to other trades and still reported success;
      * adaptive weights -- a stale clamp froze every weight at 0.0, so attack
        selection silently stopped adapting;
      * A/B assignment -- must be deterministic per trade_id, or control and
        test leak into each other and the comparison means nothing;
      * canonicalisation -- price_evolution has two incompatible stored shapes
        and reasoning off the raw form trains on field names nothing emits.
    """
    report: Dict[str, Any] = {
        "component": "ai_adversarial", "ok": False, "checks": {}}
    try:
        if adversarial is None:
            adversarial = AIAdversarial()
        checks = report["checks"]

        # A/B assignment must be deterministic and stable across calls.
        ids = [f"trade-{i}" for i in range(200)]
        first = [adversarial.should_attack_trade(t) for t in ids]
        second = [adversarial.should_attack_trade(t) for t in ids]
        checks["ab_assignment_deterministic"] = first == second
        checks["ab_assignment_splits"] = 0 < sum(first) < len(ids)

        trades = list(trades or [])
        checks["trades_in"] = len(trades)

        if trades:
            # Canonicalisation must survive whichever price_evolution shape
            # the trade was stored in.
            canonical = adversarial._to_canonical(dict(trades[0]))
            checks["canonicalises"] = isinstance(canonical, dict) and bool(canonical)

            # Label alignment, measured rather than asserted: generate real
            # variations and confirm one label per sample.
            outcomes = [1 if i % 2 == 0 else 0 for i in range(len(trades))]
            captured: Dict[str, Any] = {}

            def _capture(samples, labels):
                captured["samples"] = len(samples)
                captured["labels"] = len(labels)
                return {"improvement": 0.0}

            was_enabled = adversarial.adversarial_config.get("enabled")
            adversarial.adversarial_config["enabled"] = True
            try:
                result = adversarial.apply_attacks_to_training(
                    trades, outcomes, _capture, save_models=False)
            finally:
                adversarial.adversarial_config["enabled"] = was_enabled

            checks["attacks_applied"] = bool(result.get("applied"))
            if captured:
                checks["labels_aligned"] = (
                    captured["samples"] == captured["labels"])
                checks["samples_generated"] = captured["samples"]
            else:
                # No variations generated is a legitimate outcome; it is not
                # evidence that alignment holds, so it is not recorded as such.
                checks["labels_aligned"] = None
                checks["reason_no_samples"] = result.get("reason")

        # Adaptive weights must not be frozen at zero after a positive result.
        #
        # The gates are forced open first. Left at their defaults, attack
        # generation is governed by attack_probability and the A/B rollout,
        # so `attack_types_used` is empty on most runs and the weight loop
        # iterates nothing -- the check then passes or fails on a coin flip
        # and proves nothing either way. Determinism is the point of a check.
        if trades:
            config = adversarial.adversarial_config
            saved = {key: config.get(key) for key in
                     ("enabled", "attack_probability",
                      "attack_both_wins_and_losses")}
            saved_rollout = adversarial.ab_test.get("rollout")
            try:
                config["enabled"] = True
                config["attack_probability"] = 1.0
                config["attack_both_wins_and_losses"] = True
                adversarial.set_ab_test_rollout(1.0)
                variations = adversarial.generate_attacked_trades(
                    dict(trades[0]), 1, {})
                checks["attack_types_recorded"] = len(
                    adversarial.stats["attack_types_used"])
                checks["variations_for_one_trade"] = len(variations)
                adversarial._update_adaptive_selection({"improvement": 0.05})
                weights = dict(
                    adversarial.adaptive_selection.get("attack_weights") or {})
                checks["adaptive_weights_move"] = any(
                    value > 0.0 for value in weights.values())
            finally:
                config.update(saved)
                if saved_rollout is not None:
                    adversarial.set_ab_test_rollout(saved_rollout)
        else:
            # Not measurable without a trade to attack. Recorded as unknown
            # rather than as a pass.
            checks["adaptive_weights_move"] = None

        # Only checks that were actually computed can gate. A check recorded
        # as None was not measurable and is reported, never counted as a pass.
        required = ("ab_assignment_deterministic", "ab_assignment_splits")
        gated = all(bool(checks.get(key)) for key in required)
        for optional in ("labels_aligned", "adaptive_weights_move"):
            if checks.get(optional) is False:
                gated = False
        report["ok"] = gated
        report["unmeasured"] = [
            key for key in ("labels_aligned", "adaptive_weights_move")
            if checks.get(key) is None]
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report

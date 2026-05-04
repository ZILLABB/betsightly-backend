from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from services.risk_scorer import RiskScorer, SAFE_RISK_THRESHOLD, SAFE_CONFIDENCE_THRESHOLD
except ImportError:
    from risk_scorer import RiskScorer, SAFE_RISK_THRESHOLD, SAFE_CONFIDENCE_THRESHOLD


class AccumulatorBuilder:
    '''
    Accumulator Builder -- Safe Games Only.
    Greedy: combine many safe low-odds games until combined odds hits target range.
    Example for 10_odds: 10 games at 1.28 each = 10.0 total odds.
    Never uses risky games just to hit an odds target.
    '''

    TARGET_ODDS = {
        '2_odds':   {'min': 1.80, 'max': 2.50},
        '5_odds':   {'min': 4.50, 'max': 6.00},
        '10_odds':  {'min': 8.00, 'max': 15.00},
        'rollover': {'min': 2.00, 'max': 3.00},
    }
    MAX_GAMES = 15

    def __init__(self, risk_threshold=SAFE_RISK_THRESHOLD, confidence_threshold=SAFE_CONFIDENCE_THRESHOLD):
        self.risk_scorer = RiskScorer()
        self.risk_threshold = risk_threshold
        self.confidence_threshold = confidence_threshold

    def build_accumulators(self, predictions):
        try:
            selections = self._extract_and_score(predictions)
            safe_pool = [s for s in selections if s.get('is_safe', False)]
            logger.info('Accumulator: %d analyzed, %d confident, %d safe',
                        len(predictions), len(selections), len(safe_pool))
            if not safe_pool:
                return {'status': 'no_safe_selections',
                        'total_games_analyzed': len(predictions), 'safe_selections': 0,
                        'accumulators': self._empty_accumulators('No safe selections found'),
                        'summary': self._summary({})}
            accumulators = {cat: self._build_category(safe_pool, cat, t)
                            for cat, t in self.TARGET_ODDS.items()}
            return {'status': 'success', 'total_games_analyzed': len(predictions),
                    'high_confidence_selections': len(selections), 'safe_selections': len(safe_pool),
                    'accumulators': accumulators, 'summary': self._summary(accumulators)}
        except Exception as e:
            logger.error('AccumulatorBuilder error: %s', e, exc_info=True)
            return {'status': 'error', 'message': str(e),
                    'accumulators': self._empty_accumulators('Internal error')}

    def _extract_and_score(self, predictions):
        selections = []
        for pred in predictions:
            fi = pred.get('fixture_info', {})
            ml = pred.get('ml_predictions', {})
            best = None
            for pk, pd in ml.items():
                conf = pd.get('confidence', 0.0)
                if conf < self.confidence_threshold:
                    continue
                if best is None or conf > best.get('confidence', 0):
                    val = str(pd.get('prediction', ''))
                    best = {
                        'fixture_id': fi.get('fixture_id'),
                        'home_team': fi.get('home_team', ''),
                        'away_team': fi.get('away_team', ''),
                        'league': fi.get('league', ''),
                        'date': fi.get('date', ''),
                        'prediction_type': pd.get('model_name', pk),
                        'prediction_value': val,
                        'readable_prediction': self._fmt_readable(val),
                        'confidence': conf,
                        'estimated_odds': self._conf_to_odds(conf),
                        'model_type': pd.get('model_type', ''),
                        'raw_prediction': pd.get('prediction'),
                        'model_disagreement': pd.get('model_disagreement', 0.0),
                        'elo_gap': pd.get('elo_gap', 0.0),
                        'probabilities': pd.get('probabilities', {}),
                    }
            if best is not None:
                selections.append(self.risk_scorer.score_and_annotate(best))
        return sorted(selections, key=lambda x: x.get('risk_score', 1.0))

    def _build_category(self, safe_pool, category, target):
        min_odds, max_odds = target['min'], target['max']
        if not safe_pool:
            return self._no(category, min_odds, max_odds, 'No safe games available')
        chosen = []; running_odds = 1.0; used = set()
        for g in safe_pool:
            if len(chosen) >= self.MAX_GAMES: break
            fid = g.get('fixture_id')
            if fid in used: continue
            proj = running_odds * g.get('estimated_odds', 1.5)
            if proj <= max_odds:
                chosen.append(g); running_odds = proj
                if fid is not None: used.add(fid)
                if running_odds >= min_odds: break
        if running_odds < min_odds:
            for g in safe_pool:
                if len(chosen) >= self.MAX_GAMES: break
                fid = g.get('fixture_id')
                if fid in used: continue
                proj = running_odds * g.get('estimated_odds', 1.5)
                if proj <= max_odds * 1.10:
                    chosen.append(g); running_odds = proj
                    if fid is not None: used.add(fid)
                    if running_odds >= min_odds: break
        if not chosen or running_odds < min_odds * 0.85:
            return self._no(category, min_odds, max_odds,
                            'Could not reach %.2f odds with safe games only (best: %.2f)' % (min_odds, running_odds))
        avg_conf = sum(g['confidence'] for g in chosen) / len(chosen)
        avg_risk = sum(g.get('risk_score', 0) for g in chosen) / len(chosen)
        return {'selected': True, 'category': category,
                'games': [self._fmt_game(g) for g in chosen],
                'total_odds': round(running_odds, 3),
                'target_range': '%s-%s' % (min_odds, max_odds),
                'num_games': len(chosen), 'average_confidence': round(avg_conf, 4),
                'average_risk_score': round(avg_risk, 4), 'risk_level': self._risk_label(avg_risk),
                'recommendation': 'INCLUDE', 'strategy': 'safe_greedy'}

    def _conf_to_odds(self, c):
        if c >= 0.95: return 1.05
        elif c >= 0.92: return 1.10
        elif c >= 0.88: return 1.20
        elif c >= 0.85: return 1.30
        elif c >= 0.82: return 1.40
        elif c >= 0.80: return 1.50
        elif c >= 0.78: return 1.60
        elif c >= 0.75: return 1.75
        elif c >= 0.72: return 1.90
        elif c >= 0.70: return 2.10
        elif c >= 0.65: return 2.50
        elif c >= 0.60: return 3.00
        else: return 4.00

    def _fmt_readable(self, value):
        m = {'home_win': 'Home Win', 'away_win': 'Away Win', 'draw': 'Draw',
             'yes': 'BTTS Yes', 'no': 'BTTS No'}
        if 'over' in value.lower():
            return 'Over %s goals' % value.replace('over_', '').replace('_', '.')
        if 'under' in value.lower():
            return 'Under %s goals' % value.replace('under_', '').replace('_', '.')
        return m.get(value, value.replace('_', ' ').title())

    def _fmt_game(self, g):
        return {'fixture_id': g.get('fixture_id'), 'home_team': g.get('home_team'),
                'away_team': g.get('away_team'), 'league': g.get('league'), 'date': g.get('date'),
                'prediction': g.get('readable_prediction', g.get('prediction_value', '')),
                'confidence': g.get('confidence'), 'estimated_odds': g.get('estimated_odds'),
                'risk_score': g.get('risk_score'), 'risk_level': g.get('risk_level')}

    @staticmethod
    def _risk_label(r):
        if r <= 0.15: return 'VERY_LOW'
        elif r <= 0.25: return 'LOW'
        elif r <= 0.40: return 'MEDIUM'
        else: return 'HIGH'

    def _no(self, cat, mn, mx, reason):
        return {'selected': False, 'category': cat,
                'target_range': '%s-%s' % (mn, mx), 'reason': reason, 'recommendation': 'EXCLUDE'}

    def _empty_accumulators(self, reason):
        return {cat: self._no(cat, t['min'], t['max'], reason) for cat, t in self.TARGET_ODDS.items()}

    def _summary(self, accumulators):
        sel = [a for a in accumulators.values() if a.get('selected', False)]
        return {'categories_with_accumulators': len(sel), 'total_categories': len(self.TARGET_ODDS),
                'total_games_in_accumulators': sum(a.get('num_games', 0) for a in sel),
                'success_rate': '%.1f%%' % (len(sel)/max(len(self.TARGET_ODDS),1)*100),
                'strategy': 'safe_games_only'}


def format_accumulator_for_display(result):
    lines = ['Accumulator Result (%s)' % result.get('status', 'unknown')]
    for cat, acc in result.get('accumulators', {}).items():
        if acc.get('selected'):
            lines.append('  %s: %d games @ %.2f odds (avg conf: %.1f%%, risk: %s)' % (
                cat, acc['num_games'], acc['total_odds'], acc['average_confidence']*100, acc['risk_level']))
        else:
            lines.append('  %s: NOT SELECTED - %s' % (cat, acc.get('reason', '')))
    return chr(10).join(lines)

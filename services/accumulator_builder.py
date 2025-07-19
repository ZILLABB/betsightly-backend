"""
Accumulator Builder Service
Combines multiple games to create accumulator bets that reach target odds.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from itertools import combinations
import json

# Set up logging
logger = logging.getLogger(__name__)

class AccumulatorBuilder:
    """Build accumulator bets by combining multiple games to reach target odds."""
    
    def __init__(self):
        """Initialize the accumulator builder."""
        self.target_odds = {
            '2_odds': {'min': 1.8, 'max': 2.5},
            '5_odds': {'min': 4.5, 'max': 6.0},
            '10_odds': {'min': 8.0, 'max': 15.0},  # Wider range, lower minimum
            'rollover': {'min': 2.0, 'max': 3.0}  # Conservative for next day
        }

        # Minimum confidence for including in accumulators
        self.min_confidence = 0.70  # Lower threshold for 10-odds
        
        # Maximum games per accumulator
        self.max_games_per_accumulator = 5
    
    def build_accumulators(self, predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build accumulator bets from multiple game predictions.
        
        Args:
            predictions: List of game predictions with ML data
            
        Returns:
            Dictionary with accumulator combinations for each category
        """
        try:
            logger.info(f"🎯 Building accumulators from {len(predictions)} games")
            
            # Extract high-confidence selections from all games
            selections = self._extract_selections(predictions)
            logger.info(f"📊 Found {len(selections)} high-confidence selections")
            
            if len(selections) == 0:
                return self._empty_accumulators("No high-confidence selections found")
            
            # Build accumulators for each category
            accumulators = {}
            
            for category, target in self.target_odds.items():
                accumulator = self._build_category_accumulator(selections, category, target)
                accumulators[category] = accumulator
                
                if accumulator['selected']:
                    logger.info(f"✅ {category}: {len(accumulator['games'])} games, {accumulator['total_odds']:.2f} odds")
                else:
                    logger.info(f"❌ {category}: {accumulator['reason']}")
            
            return {
                'status': 'success',
                'total_games_analyzed': len(predictions),
                'high_confidence_selections': len(selections),
                'accumulators': accumulators,
                'summary': self._generate_summary(accumulators)
            }
            
        except Exception as e:
            logger.error(f"Error building accumulators: {str(e)}")
            return {
                'status': 'error',
                'message': str(e),
                'accumulators': self._empty_accumulators("Error occurred")
            }
    
    def _extract_selections(self, predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract predictions with variety for all accumulator types."""
        selections = []

        for prediction in predictions:
            fixture_info = prediction.get('fixture_info', {})
            ml_predictions = prediction.get('ml_predictions', {})

            # Get ALL predictions above minimum confidence
            game_predictions = []

            for pred_key, pred_data in ml_predictions.items():
                confidence = pred_data.get('confidence', 0)

                if confidence >= self.min_confidence:
                    estimated_odds = self._confidence_to_odds(confidence)

                    selection = {
                        'fixture_id': fixture_info.get('fixture_id'),
                        'home_team': fixture_info.get('home_team'),
                        'away_team': fixture_info.get('away_team'),
                        'league': fixture_info.get('league'),
                        'date': fixture_info.get('date'),
                        'prediction_type': pred_data.get('model_name', pred_key),
                        'prediction_value': self._format_prediction_value(pred_data),
                        'confidence': confidence,
                        'estimated_odds': estimated_odds,
                        'model_type': pred_data.get('model_type'),
                        'raw_prediction': pred_data.get('prediction'),
                        'readable_prediction': self._format_readable_prediction(pred_data.get('model_name', pred_key), self._format_prediction_value(pred_data))
                    }
                    game_predictions.append(selection)

            # Sort by confidence and add multiple predictions per game
            game_predictions.sort(key=lambda x: x['confidence'], reverse=True)

            # Add best prediction (for conservative accumulators)
            if game_predictions:
                selections.append(game_predictions[0])

                # Add additional predictions for 10-odds variety
                for i, pred in enumerate(game_predictions[1:], 1):
                    # Include if confidence is significantly different (for higher odds)
                    if pred['confidence'] < game_predictions[0]['confidence'] - 0.10:  # 10% difference
                        # Mark as alternative for this fixture
                        pred['fixture_id'] = str(pred['fixture_id']) + f'_alt{i}'
                        selections.append(pred)

                        # Limit alternatives per game
                        if i >= 2:
                            break

        # Sort by confidence (highest first)
        selections.sort(key=lambda x: x['confidence'], reverse=True)

        return selections
    
    def _confidence_to_odds(self, confidence: float) -> float:
        """Convert confidence to estimated odds with more variety for 10-odds."""
        # Higher confidence = lower odds (more likely to happen)
        if confidence >= 0.95:
            return 1.1
        elif confidence >= 0.90:
            return 1.2
        elif confidence >= 0.85:
            return 1.4
        elif confidence >= 0.80:
            return 1.6
        elif confidence >= 0.75:
            return 1.9  # Increased for better 10-odds combinations
        elif confidence >= 0.70:
            return 2.3  # Increased for better 10-odds combinations
        elif confidence >= 0.65:
            return 2.8  # Higher odds for lower confidence
        elif confidence >= 0.60:
            return 3.5  # Even higher odds
        else:
            return 4.0  # Maximum odds for very low confidence
    
    def _format_prediction_value(self, pred_data: Dict) -> str:
        """Format prediction value for display."""
        prediction = pred_data.get('prediction', 0)
        model_name = pred_data.get('model_name', '')

        if 'match_result' in model_name:
            return ['Home Win', 'Away Win', 'Draw'][prediction] if prediction < 3 else 'Unknown'
        elif 'btts' in model_name:
            return 'Yes' if prediction == 1 else 'No'
        elif 'clean_sheet' in model_name:
            return 'Yes' if prediction == 1 else 'No'
        elif 'over' in model_name:
            return 'Yes' if prediction == 1 else 'No'
        elif 'win_to_nil' in model_name:
            return 'Yes' if prediction == 1 else 'No'
        else:
            return str(prediction)

    def _format_readable_prediction(self, prediction_type: str, prediction_value: str) -> str:
        """Format prediction into human-readable text."""
        predictions = {
            'over_2_5': {
                'Yes': 'Over 2.5 Goals',
                'No': 'Under 2.5 Goals'
            },
            'over_1_5': {
                'Yes': 'Over 1.5 Goals',
                'No': 'Under 1.5 Goals'
            },
            'over_3_5': {
                'Yes': 'Over 3.5 Goals',
                'No': 'Under 3.5 Goals'
            },
            'btts': {
                'Yes': 'Both Teams to Score',
                'No': 'Both Teams NOT to Score'
            },
            'clean_sheet_home': {
                'Yes': 'Home Clean Sheet',
                'No': 'Home NO Clean Sheet'
            },
            'clean_sheet_away': {
                'Yes': 'Away Clean Sheet',
                'No': 'Away NO Clean Sheet'
            },
            'win_to_nil_home': {
                'Yes': 'Home Win to Nil',
                'No': 'Home NOT Win to Nil'
            },
            'win_to_nil_away': {
                'Yes': 'Away Win to Nil',
                'No': 'Away NOT Win to Nil'
            },
            'match_result': {
                'Home Win': 'Home Win',
                'Away Win': 'Away Win',
                'Draw': 'Draw'
            }
        }

        return predictions.get(prediction_type, {}).get(prediction_value, f"{prediction_type}: {prediction_value}")
    
    def _build_category_accumulator(self, selections: List[Dict], category: str, target: Dict) -> Dict[str, Any]:
        """Build accumulator for a specific category."""
        min_odds = target['min']
        max_odds = target['max']
        
        # Try different combinations to reach target odds
        best_combination = None
        best_odds = 0
        
        # Try combinations of 1 to max_games_per_accumulator games
        for num_games in range(1, min(len(selections) + 1, self.max_games_per_accumulator + 1)):
            for combination in combinations(selections, num_games):
                # Calculate total odds (multiply individual odds)
                total_odds = 1.0
                for selection in combination:
                    total_odds *= selection['estimated_odds']
                
                # Check if this combination fits the target
                if min_odds <= total_odds <= max_odds:
                    # Prefer combinations with higher total confidence
                    total_confidence = sum(s['confidence'] for s in combination) / len(combination)
                    
                    if best_combination is None or total_confidence > best_combination['avg_confidence']:
                        best_combination = {
                            'games': list(combination),
                            'total_odds': total_odds,
                            'avg_confidence': total_confidence,
                            'num_games': len(combination)
                        }
        
        if best_combination:
            return {
                'selected': True,
                'category': category,
                'games': best_combination['games'],
                'total_odds': round(best_combination['total_odds'], 2),
                'average_confidence': round(best_combination['avg_confidence'], 3),
                'num_games': best_combination['num_games'],
                'target_range': f"{min_odds}-{max_odds}",
                'risk_level': self._get_category_risk(category),
                'recommendation': 'INCLUDE'
            }
        else:
            return {
                'selected': False,
                'category': category,
                'reason': f'No combination found for {min_odds}-{max_odds} odds range',
                'target_range': f"{min_odds}-{max_odds}",
                'recommendation': 'EXCLUDE'
            }
    
    def _get_category_risk(self, category: str) -> str:
        """Get risk level for category."""
        risk_mapping = {
            '2_odds': 'VERY_LOW',
            '5_odds': 'LOW', 
            '10_odds': 'MEDIUM',
            'rollover': 'VERY_LOW'
        }
        return risk_mapping.get(category, 'UNKNOWN')
    
    def _empty_accumulators(self, reason: str) -> Dict[str, Any]:
        """Return empty accumulators structure."""
        empty_accumulators = {}
        for category in self.target_odds.keys():
            empty_accumulators[category] = {
                'selected': False,
                'category': category,
                'reason': reason,
                'recommendation': 'EXCLUDE'
            }
        return empty_accumulators
    
    def _generate_summary(self, accumulators: Dict) -> Dict[str, Any]:
        """Generate summary of accumulator results."""
        selected_count = sum(1 for acc in accumulators.values() if acc.get('selected', False))
        total_games_used = sum(acc.get('num_games', 0) for acc in accumulators.values() if acc.get('selected', False))
        
        return {
            'categories_with_accumulators': selected_count,
            'total_categories': len(accumulators),
            'total_games_in_accumulators': total_games_used,
            'success_rate': f"{(selected_count/len(accumulators)*100):.1f}%"
        }

def format_accumulator_for_display(accumulator: Dict) -> str:
    """Format accumulator for display."""
    if not accumulator.get('selected', False):
        return f"{accumulator['category']}: Not selected - {accumulator.get('reason', 'Unknown')}"
    
    games_text = []
    for game in accumulator['games']:
        game_text = f"{game['home_team']} vs {game['away_team']} ({game['prediction_type']}: {game['prediction_value']})"
        games_text.append(game_text)
    
    return f"""
{accumulator['category'].upper()} ACCUMULATOR:
├─ Total Odds: {accumulator['total_odds']}x
├─ Games: {accumulator['num_games']}
├─ Average Confidence: {accumulator['average_confidence']*100:.1f}%
├─ Risk Level: {accumulator['risk_level']}
└─ Games:
   {chr(10).join(f'   • {game}' for game in games_text)}
"""

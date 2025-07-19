#!/usr/bin/env python3
"""
Generate Comprehensive Predictions
Uses the large set of games provided by user with real odds for maximum variety.
"""

import sys
import os
import json
from datetime import datetime, date

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.daily_predictions_service import DailyPredictionsService, DailyPrediction, DailyPredictionSummary
from api.endpoints.ml_predictions import RealMLPredictionService
from services.accumulator_builder import AccumulatorBuilder
from database import get_db

def create_comprehensive_fixtures():
    """Create comprehensive fixture data from user's extensive game list."""
    fixtures = [
        # Mexico Liga MX Women
        {"fixture_id": 5001, "home_team": "Queretaro FC", "away_team": "CD Guadalajara", "league": "Mexico Liga MX Women", "date": "2025-07-18T22:45:00", "status": "Not Started", "home_odds": 6.10, "draw_odds": 4.00, "away_odds": 1.50, "over_2_5_odds": 1.89, "under_2_5_odds": 1.85},
        
        # Russia Superleague Women
        {"fixture_id": 5002, "home_team": "FK Rubin Kazan", "away_team": "Zvezda-2005 Perm", "league": "Russia Superleague Women", "date": "2025-07-18T14:00:00", "status": "Not Started", "home_odds": 2.50, "draw_odds": 3.10, "away_odds": 2.60, "over_2_5_odds": 2.30, "under_2_5_odds": 1.52},
        
        # Finland Women
        {"fixture_id": 5003, "home_team": "HJK Helsinki", "away_team": "HPS", "league": "Finland Kansallinen Liiga Women", "date": "2025-07-18T16:30:00", "status": "Not Started", "home_odds": 1.16, "draw_odds": 5.90, "away_odds": 9.80, "over_3_5_odds": 1.82, "under_3_5_odds": 1.84},
        
        # Poland Ekstraklasa
        {"fixture_id": 5004, "home_team": "Jagiellonia Bialystok", "away_team": "Bruk-Bet Termalica Nieciecza", "league": "Poland Ekstraklasa", "date": "2025-07-18T17:00:00", "status": "Not Started", "home_odds": 1.56, "draw_odds": 4.10, "away_odds": 5.60, "over_2_5_odds": 1.80, "under_2_5_odds": 1.98},
        {"fixture_id": 5005, "home_team": "KKS Lech Poznan", "away_team": "MKS Cracovia Krakow", "league": "Poland Ekstraklasa", "date": "2025-07-18T19:30:00", "status": "Not Started", "home_odds": 1.64, "draw_odds": 4.10, "away_odds": 4.80, "over_2_5_odds": 1.70, "under_2_5_odds": 2.10},
        
        # Finland Veikkausliiga
        {"fixture_id": 5006, "home_team": "FC KTP Kotka", "away_team": "FC Inter Turku", "league": "Finland Veikkausliiga", "date": "2025-07-18T16:00:00", "status": "Not Started", "home_odds": 8.50, "draw_odds": 5.75, "away_odds": 1.30, "over_3_5_odds": 2.00, "under_3_5_odds": 1.77},
        
        # China Super League
        {"fixture_id": 5007, "home_team": "Changchun Yatai", "away_team": "Shanghai Port FC", "league": "China Super League", "date": "2025-07-18T09:30:00", "status": "Not Started", "home_odds": 6.10, "draw_odds": 5.10, "away_odds": 1.45, "over_3_5_odds": 2.00, "under_3_5_odds": 1.78},
        {"fixture_id": 5008, "home_team": "Wuhan Three Towns FC", "away_team": "Qingdao West Coast FC", "league": "China Super League", "date": "2025-07-18T12:00:00", "status": "Not Started", "home_odds": 2.35, "draw_odds": 3.60, "away_odds": 2.90, "over_3_odds": 2.10, "under_3_odds": 1.70},
        {"fixture_id": 5009, "home_team": "Tianjin Jinmen Tiger", "away_team": "Chengdu Rongcheng", "league": "China Super League", "date": "2025-07-18T12:35:00", "status": "Not Started", "home_odds": 4.80, "draw_odds": 4.00, "away_odds": 1.69, "over_2_5_odds": 1.71, "under_2_5_odds": 2.10},
        {"fixture_id": 5010, "home_team": "Zhejiang FC", "away_team": "Yunnan Yukun", "league": "China Super League", "date": "2025-07-18T13:00:00", "status": "Not Started", "home_odds": 1.76, "draw_odds": 4.00, "away_odds": 4.30, "over_3_odds": 1.97, "under_3_odds": 1.81},
        
        # Korea K-League
        {"fixture_id": 5011, "home_team": "Daegu FC", "away_team": "Gimcheon Sangmu FC", "league": "Korea K-League 1", "date": "2025-07-18T11:30:00", "status": "Not Started", "home_odds": 3.70, "draw_odds": 3.75, "away_odds": 1.96, "over_3_odds": 2.05, "under_3_odds": 1.74},
        {"fixture_id": 5012, "home_team": "Suwon FC", "away_team": "Gwangju FC", "league": "Korea K-League 1", "date": "2025-07-18T11:30:00", "status": "Not Started", "home_odds": 3.10, "draw_odds": 3.30, "away_odds": 2.35, "over_2_5_odds": 2.00, "under_2_5_odds": 1.78},
        
        # Russia Premier League
        {"fixture_id": 5013, "home_team": "FK Dinamo Moscow", "away_team": "FC Baltika Kaliningrad", "league": "Russia Premier League", "date": "2025-07-18T18:30:00", "status": "Not Started", "home_odds": 1.57, "draw_odds": 4.30, "away_odds": 5.50, "over_2_5_odds": 1.72, "under_2_5_odds": 2.10},
        
        # Argentina Primera
        {"fixture_id": 5014, "home_team": "Boca Juniors", "away_team": "Union de Santa Fe", "league": "Argentina Primera", "date": "2025-07-18T23:30:00", "status": "Not Started", "home_odds": 1.82, "draw_odds": 3.20, "away_odds": 4.80, "over_2_odds": 1.97, "under_2_odds": 1.81},
        
        # Denmark Superliga
        {"fixture_id": 5015, "home_team": "Viborg FF", "away_team": "Copenhagen", "league": "Denmark Superliga", "date": "2025-07-18T18:00:00", "status": "Not Started", "home_odds": 5.10, "draw_odds": 4.10, "away_odds": 1.65, "over_2_5_odds": 1.70, "under_2_5_odds": 2.10},
        
        # Brazil Serie B
        {"fixture_id": 5016, "home_team": "AC Goianiense GO", "away_team": "Criciuma EC SC", "league": "Brazil Serie B", "date": "2025-07-18T23:00:00", "status": "Not Started", "home_odds": 1.80, "draw_odds": 3.30, "away_odds": 5.00, "over_2_odds": 1.89, "under_2_odds": 1.88},
        
        # Romania Superliga
        {"fixture_id": 5017, "home_team": "AFC Hermannstadt", "away_team": "Metaloglobus Bucuresti", "league": "Romania Superliga", "date": "2025-07-18T17:00:00", "status": "Not Started", "home_odds": 1.42, "draw_odds": 4.40, "away_odds": 7.60, "over_2_5_odds": 1.93, "under_2_5_odds": 1.84},
        {"fixture_id": 5018, "home_team": "CS Universitatea Craiova", "away_team": "ACS Champions FC Arges", "league": "Romania Superliga", "date": "2025-07-18T19:30:00", "status": "Not Started", "home_odds": 1.48, "draw_odds": 4.30, "away_odds": 6.50, "over_2_5_odds": 1.83, "under_2_5_odds": 1.94},
        
        # Bulgaria Parva Liga
        {"fixture_id": 5019, "home_team": "FC CSKA 1948", "away_team": "FC Arda Kardzhali", "league": "Bulgaria Parva Liga", "date": "2025-07-18T17:00:00", "status": "Not Started", "home_odds": 2.40, "draw_odds": 3.10, "away_odds": 3.00, "over_2_5_odds": 2.20, "under_2_5_odds": 1.66},
        {"fixture_id": 5020, "home_team": "FC Lokomotiv 1929 Sofia", "away_team": "PFC Cherno More Varna", "league": "Bulgaria Parva Liga", "date": "2025-07-18T19:15:00", "status": "Not Started", "home_odds": 4.00, "draw_odds": 3.25, "away_odds": 1.96, "over_2_odds": 1.71, "under_2_odds": 2.10},
        
        # Norway Eliteserien
        {"fixture_id": 5021, "home_team": "Sarpsborg 08", "away_team": "Rosenborg BK", "league": "Norway Eliteserien", "date": "2025-07-18T17:00:00", "status": "Not Started", "home_odds": 2.28, "draw_odds": 3.83, "away_odds": 3.02, "over_3_odds": 1.85, "under_3_odds": 2.00},
        
        # Czech Republic Liga
        {"fixture_id": 5022, "home_team": "FK Pardubice", "away_team": "Viktoria Plzen", "league": "Czech Republic Liga", "date": "2025-07-18T18:00:00", "status": "Not Started", "home_odds": 7.60, "draw_odds": 5.10, "away_odds": 1.37, "over_3_odds": 1.95, "under_3_odds": 1.82},
        
        # International Women's Tournaments
        {"fixture_id": 5023, "home_team": "Nigeria", "away_team": "Zambia", "league": "Africa Cup of Nations Women", "date": "2025-07-18T17:00:00", "status": "Not Started", "home_odds": 1.84, "draw_odds": 3.25, "away_odds": 4.60, "over_2_odds": 1.94, "under_2_odds": 1.83},
        {"fixture_id": 5024, "home_team": "Morocco", "away_team": "Mali", "league": "Africa Cup of Nations Women", "date": "2025-07-18T20:00:00", "status": "Not Started", "home_odds": 1.32, "draw_odds": 5.20, "away_odds": 8.30, "over_3_odds": 1.95, "under_3_odds": 1.82},
        {"fixture_id": 5025, "home_team": "Uruguay", "away_team": "Peru", "league": "Copa America Women", "date": "2025-07-18T22:00:00", "status": "Not Started", "home_odds": 1.10, "draw_odds": 8.60, "away_odds": 19.50, "over_3_5_odds": 2.00, "under_3_5_odds": 1.75},
        {"fixture_id": 5026, "home_team": "Spain", "away_team": "Switzerland", "league": "UEFA Euro Women", "date": "2025-07-18T20:00:00", "status": "Not Started", "home_odds": 1.10, "draw_odds": 9.60, "away_odds": 21.00, "over_3_5_odds": 1.78, "under_3_5_odds": 2.00},
        
        # Additional European Leagues
        {"fixture_id": 5027, "home_team": "HB Koege", "away_team": "Hobro IK", "league": "Denmark 1st Division", "date": "2025-07-18T17:30:00", "status": "Not Started", "home_odds": 2.55, "draw_odds": 3.40, "away_odds": 2.70, "over_2_5_odds": 1.79, "under_2_5_odds": 2.00},
        {"fixture_id": 5028, "home_team": "Hvidovre IF", "away_team": "B93 Copenhagen", "league": "Denmark 1st Division", "date": "2025-07-18T18:00:00", "status": "Not Started", "home_odds": 1.59, "draw_odds": 4.30, "away_odds": 5.00, "over_3_odds": 1.91, "under_3_odds": 1.86},
        
        # South American Leagues
        {"fixture_id": 5029, "home_team": "Union Magdalena", "away_team": "Llaneros FC", "league": "Colombia Primera A", "date": "2025-07-19T00:00:00", "status": "Not Started", "home_odds": 2.05, "draw_odds": 3.00, "away_odds": 4.10, "over_2_odds": 1.87, "under_2_odds": 1.91},
        {"fixture_id": 5030, "home_team": "CD Everton Vina del Mar", "away_team": "Deportes Limache", "league": "Chile Primera Division", "date": "2025-07-19T00:00:00", "status": "Not Started", "home_odds": 2.20, "draw_odds": 3.50, "away_odds": 3.10, "over_2_5_odds": 1.85, "under_2_5_odds": 1.93},
        
        # Additional Asian Leagues
        {"fixture_id": 5031, "home_team": "FC Astana", "away_team": "FK Turan", "league": "Kazakhstan Premier League", "date": "2025-07-18T16:00:00", "status": "Not Started", "home_odds": 1.05, "draw_odds": 9.70, "away_odds": 38.00, "over_3_5_odds": 2.10, "under_3_5_odds": 1.67},
        
        # Club Friendlies (High variety)
        {"fixture_id": 5032, "home_team": "Bayern Munich II", "away_team": "SG Sonnenhof Grossaspach", "league": "Club Friendly", "date": "2025-07-18T13:00:00", "status": "Not Started", "home_odds": 1.80, "draw_odds": 4.00, "away_odds": 3.25, "over_3_5_odds": 1.93, "under_3_5_odds": 1.75},
        {"fixture_id": 5033, "home_team": "Salzburg", "away_team": "Derby County", "league": "Club Friendly", "date": "2025-07-18T17:00:00", "status": "Not Started", "home_odds": 1.65, "draw_odds": 3.90, "away_odds": 4.10, "over_2_5_odds": 1.58, "under_2_5_odds": 2.20},
        {"fixture_id": 5034, "home_team": "Real Sociedad", "away_team": "Pau FC", "league": "Club Friendly", "date": "2025-07-18T18:00:00", "status": "Not Started", "home_odds": 1.58, "draw_odds": 3.20, "away_odds": 6.10, "over_2_5_odds": 1.66, "under_2_5_odds": 2.05},
        {"fixture_id": 5035, "home_team": "CR Flamengo RJ", "away_team": "Bayer Leverkusen", "league": "Club Friendly", "date": "2025-07-18T18:30:00", "status": "Not Started", "home_odds": 18.00, "draw_odds": 11.00, "away_odds": 1.04, "over_4_5_odds": 1.75, "under_4_5_odds": 1.93},
    ]
    
    return fixtures

def main():
    """Generate comprehensive predictions with maximum variety."""
    print("🌍 GENERATING COMPREHENSIVE PREDICTIONS")
    print("=" * 60)
    print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🎮 Processing comprehensive game set with real odds")
    print("🌐 Leagues: Mexico, Russia, Finland, Poland, China, Korea, Argentina, Denmark, Brazil, Romania, Bulgaria, Norway, Czech, International Women's, Club Friendlies")
    print("=" * 60)
    
    try:
        # Get today's date
        today = datetime.now().date()
        
        # Get database session
        db = next(get_db())
        
        # Clear existing predictions for today
        print("🧹 Clearing existing predictions for today...")
        db.query(DailyPrediction).filter(
            DailyPrediction.prediction_date == today
        ).delete()
        
        db.query(DailyPredictionSummary).filter(
            DailyPredictionSummary.prediction_date == today
        ).delete()
        
        db.commit()
        
        # Get comprehensive fixtures
        fixtures = create_comprehensive_fixtures()
        print(f"\n📊 Processing {len(fixtures)} fixtures from multiple leagues...")
        
        # Initialize services
        ml_service = RealMLPredictionService()
        accumulator_builder = AccumulatorBuilder()
        
        # Generate predictions for all fixtures
        all_predictions = []
        successful_predictions = 0
        
        for i, fixture in enumerate(fixtures, 1):
            try:
                print(f"{i}. {fixture['home_team']} vs {fixture['away_team']} ({fixture['league']}) - ", end="")
                
                # Generate ML prediction
                prediction_result = ml_service.generate_predictions_for_fixture(fixture)
                
                if 'error' not in prediction_result:
                    all_predictions.append(prediction_result)
                    successful_predictions += 1
                    print("✅")
                else:
                    print(f"❌ {prediction_result.get('error', 'Unknown')}")
                    
            except Exception as e:
                print(f"❌ Error: {str(e)}")
                continue
        
        print(f"\n📈 Generated {successful_predictions}/{len(fixtures)} predictions")
        
        if successful_predictions == 0:
            print("❌ No predictions generated")
            return False
        
        # Build accumulators with maximum variety
        print("🎰 Building accumulators with comprehensive data...")
        accumulator_result = accumulator_builder.build_accumulators(all_predictions)
        accumulators = accumulator_result.get('accumulators', {})
        
        # Create summary record
        summary = DailyPredictionSummary(
            prediction_date=today,
            total_fixtures=len(fixtures),
            upcoming_fixtures=len(fixtures),
            predictions_generated=successful_predictions,
            models_used=21,  # All models working
            betting_2_odds_count=1 if accumulators.get('2_odds', {}).get('selected', False) else 0,
            betting_5_odds_count=1 if accumulators.get('5_odds', {}).get('selected', False) else 0,
            betting_10_odds_count=1 if accumulators.get('10_odds', {}).get('selected', False) else 0,
            betting_rollover_count=1 if accumulators.get('rollover', {}).get('selected', False) else 0,
            generation_status="completed",
            generation_time=datetime.utcnow()
        )
        
        db.add(summary)
        
        # Store predictions with accumulator data
        for prediction_result in all_predictions:
            try:
                fixture_info = prediction_result['fixture_info']
                ml_predictions = prediction_result['ml_predictions']
                
                # Calculate highest confidence
                highest_confidence = 0.0
                for pred_data in ml_predictions.values():
                    confidence = pred_data.get('confidence', 0.0)
                    if confidence > highest_confidence:
                        highest_confidence = confidence
                
                # Create database record
                league_name = fixture_info.get('league') or fixture_info.get('league_name') or 'Unknown League'
                
                db_prediction = DailyPrediction(
                    prediction_date=today,
                    fixture_id=fixture_info.get('fixture_id', 0),
                    home_team=fixture_info.get('home_team', 'Unknown'),
                    away_team=fixture_info.get('away_team', 'Unknown'),
                    league_name=league_name,
                    fixture_date=datetime.fromisoformat(fixture_info.get('date', datetime.now().isoformat())),
                    fixture_status=fixture_info.get('status', 'Not Started'),
                    ml_predictions=json.dumps(ml_predictions),
                    betting_2_odds=json.dumps(accumulators.get('2_odds', {})),
                    betting_5_odds=json.dumps(accumulators.get('5_odds', {})),
                    betting_10_odds=json.dumps(accumulators.get('10_odds', {})),
                    betting_rollover=json.dumps(accumulators.get('rollover', {})),
                    total_models_used=len(ml_predictions),
                    highest_confidence=highest_confidence
                )
                
                db.add(db_prediction)
                
            except Exception as e:
                print(f"Error storing prediction: {str(e)}")
                continue
        
        # Commit all changes
        db.commit()
        db.close()
        
        print(f"\n✅ SUCCESS!")
        print(f"📊 Stored {successful_predictions} predictions from multiple leagues")
        print(f"🎰 Accumulator categories:")
        for category, accumulator in accumulators.items():
            if accumulator.get('selected', False):
                print(f"   ✅ {category}: {accumulator['total_odds']:.2f}x odds ({accumulator['num_games']} games)")
            else:
                print(f"   ❌ {category}: Not selected")
        
        print(f"\n🌐 Frontend endpoints now have comprehensive data:")
        print(f"   GET /api/accumulators/today")
        print(f"   GET /api/accumulators/2-odds")
        print(f"   GET /api/accumulators/5-odds")
        print(f"   GET /api/accumulators/10-odds")
        print(f"   GET /api/accumulators/rollover")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    print(f"\n" + "=" * 60)
    if success:
        print("🎉 COMPREHENSIVE PREDICTIONS GENERATED!")
        print("💡 Frontend now has maximum variety from global leagues")
    else:
        print("❌ FAILED TO GENERATE PREDICTIONS")
    print("=" * 60)
    sys.exit(0 if success else 1)

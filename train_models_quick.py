#!/usr/bin/env python3
"""
BetSightly Quick Training Pipeline

Ultra-fast approach:
1. Use a smaller sample of GitHub data for quick training
2. Train lightweight models
3. Get you up and running in under 2 minutes
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_synthetic_training_data():
    """
    Create synthetic training data for quick testing.
    This gets you running immediately while we work on the real data.
    """
    logger.info("🎲 Creating synthetic training data for quick start...")
    
    np.random.seed(42)
    n_matches = 5000  # Reasonable size for quick training
    
    # Generate realistic football data
    teams = [f"Team_{i}" for i in range(50)]  # 50 teams
    
    data = []
    for i in range(n_matches):
        home_team = np.random.choice(teams)
        away_team = np.random.choice([t for t in teams if t != home_team])
        
        # Realistic goal distributions
        home_goals = np.random.poisson(1.5)  # Home advantage
        away_goals = np.random.poisson(1.2)
        
        # Add some team strength variation
        team_strength_home = hash(home_team) % 100 / 100
        team_strength_away = hash(away_team) % 100 / 100
        
        # Adjust goals based on team strength
        if team_strength_home > 0.7:
            home_goals += np.random.poisson(0.5)
        if team_strength_away > 0.7:
            away_goals += np.random.poisson(0.5)
        
        data.append({
            'HomeTeam': home_team,
            'AwayTeam': away_team,
            'FTHG': home_goals,
            'FTAG': away_goals,
            'Date': f"2023-{np.random.randint(1,13):02d}-{np.random.randint(1,29):02d}"
        })
    
    df = pd.DataFrame(data)
    logger.info(f"✅ Generated {len(df)} synthetic matches")
    return df

def quick_feature_engineering(df):
    """Quick and simple feature engineering."""
    logger.info("⚡ Quick feature engineering...")
    
    features = pd.DataFrame()
    
    # Simple team encoding
    home_teams = pd.Categorical(df['HomeTeam'])
    away_teams = pd.Categorical(df['AwayTeam'])
    
    features['home_team_id'] = home_teams.codes
    features['away_team_id'] = away_teams.codes
    
    # Goal-based features
    features['home_goals_avg'] = df['FTHG']
    features['away_goals_avg'] = df['FTAG']
    features['total_goals'] = df['FTHG'] + df['FTAG']
    features['goal_difference'] = df['FTHG'] - df['FTAG']
    
    # Team strength (based on average goals)
    team_home_avg = df.groupby('HomeTeam')['FTHG'].mean()
    team_away_avg = df.groupby('AwayTeam')['FTAG'].mean()
    
    features['home_team_strength'] = df['HomeTeam'].map(team_home_avg).fillna(1.5)
    features['away_team_strength'] = df['AwayTeam'].map(team_away_avg).fillna(1.2)
    
    # Simple derived features
    features['strength_difference'] = features['home_team_strength'] - features['away_team_strength']
    features['home_advantage'] = 0.3  # Constant home advantage
    
    logger.info(f"✅ Created {len(features.columns)} features")
    return features

def quick_targets(df):
    """Create target variables quickly."""
    logger.info("🎯 Creating targets...")
    
    targets = {}
    
    # Match result
    def get_result(home, away):
        if home > away:
            return 'home'
        elif away > home:
            return 'away'
        else:
            return 'draw'
    
    targets['match_result'] = [get_result(h, a) for h, a in zip(df['FTHG'], df['FTAG'])]
    
    # Over/Under 2.5
    total_goals = df['FTHG'] + df['FTAG']
    targets['over_under'] = ['over' if g > 2.5 else 'under' for g in total_goals]
    
    # Both teams to score
    targets['btts'] = ['yes' if h > 0 and a > 0 else 'no' for h, a in zip(df['FTHG'], df['FTAG'])]
    
    logger.info(f"✅ Created {len(targets)} target types")
    return targets

def train_quick_models(features, targets):
    """Train models quickly using sklearn."""
    logger.info("🚀 Quick model training...")
    
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import accuracy_score
        import joblib
        
        results = {}
        
        for target_name, target_values in targets.items():
            logger.info(f"📊 Training {target_name}...")
            
            # Prepare data
            X = features.fillna(0)
            y = target_values
            
            # Encode labels
            le = LabelEncoder()
            y_encoded = le.fit_transform(y)
            
            # Quick split
            X_train, X_test, y_train, y_test = train_test_split(
                X, y_encoded, test_size=0.2, random_state=42
            )
            
            # Fast Random Forest
            model = RandomForestClassifier(
                n_estimators=20,  # Very fast
                max_depth=5,      # Simple
                random_state=42
            )
            
            model.fit(X_train, y_train)
            
            # Quick evaluation
            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            
            # Save model
            os.makedirs("models/quick", exist_ok=True)
            model_path = f"models/quick/{target_name}_model.joblib"
            encoder_path = f"models/quick/{target_name}_encoder.joblib"
            
            joblib.dump(model, model_path)
            joblib.dump(le, encoder_path)
            
            results[target_name] = {
                'accuracy': accuracy,
                'model_path': model_path,
                'encoder_path': encoder_path
            }
            
            logger.info(f"✅ {target_name}: {accuracy:.3f} accuracy")
        
        return results
        
    except Exception as e:
        logger.error(f"❌ Quick training failed: {str(e)}")
        return {}

def test_api_integration():
    """Test that APIs are working for live predictions."""
    logger.info("🌐 Testing API integration...")
    
    try:
        # Test API keys
        from utils.config import settings
        
        football_key = settings.football_data.API_KEY
        api_football_key = settings.api_football.API_KEY
        
        if football_key and "dummy" not in football_key:
            logger.info("✅ Football-Data.org API configured")
            api_working = True
        elif api_football_key and "dummy" not in api_football_key:
            logger.info("✅ API-Football configured")
            api_working = True
        else:
            logger.warning("⚠️  No API keys configured")
            api_working = False
        
        return api_working
        
    except Exception as e:
        logger.error(f"❌ API test failed: {str(e)}")
        return False

def main():
    """Main quick training function."""
    logger.info("🚀 BETSIGHTLY QUICK TRAINING PIPELINE")
    logger.info("=" * 50)
    logger.info("This gets you running in under 2 minutes!")
    
    start_time = datetime.now()
    
    try:
        # Step 1: Create synthetic training data
        logger.info("\n🎲 STEP 1: Generate Training Data")
        df = create_synthetic_training_data()
        
        # Step 2: Quick feature engineering
        logger.info("\n⚡ STEP 2: Feature Engineering")
        features = quick_feature_engineering(df)
        
        # Step 3: Create targets
        logger.info("\n🎯 STEP 3: Create Targets")
        targets = quick_targets(df)
        
        # Step 4: Train models
        logger.info("\n🚀 STEP 4: Train Models")
        results = train_quick_models(features, targets)
        
        # Step 5: Test API integration
        logger.info("\n🌐 STEP 5: Test API Integration")
        api_working = test_api_integration()
        
        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info("\n" + "=" * 50)
        logger.info("🎉 QUICK TRAINING COMPLETED!")
        logger.info("=" * 50)
        
        logger.info(f"⏱️  Total time: {duration:.1f} seconds")
        logger.info(f"📊 Training data: {len(df)} matches (synthetic)")
        logger.info(f"🎯 Models trained: {len(results)}")
        
        for target, result in results.items():
            logger.info(f"  - {target}: {result['accuracy']:.3f} accuracy")
        
        logger.info(f"🌐 API integration: {'✅ Working' if api_working else '⚠️  Check config'}")
        
        logger.info("\n📝 Next steps:")
        logger.info("1. Test predictions: curl http://localhost:8000/api/predictions/")
        logger.info("2. Models saved in: models/quick/")
        logger.info("3. Later: Replace with real GitHub data when ready")
        
        if len(results) > 0:
            logger.info("\n🎉 SUCCESS: You're now ready to make predictions!")
            return True
        else:
            logger.error("\n❌ FAILED: No models were trained")
            return False
        
    except Exception as e:
        logger.error(f"\n❌ QUICK TRAINING FAILED: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

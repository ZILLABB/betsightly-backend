#!/usr/bin/env python3
"""
BetSightly Hybrid Model Training Script

This script implements the hybrid data approach:
1. Uses GitHub dataset for training (cached locally)
2. Uses API keys for live fixture data
3. Trains models using existing infrastructure
4. No duplication - builds on existing code
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
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

def check_prerequisites():
    """Check if all prerequisites are met."""
    logger.info("🔍 Checking prerequisites...")
    
    issues = []
    
    # Check API keys
    try:
        from utils.config import settings
        
        football_key = settings.football_data.API_KEY
        api_football_key = settings.api_football.API_KEY
        
        if not football_key or "dummy" in football_key:
            if not api_football_key or "dummy" in api_football_key:
                issues.append("❌ No valid API keys configured")
            else:
                logger.info("✅ API-Football key configured")
        else:
            logger.info("✅ Football-Data.org key configured")
            
    except Exception as e:
        issues.append(f"❌ Config error: {str(e)}")
    
    # Check required packages
    try:
        import sklearn
        import joblib
        logger.info("✅ ML packages available")
    except ImportError as e:
        issues.append(f"❌ Missing ML package: {str(e)}")
    
    # Check directories
    try:
        os.makedirs("models", exist_ok=True)
        os.makedirs("data", exist_ok=True)
        os.makedirs("cache", exist_ok=True)
        logger.info("✅ Directories ready")
    except Exception as e:
        issues.append(f"❌ Directory error: {str(e)}")
    
    if issues:
        logger.error("Prerequisites check failed:")
        for issue in issues:
            logger.error(f"  {issue}")
        return False
    
    logger.info("✅ All prerequisites met")
    return True

def download_training_data():
    """Download and cache GitHub training dataset."""
    logger.info("📥 Downloading training data...")
    
    cache_file = "data/github_training_data.csv"
    
    # Check if cached version exists and is recent (less than 7 days old)
    if os.path.exists(cache_file):
        file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))
        if file_age.days < 7:
            logger.info("📂 Using cached training data")
            return pd.read_csv(cache_file)
    
    # Download from GitHub
    try:
        import requests
        
        url = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
        logger.info(f"🌐 Downloading from GitHub: {url}")
        
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        
        # Parse and save
        df = pd.read_csv(response.content.decode('utf-8'))
        df.to_csv(cache_file, index=False)
        
        logger.info(f"✅ Downloaded and cached {len(df)} training records")
        return df
        
    except Exception as e:
        logger.error(f"❌ Failed to download training data: {str(e)}")
        
        # Try to use existing cache even if old
        if os.path.exists(cache_file):
            logger.info("📂 Using old cached data as fallback")
            return pd.read_csv(cache_file)
        
        raise

def prepare_training_features(df):
    """Prepare basic training features from the dataset."""
    logger.info("🔧 Preparing training features...")
    
    try:
        # Basic feature engineering
        features = pd.DataFrame()
        
        # Team strength indicators (simplified)
        features['home_team_encoded'] = pd.Categorical(df.get('HomeTeam', df.get('home_team', ''))).codes
        features['away_team_encoded'] = pd.Categorical(df.get('AwayTeam', df.get('away_team', ''))).codes
        
        # Historical averages (simplified)
        features['home_goals_avg'] = df.get('FTHG', df.get('home_goals', 1.5))
        features['away_goals_avg'] = df.get('FTAG', df.get('away_goals', 1.2))
        
        # Basic stats
        features['total_goals_avg'] = features['home_goals_avg'] + features['away_goals_avg']
        features['goal_difference'] = features['home_goals_avg'] - features['away_goals_avg']
        
        # Fill any NaN values
        features = features.fillna(0)
        
        logger.info(f"✅ Prepared {len(features)} training samples with {len(features.columns)} features")
        return features
        
    except Exception as e:
        logger.error(f"❌ Feature preparation failed: {str(e)}")
        raise

def create_targets(df):
    """Create target variables for training."""
    logger.info("🎯 Creating target variables...")
    
    try:
        targets = {}
        
        # Get goal columns (try different naming conventions)
        home_goals = df.get('FTHG', df.get('home_goals', df.get('HomeGoals', 0)))
        away_goals = df.get('FTAG', df.get('away_goals', df.get('AwayGoals', 0)))
        
        # Match result target
        def get_match_result(home, away):
            if home > away:
                return 'home'
            elif away > home:
                return 'away'
            else:
                return 'draw'
        
        targets['match_result'] = [get_match_result(h, a) for h, a in zip(home_goals, away_goals)]
        
        # Over/Under 2.5 goals target
        total_goals = home_goals + away_goals
        targets['over_under'] = ['over' if goals > 2.5 else 'under' for goals in total_goals]
        
        # Both teams to score target
        targets['btts'] = ['yes' if h > 0 and a > 0 else 'no' for h, a in zip(home_goals, away_goals)]
        
        logger.info(f"✅ Created {len(targets)} target variables")
        return targets
        
    except Exception as e:
        logger.error(f"❌ Target creation failed: {str(e)}")
        raise

def train_xgboost_models(features, targets):
    """Train XGBoost models for all prediction types."""
    logger.info("🤖 Training XGBoost models...")
    
    try:
        import xgboost as xgb
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import accuracy_score
        import joblib
        
        results = {}
        
        for target_name, target_values in targets.items():
            logger.info(f"📊 Training XGBoost model for {target_name}")
            
            # Prepare data
            X = features.fillna(0)
            y = target_values
            
            # Encode labels
            le = LabelEncoder()
            y_encoded = le.fit_transform(y)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y_encoded, test_size=0.2, random_state=42
            )
            
            # Train model
            if len(le.classes_) > 2:
                # Multi-class
                model = xgb.XGBClassifier(
                    objective='multi:softprob',
                    num_class=len(le.classes_),
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    random_state=42
                )
            else:
                # Binary
                model = xgb.XGBClassifier(
                    objective='binary:logistic',
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    random_state=42
                )
            
            # Fit model
            model.fit(X_train, y_train)
            
            # Evaluate
            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            
            # Save model
            model_dir = "models/hybrid"
            os.makedirs(model_dir, exist_ok=True)
            
            model_path = os.path.join(model_dir, f"xgboost_{target_name}_model.joblib")
            encoder_path = os.path.join(model_dir, f"xgboost_{target_name}_encoder.joblib")
            
            joblib.dump(model, model_path)
            joblib.dump(le, encoder_path)
            
            results[target_name] = {
                'accuracy': accuracy,
                'model_path': model_path,
                'encoder_path': encoder_path,
                'classes': le.classes_.tolist()
            }
            
            logger.info(f"✅ {target_name} model trained - Accuracy: {accuracy:.3f}")
        
        return results
        
    except ImportError:
        logger.warning("⚠️  XGBoost not available, skipping XGBoost models")
        return {}
    except Exception as e:
        logger.error(f"❌ XGBoost training failed: {str(e)}")
        return {}

def train_ensemble_models(features, targets):
    """Train ensemble models as fallback."""
    logger.info("🤖 Training ensemble models...")
    
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import accuracy_score
        import joblib
        
        results = {}
        
        for target_name, target_values in targets.items():
            logger.info(f"📊 Training ensemble model for {target_name}")
            
            # Prepare data
            X = features.fillna(0)
            y = target_values
            
            # Encode labels
            le = LabelEncoder()
            y_encoded = le.fit_transform(y)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y_encoded, test_size=0.2, random_state=42
            )
            
            # Train Random Forest
            model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42
            )
            
            # Fit model
            model.fit(X_train, y_train)
            
            # Evaluate
            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            
            # Save model
            model_dir = "models/hybrid"
            os.makedirs(model_dir, exist_ok=True)
            
            model_path = os.path.join(model_dir, f"ensemble_{target_name}_model.joblib")
            encoder_path = os.path.join(model_dir, f"ensemble_{target_name}_encoder.joblib")
            
            joblib.dump(model, model_path)
            joblib.dump(le, encoder_path)
            
            results[target_name] = {
                'accuracy': accuracy,
                'model_path': model_path,
                'encoder_path': encoder_path,
                'classes': le.classes_.tolist()
            }
            
            logger.info(f"✅ {target_name} ensemble model trained - Accuracy: {accuracy:.3f}")
        
        return results
        
    except Exception as e:
        logger.error(f"❌ Ensemble training failed: {str(e)}")
        return {}

def test_live_data_integration():
    """Test integration with live fixture data."""
    logger.info("🌐 Testing live data integration...")
    
    try:
        # Test API connection
        from test_api_simple import test_football_data_org, test_api_football
        
        football_data_ok = test_football_data_org()
        api_football_ok = test_api_football()
        
        if football_data_ok or api_football_ok:
            logger.info("✅ Live data integration working")
            return True
        else:
            logger.warning("⚠️  Live data integration not working")
            return False
            
    except Exception as e:
        logger.error(f"❌ Live data integration test failed: {str(e)}")
        return False

def main():
    """Main training function."""
    logger.info("🚀 BETSIGHTLY HYBRID MODEL TRAINING")
    logger.info("=" * 50)
    
    # Check prerequisites
    if not check_prerequisites():
        logger.error("❌ Prerequisites not met. Please fix issues and try again.")
        return False
    
    try:
        # Step 1: Download training data
        logger.info("\n📥 STEP 1: Download Training Data")
        df = download_training_data()
        
        # Step 2: Prepare features
        logger.info("\n🔧 STEP 2: Prepare Features")
        features = prepare_training_features(df)
        
        # Step 3: Create targets
        logger.info("\n🎯 STEP 3: Create Targets")
        targets = create_targets(df)
        
        # Step 4: Train models
        logger.info("\n🤖 STEP 4: Train Models")
        xgb_results = train_xgboost_models(features, targets)
        ensemble_results = train_ensemble_models(features, targets)
        
        # Step 5: Test live data integration
        logger.info("\n🌐 STEP 5: Test Live Data Integration")
        live_data_ok = test_live_data_integration()
        
        # Summary
        logger.info("\n" + "=" * 50)
        logger.info("📊 TRAINING SUMMARY")
        logger.info("=" * 50)
        
        total_models = len(xgb_results) + len(ensemble_results)
        logger.info(f"✅ Total models trained: {total_models}")
        
        if xgb_results:
            logger.info("🎯 XGBoost models:")
            for target, result in xgb_results.items():
                logger.info(f"  - {target}: {result['accuracy']:.3f} accuracy")
        
        if ensemble_results:
            logger.info("🎯 Ensemble models:")
            for target, result in ensemble_results.items():
                logger.info(f"  - {target}: {result['accuracy']:.3f} accuracy")
        
        logger.info(f"🌐 Live data integration: {'✅ Working' if live_data_ok else '⚠️  Issues'}")
        
        if total_models > 0:
            logger.info("\n🎉 TRAINING COMPLETED SUCCESSFULLY!")
            logger.info("📝 Next steps:")
            logger.info("1. Test predictions: curl http://localhost:8000/api/predictions/")
            logger.info("2. Check enhanced predictions: curl http://localhost:8000/api/predictions/enhanced/")
            return True
        else:
            logger.error("\n❌ TRAINING FAILED - No models were trained")
            return False
            
    except Exception as e:
        logger.error(f"\n❌ TRAINING FAILED: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

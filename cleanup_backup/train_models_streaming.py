#!/usr/bin/env python3
"""
BetSightly Streaming ML Pipeline

Optimized approach:
1. Stream GitHub dataset directly into memory (no saving)
2. Train models on historical data
3. Use APIs for live predictions
4. Fast, efficient, no storage overhead
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from pathlib import Path
import io

# Add project root to path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def stream_github_training_data():
    """
    Stream GitHub dataset directly into memory without saving.
    Fast and efficient - no disk I/O overhead.
    """
    logger.info("📡 Streaming GitHub training dataset...")
    
    try:
        url = "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
        
        # Stream download with progress
        logger.info(f"🌐 Downloading from: {url}")
        
        response = requests.get(url, timeout=120, stream=True)
        response.raise_for_status()
        
        # Get content length for progress tracking
        total_size = int(response.headers.get('content-length', 0))
        logger.info(f"📊 Dataset size: {total_size / (1024*1024):.1f} MB")
        
        # Read content in chunks and build string
        content = ""
        downloaded = 0
        
        for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
            if chunk:
                content += chunk
                downloaded += len(chunk.encode('utf-8'))
                
                # Progress update every 1MB
                if downloaded % (1024*1024) < 8192:
                    progress = (downloaded / total_size * 100) if total_size > 0 else 0
                    logger.info(f"📥 Download progress: {progress:.1f}%")
        
        # Parse CSV directly from memory
        logger.info("🔄 Parsing CSV data...")
        df = pd.read_csv(io.StringIO(content))
        
        logger.info(f"✅ Loaded {len(df)} matches with {len(df.columns)} columns")
        logger.info(f"📅 Date range: {df.get('Date', 'Unknown').min()} to {df.get('Date', 'Unknown').max()}")
        
        return df
        
    except Exception as e:
        logger.error(f"❌ Failed to stream training data: {str(e)}")
        raise

def prepare_features_fast(df):
    """
    Fast feature engineering optimized for streaming data.
    """
    logger.info("⚡ Fast feature engineering...")
    
    try:
        # Detect column names (different datasets use different naming)
        home_team_col = None
        away_team_col = None
        home_goals_col = None
        away_goals_col = None
        date_col = None
        
        # Try common column name patterns
        for col in df.columns:
            col_lower = col.lower()
            if 'home' in col_lower and 'team' in col_lower:
                home_team_col = col
            elif 'away' in col_lower and 'team' in col_lower:
                away_team_col = col
            elif col in ['FTHG', 'HomeGoals', 'home_goals']:
                home_goals_col = col
            elif col in ['FTAG', 'AwayGoals', 'away_goals']:
                away_goals_col = col
            elif col in ['Date', 'date', 'match_date']:
                date_col = col
        
        logger.info(f"📊 Detected columns: Home={home_team_col}, Away={away_team_col}, Goals={home_goals_col}/{away_goals_col}")
        
        # Create features
        features = pd.DataFrame()
        
        # Team encoding (fast categorical encoding)
        if home_team_col and away_team_col:
            home_teams = pd.Categorical(df[home_team_col])
            away_teams = pd.Categorical(df[away_team_col])
            
            features['home_team_id'] = home_teams.codes
            features['away_team_id'] = away_teams.codes
            features['team_count'] = len(set(home_teams.categories) | set(away_teams.categories))
        
        # Goal-based features
        if home_goals_col and away_goals_col:
            home_goals = pd.to_numeric(df[home_goals_col], errors='coerce').fillna(0)
            away_goals = pd.to_numeric(df[away_goals_col], errors='coerce').fillna(0)
            
            features['home_goals_avg'] = home_goals
            features['away_goals_avg'] = away_goals
            features['total_goals'] = home_goals + away_goals
            features['goal_difference'] = home_goals - away_goals
            features['home_advantage'] = (home_goals > away_goals).astype(int)
        else:
            # Fallback features
            features['home_goals_avg'] = 1.5
            features['away_goals_avg'] = 1.2
            features['total_goals'] = 2.7
            features['goal_difference'] = 0.3
            features['home_advantage'] = 0.55
        
        # Time-based features (if date available)
        if date_col:
            try:
                dates = pd.to_datetime(df[date_col], errors='coerce')
                features['month'] = dates.dt.month.fillna(6)
                features['day_of_week'] = dates.dt.dayofweek.fillna(3)
                features['season'] = ((dates.dt.month >= 8) | (dates.dt.month <= 5)).astype(int)
            except:
                features['month'] = 6
                features['day_of_week'] = 3
                features['season'] = 1
        else:
            features['month'] = 6
            features['day_of_week'] = 3
            features['season'] = 1
        
        # Statistical features
        features['home_strength'] = features['home_goals_avg'] / (features['away_goals_avg'] + 0.1)
        features['away_strength'] = features['away_goals_avg'] / (features['home_goals_avg'] + 0.1)
        features['match_intensity'] = features['total_goals'] * features['goal_difference'].abs()
        
        # Fill any remaining NaN values
        features = features.fillna(features.mean())
        
        logger.info(f"✅ Created {len(features)} samples with {len(features.columns)} features")
        return features
        
    except Exception as e:
        logger.error(f"❌ Feature engineering failed: {str(e)}")
        raise

def create_targets_fast(df):
    """
    Fast target creation optimized for streaming data.
    """
    logger.info("🎯 Creating targets...")
    
    try:
        # Detect goal columns
        home_goals_col = None
        away_goals_col = None
        
        for col in df.columns:
            if col in ['FTHG', 'HomeGoals', 'home_goals']:
                home_goals_col = col
            elif col in ['FTAG', 'AwayGoals', 'away_goals']:
                away_goals_col = col
        
        if home_goals_col and away_goals_col:
            home_goals = pd.to_numeric(df[home_goals_col], errors='coerce').fillna(1)
            away_goals = pd.to_numeric(df[away_goals_col], errors='coerce').fillna(1)
        else:
            # Generate synthetic targets for testing
            logger.warning("⚠️  No goal columns found, generating synthetic targets")
            np.random.seed(42)
            home_goals = np.random.poisson(1.5, len(df))
            away_goals = np.random.poisson(1.2, len(df))
        
        targets = {}
        
        # Match result
        def get_result(h, a):
            if h > a:
                return 'home'
            elif a > h:
                return 'away'
            else:
                return 'draw'
        
        targets['match_result'] = [get_result(h, a) for h, a in zip(home_goals, away_goals)]
        
        # Over/Under 2.5
        total_goals = home_goals + away_goals
        targets['over_under'] = ['over' if g > 2.5 else 'under' for g in total_goals]
        
        # Both teams to score
        targets['btts'] = ['yes' if h > 0 and a > 0 else 'no' for h, a in zip(home_goals, away_goals)]
        
        logger.info(f"✅ Created targets: {len(targets)} types")
        return targets
        
    except Exception as e:
        logger.error(f"❌ Target creation failed: {str(e)}")
        raise

def train_models_fast(features, targets):
    """
    Fast model training with automatic fallbacks.
    """
    logger.info("🚀 Fast model training...")
    
    results = {}
    
    # Try XGBoost first
    try:
        import xgboost as xgb
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import accuracy_score
        import joblib
        
        logger.info("🎯 Training XGBoost models...")
        
        for target_name, target_values in targets.items():
            logger.info(f"📊 Training {target_name}...")
            
            # Prepare data
            X = features.fillna(0)
            y = target_values
            
            # Encode labels
            le = LabelEncoder()
            y_encoded = le.fit_transform(y)
            
            # Quick train/test split
            X_train, X_test, y_train, y_test = train_test_split(
                X, y_encoded, test_size=0.2, random_state=42
            )
            
            # Fast XGBoost training
            model = xgb.XGBClassifier(
                n_estimators=50,  # Reduced for speed
                max_depth=4,      # Reduced for speed
                learning_rate=0.2, # Increased for speed
                random_state=42,
                verbosity=0       # Quiet training
            )
            
            model.fit(X_train, y_train)
            
            # Quick evaluation
            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            
            # Save model
            os.makedirs("models/streaming", exist_ok=True)
            model_path = f"models/streaming/xgb_{target_name}.joblib"
            encoder_path = f"models/streaming/xgb_{target_name}_encoder.joblib"
            
            joblib.dump(model, model_path)
            joblib.dump(le, encoder_path)
            
            results[target_name] = {
                'model': 'xgboost',
                'accuracy': accuracy,
                'path': model_path
            }
            
            logger.info(f"✅ {target_name}: {accuracy:.3f} accuracy")
        
        return results
        
    except ImportError:
        logger.warning("⚠️  XGBoost not available, using sklearn...")
        
        # Fallback to sklearn
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import accuracy_score
        import joblib
        
        for target_name, target_values in targets.items():
            logger.info(f"📊 Training sklearn {target_name}...")
            
            X = features.fillna(0)
            y = target_values
            
            le = LabelEncoder()
            y_encoded = le.fit_transform(y)
            
            X_train, X_test, y_train, y_test = train_test_split(
                X, y_encoded, test_size=0.2, random_state=42
            )
            
            model = RandomForestClassifier(
                n_estimators=50,
                max_depth=8,
                random_state=42
            )
            
            model.fit(X_train, y_train)
            
            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            
            os.makedirs("models/streaming", exist_ok=True)
            model_path = f"models/streaming/rf_{target_name}.joblib"
            encoder_path = f"models/streaming/rf_{target_name}_encoder.joblib"
            
            joblib.dump(model, model_path)
            joblib.dump(le, encoder_path)
            
            results[target_name] = {
                'model': 'random_forest',
                'accuracy': accuracy,
                'path': model_path
            }
            
            logger.info(f"✅ {target_name}: {accuracy:.3f} accuracy")
        
        return results

def main():
    """Main streaming training function."""
    logger.info("🚀 BETSIGHTLY STREAMING ML PIPELINE")
    logger.info("=" * 50)
    
    start_time = datetime.now()
    
    try:
        # Step 1: Stream training data (no saving)
        logger.info("\n📡 STEP 1: Stream Training Data")
        df = stream_github_training_data()
        
        # Step 2: Fast feature engineering
        logger.info("\n⚡ STEP 2: Fast Feature Engineering")
        features = prepare_features_fast(df)
        
        # Step 3: Create targets
        logger.info("\n🎯 STEP 3: Create Targets")
        targets = create_targets_fast(df)
        
        # Step 4: Fast model training
        logger.info("\n🚀 STEP 4: Fast Model Training")
        results = train_models_fast(features, targets)
        
        # Summary
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info("\n" + "=" * 50)
        logger.info("🎉 STREAMING TRAINING COMPLETED!")
        logger.info("=" * 50)
        
        logger.info(f"⏱️  Total time: {duration:.1f} seconds")
        logger.info(f"📊 Training data: {len(df)} matches")
        logger.info(f"🎯 Models trained: {len(results)}")
        
        for target, result in results.items():
            logger.info(f"  - {target}: {result['accuracy']:.3f} ({result['model']})")
        
        logger.info("\n📝 Next steps:")
        logger.info("1. Test predictions: curl http://localhost:8000/api/predictions/")
        logger.info("2. Models saved in: models/streaming/")
        
        return True
        
    except Exception as e:
        logger.error(f"\n❌ STREAMING TRAINING FAILED: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

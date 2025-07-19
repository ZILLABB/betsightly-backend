#!/usr/bin/env python3
"""
Fixed ML Training Suite for BetSightly
Trains all 22 models using real data with proper format handling.
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import xgboost as xgb
import lightgbm as lgb

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class FixedMLTrainer:
    """Fixed ML trainer with proper data handling."""
    
    def __init__(self):
        """Initialize the trainer."""
        self.models_dir = Path("models")
        self.models_dir.mkdir(exist_ok=True)
        
        # Create model type directories
        for model_type in ['xgboost', 'lightgbm', 'random_forest', 'neural_network']:
            (self.models_dir / model_type).mkdir(exist_ok=True)
        
        self.training_stats = {
            'total_models': 22,
            'trained_models': 0,
            'training_samples': 0,
            'errors': 0
        }
    
    def load_and_prepare_data(self) -> pd.DataFrame:
        """Load and prepare training data from GitHub dataset."""
        print("📊 LOADING AND PREPARING TRAINING DATA")
        print("-" * 60)
        
        try:
            # Load GitHub matches data
            matches_file = "data/historical/raw/matches.csv"
            if not os.path.exists(matches_file):
                print(f"❌ {matches_file} not found!")
                return pd.DataFrame()
            
            print(f"📁 Loading {matches_file}...")
            df = pd.read_csv(matches_file, low_memory=False)
            print(f"✅ Loaded {len(df)} matches")
            
            # Convert to training format
            print("🔄 Converting to training format...")
            training_data = []
            
            for _, row in df.iterrows():
                try:
                    home_score = int(row['home_team_score'])
                    away_score = int(row['away_team_score'])
                    total_goals = home_score + away_score
                    
                    # Create training record
                    record = {
                        'home_team': str(row['home_team_name']),
                        'away_team': str(row['away_team_name']),
                        'home_score': home_score,
                        'away_score': away_score,
                        'total_goals': total_goals,
                        'season': str(row['season']),
                        'division': str(row['division']),
                        
                        # Target variables
                        'match_result': 0 if home_score > away_score else 1 if away_score > home_score else 2,  # 0=home, 1=away, 2=draw
                        'btts': 1 if home_score > 0 and away_score > 0 else 0,
                        'over_1_5': 1 if total_goals > 1.5 else 0,
                        'over_2_5': 1 if total_goals > 2.5 else 0,
                        'over_3_5': 1 if total_goals > 3.5 else 0,
                        'clean_sheet_home': 1 if away_score == 0 else 0,
                        'clean_sheet_away': 1 if home_score == 0 else 0,
                        'win_to_nil_home': 1 if home_score > away_score and away_score == 0 else 0,
                        'win_to_nil_away': 1 if away_score > home_score and home_score == 0 else 0,
                    }
                    training_data.append(record)
                    
                except (ValueError, TypeError):
                    continue
            
            training_df = pd.DataFrame(training_data)
            print(f"✅ Converted {len(training_df)} valid matches")
            
            # Add encoded features
            training_df = self.add_encoded_features(training_df)
            
            self.training_stats['training_samples'] = len(training_df)
            return training_df
            
        except Exception as e:
            logger.error(f"Error loading data: {str(e)}")
            print(f"❌ Error loading data: {str(e)}")
            return pd.DataFrame()
    
    def add_encoded_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add encoded features for ML training."""
        try:
            # Encode teams
            le_home = LabelEncoder()
            le_away = LabelEncoder()
            le_division = LabelEncoder()
            
            df['home_team_encoded'] = le_home.fit_transform(df['home_team'])
            df['away_team_encoded'] = le_away.fit_transform(df['away_team'])
            df['division_encoded'] = le_division.fit_transform(df['division'])
            
            # Save encoders
            joblib.dump(le_home, self.models_dir / "home_team_encoder.joblib")
            joblib.dump(le_away, self.models_dir / "away_team_encoder.joblib")
            joblib.dump(le_division, self.models_dir / "division_encoder.joblib")
            
            print("✅ Added encoded features")
            return df
            
        except Exception as e:
            logger.error(f"Error encoding features: {str(e)}")
            return df
    
    def train_all_models(self, training_data: pd.DataFrame):
        """Train all ML models."""
        print(f"\n🤖 TRAINING ML MODELS")
        print("-" * 60)
        
        if training_data.empty:
            print("❌ No training data available!")
            return False
        
        # Feature columns
        feature_columns = ['home_team_encoded', 'away_team_encoded', 'division_encoded']
        X = training_data[feature_columns]
        
        # Model configurations
        models_to_train = {
            'xgboost': {
                'match_result': 'match_result',
                'btts': 'btts', 
                'over_2_5': 'over_2_5',
                'over_1_5': 'over_1_5',
                'over_3_5': 'over_3_5',
                'clean_sheet_home': 'clean_sheet_home',
                'clean_sheet_away': 'clean_sheet_away',
                'win_to_nil_home': 'win_to_nil_home'
            },
            'lightgbm': {
                'match_result': 'match_result',
                'btts': 'btts',
                'over_2_5': 'over_2_5',
                'over_3_5': 'over_3_5',
                'clean_sheet_home': 'clean_sheet_home',
                'clean_sheet_away': 'clean_sheet_away'
            },
            'random_forest': {
                'match_result': 'match_result',
                'btts': 'btts',
                'over_2_5': 'over_2_5',
                'win_to_nil_home': 'win_to_nil_home'
            },
            'neural_network': {
                'match_result': 'match_result',
                'btts': 'btts',
                'over_2_5': 'over_2_5',
                'win_to_nil_away': 'win_to_nil_away'
            }
        }
        
        # Train each model
        for model_type, model_configs in models_to_train.items():
            print(f"\n🧠 Training {model_type.upper()} models...")
            
            for model_name, target_col in model_configs.items():
                try:
                    print(f"   🔄 Training {model_name}...")
                    
                    y = training_data[target_col]
                    
                    # Check target variation
                    if len(y.unique()) < 2:
                        print(f"   ⚠️  Insufficient variation in {target_col}")
                        continue
                    
                    # Split data
                    X_train, X_test, y_train, y_test = train_test_split(
                        X, y, test_size=0.2, random_state=42, stratify=y
                    )
                    
                    # Train model
                    model, scaler = self.train_single_model(model_type, X_train, y_train)
                    
                    if model is not None:
                        # Evaluate
                        if scaler:
                            X_test_scaled = scaler.transform(X_test)
                            accuracy = accuracy_score(y_test, model.predict(X_test_scaled))
                        else:
                            accuracy = accuracy_score(y_test, model.predict(X_test))
                        
                        # Save model
                        model_path = self.models_dir / model_type / f"{model_name}_model.joblib"
                        joblib.dump(model, model_path)
                        
                        if scaler:
                            scaler_path = self.models_dir / model_type / f"{model_name}_scaler.joblib"
                            joblib.dump(scaler, scaler_path)
                        
                        self.training_stats['trained_models'] += 1
                        print(f"   ✅ {model_name}: {accuracy:.3f} accuracy")
                    else:
                        print(f"   ❌ Failed to train {model_name}")
                        self.training_stats['errors'] += 1
                        
                except Exception as e:
                    logger.error(f"Error training {model_name}: {str(e)}")
                    print(f"   ❌ Error: {str(e)}")
                    self.training_stats['errors'] += 1
        
        return True
    
    def train_single_model(self, model_type: str, X_train, y_train):
        """Train a single model."""
        try:
            scaler = None
            
            if model_type == 'xgboost':
                model = xgb.XGBClassifier(
                    n_estimators=100, max_depth=6, learning_rate=0.1,
                    random_state=42, eval_metric='logloss'
                )
                model.fit(X_train, y_train)
                
            elif model_type == 'lightgbm':
                model = lgb.LGBMClassifier(
                    n_estimators=100, max_depth=6, learning_rate=0.1,
                    random_state=42, verbose=-1
                )
                model.fit(X_train, y_train)
                
            elif model_type == 'random_forest':
                model = RandomForestClassifier(
                    n_estimators=100, max_depth=10, random_state=42
                )
                model.fit(X_train, y_train)
                
            elif model_type == 'neural_network':
                from sklearn.neural_network import MLPClassifier
                scaler = StandardScaler()
                X_train_scaled = scaler.fit_transform(X_train)
                
                model = MLPClassifier(
                    hidden_layer_sizes=(100, 50), max_iter=500,
                    random_state=42, early_stopping=True
                )
                model.fit(X_train_scaled, y_train)
            
            else:
                return None, None
            
            return model, scaler
            
        except Exception as e:
            logger.error(f"Error training {model_type}: {str(e)}")
            return None, None
    
    def display_summary(self):
        """Display training summary."""
        print(f"\n📊 TRAINING SUMMARY")
        print("=" * 60)
        print(f"🎯 Target Models: {self.training_stats['total_models']}")
        print(f"✅ Successfully Trained: {self.training_stats['trained_models']}")
        print(f"❌ Errors: {self.training_stats['errors']}")
        print(f"📊 Training Samples: {self.training_stats['training_samples']}")
        
        success_rate = (self.training_stats['trained_models'] / self.training_stats['total_models']) * 100
        print(f"📈 Success Rate: {success_rate:.1f}%")
        
        # List saved models
        print(f"\n💾 Saved Models:")
        total_files = 0
        for model_type in ['xgboost', 'lightgbm', 'random_forest', 'neural_network']:
            type_dir = self.models_dir / model_type
            if type_dir.exists():
                files = list(type_dir.glob("*_model.joblib"))
                total_files += len(files)
                print(f"   {model_type}: {len(files)} models")
                for file in files:
                    print(f"      ✅ {file.stem}")
        
        print(f"\n🎉 Training completed! {total_files} models ready for predictions.")
        print("=" * 60)
    
    def run_training(self):
        """Run the complete training process."""
        print("🚀 BETSIGHTLY ML TRAINING SUITE")
        print("=" * 60)
        print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("🎯 Training 22 ML models with real data")
        print("=" * 60)
        
        # Load data
        training_data = self.load_and_prepare_data()
        
        if training_data.empty:
            print("❌ No training data available!")
            return False
        
        # Train models
        success = self.train_all_models(training_data)
        
        # Display summary
        self.display_summary()
        
        return success


def main():
    """Main execution."""
    trainer = FixedMLTrainer()
    success = trainer.run_training()
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

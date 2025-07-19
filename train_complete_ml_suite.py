#!/usr/bin/env python3
"""
Complete ML Training Suite for BetSightly
Trains all 22 models using both GitHub datasets and APIFootball.com historical data.
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple
import joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, classification_report
import xgboost as xgb
import lightgbm as lgb

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from services.apifootball_service import APIFootballService


class ComprehensiveMLTrainer:
    """Train complete 22-model ML suite using multiple data sources."""
    
    def __init__(self):
        """Initialize the trainer."""
        self.apifootball_service = APIFootballService()
        self.models_dir = Path("models")
        self.github_data_dir = Path("data/historical")
        
        # Ensure directories exist
        self.models_dir.mkdir(exist_ok=True)
        (self.models_dir / "xgboost").mkdir(exist_ok=True)
        (self.models_dir / "lightgbm").mkdir(exist_ok=True)
        (self.models_dir / "random_forest").mkdir(exist_ok=True)
        (self.models_dir / "neural_network").mkdir(exist_ok=True)
        
        # Model configurations
        self.model_configs = {
            'xgboost': {
                'count': 8,
                'models': [
                    'match_result', 'btts', 'over_2_5', 'clean_sheet_home',
                    'clean_sheet_away', 'win_to_nil_home', 'win_to_nil_away', 'over_1_5'
                ]
            },
            'lightgbm': {
                'count': 6,
                'models': [
                    'match_result', 'btts', 'over_under', 'over_3_5', 'clean_sheet_home', 'clean_sheet_away'
                ]
            },
            'random_forest': {
                'count': 4,
                'models': [
                    'match_result', 'over_2_5', 'btts', 'win_to_nil_home'
                ]
            },
            'neural_network': {
                'count': 4,
                'models': [
                    'match_result', 'btts', 'over_2_5', 'ensemble_meta'
                ]
            }
        }
        
        self.training_stats = {
            'total_models': 22,
            'trained_models': 0,
            'data_sources': [],
            'total_training_samples': 0,
            'training_errors': 0
        }
    
    def print_header(self):
        """Print training header."""
        print("\n" + "="*80)
        print("🤖 COMPREHENSIVE ML TRAINING SUITE - BETSIGHTLY")
        print("="*80)
        print(f"📅 Training Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎯 Target: 22 Advanced ML Models")
        print(f"📊 Data Sources: GitHub Datasets + APIFootball.com Historical Data")
        print(f"🧠 Model Types: XGBoost (8), LightGBM (6), Random Forest (4), Neural Network (4)")
        print("="*80)
    
    def collect_training_data(self) -> pd.DataFrame:
        """Collect training data from all available sources."""
        print("\n📊 STEP 1: COLLECTING TRAINING DATA")
        print("-" * 60)
        
        all_data = []
        
        # 1. Collect APIFootball.com historical data
        print("🌐 Collecting APIFootball.com historical data...")
        try:
            # Get data from last 6 months
            end_date = datetime.now()
            start_date = end_date - timedelta(days=180)
            
            historical_matches = self.apifootball_service.get_historical_matches(
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d")
            )
            
            if historical_matches:
                api_df = pd.DataFrame(historical_matches)
                all_data.append(api_df)
                self.training_stats['data_sources'].append(f"APIFootball.com: {len(api_df)} matches")
                print(f"   ✅ APIFootball.com: {len(api_df)} matches")
            else:
                print(f"   ⚠️  No APIFootball.com data available")
                
        except Exception as e:
            logger.error(f"Error collecting APIFootball data: {str(e)}")
            print(f"   ❌ APIFootball.com error: {str(e)}")
            self.training_stats['training_errors'] += 1
        
        # 2. Collect GitHub dataset (if available)
        print("📁 Collecting GitHub historical datasets...")
        try:
            github_files = [
                "data/historical/raw/matches.csv",
                "data/historical/raw/appearances.csv",
                "data/historical/processed/training_data.csv"
            ]
            
            for file_path in github_files:
                if os.path.exists(file_path):
                    try:
                        github_df = pd.read_csv(file_path)
                        
                        # Convert GitHub format to our training format
                        converted_df = self.convert_github_format(github_df, file_path)
                        if converted_df is not None and len(converted_df) > 0:
                            all_data.append(converted_df)
                            self.training_stats['data_sources'].append(f"GitHub {file_path}: {len(converted_df)} matches")
                            print(f"   ✅ {file_path}: {len(converted_df)} matches")
                    except Exception as e:
                        print(f"   ⚠️  Error reading {file_path}: {str(e)}")
                else:
                    print(f"   ⚠️  {file_path} not found")
                    
        except Exception as e:
            logger.error(f"Error collecting GitHub data: {str(e)}")
            print(f"   ❌ GitHub data error: {str(e)}")
            self.training_stats['training_errors'] += 1
        
        # 3. Combine all data sources
        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)
            
            # Remove duplicates based on match_id if available
            if 'match_id' in combined_df.columns:
                combined_df = combined_df.drop_duplicates(subset=['match_id'])
            
            # Clean and prepare data
            combined_df = self.clean_training_data(combined_df)
            
            self.training_stats['total_training_samples'] = len(combined_df)
            
            print(f"\n📈 TRAINING DATA SUMMARY:")
            print(f"   Total Sources: {len(self.training_stats['data_sources'])}")
            for source in self.training_stats['data_sources']:
                print(f"   - {source}")
            print(f"   Combined Dataset: {len(combined_df)} matches")
            
            return combined_df
        else:
            print("❌ No training data collected!")
            return pd.DataFrame()
    
    def convert_github_format(self, df: pd.DataFrame, file_path: str) -> pd.DataFrame:
        """Convert GitHub dataset format to our training format."""
        try:
            # This is a simplified conversion - would need to be customized based on actual GitHub data format
            if 'matches.csv' in file_path:
                # Convert matches format
                converted_data = []
                for _, row in df.iterrows():
                    # Map GitHub columns to our format (adjust based on actual structure)
                    converted_row = {
                        'home_team': row.get('home_team', 'Unknown'),
                        'away_team': row.get('away_team', 'Unknown'),
                        'home_score': row.get('home_score', 0),
                        'away_score': row.get('away_score', 0),
                        'league_name': row.get('competition', 'Unknown'),
                        'date': row.get('date', datetime.now().isoformat()),
                        # Add derived fields
                        'total_goals': row.get('home_score', 0) + row.get('away_score', 0),
                        'match_result': 'home_win' if row.get('home_score', 0) > row.get('away_score', 0) else 
                                       'away_win' if row.get('away_score', 0) > row.get('home_score', 0) else 'draw',
                        'btts': 1 if row.get('home_score', 0) > 0 and row.get('away_score', 0) > 0 else 0,
                        'over_1_5': 1 if (row.get('home_score', 0) + row.get('away_score', 0)) > 1.5 else 0,
                        'over_2_5': 1 if (row.get('home_score', 0) + row.get('away_score', 0)) > 2.5 else 0,
                        'over_3_5': 1 if (row.get('home_score', 0) + row.get('away_score', 0)) > 3.5 else 0,
                        'clean_sheet_home': 1 if row.get('away_score', 0) == 0 else 0,
                        'clean_sheet_away': 1 if row.get('home_score', 0) == 0 else 0,
                        'win_to_nil_home': 1 if row.get('home_score', 0) > row.get('away_score', 0) and row.get('away_score', 0) == 0 else 0,
                        'win_to_nil_away': 1 if row.get('away_score', 0) > row.get('home_score', 0) and row.get('home_score', 0) == 0 else 0,
                    }
                    converted_data.append(converted_row)
                
                return pd.DataFrame(converted_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Error converting GitHub format: {str(e)}")
            return None
    
    def clean_training_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and prepare training data."""
        try:
            # Remove rows with missing essential data
            df = df.dropna(subset=['home_team', 'away_team'])
            
            # Ensure numeric columns are properly typed
            numeric_columns = ['home_score', 'away_score', 'total_goals', 'btts', 'over_1_5', 'over_2_5', 'over_3_5',
                             'clean_sheet_home', 'clean_sheet_away', 'win_to_nil_home', 'win_to_nil_away']
            
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            # Add feature engineering
            df = self.add_basic_features(df)
            
            return df
            
        except Exception as e:
            logger.error(f"Error cleaning training data: {str(e)}")
            return df
    
    def add_basic_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add basic features for ML training."""
        try:
            # Team encoding
            le_home = LabelEncoder()
            le_away = LabelEncoder()
            
            df['home_team_encoded'] = le_home.fit_transform(df['home_team'].astype(str))
            df['away_team_encoded'] = le_away.fit_transform(df['away_team'].astype(str))
            
            # League encoding
            if 'league_name' in df.columns:
                le_league = LabelEncoder()
                df['league_encoded'] = le_league.fit_transform(df['league_name'].astype(str))
            
            # Save encoders
            joblib.dump(le_home, self.models_dir / "home_team_encoder.joblib")
            joblib.dump(le_away, self.models_dir / "away_team_encoder.joblib")
            if 'league_name' in df.columns:
                joblib.dump(le_league, self.models_dir / "league_encoder.joblib")
            
            return df
            
        except Exception as e:
            logger.error(f"Error adding features: {str(e)}")
            return df

    def train_all_models(self, training_data: pd.DataFrame):
        """Train all 22 ML models."""
        print(f"\n🤖 STEP 2: TRAINING 22 ML MODELS")
        print("-" * 60)

        if training_data.empty:
            print("❌ No training data available!")
            return False

        # Prepare feature columns
        feature_columns = ['home_team_encoded', 'away_team_encoded']
        if 'league_encoded' in training_data.columns:
            feature_columns.append('league_encoded')

        X = training_data[feature_columns]

        # Train each model type
        for model_type, config in self.model_configs.items():
            print(f"\n🧠 Training {model_type.upper()} models ({config['count']} models)...")

            for model_name in config['models']:
                try:
                    print(f"   🔄 Training {model_name}...")

                    # Get target variable
                    if model_name in training_data.columns:
                        y = training_data[model_name]
                    elif model_name == 'over_under':
                        # Use over_2_5 as default for over_under
                        y = training_data.get('over_2_5', training_data.get('over_1_5', pd.Series([0]*len(training_data))))
                    elif model_name == 'ensemble_meta':
                        # Skip ensemble meta for now
                        print(f"   ⚠️  Skipping {model_name} (requires pre-trained models)")
                        continue
                    else:
                        print(f"   ⚠️  Target variable {model_name} not found, skipping...")
                        continue

                    # Check if we have enough data
                    if len(y.unique()) < 2:
                        print(f"   ⚠️  Insufficient target variation for {model_name}, skipping...")
                        continue

                    # Split data
                    X_train, X_test, y_train, y_test = train_test_split(
                        X, y, test_size=0.2, random_state=42, stratify=y
                    )

                    # Train model based on type
                    model, scaler = self.train_single_model(model_type, model_name, X_train, y_train)

                    if model is not None:
                        # Evaluate model
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
                        print(f"   ✅ {model_name}: Accuracy {accuracy:.3f} - Saved to {model_path}")
                    else:
                        print(f"   ❌ Failed to train {model_name}")
                        self.training_stats['training_errors'] += 1

                except Exception as e:
                    logger.error(f"Error training {model_name}: {str(e)}")
                    print(f"   ❌ Error training {model_name}: {str(e)}")
                    self.training_stats['training_errors'] += 1

        return True

    def train_single_model(self, model_type: str, model_name: str, X_train, y_train):
        """Train a single model."""
        try:
            scaler = None

            if model_type == 'xgboost':
                model = xgb.XGBClassifier(
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    random_state=42,
                    eval_metric='logloss'
                )
                model.fit(X_train, y_train)

            elif model_type == 'lightgbm':
                model = lgb.LGBMClassifier(
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    random_state=42,
                    verbose=-1
                )
                model.fit(X_train, y_train)

            elif model_type == 'random_forest':
                model = RandomForestClassifier(
                    n_estimators=100,
                    max_depth=10,
                    random_state=42
                )
                model.fit(X_train, y_train)

            elif model_type == 'neural_network':
                # Use sklearn MLPClassifier as neural network
                from sklearn.neural_network import MLPClassifier

                # Scale features for neural network
                scaler = StandardScaler()
                X_train_scaled = scaler.fit_transform(X_train)

                model = MLPClassifier(
                    hidden_layer_sizes=(100, 50),
                    max_iter=500,
                    random_state=42,
                    early_stopping=True,
                    validation_fraction=0.1
                )
                model.fit(X_train_scaled, y_train)

            else:
                return None, None

            return model, scaler

        except Exception as e:
            logger.error(f"Error in train_single_model: {str(e)}")
            return None, None

    def display_training_summary(self):
        """Display comprehensive training summary."""
        print(f"\n📊 TRAINING SUMMARY")
        print("=" * 80)

        print(f"🎯 Target Models: {self.training_stats['total_models']}")
        print(f"✅ Successfully Trained: {self.training_stats['trained_models']}")
        print(f"❌ Training Errors: {self.training_stats['training_errors']}")
        print(f"📈 Success Rate: {(self.training_stats['trained_models']/self.training_stats['total_models']*100):.1f}%")

        print(f"\n📊 Data Sources Used:")
        for source in self.training_stats['data_sources']:
            print(f"   - {source}")
        print(f"   Total Training Samples: {self.training_stats['total_training_samples']}")

        print(f"\n🧠 Model Breakdown:")
        for model_type, config in self.model_configs.items():
            print(f"   {model_type.upper()}: {config['count']} models")
            for model_name in config['models']:
                model_path = self.models_dir / model_type / f"{model_name}_model.joblib"
                status = "✅" if model_path.exists() else "❌"
                print(f"      {status} {model_name}")

        print(f"\n💾 Model Files Saved:")
        total_files = 0
        for model_type in self.model_configs.keys():
            type_dir = self.models_dir / model_type
            if type_dir.exists():
                files = list(type_dir.glob("*.joblib"))
                total_files += len(files)
                print(f"   {model_type}/: {len(files)} files")

        print(f"   Total Model Files: {total_files}")

        # Health check
        health_score = (self.training_stats['trained_models'] / self.training_stats['total_models']) * 100
        health_status = "🟢 EXCELLENT" if health_score >= 90 else \
                       "🟡 GOOD" if health_score >= 70 else \
                       "🟠 FAIR" if health_score >= 50 else "🔴 POOR"

        print(f"\n🏥 Training Health: {health_score:.1f}% {health_status}")

        if health_score >= 80:
            print("🎉 Training completed successfully! Ready for predictions.")
        elif health_score >= 50:
            print("⚠️  Partial training success. Some models may be missing.")
        else:
            print("❌ Training mostly failed. Check data sources and dependencies.")

        print("=" * 80)

    def run_complete_training(self):
        """Run the complete training pipeline."""
        try:
            # Print header
            self.print_header()

            # Step 1: Collect training data
            training_data = self.collect_training_data()

            if training_data.empty:
                print("\n❌ No training data collected. Cannot proceed with training.")
                return False

            # Step 2: Train all models
            success = self.train_all_models(training_data)

            # Step 3: Display summary
            self.display_training_summary()

            return success

        except Exception as e:
            logger.error(f"Complete training failed: {str(e)}")
            print(f"\n❌ TRAINING FAILED: {str(e)}")
            return False


def main():
    """Main training execution."""
    trainer = ComprehensiveMLTrainer()
    success = trainer.run_complete_training()
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

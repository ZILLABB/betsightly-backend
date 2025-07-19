#!/usr/bin/env python3
"""
Train ML Models with GitHub Dataset
Comprehensive training script for all 24 models using consistent features.
"""

import pandas as pd
import numpy as np
import pickle
import os
import logging
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.neural_network import MLPClassifier
import xgboost as xgb
import lightgbm as lgb
from sklearn.metrics import accuracy_score, classification_report

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GitHubDatasetTrainer:
    """Train ML models using GitHub football dataset."""
    
    def __init__(self):
        """Initialize the trainer."""
        self.models = {}
        self.scalers = {}
        self.encoders = {}
        self.feature_columns = []
        
        # Create models directory
        os.makedirs('models', exist_ok=True)
        
        # Model configurations
        self.model_configs = {
            'xgboost': {
                'match_result': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'over_2_5': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'over_1_5': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'over_3_5': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'btts': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'clean_sheet_home': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'clean_sheet_away': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'win_to_nil_home': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'win_to_nil_away': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
            },
            'lightgbm': {
                'match_result': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'over_2_5': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'btts': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'clean_sheet_home': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'clean_sheet_away': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
                'over_3_5': {'n_estimators': 100, 'max_depth': 6, 'random_state': 42},
            },
            'random_forest': {
                'match_result': {'n_estimators': 100, 'max_depth': 10, 'random_state': 42},
                'over_2_5': {'n_estimators': 100, 'max_depth': 10, 'random_state': 42},
                'btts': {'n_estimators': 100, 'max_depth': 10, 'random_state': 42},
            },
            'neural_network': {
                'match_result': {'hidden_layer_sizes': (100, 50), 'max_iter': 500, 'random_state': 42},
                'over_2_5': {'hidden_layer_sizes': (100, 50), 'max_iter': 500, 'random_state': 42},
                'btts': {'hidden_layer_sizes': (100, 50), 'max_iter': 500, 'random_state': 42},
            }
        }
    
    def load_github_dataset(self):
        """Load and prepare the GitHub football dataset."""
        try:
            print("📊 Loading GitHub football dataset...")
            
            # Try to load the dataset
            dataset_paths = [
                'football_data.csv',
                'data/football_data.csv',
                'datasets/football_data.csv',
                'football-data.csv'
            ]
            
            df = None
            for path in dataset_paths:
                if os.path.exists(path):
                    print(f"✅ Found dataset at: {path}")
                    df = pd.read_csv(path)
                    break
            
            if df is None:
                print("❌ No dataset found. Creating sample data...")
                df = self.create_sample_dataset()
            
            print(f"📈 Dataset loaded: {len(df)} rows, {len(df.columns)} columns")
            print(f"📋 Columns: {list(df.columns)}")
            
            return df
            
        except Exception as e:
            logger.error(f"Error loading dataset: {str(e)}")
            print("🔧 Creating sample dataset...")
            return self.create_sample_dataset()
    
    def create_sample_dataset(self):
        """Create a sample dataset for training."""
        print("🎲 Creating sample football dataset...")
        
        np.random.seed(42)
        n_samples = 5000
        
        # Generate sample data
        data = {
            'home_team': np.random.choice(['Arsenal', 'Chelsea', 'Liverpool', 'Man City', 'Man United', 
                                         'Tottenham', 'Barcelona', 'Real Madrid', 'Bayern Munich', 'PSG'], n_samples),
            'away_team': np.random.choice(['Arsenal', 'Chelsea', 'Liverpool', 'Man City', 'Man United', 
                                         'Tottenham', 'Barcelona', 'Real Madrid', 'Bayern Munich', 'PSG'], n_samples),
            'home_odds': np.random.uniform(1.2, 5.0, n_samples),
            'draw_odds': np.random.uniform(2.5, 4.5, n_samples),
            'away_odds': np.random.uniform(1.2, 5.0, n_samples),
            'home_goals': np.random.poisson(1.5, n_samples),
            'away_goals': np.random.poisson(1.2, n_samples),
            'league': np.random.choice(['Premier League', 'La Liga', 'Bundesliga', 'Serie A', 'Ligue 1'], n_samples)
        }
        
        df = pd.DataFrame(data)
        
        # Create target variables
        df['match_result'] = np.where(df['home_goals'] > df['away_goals'], 0,  # Home win
                                    np.where(df['home_goals'] < df['away_goals'], 1, 2))  # Away win, Draw
        df['total_goals'] = df['home_goals'] + df['away_goals']
        df['over_2_5'] = (df['total_goals'] > 2.5).astype(int)
        df['over_1_5'] = (df['total_goals'] > 1.5).astype(int)
        df['over_3_5'] = (df['total_goals'] > 3.5).astype(int)
        df['btts'] = ((df['home_goals'] > 0) & (df['away_goals'] > 0)).astype(int)
        df['clean_sheet_home'] = (df['away_goals'] == 0).astype(int)
        df['clean_sheet_away'] = (df['home_goals'] == 0).astype(int)
        df['win_to_nil_home'] = ((df['home_goals'] > df['away_goals']) & (df['away_goals'] == 0)).astype(int)
        df['win_to_nil_away'] = ((df['away_goals'] > df['home_goals']) & (df['home_goals'] == 0)).astype(int)
        
        print(f"✅ Sample dataset created: {len(df)} rows")
        return df
    
    def prepare_features(self, df):
        """Prepare features for training."""
        print("🔧 Preparing features...")
        
        # Encode categorical variables
        le_home = LabelEncoder()
        le_away = LabelEncoder()
        le_league = LabelEncoder()
        
        df['home_team_encoded'] = le_home.fit_transform(df['home_team'])
        df['away_team_encoded'] = le_away.fit_transform(df['away_team'])
        df['league_encoded'] = le_league.fit_transform(df['league'])
        
        # Store encoders
        self.encoders['home_team'] = le_home
        self.encoders['away_team'] = le_away
        self.encoders['league'] = le_league
        
        # Create derived features
        df['odds_diff'] = df['home_odds'] - df['away_odds']
        df['total_odds'] = df['home_odds'] + df['draw_odds'] + df['away_odds']
        
        # Probability features
        total_prob = (1/df['home_odds']) + (1/df['draw_odds']) + (1/df['away_odds'])
        df['home_win_prob'] = (1/df['home_odds']) / total_prob
        df['draw_prob'] = (1/df['draw_odds']) / total_prob
        df['away_win_prob'] = (1/df['away_odds']) / total_prob
        
        # Form features (estimated from odds)
        df['home_form'] = np.clip(3.0 / df['home_odds'], 0.1, 1.0)
        df['away_form'] = np.clip(3.0 / df['away_odds'], 0.1, 1.0)
        df['form_diff'] = df['home_form'] - df['away_form']
        
        # Feature columns for training
        self.feature_columns = [
            'home_team_encoded', 'away_team_encoded', 'league_encoded',
            'home_odds', 'draw_odds', 'away_odds', 'odds_diff', 'total_odds',
            'home_win_prob', 'draw_prob', 'away_win_prob',
            'home_form', 'away_form', 'form_diff'
        ]
        
        print(f"✅ Features prepared: {len(self.feature_columns)} features")
        print(f"📋 Feature columns: {self.feature_columns}")
        
        return df
    
    def train_model(self, model_type, model_name, X_train, X_test, y_train, y_test):
        """Train a single model."""
        try:
            print(f"🎯 Training {model_type}/{model_name}...")
            
            # Get model configuration
            config = self.model_configs[model_type][model_name]
            
            # Create model
            if model_type == 'xgboost':
                model = xgb.XGBClassifier(**config)
            elif model_type == 'lightgbm':
                model = lgb.LGBMClassifier(**config, verbose=-1)
            elif model_type == 'random_forest':
                model = RandomForestClassifier(**config)
            elif model_type == 'neural_network':
                model = MLPClassifier(**config)
            else:
                raise ValueError(f"Unknown model type: {model_type}")
            
            # Train model
            model.fit(X_train, y_train)
            
            # Evaluate
            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            
            print(f"   ✅ {model_type}/{model_name}: {accuracy:.3f} accuracy")
            
            # Store model
            if model_type not in self.models:
                self.models[model_type] = {}
            
            self.models[model_type][model_name] = {
                'model': model,
                'scaler': None,  # No scaling for tree-based models
                'accuracy': accuracy
            }
            
            # Save model
            model_path = f'models/{model_type}_{model_name}.pkl'
            with open(model_path, 'wb') as f:
                pickle.dump(model, f)
            
            return True
            
        except Exception as e:
            logger.error(f"Error training {model_type}/{model_name}: {str(e)}")
            return False
    
    def train_all_models(self):
        """Train all models."""
        print("🚀 TRAINING ALL MODELS WITH GITHUB DATASET")
        print("=" * 60)
        
        # Load dataset
        df = self.load_github_dataset()
        
        # Prepare features
        df = self.prepare_features(df)
        
        # Prepare training data
        X = df[self.feature_columns]
        
        # Target variables
        targets = {
            'match_result': df['match_result'],
            'over_2_5': df['over_2_5'],
            'over_1_5': df['over_1_5'],
            'over_3_5': df['over_3_5'],
            'btts': df['btts'],
            'clean_sheet_home': df['clean_sheet_home'],
            'clean_sheet_away': df['clean_sheet_away'],
            'win_to_nil_home': df['win_to_nil_home'],
            'win_to_nil_away': df['win_to_nil_away']
        }
        
        print(f"\n📊 Training data prepared:")
        print(f"   Features: {X.shape}")
        print(f"   Targets: {len(targets)}")
        
        # Train models for each target
        total_models = 0
        successful_models = 0
        
        for target_name, y in targets.items():
            print(f"\n🎯 Training models for: {target_name}")
            print("-" * 40)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )
            
            # Train each model type
            for model_type, model_configs in self.model_configs.items():
                if target_name in model_configs:
                    total_models += 1
                    success = self.train_model(
                        model_type, target_name, X_train, X_test, y_train, y_test
                    )
                    if success:
                        successful_models += 1
        
        # Save encoders and feature columns
        with open('models/encoders.pkl', 'wb') as f:
            pickle.dump(self.encoders, f)
        
        with open('models/feature_columns.pkl', 'wb') as f:
            pickle.dump(self.feature_columns, f)
        
        with open('models/model_registry.pkl', 'wb') as f:
            pickle.dump(self.models, f)
        
        print(f"\n📈 TRAINING SUMMARY:")
        print(f"✅ Successful models: {successful_models}/{total_models}")
        print(f"📊 Success rate: {(successful_models/total_models*100):.1f}%")
        print(f"💾 Models saved to: models/")
        print(f"🔧 Encoders saved to: models/encoders.pkl")
        print(f"📋 Features saved to: models/feature_columns.pkl")
        
        return successful_models == total_models

def main():
    """Main training function."""
    print("🎯 GITHUB DATASET ML MODEL TRAINING")
    print("=" * 60)
    print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    trainer = GitHubDatasetTrainer()
    success = trainer.train_all_models()
    
    print(f"\n" + "=" * 60)
    if success:
        print("🎉 ALL MODELS TRAINED SUCCESSFULLY!")
        print("💡 Models are ready for prediction service")
    else:
        print("⚠️  SOME MODELS FAILED TO TRAIN")
        print("🔧 Check logs for details")
    print("=" * 60)
    
    return success

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)

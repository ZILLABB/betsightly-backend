#!/usr/bin/env python3
"""
Seed Data Script

This script seeds the database with initial data for punters and bookmakers.
"""

import os
import sys
import json
import logging
from datetime import datetime

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.common import setup_logging
from app.database import init_db, get_db
from app.models.punter import Punter
from app.models.bookmaker import Bookmaker

# Set up logging
logger = setup_logging(__name__)

# Top 20 Nigerian punters
TOP_PUNTERS = [
    {
        "name": "Adigun Somefun",
        "nickname": "Sokadibet",
        "country": "Nigeria",
        "popularity": 95,
        "specialty": "Premier League predictions",
        "success_rate": 78.0,
        "image_url": "https://example.com/images/punters/adigun.jpg",
        "social_media": {
            "twitter": "@sokadibet",
            "instagram": "sokadibet"
        },
        "bio": "Premier League specialist with over 10 years of experience in football predictions.",
        "verified": True
    },
    {
        "name": "Olusegun Obende",
        "nickname": "BetKing",
        "country": "Nigeria",
        "popularity": 92,
        "specialty": "BTTS predictions",
        "success_rate": 82.0,
        "image_url": "https://example.com/images/punters/olusegun.jpg",
        "social_media": {
            "twitter": "@betking_ng",
            "instagram": "betking_ng"
        },
        "bio": "Both Teams To Score (BTTS) specialist with a remarkable success rate.",
        "verified": True
    },
    {
        "name": "Kelechi Iheanacho",
        "nickname": "PredictionMaster",
        "country": "Nigeria",
        "popularity": 88,
        "specialty": "African leagues",
        "success_rate": 75.0,
        "image_url": "https://example.com/images/punters/kelechi.jpg",
        "social_media": {
            "twitter": "@predictionmaster",
            "instagram": "prediction_master"
        },
        "bio": "Expert in African football leagues with deep knowledge of local teams.",
        "verified": True
    },
    {
        "name": "Adebayo Williams",
        "nickname": "BetMaster",
        "country": "Nigeria",
        "popularity": 85,
        "specialty": "Over/Under markets",
        "success_rate": 80.0,
        "image_url": "https://example.com/images/punters/adebayo.jpg",
        "social_media": {
            "twitter": "@betmaster",
            "instagram": "betmaster_ng"
        },
        "bio": "Specializes in Over/Under markets with consistent success.",
        "verified": True
    },
    {
        "name": "Chinedu Okonkwo",
        "nickname": "EaglePredicts",
        "country": "Nigeria",
        "popularity": 83,
        "specialty": "Correct score predictions",
        "success_rate": 68.0,
        "image_url": "https://example.com/images/punters/chinedu.jpg",
        "social_media": {
            "twitter": "@eaglepredicts",
            "instagram": "eagle_predicts"
        },
        "bio": "Known for accurate correct score predictions in major leagues.",
        "verified": True
    },
    {
        "name": "Oluwaseun Adeniyi",
        "nickname": "WinnersTips",
        "country": "Nigeria",
        "popularity": 80,
        "specialty": "Accumulator bets",
        "success_rate": 72.0,
        "image_url": "https://example.com/images/punters/oluwaseun.jpg",
        "social_media": {
            "twitter": "@winnerstips",
            "instagram": "winners_tips"
        },
        "bio": "Accumulator specialist with a knack for combining high-value selections.",
        "verified": True
    },
    {
        "name": "Emeka Okafor",
        "nickname": "GoalMachine",
        "country": "Nigeria",
        "popularity": 78,
        "specialty": "Goal scorer markets",
        "success_rate": 71.0,
        "image_url": "https://example.com/images/punters/emeka.jpg",
        "social_media": {
            "twitter": "@goalmachine",
            "instagram": "goal_machine"
        },
        "bio": "Expert in predicting goal scorers across major European leagues.",
        "verified": True
    },
    {
        "name": "Tunde Adeleke",
        "nickname": "BetOracleNG",
        "country": "Nigeria",
        "popularity": 77,
        "specialty": "La Liga predictions",
        "success_rate": 77.0,
        "image_url": "https://example.com/images/punters/tunde.jpg",
        "social_media": {
            "twitter": "@betoracleng",
            "instagram": "bet_oracle_ng"
        },
        "bio": "Spanish La Liga specialist with deep insights into team strategies.",
        "verified": True
    },
    {
        "name": "Chijioke Nnamdi",
        "nickname": "SuperEagles",
        "country": "Nigeria",
        "popularity": 75,
        "specialty": "Nigerian league",
        "success_rate": 79.0,
        "image_url": "https://example.com/images/punters/chijioke.jpg",
        "social_media": {
            "twitter": "@supereagles",
            "instagram": "super_eagles_predictions"
        },
        "bio": "Nigerian Premier League expert with unmatched local knowledge.",
        "verified": True
    },
    {
        "name": "Folarin Johnson",
        "nickname": "NaijaBetTips",
        "country": "Nigeria",
        "popularity": 74,
        "specialty": "Champions League",
        "success_rate": 76.0,
        "image_url": "https://example.com/images/punters/folarin.jpg",
        "social_media": {
            "twitter": "@naijabettips",
            "instagram": "naija_bet_tips"
        },
        "bio": "UEFA Champions League specialist with excellent European football knowledge.",
        "verified": True
    },
    {
        "name": "Ibrahim Hassan",
        "nickname": "BetProphet",
        "country": "Nigeria",
        "popularity": 72,
        "specialty": "Asian handicap",
        "success_rate": 81.0,
        "image_url": "https://example.com/images/punters/ibrahim.jpg",
        "social_media": {
            "twitter": "@betprophet",
            "instagram": "bet_prophet"
        },
        "bio": "Asian handicap market specialist with consistent high returns.",
        "verified": True
    },
    {
        "name": "Victoria Oladipo",
        "nickname": "BetQueen",
        "country": "Nigeria",
        "popularity": 70,
        "specialty": "Women's football",
        "success_rate": 83.0,
        "image_url": "https://example.com/images/punters/victoria.jpg",
        "social_media": {
            "twitter": "@betqueen",
            "instagram": "bet_queen"
        },
        "bio": "Women's football expert with unparalleled insights into the female game.",
        "verified": True
    },
    {
        "name": "Samuel Okoye",
        "nickname": "OddsKing",
        "country": "Nigeria",
        "popularity": 68,
        "specialty": "Value betting",
        "success_rate": 74.0,
        "image_url": "https://example.com/images/punters/samuel.jpg",
        "social_media": {
            "twitter": "@oddsking",
            "instagram": "odds_king"
        },
        "bio": "Value betting specialist who identifies underpriced odds in the market.",
        "verified": True
    },
    {
        "name": "Funke Adeyemi",
        "nickname": "BetDiva",
        "country": "Nigeria",
        "popularity": 67,
        "specialty": "In-play betting",
        "success_rate": 77.0,
        "image_url": "https://example.com/images/punters/funke.jpg",
        "social_media": {
            "twitter": "@betdiva",
            "instagram": "bet_diva"
        },
        "bio": "Live betting expert with a talent for spotting in-game opportunities.",
        "verified": True
    },
    {
        "name": "Yusuf Bello",
        "nickname": "PredictionGuru",
        "country": "Nigeria",
        "popularity": 65,
        "specialty": "Serie A predictions",
        "success_rate": 79.0,
        "image_url": "https://example.com/images/punters/yusuf.jpg",
        "social_media": {
            "twitter": "@predictionguru",
            "instagram": "prediction_guru"
        },
        "bio": "Italian Serie A specialist with deep tactical knowledge.",
        "verified": True
    },
    {
        "name": "Blessing Okoro",
        "nickname": "WinningStreak",
        "country": "Nigeria",
        "popularity": 63,
        "specialty": "Bundesliga predictions",
        "success_rate": 75.0,
        "image_url": "https://example.com/images/punters/blessing.jpg",
        "social_media": {
            "twitter": "@winningstreak",
            "instagram": "winning_streak"
        },
        "bio": "German Bundesliga expert with a focus on high-scoring matches.",
        "verified": True
    },
    {
        "name": "David Ogunleye",
        "nickname": "BetMogul",
        "country": "Nigeria",
        "popularity": 62,
        "specialty": "Corner markets",
        "success_rate": 82.0,
        "image_url": "https://example.com/images/punters/david.jpg",
        "social_media": {
            "twitter": "@betmogul",
            "instagram": "bet_mogul"
        },
        "bio": "Corner kick market specialist with statistical approach to predictions.",
        "verified": True
    },
    {
        "name": "Grace Eze",
        "nickname": "LuckyPicks",
        "country": "Nigeria",
        "popularity": 60,
        "specialty": "Draw specialists",
        "success_rate": 70.0,
        "image_url": "https://example.com/images/punters/grace.jpg",
        "social_media": {
            "twitter": "@luckypicks",
            "instagram": "lucky_picks"
        },
        "bio": "Specializes in identifying matches likely to end in draws.",
        "verified": True
    },
    {
        "name": "Taiwo Afolabi",
        "nickname": "BetWizard",
        "country": "Nigeria",
        "popularity": 58,
        "specialty": "Card markets",
        "success_rate": 76.0,
        "image_url": "https://example.com/images/punters/taiwo.jpg",
        "social_media": {
            "twitter": "@betwizard",
            "instagram": "bet_wizard"
        },
        "bio": "Card and booking market specialist with insights into referee tendencies.",
        "verified": True
    },
    {
        "name": "Chika Nwosu",
        "nickname": "GoldenTips",
        "country": "Nigeria",
        "popularity": 55,
        "specialty": "Long-term bets",
        "success_rate": 73.0,
        "image_url": "https://example.com/images/punters/chika.jpg",
        "social_media": {
            "twitter": "@goldentips",
            "instagram": "golden_tips"
        },
        "bio": "Specializes in long-term tournament and season outcome predictions.",
        "verified": True
    }
]

# Popular bookmakers
BOOKMAKERS = [
    {
        "name": "Bet9ja",
        "logo_url": "https://example.com/images/bookmakers/bet9ja.png",
        "website": "https://www.bet9ja.com",
        "country": "Nigeria"
    },
    {
        "name": "1xBet",
        "logo_url": "https://example.com/images/bookmakers/1xbet.png",
        "website": "https://www.1xbet.ng",
        "country": "International"
    },
    {
        "name": "BetKing",
        "logo_url": "https://example.com/images/bookmakers/betking.png",
        "website": "https://www.betking.com",
        "country": "Nigeria"
    },
    {
        "name": "Sportybet",
        "logo_url": "https://example.com/images/bookmakers/sportybet.png",
        "website": "https://www.sportybet.com",
        "country": "Nigeria"
    },
    {
        "name": "NairaBet",
        "logo_url": "https://example.com/images/bookmakers/nairabet.png",
        "website": "https://www.nairabet.com",
        "country": "Nigeria"
    },
    {
        "name": "Betway",
        "logo_url": "https://example.com/images/bookmakers/betway.png",
        "website": "https://www.betway.com.ng",
        "country": "International"
    },
    {
        "name": "BetLion",
        "logo_url": "https://example.com/images/bookmakers/betlion.png",
        "website": "https://www.betlion.ng",
        "country": "Nigeria"
    },
    {
        "name": "MerryBet",
        "logo_url": "https://example.com/images/bookmakers/merrybet.png",
        "website": "https://www.merrybet.com",
        "country": "Nigeria"
    },
    {
        "name": "AccessBet",
        "logo_url": "https://example.com/images/bookmakers/accessbet.png",
        "website": "https://www.accessbet.com",
        "country": "Nigeria"
    },
    {
        "name": "BangBet",
        "logo_url": "https://example.com/images/bookmakers/bangbet.png",
        "website": "https://www.bangbet.com",
        "country": "Nigeria"
    }
]

def seed_punters(db):
    """
    Seed the database with punters.
    
    Args:
        db: Database session
    """
    try:
        logger.info("Seeding punters...")
        
        # Check if punters already exist
        existing_count = db.query(Punter).count()
        
        if existing_count > 0:
            logger.info(f"Found {existing_count} existing punters. Skipping punter seeding.")
            return
        
        # Add punters
        for punter_data in TOP_PUNTERS:
            punter = Punter(
                name=punter_data["name"],
                nickname=punter_data["nickname"],
                country=punter_data["country"],
                popularity=punter_data["popularity"],
                specialty=punter_data["specialty"],
                success_rate=punter_data["success_rate"],
                image_url=punter_data["image_url"],
                social_media=punter_data["social_media"],
                bio=punter_data["bio"],
                verified=punter_data["verified"]
            )
            
            db.add(punter)
        
        # Commit changes
        db.commit()
        
        logger.info(f"Added {len(TOP_PUNTERS)} punters to the database")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding punters: {str(e)}")

def seed_bookmakers(db):
    """
    Seed the database with bookmakers.
    
    Args:
        db: Database session
    """
    try:
        logger.info("Seeding bookmakers...")
        
        # Check if bookmakers already exist
        existing_count = db.query(Bookmaker).count()
        
        if existing_count > 0:
            logger.info(f"Found {existing_count} existing bookmakers. Skipping bookmaker seeding.")
            return
        
        # Add bookmakers
        for bookmaker_data in BOOKMAKERS:
            bookmaker = Bookmaker(
                name=bookmaker_data["name"],
                logo_url=bookmaker_data["logo_url"],
                website=bookmaker_data["website"],
                country=bookmaker_data["country"]
            )
            
            db.add(bookmaker)
        
        # Commit changes
        db.commit()
        
        logger.info(f"Added {len(BOOKMAKERS)} bookmakers to the database")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding bookmakers: {str(e)}")

def main():
    """Main function."""
    try:
        # Initialize database
        init_db()
        
        # Get database session
        db = next(get_db())
        
        # Seed data
        seed_punters(db)
        seed_bookmakers(db)
        
        logger.info("Database seeding completed successfully")
        
    except Exception as e:
        logger.error(f"Error seeding database: {str(e)}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Run API Server Script

This script runs a simple FastAPI server with only the betting code endpoints.
"""

import os
import sys
import logging
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.common import setup_logging
from app.database import get_db, init_db
from app.models.punter import Punter
from app.models.bookmaker import Bookmaker
from app.models.betting_code import BettingCode
from app.schemas.betting_code import BettingCodeCreate, BettingCodeUpdate

# Set up logging
logger = setup_logging(__name__)

# Create FastAPI app
app = FastAPI(title="Betting Codes API", description="API for managing betting codes")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
@app.get("/api/punters")
def get_punters(
    db: Session = Depends(get_db),
    skip: int = Query(0, description="Number of punters to skip"),
    limit: int = Query(100, description="Maximum number of punters to return")
):
    """Get all punters."""
    try:
        # Get punters
        punters = (
            db.query(Punter)
            .order_by(Punter.name)
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Get total count
        total = db.query(Punter).count()

        # Convert to dictionaries
        punters_dict = [punter.to_dict() for punter in punters]

        return {
            "status": "success",
            "punters": punters_dict,
            "total": total,
            "skip": skip,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error getting punters: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting punters: {str(e)}")

@app.get("/api/bookmakers")
def get_bookmakers(
    db: Session = Depends(get_db),
    skip: int = Query(0, description="Number of bookmakers to skip"),
    limit: int = Query(100, description="Maximum number of bookmakers to return")
):
    """Get all bookmakers."""
    try:
        # Get bookmakers
        bookmakers = (
            db.query(Bookmaker)
            .order_by(Bookmaker.name)
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Get total count
        total = db.query(Bookmaker).count()

        # Convert to dictionaries
        bookmakers_dict = [bookmaker.to_dict() for bookmaker in bookmakers]

        return {
            "status": "success",
            "bookmakers": bookmakers_dict,
            "total": total,
            "skip": skip,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error getting bookmakers: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting bookmakers: {str(e)}")

@app.get("/api/betting-codes")
def get_betting_codes(
    db: Session = Depends(get_db),
    skip: int = Query(0, description="Number of codes to skip"),
    limit: int = Query(100, description="Maximum number of codes to return")
):
    """Get all betting codes."""
    try:
        # Get betting codes
        codes = (
            db.query(BettingCode)
            .order_by(BettingCode.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Get total count
        total = db.query(BettingCode).count()

        # Convert to dictionaries
        codes_dict = [code.to_dict() for code in codes]

        return {
            "status": "success",
            "betting_codes": codes_dict,
            "total": total,
            "skip": skip,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error getting betting codes: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting betting codes: {str(e)}")

@app.post("/api/betting-codes")
def create_betting_code(
    betting_code: BettingCodeCreate,
    db: Session = Depends(get_db)
):
    """Create a new betting code."""
    try:
        # Check if punter exists
        punter = db.query(Punter).filter(Punter.id == betting_code.punter_id).first()

        if not punter:
            raise HTTPException(status_code=404, detail=f"Punter with ID {betting_code.punter_id} not found")

        # Check if bookmaker exists if provided
        if betting_code.bookmaker_id:
            bookmaker = db.query(Bookmaker).filter(Bookmaker.id == betting_code.bookmaker_id).first()

            if not bookmaker:
                raise HTTPException(status_code=404, detail=f"Bookmaker with ID {betting_code.bookmaker_id} not found")

        # Create new betting code
        new_code = BettingCode(
            code=betting_code.code,
            punter_id=betting_code.punter_id,
            bookmaker_id=betting_code.bookmaker_id,
            odds=betting_code.odds,
            event_date=betting_code.event_date,
            expiry_date=betting_code.expiry_date,
            status=betting_code.status,
            confidence=betting_code.confidence,
            featured=betting_code.featured,
            notes=betting_code.notes
        )

        # Add to database
        db.add(new_code)
        db.commit()
        db.refresh(new_code)

        return {
            "status": "success",
            "betting_code": new_code.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating betting code: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating betting code: {str(e)}")

@app.get("/api/betting-codes/{code_id}")
def get_betting_code(
    code_id: int,
    db: Session = Depends(get_db)
):
    """Get betting code by ID."""
    try:
        # Get betting code
        code = db.query(BettingCode).filter(BettingCode.id == code_id).first()

        if not code:
            raise HTTPException(status_code=404, detail=f"Betting code with ID {code_id} not found")

        return {
            "status": "success",
            "betting_code": code.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting betting code {code_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting betting code: {str(e)}")

@app.put("/api/betting-codes/{code_id}")
def update_betting_code(
    code_id: int,
    betting_code: BettingCodeUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing betting code."""
    try:
        # Get betting code
        db_code = db.query(BettingCode).filter(BettingCode.id == code_id).first()

        if not db_code:
            raise HTTPException(status_code=404, detail=f"Betting code with ID {code_id} not found")

        # Check if punter exists if provided
        if betting_code.punter_id is not None:
            punter = db.query(Punter).filter(Punter.id == betting_code.punter_id).first()

            if not punter:
                raise HTTPException(status_code=404, detail=f"Punter with ID {betting_code.punter_id} not found")

        # Check if bookmaker exists if provided
        if betting_code.bookmaker_id is not None:
            bookmaker = db.query(Bookmaker).filter(Bookmaker.id == betting_code.bookmaker_id).first()

            if not bookmaker:
                raise HTTPException(status_code=404, detail=f"Bookmaker with ID {betting_code.bookmaker_id} not found")

        # Update fields
        update_data = betting_code.dict(exclude_unset=True)

        for key, value in update_data.items():
            setattr(db_code, key, value)

        # Commit changes
        db.commit()
        db.refresh(db_code)

        return {
            "status": "success",
            "betting_code": db_code.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating betting code {code_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating betting code: {str(e)}")

@app.delete("/api/betting-codes/{code_id}")
def delete_betting_code(
    code_id: int,
    db: Session = Depends(get_db)
):
    """Delete a betting code."""
    try:
        # Get betting code
        code = db.query(BettingCode).filter(BettingCode.id == code_id).first()

        if not code:
            raise HTTPException(status_code=404, detail=f"Betting code with ID {code_id} not found")

        # Delete betting code
        db.delete(code)
        db.commit()

        return {
            "status": "success",
            "message": f"Betting code with ID {code_id} deleted"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting betting code {code_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting betting code: {str(e)}")

def main():
    """Main function."""
    try:
        # Initialize database
        logger.info("Initializing database...")
        init_db()

        # Run server
        logger.info("Starting server...")
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except Exception as e:
        logger.error(f"Error running server: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()

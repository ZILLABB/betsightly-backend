"""
Betting Codes API Endpoints

This module defines the API endpoints for betting codes.
"""

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models.betting_code import BettingCode
from app.models.punter import Punter
from app.models.bookmaker import Bookmaker
from app.schemas.betting_code import BettingCodeCreate, BettingCodeUpdate, BettingCodeResponse, BettingCodeListResponse
from app.utils.common import setup_logging

# Set up logging
logger = setup_logging(__name__)

# Create router
router = APIRouter()

@router.get("/", response_model=BettingCodeListResponse)
def get_betting_codes(
    db: Session = Depends(get_db),
    skip: int = Query(0, description="Number of codes to skip"),
    limit: int = Query(100, description="Maximum number of codes to return")
):
    """
    Get all betting codes.

    Args:
        skip: Number of codes to skip
        limit: Maximum number of codes to return
    """
    try:
        # Get betting codes
        codes = (
            db.query(BettingCode)
            .order_by(desc(BettingCode.created_at))
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

@router.get("/{code_id}", response_model=BettingCodeResponse)
def get_betting_code(
    code_id: int,
    db: Session = Depends(get_db)
):
    """
    Get betting code by ID.

    Args:
        code_id: Betting code ID
    """
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

@router.post("/", response_model=BettingCodeResponse)
def create_betting_code(
    betting_code: BettingCodeCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new betting code.

    Args:
        betting_code: Betting code data
    """
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

@router.put("/{code_id}", response_model=BettingCodeResponse)
def update_betting_code(
    code_id: int,
    betting_code: BettingCodeUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing betting code.

    Args:
        code_id: Betting code ID
        betting_code: Updated betting code data
    """
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
        update_data = betting_code.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(db_code, key, value)

        # Update timestamp
        db_code.updated_at = datetime.now()

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

@router.delete("/{code_id}")
def delete_betting_code(
    code_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a betting code.

    Args:
        code_id: Betting code ID
    """
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

@router.get("/latest/", response_model=BettingCodeResponse)
def get_latest_betting_code(
    db: Session = Depends(get_db)
):
    """
    Get the latest betting code.
    """
    try:
        # Get latest betting code
        code = db.query(BettingCode).order_by(desc(BettingCode.created_at)).first()

        if not code:
            raise HTTPException(status_code=404, detail="No betting codes found")

        return {
            "status": "success",
            "betting_code": code.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting latest betting code: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting latest betting code: {str(e)}")

@router.get("/punter/{punter_id}", response_model=BettingCodeListResponse)
def get_betting_codes_by_punter(
    punter_id: int,
    db: Session = Depends(get_db),
    skip: int = Query(0, description="Number of codes to skip"),
    limit: int = Query(100, description="Maximum number of codes to return")
):
    """
    Get betting codes by punter ID.

    Args:
        punter_id: Punter ID
        skip: Number of codes to skip
        limit: Maximum number of codes to return
    """
    try:
        # Check if punter exists
        punter = db.query(Punter).filter(Punter.id == punter_id).first()

        if not punter:
            raise HTTPException(status_code=404, detail=f"Punter with ID {punter_id} not found")

        # Get betting codes
        codes = (
            db.query(BettingCode)
            .filter(BettingCode.punter_id == punter_id)
            .order_by(desc(BettingCode.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Get total count
        total = db.query(BettingCode).filter(BettingCode.punter_id == punter_id).count()

        # Convert to dictionaries
        codes_dict = [code.to_dict() for code in codes]

        return {
            "status": "success",
            "betting_codes": codes_dict,
            "total": total,
            "skip": skip,
            "limit": limit
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting betting codes for punter {punter_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting betting codes: {str(e)}")

@router.get("/code/{code}", response_model=BettingCodeResponse)
def get_betting_code_by_code(
    code: str,
    db: Session = Depends(get_db)
):
    """
    Get betting code by code value.

    Args:
        code: Betting code value
    """
    try:
        # Get betting code
        code_obj = db.query(BettingCode).filter(BettingCode.code == code).first()

        if not code_obj:
            raise HTTPException(status_code=404, detail=f"Betting code {code} not found")

        return {
            "status": "success",
            "betting_code": code_obj.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting betting code {code}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting betting code: {str(e)}")

@router.get("/featured/", response_model=BettingCodeListResponse)
def get_featured_betting_codes(
    db: Session = Depends(get_db),
    limit: int = Query(10, description="Maximum number of codes to return")
):
    """
    Get featured betting codes.

    Args:
        limit: Maximum number of codes to return
    """
    try:
        # Get featured betting codes
        codes = (
            db.query(BettingCode)
            .filter(BettingCode.featured == True)
            .order_by(desc(BettingCode.created_at))
            .limit(limit)
            .all()
        )

        # Get total count
        total = db.query(BettingCode).filter(BettingCode.featured == True).count()

        # Convert to dictionaries
        codes_dict = [code.to_dict() for code in codes]

        return {
            "status": "success",
            "betting_codes": codes_dict,
            "total": total,
            "skip": 0,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error getting featured betting codes: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting featured betting codes: {str(e)}")

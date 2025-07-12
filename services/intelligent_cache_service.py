"""
Intelligent Cache Service

Advanced caching system for optimal performance with 33 ML models.
"""

import redis
import json
import hashlib
import pickle
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import numpy as np
from functools import wraps

logger = logging.getLogger(__name__)

class IntelligentCacheService:
    """
    Advanced caching service optimized for ML predictions.
    
    Features:
    - Multi-tier caching (memory + Redis)
    - Intelligent cache warming
    - Prediction result caching
    - Model-specific cache strategies
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """Initialize the cache service."""
        try:
            self.redis_client = redis.from_url(redis_url)
            self.redis_available = True
            logger.info("✅ Redis cache connected")
        except Exception as e:
            logger.warning(f"⚠️ Redis not available: {str(e)}")
            self.redis_available = False
            
        # Memory cache for frequently accessed data
        self.memory_cache = {}
        self.cache_stats = {
            "hits": 0,
            "misses": 0,
            "memory_hits": 0,
            "redis_hits": 0
        }
        
    def _generate_cache_key(self, prefix: str, data: Dict[str, Any]) -> str:
        """Generate a unique cache key."""
        # Create deterministic hash from data
        data_str = json.dumps(data, sort_keys=True)
        hash_obj = hashlib.md5(data_str.encode())
        return f"{prefix}:{hash_obj.hexdigest()}"
    
    def cache_prediction_result(self, 
                              fixture_data: Dict[str, Any], 
                              predictions: Dict[str, Any],
                              ttl: int = 3600) -> bool:
        """Cache prediction results with intelligent TTL."""
        try:
            cache_key = self._generate_cache_key("prediction", fixture_data)
            
            cache_data = {
                "predictions": predictions,
                "timestamp": datetime.now().isoformat(),
                "fixture_data": fixture_data
            }
            
            # Store in memory cache
            self.memory_cache[cache_key] = cache_data
            
            # Store in Redis if available
            if self.redis_available:
                self.redis_client.setex(
                    cache_key, 
                    ttl, 
                    pickle.dumps(cache_data)
                )
                
            logger.debug(f"Cached prediction: {cache_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cache prediction: {str(e)}")
            return False
    
    def get_cached_prediction(self, fixture_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Retrieve cached prediction if available."""
        try:
            cache_key = self._generate_cache_key("prediction", fixture_data)
            
            # Check memory cache first
            if cache_key in self.memory_cache:
                self.cache_stats["hits"] += 1
                self.cache_stats["memory_hits"] += 1
                logger.debug(f"Memory cache hit: {cache_key}")
                return self.memory_cache[cache_key]["predictions"]
            
            # Check Redis cache
            if self.redis_available:
                cached_data = self.redis_client.get(cache_key)
                if cached_data:
                    data = pickle.loads(cached_data)
                    # Store in memory for next time
                    self.memory_cache[cache_key] = data
                    self.cache_stats["hits"] += 1
                    self.cache_stats["redis_hits"] += 1
                    logger.debug(f"Redis cache hit: {cache_key}")
                    return data["predictions"]
            
            # Cache miss
            self.cache_stats["misses"] += 1
            return None
            
        except Exception as e:
            logger.error(f"Failed to retrieve cached prediction: {str(e)}")
            return None
    
    def warm_cache_for_date(self, date: str, fixtures: List[Dict[str, Any]]):
        """Pre-warm cache for upcoming fixtures."""
        logger.info(f"🔥 Warming cache for {len(fixtures)} fixtures on {date}")
        
        # This would be called by a background task
        # to pre-generate predictions for popular fixtures
        for fixture in fixtures:
            cache_key = self._generate_cache_key("prediction", fixture)
            if not self.get_cached_prediction(fixture):
                logger.debug(f"Cache warming needed for: {fixture.get('home_team')} vs {fixture.get('away_team')}")
    
    def cache_model_predictions(self, 
                              model_name: str, 
                              features: np.ndarray, 
                              prediction: Any,
                              ttl: int = 1800) -> bool:
        """Cache individual model predictions."""
        try:
            # Create cache key from model name and feature hash
            features_hash = hashlib.md5(features.tobytes()).hexdigest()
            cache_key = f"model:{model_name}:{features_hash}"
            
            if self.redis_available:
                self.redis_client.setex(
                    cache_key,
                    ttl,
                    pickle.dumps(prediction)
                )
                return True
                
        except Exception as e:
            logger.error(f"Failed to cache model prediction: {str(e)}")
            
        return False
    
    def get_cached_model_prediction(self, model_name: str, features: np.ndarray) -> Optional[Any]:
        """Retrieve cached model prediction."""
        try:
            features_hash = hashlib.md5(features.tobytes()).hexdigest()
            cache_key = f"model:{model_name}:{features_hash}"
            
            if self.redis_available:
                cached_data = self.redis_client.get(cache_key)
                if cached_data:
                    return pickle.loads(cached_data)
                    
        except Exception as e:
            logger.error(f"Failed to retrieve cached model prediction: {str(e)}")
            
        return None
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        total_requests = self.cache_stats["hits"] + self.cache_stats["misses"]
        hit_rate = (self.cache_stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "hit_rate_percentage": round(hit_rate, 2),
            "total_requests": total_requests,
            "memory_hits": self.cache_stats["memory_hits"],
            "redis_hits": self.cache_stats["redis_hits"],
            "misses": self.cache_stats["misses"],
            "redis_available": self.redis_available
        }
    
    def clear_cache(self, pattern: str = "*"):
        """Clear cache entries matching pattern."""
        try:
            # Clear memory cache
            if pattern == "*":
                self.memory_cache.clear()
            else:
                keys_to_remove = [k for k in self.memory_cache.keys() if pattern in k]
                for key in keys_to_remove:
                    del self.memory_cache[key]
            
            # Clear Redis cache
            if self.redis_available:
                if pattern == "*":
                    self.redis_client.flushdb()
                else:
                    keys = self.redis_client.keys(f"*{pattern}*")
                    if keys:
                        self.redis_client.delete(*keys)
                        
            logger.info(f"Cache cleared for pattern: {pattern}")
            
        except Exception as e:
            logger.error(f"Failed to clear cache: {str(e)}")

# Decorator for automatic caching
def cache_predictions(ttl: int = 3600):
    """Decorator to automatically cache prediction results."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # This would integrate with the cache service
            # to automatically cache and retrieve predictions
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Global cache instance
cache_service = IntelligentCacheService()

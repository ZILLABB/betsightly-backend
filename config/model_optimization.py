"""
Model Optimization Configuration

This module provides optimized settings for model loading and memory management.
"""

import os
import logging
from typing import Dict, List, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ModelOptimizationConfig:
    """Configuration for model optimization and memory management."""
    
    # Memory thresholds (in MB)
    MAX_MODEL_SIZE_MB: int = 100  # Increased from 50MB
    TOTAL_MEMORY_LIMIT_MB: int = 2048  # 2GB total limit
    
    # Model loading priorities (1 = highest priority)
    MODEL_PRIORITIES: Dict[str, int] = None
    
    # Performance settings
    ENABLE_MODEL_CACHING: bool = True
    LAZY_LOADING: bool = True
    PARALLEL_LOADING: bool = False  # Disabled for memory safety
    
    # PyTorch optimizations
    PYTORCH_MEMORY_FRACTION: float = 0.8
    PYTORCH_ALLOW_TF32: bool = True
    
    def __post_init__(self):
        if self.MODEL_PRIORITIES is None:
            self.MODEL_PRIORITIES = {
                # XGBoost models (highest priority - fast and accurate)
                "xgboost": 1,
                
                # PyTorch models (high priority - TensorFlow alternatives)
                "pytorch": 2,
                
                # LightGBM models (high priority - efficient)
                "lightgbm": 3,
                
                # Advanced models (medium priority)
                "advanced": 4,
                
                # Quick models (medium priority - fallbacks)
                "quick": 5,
                
                # Enhanced models (lower priority - memory intensive)
                "enhanced": 6,
                
                # Legacy models (lowest priority)
                "legacy": 7
            }

class ModelMemoryManager:
    """Manages model memory usage and optimization."""
    
    def __init__(self, config: ModelOptimizationConfig = None):
        self.config = config or ModelOptimizationConfig()
        self.loaded_models = {}
        self.memory_usage = {}
        self.total_memory_used = 0
        
    def can_load_model(self, model_path: str, model_name: str) -> bool:
        """Check if a model can be loaded based on memory constraints."""
        try:
            if not os.path.exists(model_path):
                return False
                
            file_size_mb = os.path.getsize(model_path) / (1024 * 1024)
            
            # Check individual model size limit
            if file_size_mb > self.config.MAX_MODEL_SIZE_MB:
                logger.warning(f"⚠️  Model {model_name} ({file_size_mb:.1f}MB) exceeds size limit")
                return False
            
            # Check total memory limit
            if self.total_memory_used + file_size_mb > self.config.TOTAL_MEMORY_LIMIT_MB:
                logger.warning(f"⚠️  Loading {model_name} would exceed memory limit")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error checking model {model_name}: {str(e)}")
            return False
    
    def register_model_loaded(self, model_name: str, memory_mb: float):
        """Register that a model has been loaded."""
        self.memory_usage[model_name] = memory_mb
        self.total_memory_used += memory_mb
        logger.info(f"📊 Model {model_name} loaded: {memory_mb:.1f}MB (Total: {self.total_memory_used:.1f}MB)")
    
    def unload_model(self, model_name: str):
        """Unload a model to free memory."""
        if model_name in self.memory_usage:
            memory_freed = self.memory_usage[model_name]
            self.total_memory_used -= memory_freed
            del self.memory_usage[model_name]
            
            if model_name in self.loaded_models:
                del self.loaded_models[model_name]
                
            logger.info(f"🗑️  Unloaded {model_name}: freed {memory_freed:.1f}MB")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get current memory usage statistics."""
        return {
            "total_memory_used_mb": self.total_memory_used,
            "memory_limit_mb": self.config.TOTAL_MEMORY_LIMIT_MB,
            "memory_utilization_percent": (self.total_memory_used / self.config.TOTAL_MEMORY_LIMIT_MB) * 100,
            "loaded_models_count": len(self.loaded_models),
            "models_memory_breakdown": self.memory_usage
        }

class PyTorchOptimizer:
    """Optimizations specific to PyTorch models."""
    
    @staticmethod
    def optimize_pytorch_settings():
        """Apply PyTorch-specific optimizations."""
        try:
            import torch
            
            # Memory optimizations
            torch.backends.cudnn.benchmark = True
            torch.backends.cudnn.deterministic = False
            
            # Enable TF32 for better performance on Ampere GPUs
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            
            # Set memory fraction if CUDA is available
            if torch.cuda.is_available():
                torch.cuda.set_per_process_memory_fraction(0.8)
                logger.info("🚀 PyTorch CUDA optimizations applied")
            else:
                logger.info("💻 PyTorch CPU optimizations applied")
                
            return True
            
        except ImportError:
            logger.warning("⚠️  PyTorch not available for optimization")
            return False
        except Exception as e:
            logger.error(f"❌ PyTorch optimization failed: {str(e)}")
            return False

def get_optimized_model_loading_order(available_models: List[str]) -> List[str]:
    """
    Get optimized model loading order based on priorities.
    
    Args:
        available_models: List of available model names
        
    Returns:
        List of models sorted by loading priority
    """
    config = ModelOptimizationConfig()
    
    def get_priority(model_name: str) -> int:
        """Get priority for a model based on its type."""
        for model_type, priority in config.MODEL_PRIORITIES.items():
            if model_type in model_name.lower():
                return priority
        return 999  # Unknown models get lowest priority
    
    # Sort by priority (lower number = higher priority)
    sorted_models = sorted(available_models, key=get_priority)
    
    logger.info(f"📋 Optimized loading order: {sorted_models[:5]}..." if len(sorted_models) > 5 else f"📋 Loading order: {sorted_models}")
    
    return sorted_models

def apply_system_optimizations():
    """Apply system-wide optimizations."""
    logger.info("🔧 Applying system optimizations...")
    
    # PyTorch optimizations
    pytorch_optimized = PyTorchOptimizer.optimize_pytorch_settings()
    
    # Memory management
    import gc
    gc.collect()  # Force garbage collection
    
    optimizations_applied = []
    if pytorch_optimized:
        optimizations_applied.append("PyTorch")
    
    optimizations_applied.append("Memory Management")
    
    logger.info(f"✅ System optimizations applied: {', '.join(optimizations_applied)}")
    
    return {
        "pytorch_optimized": pytorch_optimized,
        "memory_optimized": True,
        "optimizations": optimizations_applied
    }

# Global instances
model_memory_manager = ModelMemoryManager()
optimization_config = ModelOptimizationConfig()

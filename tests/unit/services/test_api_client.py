"""
Test API Client

This module contains tests for the base API client.
"""

import os
import sys
import pytest
import requests
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import the app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from app.services.api_client import APIClient

class TestAPIClient:
    """Tests for the APIClient class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.client = APIClient(
            base_url="https://api.example.com",
            headers={"Authorization": "Bearer test_token"},
            timeout=10
        )
    
    def test_init(self):
        """Test initialization."""
        assert self.client.base_url == "https://api.example.com"
        assert self.client.headers == {"Authorization": "Bearer test_token"}
        assert self.client.timeout == 10
        assert self.client.rate_limit["limit"] == 100
        assert self.client.rate_limit["remaining"] == 100
        assert isinstance(self.client.rate_limit["reset"], datetime)
        assert self.client.cache == {}
        assert self.client.cache_expiry == {}
    
    def test_get_cache_key(self):
        """Test cache key generation."""
        key1 = self.client._get_cache_key("endpoint")
        key2 = self.client._get_cache_key("endpoint", {"param": "value"})
        
        assert key1 == "endpoint_{}"
        assert key2 == 'endpoint_{"param": "value"}'
        assert key1 != key2
    
    @patch("requests.request")
    def test_request_success(self, mock_request):
        """Test successful request."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.headers = {}
        
        mock_request.return_value = mock_response
        
        # Make request
        response = self.client.request("GET", "test")
        
        # Check request was made correctly
        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.example.com/test",
            headers={"Authorization": "Bearer test_token"},
            params=None,
            json=None,
            timeout=10
        )
        
        # Check response
        assert response == {"data": "test"}
        
        # Check rate limit was updated
        assert self.client.rate_limit["remaining"] == 99
    
    @patch("requests.request")
    def test_request_error(self, mock_request):
        """Test request with error."""
        # Mock error
        mock_request.side_effect = requests.RequestException("Test error")
        
        # Make request
        response = self.client.request("GET", "test")
        
        # Check response
        assert response["status"] == "error"
        assert "Test error" in response["message"]
        assert response["endpoint"] == "test"
    
    @patch("requests.request")
    def test_get(self, mock_request):
        """Test GET request."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.headers = {}
        
        mock_request.return_value = mock_response
        
        # Make request
        response = self.client.get("test", params={"param": "value"})
        
        # Check request was made correctly
        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.example.com/test",
            headers={"Authorization": "Bearer test_token"},
            params={"param": "value"},
            json=None,
            timeout=10
        )
        
        # Check response
        assert response == {"data": "test"}
    
    @patch("requests.request")
    def test_post(self, mock_request):
        """Test POST request."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.headers = {}
        
        mock_request.return_value = mock_response
        
        # Make request
        response = self.client.post("test", data={"data": "value"})
        
        # Check request was made correctly
        mock_request.assert_called_once_with(
            method="POST",
            url="https://api.example.com/test",
            headers={"Authorization": "Bearer test_token"},
            params=None,
            json={"data": "value"},
            timeout=10
        )
        
        # Check response
        assert response == {"data": "test"}
    
    def test_check_rate_limit(self):
        """Test rate limit checking."""
        # Test with remaining requests
        self.client.rate_limit["remaining"] = 10
        assert self.client._check_rate_limit() is True
        
        # Test with no remaining requests but reset time in the past
        self.client.rate_limit["remaining"] = 0
        self.client.rate_limit["reset"] = datetime.now() - timedelta(seconds=10)
        assert self.client._check_rate_limit() is True
        assert self.client.rate_limit["remaining"] == self.client.rate_limit["limit"]
        
        # Test with no remaining requests and reset time in the future
        self.client.rate_limit["remaining"] = 0
        self.client.rate_limit["reset"] = datetime.now() + timedelta(seconds=10)
        assert self.client._check_rate_limit() is False
    
    def test_get_from_cache(self):
        """Test getting from cache."""
        # Test with empty cache
        assert self.client._get_from_cache("test") is None
        
        # Test with cached item but expired
        self.client.cache["test_{}"] = {"data": "test"}
        self.client.cache_expiry["test_{}"] = datetime.now() - timedelta(seconds=10)
        assert self.client._get_from_cache("test") is None
        assert "test_{}" not in self.client.cache
        
        # Test with cached item not expired
        self.client.cache["test_{}"] = {"data": "test"}
        self.client.cache_expiry["test_{}"] = datetime.now() + timedelta(seconds=10)
        assert self.client._get_from_cache("test") == {"data": "test"}
    
    def test_add_to_cache(self):
        """Test adding to cache."""
        self.client._add_to_cache("test", {"param": "value"}, {"data": "test"}, 60)
        
        cache_key = self.client._get_cache_key("test", {"param": "value"})
        
        assert self.client.cache[cache_key] == {"data": "test"}
        assert cache_key in self.client.cache_expiry
        assert self.client.cache_expiry[cache_key] > datetime.now()

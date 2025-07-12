import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  Box, 
  Card, 
  CardContent, 
  Typography, 
  Grid, 
  Chip, 
  Button, 
  CircularProgress,
  Divider,
  Avatar,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  IconButton
} from '@mui/material';
import { 
  SportsSoccer as SportsIcon,
  AccessTime as TimeIcon,
  Person as PersonIcon,
  Casino as OddsIcon,
  Code as CodeIcon,
  Store as BookmakerIcon,
  Refresh as RefreshIcon
} from '@mui/icons-material';

// API base URL
const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:8000';

/**
 * BettingCodes component displays betting codes from punters
 */
const BettingCodes = () => {
  // State
  const [bettingCodes, setBettingCodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedPunter, setSelectedPunter] = useState(null);
  const [punters, setPunters] = useState([]);

  // Fetch betting codes
  const fetchBettingCodes = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await axios.get(`${API_BASE_URL}/api/betting-codes/`);
      
      if (response.data.status === 'success') {
        setBettingCodes(response.data.betting_codes);
      } else {
        setError('Failed to fetch betting codes');
      }
    } catch (err) {
      setError(`Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Fetch punters
  const fetchPunters = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/punters/`);
      
      if (response.data.status === 'success') {
        setPunters(response.data.punters);
      }
    } catch (err) {
      console.error('Error fetching punters:', err);
    }
  };

  // Fetch betting codes by punter
  const fetchBettingCodesByPunter = async (punterId) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await axios.get(`${API_BASE_URL}/api/betting-codes/punter/${punterId}`);
      
      if (response.data.status === 'success') {
        setBettingCodes(response.data.betting_codes);
        setSelectedPunter(punterId);
      } else {
        setError('Failed to fetch betting codes');
      }
    } catch (err) {
      setError(`Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Load data on component mount
  useEffect(() => {
    fetchBettingCodes();
    fetchPunters();
  }, []);

  // Format date
  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  // Get status color
  const getStatusColor = (status) => {
    switch (status) {
      case 'won':
        return 'success';
      case 'lost':
        return 'error';
      case 'pending':
        return 'warning';
      default:
        return 'default';
    }
  };

  // Render punter filter
  const renderPunterFilter = () => (
    <Box sx={{ mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        Filter by Punter
      </Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        <Button 
          variant={selectedPunter === null ? 'contained' : 'outlined'} 
          onClick={() => fetchBettingCodes()}
          size="small"
        >
          All
        </Button>
        {punters.map((punter) => (
          <Button
            key={punter.id}
            variant={selectedPunter === punter.id ? 'contained' : 'outlined'}
            onClick={() => fetchBettingCodesByPunter(punter.id)}
            size="small"
          >
            {punter.name}
          </Button>
        ))}
      </Box>
    </Box>
  );

  // Render betting code card
  const renderBettingCodeCard = (code) => (
    <Grid item xs={12} sm={6} md={4} key={code.id}>
      <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6" component="div">
              <CodeIcon sx={{ mr: 1, verticalAlign: 'middle' }} />
              {code.code}
            </Typography>
            <Chip 
              label={code.status} 
              color={getStatusColor(code.status)} 
              size="small" 
            />
          </Box>
          
          <Divider sx={{ my: 1 }} />
          
          <List dense>
            <ListItem>
              <ListItemAvatar>
                <Avatar>
                  <PersonIcon />
                </Avatar>
              </ListItemAvatar>
              <ListItemText 
                primary="Punter" 
                secondary={code.punter_name || 'Unknown'} 
              />
            </ListItem>
            
            <ListItem>
              <ListItemAvatar>
                <Avatar>
                  <BookmakerIcon />
                </Avatar>
              </ListItemAvatar>
              <ListItemText 
                primary="Bookmaker" 
                secondary={code.bookmaker_name || 'Unknown'} 
              />
            </ListItem>
            
            <ListItem>
              <ListItemAvatar>
                <Avatar>
                  <OddsIcon />
                </Avatar>
              </ListItemAvatar>
              <ListItemText 
                primary="Odds" 
                secondary={code.odds || 'N/A'} 
              />
            </ListItem>
            
            <ListItem>
              <ListItemAvatar>
                <Avatar>
                  <TimeIcon />
                </Avatar>
              </ListItemAvatar>
              <ListItemText 
                primary="Event Date" 
                secondary={formatDate(code.event_date)} 
              />
            </ListItem>
          </List>
          
          {code.notes && (
            <>
              <Divider sx={{ my: 1 }} />
              <Typography variant="body2" color="text.secondary">
                {code.notes}
              </Typography>
            </>
          )}
        </CardContent>
      </Card>
    </Grid>
  );

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" component="h1">
          Betting Codes
        </Typography>
        <IconButton onClick={fetchBettingCodes} disabled={loading}>
          <RefreshIcon />
        </IconButton>
      </Box>
      
      {renderPunterFilter()}
      
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
          <CircularProgress />
        </Box>
      ) : error ? (
        <Box sx={{ p: 2, bgcolor: 'error.light', borderRadius: 1 }}>
          <Typography color="error">{error}</Typography>
        </Box>
      ) : bettingCodes.length === 0 ? (
        <Box sx={{ p: 2, bgcolor: 'grey.100', borderRadius: 1 }}>
          <Typography>No betting codes found.</Typography>
        </Box>
      ) : (
        <Grid container spacing={3}>
          {bettingCodes.map(renderBettingCodeCard)}
        </Grid>
      )}
    </Box>
  );
};

export default BettingCodes;

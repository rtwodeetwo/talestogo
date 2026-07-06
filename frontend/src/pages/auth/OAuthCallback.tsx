import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Box, CircularProgress, Alert } from '@mui/material';
import { authAPI } from '../../services/api';

const OAuthCallback: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState('');

  useEffect(() => {
    const token = searchParams.get('token');
    const errorParam = searchParams.get('error');

    if (errorParam) {
      if (errorParam === 'account_inactive') {
        setError('Account is not active. Please contact your administrator for approval.');
      } else if (errorParam === 'email_not_verified') {
        setError('Email not verified with the identity provider.');
      } else {
        setError('Authentication failed. Please try again.');
      }
      return;
    }

    if (!token) {
      setError('No authentication token received.');
      return;
    }

    localStorage.setItem('tales_access_token', token);

    // Clear the token from the URL to prevent leakage via history/bookmarks
    window.history.replaceState({}, '', '/login/callback');

    authAPI.getCurrentUser()
      .then(() => {
        navigate('/', { replace: true });
      })
      .catch(() => {
        localStorage.removeItem('tales_access_token');
        setError('Failed to complete login. Please try again.');
      });
  }, [searchParams, navigate]);

  if (error) {
    return (
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: '100vh',
          backgroundColor: '#000000',
          padding: 3,
        }}
      >
        <Alert severity="error" sx={{ maxWidth: 400 }}>
          {error}
        </Alert>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        backgroundColor: '#000000',
      }}
    >
      <CircularProgress sx={{ color: '#75c9c8' }} />
    </Box>
  );
};

export default OAuthCallback;

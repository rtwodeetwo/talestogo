import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  TextField,
  Button,
  Alert,
  CircularProgress,
} from '@mui/material';
import { api } from '../../services/api';
import type { BrandingConfig } from '../../types';

interface InvitationInfo {
  email: string;
  full_name: string;
  expires_at: string;
}

export default function InviteAccept() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token');

  const [loading, setLoading] = useState(true);
  const [validating, setValidating] = useState(false);
  const [invitationInfo, setInvitationInfo] = useState<InvitationInfo | null>(null);
  const [branding, setBranding] = useState<BrandingConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // Same brand fallbacks as the Login page
  const siteName = branding?.site_name || 'Tales';
  const primaryColor = branding?.primary_color || '#003e60';
  const secondaryColor = branding?.secondary_color || '#75c9c8';

  // Shared style fragments, mirroring Login.tsx
  const pageSx = {
    backgroundColor: '#000000',
    minHeight: '100vh',
    width: '100vw',
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    alignItems: 'center',
    fontFamily: '"Roboto Condensed", "Roboto", "Arial", sans-serif',
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    padding: 3,
  } as const;

  const cardSx = {
    p: 5,
    width: 500,
    maxWidth: '90vw',
    textAlign: 'center',
    borderRadius: 2,
    backgroundColor: '#ffffff',
    border: '1px solid rgba(0, 0, 0, 0.12)',
  } as const;

  const headingSx = {
    color: '#000000',
    fontWeight: 700,
    lineHeight: 1.3,
    fontFamily: '"Montserrat", "Arial", sans-serif',
    mb: 2,
  } as const;

  const bodyFontSx = { fontFamily: '"Roboto Condensed", sans-serif' } as const;

  const submitButtonSx = {
    mt: 3,
    backgroundColor: primaryColor,
    '&:hover': { backgroundColor: primaryColor, opacity: 0.9 },
    textTransform: 'none',
    fontSize: '15px',
    padding: '10px 24px',
    fontWeight: 600,
    fontFamily: '"Roboto Condensed", sans-serif',
    borderRadius: 1,
  } as const;

  // Validate token and load branding on mount
  useEffect(() => {
    api
      .get<BrandingConfig>('/site/branding')
      .then((response) => setBranding(response.data))
      .catch(() => {
        // Branding is cosmetic; the Tales defaults above cover a failure.
      });

    if (!token) {
      setError('Invalid invitation link. No token provided.');
      setLoading(false);
      return;
    }

    validateToken();
  }, [token]);

  const validateToken = async () => {
    try {
      const response = await api.get<InvitationInfo>(`/invite/validate?token=${token}`);
      setInvitationInfo(response.data);
      setError(null);
    } catch (err: any) {
      console.error('Validation error:', err);
      setError(
        err.response?.data?.detail ||
        'This invitation link is invalid or has expired. Please contact your administrator.'
      );
    } finally {
      setLoading(false);
    }
  };

  const handleAcceptInvitation = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError(null);

    // Validate password
    if (password.length < 8) {
      setPasswordError('Password must be at least 8 characters long');
      return;
    }

    if (password !== confirmPassword) {
      setPasswordError('Passwords do not match');
      return;
    }

    setValidating(true);
    try {
      // Accept invitation - this sets password and activates account
      const response = await api.post<{ access_token: string; token_type: string }>(
        '/invite/accept',
        { token, password }
      );

      // Store token
      localStorage.setItem('tales_access_token', response.data.access_token);

      // Fetch and store user data
      const userResponse = await api.get('/auth/me');
      localStorage.setItem('tales_user', JSON.stringify(userResponse.data));

      // Redirect to Brand Info page to set up their brand
      navigate('/manage/brand-info');
    } catch (err: any) {
      console.error('Accept invitation error:', err);
      setError(
        err.response?.data?.detail ||
        'Failed to accept invitation. Please try again.'
      );
    } finally {
      setValidating(false);
    }
  };

  const footer = (
    <Box sx={{ mt: 4, textAlign: 'center' }}>
      <Typography
        variant="caption"
        sx={{
          color: 'rgba(255, 255, 255, 0.7)',
          fontSize: '0.75rem',
          ...bodyFontSx,
        }}
      >
        {siteName} - AI Reputation Intelligence
      </Typography>
    </Box>
  );

  const logoAndHeading = (title: string) => (
    <Box sx={{ mb: 4 }}>
      {branding?.site_logo_url && (
        <Box sx={{ mb: 3 }}>
          <img
            src={branding.site_logo_url}
            alt={siteName}
            style={{ maxWidth: '220px', maxHeight: '80px' }}
          />
        </Box>
      )}
      <Typography variant="h4" component="h1" gutterBottom sx={headingSx}>
        {title}
      </Typography>
    </Box>
  );

  if (loading) {
    return (
      <Box sx={pageSx}>
        <CircularProgress sx={{ color: secondaryColor }} />
      </Box>
    );
  }

  if (error && !invitationInfo) {
    return (
      <Box sx={pageSx}>
        <Paper elevation={0} sx={cardSx}>
          {logoAndHeading('Invalid Invitation')}
          <Alert severity="error" sx={{ mt: 2, textAlign: 'left' }}>
            {error}
          </Alert>
          <Button
            variant="contained"
            fullWidth
            sx={submitButtonSx}
            onClick={() => navigate('/login')}
          >
            Go to Login
          </Button>
        </Paper>
        {footer}
      </Box>
    );
  }

  return (
    <Box sx={pageSx}>
      <Paper elevation={0} sx={cardSx}>
        {logoAndHeading(`Welcome to ${siteName}!`)}

        {invitationInfo && (
          <>
            <Typography variant="body1" sx={{ color: 'rgba(0, 0, 0, 0.7)', mb: 3, lineHeight: 1.6, ...bodyFontSx }}>
              Hi <strong>{invitationInfo.full_name}</strong>! You've been invited to join {siteName}.
            </Typography>

            <Alert severity="info" sx={{ mb: 3, textAlign: 'left' }}>
              Email: <strong>{invitationInfo.email}</strong>
            </Alert>

            <Typography variant="body2" sx={{ color: 'rgba(0, 0, 0, 0.6)', mb: 1, ...bodyFontSx }}>
              Set your password to create your account and get started.
            </Typography>

            <form onSubmit={handleAcceptInvitation}>
              <TextField
                label="Password"
                type="password"
                fullWidth
                required
                size="small"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                margin="normal"
                helperText="At least 8 characters"
                error={!!passwordError && passwordError.includes('8 characters')}
                sx={bodyFontSx}
              />

              <TextField
                label="Confirm Password"
                type="password"
                fullWidth
                required
                size="small"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                margin="normal"
                error={!!passwordError && passwordError.includes('do not match')}
                sx={bodyFontSx}
              />

              {passwordError && (
                <Alert severity="error" sx={{ mt: 2, textAlign: 'left' }}>
                  {passwordError}
                </Alert>
              )}

              {error && (
                <Alert severity="error" sx={{ mt: 2, textAlign: 'left' }}>
                  {error}
                </Alert>
              )}

              <Button
                type="submit"
                variant="contained"
                fullWidth
                size="large"
                disabled={validating}
                sx={submitButtonSx}
              >
                {validating ? <CircularProgress size={24} sx={{ color: '#fff' }} /> : 'Create Account & Get Started'}
              </Button>
            </form>
          </>
        )}
      </Paper>
      {footer}
    </Box>
  );
}

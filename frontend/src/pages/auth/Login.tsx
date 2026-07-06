import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Box,
  Paper,
  Typography,
  Alert,
  CircularProgress,
  Button,
  TextField,
  Divider,
} from '@mui/material';
import { GoogleLogin, GoogleOAuthProvider } from '@react-oauth/google';
import type { CredentialResponse } from '@react-oauth/google';
import { PublicClientApplication } from '@azure/msal-browser';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../services/api';
import type { BrandingConfig } from '../../types';

// Auth configuration from backend
interface AuthConfig {
  local_auth_enabled: boolean;
  microsoft_auth_enabled: boolean;
  google_auth_enabled: boolean;
  microsoft_client_id: string | null;
  microsoft_authority: string | null;
  google_client_id: string | null;
  auth_flow_type: 'popup' | 'redirect';
}

const Login: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login, googleLogin, microsoftLogin } = useAuth();

  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [configLoading, setConfigLoading] = useState(true);
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [branding, setBranding] = useState<BrandingConfig | null>(null);
  const [msalInitialized, setMsalInitialized] = useState(false);
  const msalInstanceRef = useRef<PublicClientApplication | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  // Handle error query params from redirect flow
  useEffect(() => {
    const errorParam = searchParams.get('error');
    if (errorParam === 'account_inactive') {
      setError('Account is not active. Please contact your administrator for approval.');
    } else if (errorParam === 'email_not_verified') {
      setError('Email not verified with the identity provider.');
    } else if (errorParam) {
      setError('Authentication failed. Please try again.');
    }
  }, [searchParams]);

  // Fetch auth and branding config from backend
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const [authResponse, brandingResponse] = await Promise.all([
          api.get('/auth/config'),
          api.get('/site/branding'),
        ]);
        setAuthConfig(authResponse.data);
        setBranding(brandingResponse.data);
      } catch (err) {
        console.error('Failed to fetch config:', err);
        // Set defaults if config fetch fails
        setAuthConfig({
          local_auth_enabled: true,
          microsoft_auth_enabled: false,
          google_auth_enabled: false,
          microsoft_client_id: null,
          microsoft_authority: null,
          google_client_id: null,
          auth_flow_type: 'popup',
        });
        setBranding({
          site_name: 'Tales',
          site_logo_url: null,
          primary_color: '#003e60',
          secondary_color: '#75c9c8',
          admin_email: null,
        });
      } finally {
        setConfigLoading(false);
      }
    };

    fetchConfig();
  }, []);

  // Initialize MSAL when Microsoft auth is enabled and we have a client ID (popup mode only)
  useEffect(() => {
    if (authConfig?.auth_flow_type === 'redirect') return;
    if (authConfig?.microsoft_auth_enabled && authConfig.microsoft_client_id) {
      const msalConfig = {
        auth: {
          clientId: authConfig.microsoft_client_id,
          authority: authConfig.microsoft_authority || 'https://login.microsoftonline.com/common',
          redirectUri: window.location.origin,
        },
        cache: {
          cacheLocation: 'localStorage' as const,
          storeAuthStateInCookie: false,
        },
      };

      const instance = new PublicClientApplication(msalConfig);
      msalInstanceRef.current = instance;

      instance.initialize().then(() => {
        setMsalInitialized(true);
      });
    }
  }, [authConfig]);

  const handleGoogleSuccess = async (credentialResponse: CredentialResponse) => {
    setError('');
    setLoading(true);

    try {
      if (!credentialResponse.credential) {
        throw new Error('No credential received from Google');
      }

      await googleLogin(credentialResponse.credential);
      navigate('/');
    } catch (err: any) {
      console.error('Google login error:', err);
      setError(err.response?.data?.detail || 'Google login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleError = () => {
    setError('Google login failed. Please try again.');
  };

  const handleMicrosoftLogin = async () => {
    if (!msalInitialized || !msalInstanceRef.current) {
      setError('Microsoft login is initializing. Please wait...');
      return;
    }

    setError('');
    setLoading(true);

    try {
      const loginRequest = {
        scopes: ['openid', 'profile', 'email'],
      };

      const loginResponse = await msalInstanceRef.current.loginPopup(loginRequest);

      if (loginResponse.idToken) {
        await microsoftLogin(loginResponse.idToken);
        navigate('/');
      } else {
        throw new Error('No ID token received from Microsoft');
      }
    } catch (err: any) {
      console.error('Microsoft login error:', err);
      setError(err.response?.data?.detail || 'Microsoft login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleLocalLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(email, password);
      navigate('/');
    } catch (err: any) {
      console.error('Login error:', err);
      const detail = err.response?.data?.detail;
      if (typeof detail === 'string') {
        setError(detail);
      } else if (Array.isArray(detail)) {
        setError(detail.map((d: any) => d.msg || d).join(', '));
      } else {
        setError('Login failed. Please check your credentials.');
      }
    } finally {
      setLoading(false);
    }
  };

  // Show loading while fetching config
  if (configLoading) {
    return (
      <Box
        sx={{
          backgroundColor: '#000000',
          minHeight: '100vh',
          width: '100vw',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
        }}
      >
        <CircularProgress sx={{ color: '#75c9c8' }} />
      </Box>
    );
  }

  const siteName = branding?.site_name || 'Tales';
  const primaryColor = branding?.primary_color || '#003e60';
  const secondaryColor = branding?.secondary_color || '#75c9c8';

  // Determine which auth methods to show
  const showLocal = authConfig?.local_auth_enabled;
  const showMicrosoft = authConfig?.microsoft_auth_enabled && authConfig.microsoft_client_id;
  const showGoogle = authConfig?.google_auth_enabled && authConfig.google_client_id;
  const hasOAuth = showGoogle || showMicrosoft;
  const hasAnyAuth = showLocal || hasOAuth;

  // Build the login method description
  let loginMethodText = '';
  if (!hasAnyAuth) {
    loginMethodText = 'No authentication methods configured. Please contact your administrator.';
  }

  return (
    <Box
      sx={{
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
      }}
    >
      {/* Login Card */}
      <Paper
        elevation={0}
        sx={{
          p: 5,
          width: 500,
          maxWidth: '90vw',
          textAlign: 'center',
          borderRadius: 2,
          backgroundColor: '#ffffff',
          border: '1px solid rgba(0, 0, 0, 0.12)',
        }}
      >
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
          <Typography
            variant="h4"
            component="h1"
            gutterBottom
            sx={{
              color: '#000000',
              fontWeight: 700,
              lineHeight: 1.3,
              fontFamily: '"Montserrat", "Arial", sans-serif',
              mb: 2,
            }}
          >
            Welcome to {siteName}!
          </Typography>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 3, textAlign: 'left' }}>
            {error}
          </Alert>
        )}

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', mb: 3 }}>
            <CircularProgress sx={{ color: secondaryColor }} />
          </Box>
        )}

        {/* OAuth Buttons */}
        {hasOAuth && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5, alignItems: 'center', mb: 2 }}>
            {/* Google Login — Popup Mode */}
            {authConfig?.auth_flow_type !== 'redirect' && showGoogle && authConfig!.google_client_id && (
              <GoogleOAuthProvider clientId={authConfig!.google_client_id}>
                <Box sx={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
                  <GoogleLogin
                    onSuccess={handleGoogleSuccess}
                    onError={handleGoogleError}
                    theme="outline"
                    size="large"
                    text="signin_with"
                    shape="rectangular"
                  />
                </Box>
              </GoogleOAuthProvider>
            )}

            {/* Google Login — Redirect Mode */}
            {authConfig?.auth_flow_type === 'redirect' && showGoogle && (
              <Button
                variant="outlined"
                component="a"
                href={`${api.defaults.baseURL}/auth/google/authorize`}
                disabled={loading}
                fullWidth
                sx={{
                  borderColor: primaryColor,
                  color: primaryColor,
                  borderWidth: '1.5px',
                  '&:hover': {
                    borderColor: primaryColor,
                    borderWidth: '1.5px',
                    backgroundColor: `${primaryColor}0a`,
                  },
                  textTransform: 'none',
                  fontSize: '15px',
                  padding: '11px 24px',
                  fontWeight: 600,
                  fontFamily: '"Roboto Condensed", sans-serif',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 1.5,
                  borderRadius: 1,
                }}
              >
                <svg width="21" height="21" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
                  <path d="M20.64 10.2c0-.63-.06-1.25-.16-1.84H10.5v3.49h5.68a4.85 4.85 0 0 1-2.11 3.18v2.64h3.42c2 -1.84 3.15-4.56 3.15-7.47z" fill="#4285F4"/>
                  <path d="M10.5 21c2.85 0 5.24-.94 6.99-2.56l-3.42-2.64c-.94.63-2.15 1-3.57 1-2.74 0-5.06-1.85-5.89-4.35H1.07v2.73A10.5 10.5 0 0 0 10.5 21z" fill="#34A853"/>
                  <path d="M4.61 12.45a6.3 6.3 0 0 1 0-3.9V5.82H1.07a10.5 10.5 0 0 0 0 9.36l3.54-2.73z" fill="#FBBC05"/>
                  <path d="M10.5 4.15a5.7 5.7 0 0 1 4.02 1.57l3.01-3.01A10.12 10.12 0 0 0 10.5 0 10.5 10.5 0 0 0 1.07 5.82l3.54 2.73c.83-2.5 3.15-4.4 5.89-4.4z" fill="#EA4335"/>
                </svg>
                Sign in with Google
              </Button>
            )}

            {/* Microsoft Login — Popup Mode */}
            {authConfig?.auth_flow_type !== 'redirect' && showMicrosoft && (
              <Button
                variant="outlined"
                onClick={handleMicrosoftLogin}
                disabled={loading || !msalInitialized}
                fullWidth
                sx={{
                  borderColor: primaryColor,
                  color: primaryColor,
                  borderWidth: '1.5px',
                  '&:hover': {
                    borderColor: primaryColor,
                    borderWidth: '1.5px',
                    backgroundColor: `${primaryColor}0a`,
                  },
                  textTransform: 'none',
                  fontSize: '15px',
                  padding: '11px 24px',
                  fontWeight: 600,
                  fontFamily: '"Roboto Condensed", sans-serif',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 1.5,
                  borderRadius: 1,
                }}
              >
                <svg width="21" height="21" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
                  <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
                  <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
                  <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
                  <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
                </svg>
                Sign in with Microsoft
              </Button>
            )}

            {/* Microsoft Login — Redirect Mode */}
            {authConfig?.auth_flow_type === 'redirect' && showMicrosoft && (
              <Button
                variant="outlined"
                component="a"
                href={`${api.defaults.baseURL}/auth/microsoft/authorize`}
                disabled={loading}
                fullWidth
                sx={{
                  borderColor: primaryColor,
                  color: primaryColor,
                  borderWidth: '1.5px',
                  '&:hover': {
                    borderColor: primaryColor,
                    borderWidth: '1.5px',
                    backgroundColor: `${primaryColor}0a`,
                  },
                  textTransform: 'none',
                  fontSize: '15px',
                  padding: '11px 24px',
                  fontWeight: 600,
                  fontFamily: '"Roboto Condensed", sans-serif',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 1.5,
                  borderRadius: 1,
                }}
              >
                <svg width="21" height="21" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
                  <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
                  <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
                  <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
                  <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
                </svg>
                Sign in with Microsoft
              </Button>
            )}
          </Box>
        )}

        {/* Divider between OAuth and email/password */}
        {hasOAuth && showLocal && (
          <Divider sx={{ my: 2, fontFamily: '"Roboto Condensed", sans-serif', fontSize: '0.8rem', color: 'rgba(0,0,0,0.4)' }}>
            or
          </Divider>
        )}

        {/* Email/Password Login Form */}
        {showLocal && (
          <Box component="form" onSubmit={handleLocalLogin} sx={{ width: '100%', mb: 2 }}>
            <TextField
              fullWidth
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              size="small"
              sx={{ mb: 2, fontFamily: '"Roboto Condensed", sans-serif' }}
              disabled={loading}
            />
            <TextField
              fullWidth
              label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              size="small"
              sx={{ mb: 2, fontFamily: '"Roboto Condensed", sans-serif' }}
              disabled={loading}
            />
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading || !email || !password}
              sx={{
                backgroundColor: primaryColor,
                '&:hover': { backgroundColor: primaryColor, opacity: 0.9 },
                textTransform: 'none',
                fontSize: '15px',
                padding: '10px 24px',
                fontWeight: 600,
                fontFamily: '"Roboto Condensed", sans-serif',
                borderRadius: 1,
              }}
            >
              Sign in
            </Button>
          </Box>
        )}

        {/* No auth configured message */}
        {loginMethodText && (
          <Typography
            variant="body2"
            sx={{
              color: 'rgba(0, 0, 0, 0.6)',
              fontSize: '0.875rem',
              fontFamily: '"Roboto Condensed", sans-serif',
            }}
          >
            {loginMethodText}
          </Typography>
        )}

        <Typography
          variant="caption"
          sx={{
            mt: 2,
            display: 'block',
            color: 'rgba(0, 0, 0, 0.5)',
            fontSize: '0.75rem',
            fontStyle: 'italic',
            fontFamily: '"Roboto Condensed", sans-serif',
          }}
        >
          New users will be reviewed by an administrator for approval
        </Typography>
      </Paper>

      {/* Footer */}
      <Box sx={{ mt: 4, textAlign: 'center' }}>
        <Typography
          variant="caption"
          sx={{
            color: 'rgba(255, 255, 255, 0.7)',
            fontSize: '0.75rem',
            fontFamily: '"Roboto Condensed", sans-serif',
          }}
        >
          {siteName} - AI Reputation Intelligence
        </Typography>
      </Box>
    </Box>
  );
};

export default Login;

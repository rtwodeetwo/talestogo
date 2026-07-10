import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
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
import { PublicClientApplication, BrowserAuthError } from '@azure/msal-browser';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../services/api';
import type { BrandingConfig } from '../../types';

const MicrosoftIcon = () => (
  <svg width="21" height="21" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
    <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
    <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
  </svg>
);

// Auth configuration from backend
interface AuthConfig {
  local_auth_enabled: boolean;
  microsoft_auth_enabled: boolean;
  google_auth_enabled: boolean;
  microsoft_client_id: string | null;
  microsoft_authority: string | null;
  google_client_id: string | null;
  auth_flow_type: 'popup' | 'redirect';
  auto_login: boolean;
}

const Login: React.FC = () => {
  const navigate = useNavigate();
  const { login, googleLogin, microsoftLogin, isAuthenticated } = useAuth();

  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [configLoading, setConfigLoading] = useState(true);
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [branding, setBranding] = useState<BrandingConfig | null>(null);
  const [msalInitialized, setMsalInitialized] = useState(false);
  const msalInstanceRef = useRef<PublicClientApplication | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

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
          auto_login: false,
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

  // Initialize MSAL once when Microsoft auth is enabled and we have a client ID
  useEffect(() => {
    if (msalInstanceRef.current) return;
    if (!authConfig?.microsoft_auth_enabled || !authConfig.microsoft_client_id) return;

    const msalConfig = {
      auth: {
        clientId: authConfig.microsoft_client_id,
        authority: authConfig.microsoft_authority || 'https://login.microsoftonline.com/common',
        redirectUri: window.location.origin + '/login',
      },
      cache: {
        cacheLocation: 'localStorage' as const,
        storeAuthStateInCookie: false,
      },
    };

    const instance = new PublicClientApplication(msalConfig);
    msalInstanceRef.current = instance;

    instance.initialize()
      .then(() => {
        setMsalInitialized(true);
      })
      .catch((err) => {
        console.error('MSAL initialization failed:', err);
        setError('Microsoft login is unavailable. Please try another method or refresh.');
      });
  }, [authConfig]);

  const redirectHandledRef = useRef(false);

  // Handle MSAL redirect response (for redirect flow mode)
  useEffect(() => {
    if (!msalInitialized || !msalInstanceRef.current) return;
    if (authConfig?.auth_flow_type !== 'redirect') return;
    if (redirectHandledRef.current) return;
    redirectHandledRef.current = true;

    const msalInstance = msalInstanceRef.current;

    msalInstance.handleRedirectPromise()
      .then(async (response) => {
        if (response?.idToken) {
          sessionStorage.removeItem('tales_auto_login_attempted');
          setLoading(true);
          try {
            await microsoftLogin(response.idToken);
            navigate('/');
          } catch (err: any) {
            sessionStorage.setItem('tales_auto_login_attempted', '1');
            setError(err.response?.data?.detail || 'Microsoft login failed.');
          } finally {
            setLoading(false);
          }
        } else if (
          authConfig?.auto_login
          && !sessionStorage.getItem('tales_auto_login_attempted')
          && !isAuthenticated
        ) {
          sessionStorage.setItem('tales_auto_login_attempted', '1');
          msalInstance.loginRedirect({
            scopes: ['openid', 'profile', 'email'],
          });
        }
      })
      .catch((err) => {
        sessionStorage.setItem('tales_auto_login_attempted', '1');
        if (err instanceof BrowserAuthError && err.errorCode === 'user_cancelled') {
          setError('Login was cancelled.');
        } else if (err instanceof BrowserAuthError && err.errorCode === 'interaction_in_progress') {
          // Transient state — don't show error to user
        } else {
          setError('Microsoft login failed. Please try again.');
        }
      });
  }, [msalInitialized, authConfig, microsoftLogin, navigate, isAuthenticated]);

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

  const handleMicrosoftLogin = useCallback(async () => {
    if (!msalInitialized || !msalInstanceRef.current) {
      setError('Microsoft login is initializing. Please wait...');
      return;
    }

    setError('');

    const loginRequest = {
      scopes: ['openid', 'profile', 'email'],
    };

    if (authConfig?.auth_flow_type === 'redirect') {
      try {
        await msalInstanceRef.current.loginRedirect(loginRequest);
      } catch (err: any) {
        if (err instanceof BrowserAuthError && err.errorCode === 'interaction_in_progress') {
          // Already redirecting — ignore duplicate click
        } else {
          setError('Microsoft login failed. Please try again.');
        }
      }
    } else {
      setLoading(true);
      try {
        const loginResponse = await msalInstanceRef.current.loginPopup(loginRequest);
        if (loginResponse.idToken) {
          await microsoftLogin(loginResponse.idToken);
          navigate('/');
        } else {
          throw new Error('No ID token received from Microsoft');
        }
      } catch (err: any) {
        console.error('Microsoft login error:', err);
        if (err instanceof BrowserAuthError && err.errorCode === 'user_cancelled') {
          setError('Login was cancelled.');
        } else {
          setError(err.response?.data?.detail || 'Microsoft login failed. Please try again.');
        }
      } finally {
        setLoading(false);
      }
    }
  }, [msalInitialized, authConfig?.auth_flow_type, microsoftLogin, navigate]);

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

  const oauthButtonSx = {
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
  } as const;

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
            {/* Google Login (always popup — no client-side redirect available) */}
            {showGoogle && authConfig?.google_client_id && (
              <GoogleOAuthProvider clientId={authConfig.google_client_id}>
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

            {/* Microsoft Login (popup or redirect based on auth_flow_type) */}
            {showMicrosoft && (
              <Button
                variant="outlined"
                onClick={handleMicrosoftLogin}
                disabled={loading || !msalInitialized}
                fullWidth
                sx={oauthButtonSx}
              >
                <MicrosoftIcon />
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

import React, { useState } from 'react';
import {
  Box,
  Container,
  Paper,
  TextField,
  Button,
  Typography,
  Alert,
  CircularProgress,
  Grid,
  Divider,
} from '@mui/material';
import { CachedOutlined } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { authAPI, api } from '../services/api';

const Settings: React.FC = () => {
  const { user, refreshUser } = useAuth();

  // Profile state
  const [fullName, setFullName] = useState(user?.full_name || '');
  const [organization, setOrganization] = useState(user?.organization || '');

  // Password state
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [pwLoading, setPwLoading] = useState(false);

  // UI state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const handleSaveProfile = async () => {
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      await authAPI.updateProfile({
        full_name: fullName,
        organization: organization,
      });

      await refreshUser();
      setSuccess('Profile updated successfully!');
    } catch (err: any) {
      console.error('Profile update error:', err);
      setError(err.response?.data?.detail || 'Failed to update profile');
    } finally {
      setLoading(false);
    }
  };

  const handleChangePassword = async () => {
    setError('');
    setSuccess('');

    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters long');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match');
      return;
    }

    setPwLoading(true);
    try {
      await authAPI.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setSuccess('Password changed successfully!');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: any) {
      console.error('Change password error:', err);
      setError(err.response?.data?.detail || 'Failed to change password');
    } finally {
      setPwLoading(false);
    }
  };

  const handleClearCache = async () => {
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      const response = await api.post('/admin/cache/clear');
      setSuccess(`Cache cleared successfully! ${response.data.cleared} entries removed.`);
    } catch (err: any) {
      console.error('Clear cache error:', err);
      setError(err.response?.data?.detail || 'Failed to clear cache');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Typography variant="h4" gutterBottom>
        Settings
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {success && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess('')}>
          {success}
        </Alert>
      )}

      {/* Profile Section */}
      <Paper elevation={2} sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Profile Information
        </Typography>
        <Divider sx={{ mb: 3 }} />

        <Grid container spacing={2}>
          <Grid item xs={12}>
            <TextField
              fullWidth
              label="Email"
              value={user?.email || ''}
              disabled
              helperText="Email cannot be changed"
            />
          </Grid>

          <Grid item xs={12} md={6}>
            <TextField
              fullWidth
              label="Full Name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </Grid>

          <Grid item xs={12} md={6}>
            <TextField
              fullWidth
              label="Organization"
              value={organization}
              onChange={(e) => setOrganization(e.target.value)}
              placeholder="Brand you're tracking"
            />
          </Grid>

          <Grid item xs={12}>
            <Typography variant="caption" color="text.secondary">
              Account Status: {user?.is_active ? 'Active' : 'Pending Approval'}
              {user?.is_admin && ' - Admin'}
            </Typography>
          </Grid>

          <Grid item xs={12}>
            <Button
              variant="contained"
              onClick={handleSaveProfile}
              disabled={loading}
            >
              {loading ? <CircularProgress size={24} /> : 'Save Profile'}
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {/* Password Section - hidden for OAuth-only accounts (no local password) */}
      {!user?.oauth_provider && (
        <Paper elevation={2} sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" gutterBottom>
            Change Password
          </Typography>
          <Divider sx={{ mb: 3 }} />

          <Grid container spacing={2}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                type="password"
                label="Current Password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
              />
            </Grid>

            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                type="password"
                label="New Password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                helperText="At least 8 characters"
              />
            </Grid>

            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                type="password"
                label="Confirm New Password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
            </Grid>

            <Grid item xs={12}>
              <Button
                variant="contained"
                onClick={handleChangePassword}
                disabled={pwLoading || !currentPassword || !newPassword || !confirmPassword}
              >
                {pwLoading ? <CircularProgress size={24} /> : 'Change Password'}
              </Button>
            </Grid>
          </Grid>
        </Paper>
      )}

      {/* Admin Tools Section - Only visible to admins */}
      {user?.is_admin && (
        <Paper elevation={2} sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Admin Tools
          </Typography>
          <Divider sx={{ mb: 3 }} />

          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Clear the Redis cache to force dashboard data to be recalculated from the database.
            Use this if dashboard metrics are showing stale or incorrect values.
          </Typography>

          <Button
            variant="outlined"
            color="warning"
            onClick={handleClearCache}
            disabled={loading}
            startIcon={loading ? <CircularProgress size={20} /> : <CachedOutlined />}
          >
            Clear Analytics Cache
          </Button>
        </Paper>
      )}
    </Container>
  );
};

export default Settings;

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Container,
  Paper,
  Typography,
  Button,
  TextField,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  Chip,
  IconButton,
  Switch,
  FormControlLabel,
  Select,
  FormControl,
  InputLabel,
  Divider,
  Tooltip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  MenuItem,
  Grid,
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  MoreVert as MoreVertIcon,
  Folder as FolderIcon,
  Delete as DeleteIcon,
  Login as LoginIcon,
  FiberManualRecord as ActiveIcon,
  Visibility as VisibilityIcon,
  Email as EmailIcon,
  Person as PersonIcon,
  Business as BusinessIcon,
  Schedule as ScheduleIcon,
  AdminPanelSettings as AdminIcon,
} from '@mui/icons-material';
import { adminAPI, api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { useImpersonation } from '../../contexts/ImpersonationContext';
import { formatDateEST } from '../../utils/dateUtils';

interface User {
  id: number;
  email: string;
  full_name?: string;
  organization?: string;
  tenant_id?: number;
  is_admin: boolean;
  is_active: boolean;
  is_invited: boolean;
  invitation_expires_at?: string;
  last_login?: string;
  created_at: string;
}

interface Tenant {
  id: number;
  tenant_name: string;
  primary_color: string;
  secondary_color: string;
}

interface ActiveUser {
  id: number;
  email: string;
  full_name: string | null;
  last_activity: string | null;
  activity_type: string | null;
}

interface ActiveUsersData {
  count: number;
  active_users: ActiveUser[];
  minutes_threshold: number;
  current_admin_id: number;
}

const UserManagement: React.FC = () => {
  const { isAdmin } = useAuth();
  const { setImpersonatedUser } = useImpersonation();
  const navigate = useNavigate();

  const [users, setUsers] = useState<User[]>([]);
  const [activeUsers, setActiveUsers] = useState<ActiveUsersData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Pagination
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);

  // Tenants
  const [tenants, setTenants] = useState<Tenant[]>([]);

  // Invite dialog
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteFullName, setInviteFullName] = useState('');
  const [inviteOrganization, setInviteOrganization] = useState('');
  const [inviteTenantId, setInviteTenantId] = useState<number | ''>('');

  // User details dialog (combined view/edit)
  const [detailsDialogOpen, setDetailsDialogOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [isEditMode, setIsEditMode] = useState(false);
  const [editIsActive, setEditIsActive] = useState(false);
  const [editIsAdmin, setEditIsAdmin] = useState(false);

  // Delete confirmation dialog
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [userToDelete, setUserToDelete] = useState<User | null>(null);

  useEffect(() => {
    if (isAdmin) {
      loadUsers();
      loadTenants();
      loadActiveUsers();
    }

    const interval = setInterval(() => {
      if (isAdmin) {
        loadActiveUsers();
      }
    }, 60000);

    return () => clearInterval(interval);
  }, [isAdmin]);

  const loadTenants = async () => {
    try {
      const data = await adminAPI.listTenants();
      setTenants(data);
    } catch (err) {
      console.error('Failed to load tenants:', err);
    }
  };

  const loadUsers = async () => {
    setLoading(true);
    setError('');

    try {
      const data = await adminAPI.listUsers();
      setUsers(data);
    } catch (err) {
      console.error('Failed to load users:', err);
      setError('Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  const loadActiveUsers = async () => {
    try {
      const response = await api.get('/admin/active-users?minutes=15');
      setActiveUsers(response.data);
    } catch (err) {
      console.error('Failed to load active users:', err);
    }
  };

  const isUserActive = (userId: number) => {
    return activeUsers?.active_users.some(u => u.id === userId) || false;
  };

  const formatDateTime = (dateString: string | null) => {
    if (!dateString) return 'Never';
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return formatDateEST(dateString, 'short');
  };

  const getTenantName = (tenantId?: number) => {
    if (!tenantId) return '-';
    const tenant = tenants.find(t => t.id === tenantId);
    return tenant ? tenant.tenant_name : '-';
  };

  // Open user details dialog
  const handleOpenUserDetails = (user: User) => {
    setSelectedUser(user);
    setEditIsActive(user.is_active);
    setEditIsAdmin(user.is_admin);
    setIsEditMode(false);
    setDetailsDialogOpen(true);
  };

  const handleCloseUserDetails = () => {
    setDetailsDialogOpen(false);
    setSelectedUser(null);
    setIsEditMode(false);
  };

  const handleSaveUserChanges = async () => {
    if (!selectedUser) return;

    setError('');
    setSuccess('');

    try {
      await adminAPI.updateUserStatus(selectedUser.id, {
        is_active: editIsActive,
        is_admin: editIsAdmin,
      });

      setSuccess(`User ${selectedUser.email} updated successfully`);
      setIsEditMode(false);
      handleCloseUserDetails();
      loadUsers();
    } catch (err: any) {
      console.error('Failed to update user:', err);
      setError(err.response?.data?.detail || 'Failed to update user');
    }
  };

  const handleInviteUser = async () => {
    setError('');
    setSuccess('');

    if (!inviteEmail || !inviteFullName) {
      setError('Email and full name are required');
      return;
    }

    try {
      const tenantIdToUse = inviteTenantId === '' ? undefined : inviteTenantId;
      const invitation = await adminAPI.createInvitation(inviteEmail, inviteFullName, inviteOrganization, tenantIdToUse);
      // With local auth enabled the backend mints a set-password link; keep it
      // so the admin can share it manually if the invitation email fails.
      const setPasswordLink = invitation?.invitation_url?.includes('/invite/accept')
        ? invitation.invitation_url
        : null;

      setInviteDialogOpen(false);
      setInviteEmail('');
      setInviteFullName('');
      setInviteOrganization('');
      setInviteTenantId('');

      await loadUsers();

      const updatedUsers = await adminAPI.listUsers();
      const newUser = updatedUsers.find((u: User) => u.email === inviteEmail);

      if (newUser) {
        try {
          await adminAPI.sendInvitationEmail(newUser.id);
          setSuccess(`User ${inviteEmail} added and invitation email sent!`);
        } catch (emailErr) {
          console.error('Failed to send invitation email:', emailErr);
          setSuccess(`User ${inviteEmail} added successfully`);
          setError(
            setPasswordLink
              ? `Invitation email failed to send. Share this set-password link with them directly: ${setPasswordLink}`
              : 'Note: Invitation email failed to send.'
          );
        }
      } else {
        setSuccess(`User ${inviteEmail} added successfully`);
      }
    } catch (err: any) {
      console.error('Failed to create invitation:', err);
      setError(err.response?.data?.detail || 'Failed to create invitation');
    }
  };

  const handleViewAsUser = (user: User) => {
    setImpersonatedUser({
      id: user.id,
      email: user.email,
      full_name: user.full_name,
    });
    handleCloseUserDetails();
    navigate('/');
  };

  const handleLoginAsUser = async (user: User) => {
    if (!window.confirm(`Log in as ${user.email}? This will open a new tab.`)) {
      return;
    }

    try {
      const response = await api.post(`/admin/login-as-user/${user.id}`);
      const { access_token } = response.data;

      const userResponse = await api.get('/auth/me', {
        headers: { Authorization: `Bearer ${access_token}` }
      });
      const userData = userResponse.data;

      const impersonationData = {
        token: access_token,
        user: userData,
        timestamp: Date.now()
      };

      sessionStorage.setItem('tales_impersonation', JSON.stringify(impersonationData));
      const newTab = window.open(`${window.location.origin}/?impersonate=${Date.now()}`, '_blank');

      if (!newTab) {
        setError('Please allow popups to use the "Login As" feature');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate login token');
    }
  };

  const handleViewBrands = async (user: User) => {
    try {
      const brands = await adminAPI.getUserBrands(user.id);

      if (brands.length === 0) {
        setError(`User ${user.email} has no brands yet`);
        return;
      }

      navigate(`/settings/users/${user.id}/brands/${brands[0].id}`);
      handleCloseUserDetails();
    } catch (err) {
      console.error('Failed to load user brands:', err);
      setError('Failed to load user brands');
    }
  };

  const handleDeleteUser = (user: User) => {
    setUserToDelete(user);
    setDeleteDialogOpen(true);
    handleCloseUserDetails();
  };

  const handleConfirmDelete = async () => {
    if (!userToDelete) return;

    setError('');
    setSuccess('');

    try {
      await adminAPI.deleteUser(userToDelete.id);
      setSuccess(`User ${userToDelete.email} deleted successfully`);
      setDeleteDialogOpen(false);
      setUserToDelete(null);
      loadUsers();
    } catch (err: any) {
      console.error('Failed to delete user:', err);
      setError(err.response?.data?.detail || 'Failed to delete user');
      setDeleteDialogOpen(false);
    }
  };

  const handleChangePage = (_event: unknown, newPage: number) => {
    setPage(newPage);
  };

  const handleChangeRowsPerPage = (event: React.ChangeEvent<HTMLInputElement>) => {
    setRowsPerPage(parseInt(event.target.value, 10));
    setPage(0);
  };

  if (!isAdmin) {
    return (
      <Container maxWidth={false} sx={{ py: 4, px: 3 }}>
        <Alert severity="error">You do not have permission to access this page.</Alert>
      </Container>
    );
  }

  const paginatedUsers = users.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);

  return (
    <Box sx={{ width: '100%', overflow: 'hidden' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, px: 1 }}>
        <Typography variant="h5">User Management</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setInviteDialogOpen(true)}
          size="small"
        >
          Invite User
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2, mx: 1 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {success && (
        <Alert severity="success" sx={{ mb: 2, mx: 1 }} onClose={() => setSuccess('')}>
          {success}
        </Alert>
      )}

      {/* Active Users Alert */}
      {activeUsers && activeUsers.count > 0 && (
        <Alert severity="warning" sx={{ mb: 2, mx: 1 }} icon={<ActiveIcon />}>
          <Typography variant="body2" fontWeight="bold">
            {activeUsers.count} user{activeUsers.count !== 1 ? 's' : ''} currently active
          </Typography>
          <Box component="span" sx={{ fontSize: '0.75rem' }}>
            {activeUsers.active_users.map(u => u.email).join(', ')}
          </Box>
        </Alert>
      )}

      <Paper elevation={1} sx={{ width: '100%', overflow: 'hidden' }}>
        <TableContainer sx={{ maxWidth: '100%' }}>
          <Table size="small" sx={{ tableLayout: 'fixed', width: '100%' }}>
            <TableHead>
              <TableRow sx={{ bgcolor: 'grey.100' }}>
                <TableCell sx={{ width: '30%', fontWeight: 600 }}>Email</TableCell>
                <TableCell sx={{ width: '20%', fontWeight: 600 }}>Full Name</TableCell>
                <TableCell sx={{ width: '20%', fontWeight: 600 }}>Tenant</TableCell>
                <TableCell sx={{ width: '15%', fontWeight: 600 }}>Last Login</TableCell>
                <TableCell sx={{ width: '15%', fontWeight: 600, textAlign: 'center' }}>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={5} align="center" sx={{ py: 4 }}>
                    Loading...
                  </TableCell>
                </TableRow>
              ) : paginatedUsers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} align="center" sx={{ py: 4 }}>
                    No users found
                  </TableCell>
                </TableRow>
              ) : (
                paginatedUsers.map((user) => (
                  <TableRow
                    key={user.id}
                    hover
                    sx={{ cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' } }}
                    onClick={() => handleOpenUserDetails(user)}
                  >
                    <TableCell sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {isUserActive(user.id) && (
                          <Tooltip title="Currently active">
                            <ActiveIcon sx={{ fontSize: 10, color: 'success.main', flexShrink: 0 }} />
                          </Tooltip>
                        )}
                        {user.is_admin && (
                          <Tooltip title="Admin">
                            <AdminIcon sx={{ fontSize: 14, color: 'primary.main', flexShrink: 0 }} />
                          </Tooltip>
                        )}
                        <Typography variant="body2" noWrap>
                          {user.email}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <Typography variant="body2" noWrap>
                        {user.full_name || '-'}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {getTenantName(user.tenant_id)}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {formatDateTime(user.last_login ?? null)}
                      </Typography>
                    </TableCell>
                    <TableCell align="center" onClick={(e) => e.stopPropagation()}>
                      <Tooltip title="View Details">
                        <IconButton
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenUserDetails(user);
                          }}
                        >
                          <MoreVertIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50]}
          component="div"
          count={users.length}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={handleChangePage}
          onRowsPerPageChange={handleChangeRowsPerPage}
          sx={{ borderTop: '1px solid', borderColor: 'divider' }}
        />
      </Paper>

      {/* User Details Dialog */}
      <Dialog
        open={detailsDialogOpen}
        onClose={handleCloseUserDetails}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{ pb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography variant="h6">User Details</Typography>
            {!isEditMode && (
              <Button
                size="small"
                startIcon={<EditIcon />}
                onClick={() => setIsEditMode(true)}
              >
                Edit
              </Button>
            )}
          </Box>
        </DialogTitle>
        <DialogContent>
          {selectedUser && (
            <Box sx={{ pt: 1 }}>
              {/* User Info Section */}
              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <EmailIcon fontSize="small" color="action" />
                    <Typography variant="body2" color="text.secondary">Email</Typography>
                  </Box>
                  <Typography variant="body1" sx={{ ml: 4 }}>{selectedUser.email}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <PersonIcon fontSize="small" color="action" />
                    <Typography variant="body2" color="text.secondary">Full Name</Typography>
                  </Box>
                  <Typography variant="body1" sx={{ ml: 4 }}>{selectedUser.full_name || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <BusinessIcon fontSize="small" color="action" />
                    <Typography variant="body2" color="text.secondary">Organization</Typography>
                  </Box>
                  <Typography variant="body1" sx={{ ml: 4 }}>{selectedUser.organization || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <FolderIcon fontSize="small" color="action" />
                    <Typography variant="body2" color="text.secondary">Tenant</Typography>
                  </Box>
                  <Typography variant="body1" sx={{ ml: 4 }}>{getTenantName(selectedUser.tenant_id)}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <ScheduleIcon fontSize="small" color="action" />
                    <Typography variant="body2" color="text.secondary">Last Login</Typography>
                  </Box>
                  <Typography variant="body1" sx={{ ml: 4 }}>
                    {selectedUser.last_login ? formatDateEST(selectedUser.last_login, 'full') : 'Never'}
                  </Typography>
                </Grid>
              </Grid>

              <Divider sx={{ my: 2 }} />

              {/* Status Section */}
              <Typography variant="subtitle2" sx={{ mb: 2 }}>Status & Permissions</Typography>

              {isEditMode ? (
                <Box sx={{ mb: 3 }}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={editIsActive}
                        onChange={(e) => setEditIsActive(e.target.checked)}
                      />
                    }
                    label="Active"
                  />
                  <Typography variant="caption" display="block" color="text.secondary" sx={{ ml: 6, mb: 2 }}>
                    Inactive users cannot log in
                  </Typography>

                  <FormControlLabel
                    control={
                      <Switch
                        checked={editIsAdmin}
                        onChange={(e) => setEditIsAdmin(e.target.checked)}
                      />
                    }
                    label="Admin"
                  />
                  <Typography variant="caption" display="block" color="text.secondary" sx={{ ml: 6 }}>
                    Admins can manage users and access all apps
                  </Typography>
                </Box>
              ) : (
                <Box sx={{ display: 'flex', gap: 1, mb: 3 }}>
                  <Chip
                    label={selectedUser.is_active ? 'Active' : 'Inactive'}
                    color={selectedUser.is_active ? 'success' : 'default'}
                    size="small"
                  />
                  {selectedUser.is_admin && (
                    <Chip label="Admin" color="primary" size="small" />
                  )}
                  {!selectedUser.is_active && selectedUser.is_invited && (
                    <Chip label="Pending Invite" color="warning" size="small" />
                  )}
                </Box>
              )}

              {/* Quick Actions (only in view mode) */}
              {!isEditMode && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Typography variant="subtitle2" sx={{ mb: 2 }}>Quick Actions</Typography>
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<VisibilityIcon />}
                      onClick={() => handleViewAsUser(selectedUser)}
                    >
                      View As
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<LoginIcon />}
                      onClick={() => handleLoginAsUser(selectedUser)}
                    >
                      Login As
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<FolderIcon />}
                      onClick={() => handleViewBrands(selectedUser)}
                    >
                      Brands
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      color="error"
                      startIcon={<DeleteIcon />}
                      onClick={() => handleDeleteUser(selectedUser)}
                    >
                      Delete
                    </Button>
                  </Box>
                </>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          {isEditMode ? (
            <>
              <Button onClick={() => setIsEditMode(false)}>Cancel</Button>
              <Button onClick={handleSaveUserChanges} variant="contained">
                Save Changes
              </Button>
            </>
          ) : (
            <Button onClick={handleCloseUserDetails}>Close</Button>
          )}
        </DialogActions>
      </Dialog>

      {/* Invite User Dialog */}
      <Dialog open={inviteDialogOpen} onClose={() => setInviteDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Invite New User</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Add a user's email address to the approved list. They can sign in with Google, Microsoft, or create a password.
          </Typography>

          <TextField
            fullWidth
            label="Email Address"
            type="email"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            required
            size="small"
            sx={{ mb: 2, mt: 1 }}
          />

          <TextField
            fullWidth
            label="Full Name"
            value={inviteFullName}
            onChange={(e) => setInviteFullName(e.target.value)}
            size="small"
            sx={{ mb: 2 }}
          />

          <TextField
            fullWidth
            label="Organization"
            value={inviteOrganization}
            onChange={(e) => setInviteOrganization(e.target.value)}
            size="small"
            sx={{ mb: 2 }}
          />

          <FormControl fullWidth size="small" sx={{ mb: 2 }}>
            <InputLabel id="tenant-select-label">Tenant (Optional)</InputLabel>
            <Select
              labelId="tenant-select-label"
              id="tenant-select"
              value={inviteTenantId}
              label="Tenant (Optional)"
              onChange={(e) => setInviteTenantId(e.target.value as number | '')}
            >
              <MenuItem value="">
                <em>Use My Tenant (Default)</em>
              </MenuItem>
              {tenants.map((tenant) => (
                <MenuItem key={tenant.id} value={tenant.id}>
                  {tenant.tenant_name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

        </DialogContent>
        <DialogActions>
          <Button onClick={() => setInviteDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleInviteUser} variant="contained" disabled={!inviteEmail}>
            Add User
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>Delete User</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete user <strong>{userToDelete?.email}</strong>?
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            This will permanently delete the user and all their associated data. This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleConfirmDelete} color="error" variant="contained">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default UserManagement;

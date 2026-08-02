import { useState } from 'react';
import {
  AppBar,
  Box,
  CssBaseline,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Divider,
  Menu,
  MenuItem,
  Avatar,
  Chip,
} from '@mui/material';
import {
  Menu as MenuIcon,
  Dashboard as DashboardIcon,
  Analytics as AnalyticsIcon,
  Settings as SettingsIcon,
  Tune as CustomizeIcon,
  Label as DescriptorIcon,
  TrendingUp as TrendingUpIcon,
  Visibility as VisibilityIcon,
  SentimentSatisfied as SentimentIcon,
  Warning as WarningIcon,
  Announcement as AnnouncementIcon,
  Description as ReportIcon,
  Logout as LogoutIcon,
  AdminPanelSettings as AdminIcon,
  CloudDownload as CollectionIcon,
  Info as InfoIcon,
  Schedule as ScheduleIcon,
  HelpOutline as HelpIcon,
  Business as BusinessIcon,
  Storage as StorageIcon,
  SmartToy as LLMIcon,
  Search as InvestigationIcon,
} from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTenant } from '../contexts/TenantContext';
import BrandSwitcher from './BrandSwitcher';
import TenantSwitcher from './TenantSwitcher';
import talesWhite from './tales_white.png';

const drawerWidth = 240;

const TALES_TAGLINE = 'Shape your AI story.';

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, isAdmin } = useAuth();
  const { tenant } = useTenant();

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const handleUserMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleUserMenuClose = () => {
    setAnchorEl(null);
  };

  const handleLogout = () => {
    logout();
    handleUserMenuClose();
    navigate('/login');
  };

  const handleSettings = () => {
    navigate('/settings');
    handleUserMenuClose();
  };

  const handleAdminPanel = () => {
    navigate('/settings/users');
    handleUserMenuClose();
  };

  const handleTenantManagement = () => {
    navigate('/settings/tenants');
    handleUserMenuClose();
  };

  const handleSchedulerDashboard = () => {
    navigate('/settings/scheduler');
    handleUserMenuClose();
  };

  const handleDataBatches = () => {
    navigate('/settings/batches');
    handleUserMenuClose();
  };

  const handleLLMConfiguration = () => {
    navigate('/settings/llm-configuration');
    handleUserMenuClose();
  };

  const handleSiteSettings = () => {
    navigate('/settings/site');
    handleUserMenuClose();
  };

  const handleHelp = () => {
    navigate('/help');
    handleUserMenuClose();
  };


  // Tales navigation menu items
  const menuItems = [
    { text: 'Dashboard', icon: <DashboardIcon />, path: '/', indent: false },
    { text: 'Manage Brand', icon: <CustomizeIcon />, path: '/manage/brands', indent: false },
    { text: 'Collect & Analyze', icon: <CollectionIcon />, path: '/collect-analyze', indent: false },
    { text: 'Analytics', icon: <AnalyticsIcon />, path: '/analytics/brand-mentions', indent: false },
    { text: 'Brand Mentions', icon: <AnnouncementIcon />, path: '/analytics/brand-mentions', indent: true },
    { text: 'Positioning', icon: <TrendingUpIcon />, path: '/analytics/positioning', indent: true },
    { text: 'Share of Voice', icon: <VisibilityIcon />, path: '/analytics/share-of-voice', indent: true },
    { text: 'Descriptors', icon: <DescriptorIcon />, path: '/analytics/descriptors', indent: true },
    { text: 'Sentiment', icon: <SentimentIcon />, path: '/analytics/sentiment', indent: true },
    { text: 'Threats', icon: <WarningIcon />, path: '/analytics/threats', indent: true },
    { text: 'Investigations', icon: <InvestigationIcon />, path: '/analytics/investigations', indent: true },
    { text: 'Data Exports', icon: <ReportIcon />, path: '/exports', indent: false },
    { text: 'How Tales Works', icon: <InfoIcon />, path: '/how-tales-works', indent: false },
  ];

  const handleMenuItemClick = (item: any) => {
    if (item.path) {
      navigate(item.path);
    }
  };

  const drawer = (
    <Box sx={{
      height: '100%',
      backgroundColor: '#000000',
      display: 'flex',
      flexDirection: 'column',
    }}>
  <Toolbar
  sx={{
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    px: 2,
    minHeight: { xs: 90, sm: 114 }, // Reduced mobile height
    height: { xs: 90, sm: 114 },
    gap: 0.5,
    cursor: 'pointer',
    backgroundColor: '#000000',  // Black background
    color: 'common.white',               // make all text inside white
    '&:hover': {
    },
    '& h1': {
      margin: 0,
      color: 'common.white',             // ensure h1 text is white
    },
  }}
  onClick={() => navigate('/')}
>
  <Typography
    variant="body2"
    component="div"
    sx={{
      textAlign: 'center',
      fontSize: { xs: '0.75rem', sm: '0.875rem' }, // Smaller on mobile
      fontStyle: 'italic',
      lineHeight: 1.3,
      color: 'common.white',             // ensure secondary text is white
    }}
  >
    <Box
      component="img"
      src={talesWhite}
      alt="Tales"
      sx={{
        width: { xs: 100, sm: 120 }, // Smaller logo on mobile
        maxWidth: '100%',
        display: 'block',
        margin: '0 auto',
      }}
    />
    {TALES_TAGLINE}
  </Typography>
</Toolbar>

      <Divider sx={{ borderColor: 'rgba(255, 255, 255, 0.12)' }} />
      <Box sx={{ px: 2, py: 2 }}>
        <TenantSwitcher />
      </Box>
      <Divider sx={{ borderColor: 'rgba(255, 255, 255, 0.12)' }} />
      <List sx={{ flexGrow: 1 }}>
        {menuItems.map((item) => (
          <ListItem key={item.text} disablePadding>
            <ListItemButton
              selected={location.pathname === item.path}
              onClick={() => handleMenuItemClick(item)}
              sx={{
                pl: item.indent ? 5.75 : 2,
                '&:hover': {
                  backgroundColor: 'rgba(255, 255, 255, 0.08)',
                },
                '&.Mui-selected': {
                  backgroundColor: 'rgba(255, 255, 255, 0.16)',
                  borderLeft: '4px solid',
                  borderLeftColor: 'common.white',
                },
              }}
            >
              <ListItemIcon sx={{ color: 'common.white', minWidth: 36 }}>
                {item.icon}
              </ListItemIcon>
              <ListItemText
                primary={item.text}
                primaryTypographyProps={{
                  fontWeight: location.pathname === item.path ? 600 : 400,
                  color: 'common.white'
                }}
              />
            </ListItemButton>
          </ListItem>
        ))}
      </List>

    </Box>
  );

  return (
    <Box sx={{ display: 'flex', backgroundColor: 'white', minHeight: '100vh', width: '100%' }}>
      <CssBaseline />

      {/* Sidebar Navigation */}
      <Box
        component="nav"
        sx={{
          width: { sm: drawerWidth },
          flexShrink: { sm: 0 },
          backgroundColor: { sm: '#000000' }
        }}
      >
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{
            keepMounted: true,
          }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': {
              boxSizing: 'border-box',
              width: drawerWidth,
              borderRight: 'none',
              height: '100vh',
            },
          }}
        >
          {drawer}
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': {
              position: 'static',
              boxSizing: 'border-box',
              width: drawerWidth,
              borderRight: 'none',
              backgroundColor: 'transparent',
            },
          }}
          open
        >
          {drawer}
        </Drawer>
      </Box>

      {/* Main Content Area */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          width: '100%',
          minWidth: 0, // Allow flex item to shrink below content size
          minHeight: '100vh',
          backgroundColor: 'white',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Top AppBar */}
        <AppBar
          position="static"
          sx={{
            backgroundColor: '#000000',
            width: '100%',
          }}
        >
          <Toolbar
            sx={{
              minHeight: { xs: 90, sm: 114 }, // Reduced mobile height
              height: { xs: 90, sm: 114 },
              width: '100%',
              pr: { xs: 1, sm: '10px' }, // Less padding on mobile
              pl: { xs: 1, sm: 2 },
            }}
          >
            {/* Left: hamburger (mobile only) */}
            <IconButton
              color="inherit"
              aria-label="open drawer"
              edge="start"
              onClick={handleDrawerToggle}
              sx={{ mr: { xs: 0.5, sm: 2 }, display: { sm: 'none' } }}
            >
              <MenuIcon />
            </IconButton>

            {/* Tenant Logo (if available) */}
            {tenant?.logo_url && (
              <Box sx={{
                display: { xs: 'none', sm: 'flex' }, // Hide logo on mobile to save space
                alignItems: 'center',
                mr: 2
              }}>
                <img
                  src={tenant.logo_url}
                  alt={tenant.tenant_name}
                  style={{
                    height: '40px',
                    maxWidth: '150px',
                    objectFit: 'contain',
                  }}
                />
              </Box>
            )}

            {/* Right: group pushed to the far right with ml: 'auto' */}
            {user && (
              <Box
                sx={{
                  ml: 'auto',
                  display: 'flex',
                  alignItems: 'center',
                  gap: { xs: 0.5, sm: 2 }, // Reduced gap on mobile
                  color: 'common.white',
                  '& .MuiTypography-root': { color: 'common.white' },
                  '& .MuiSvgIcon-root': { color: 'common.white' },
                  '& *': { color: 'common.white' },
                }}
              >
                <BrandSwitcher />
                <IconButton onClick={handleUserMenuOpen} color="inherit" sx={{ p: 0.5 }}>
                  <Avatar sx={{ width: 32, height: 32, bgcolor: 'secondary.main', color: 'common.white' }}>
                    {user?.email?.charAt(0)?.toUpperCase() || '?'}
                  </Avatar>
                </IconButton>
              </Box>
            )}
          </Toolbar>
        </AppBar>

        {/* User Menu */}
        <Menu
          anchorEl={anchorEl}
          open={Boolean(anchorEl)}
          onClose={handleUserMenuClose}
          anchorOrigin={{
            vertical: 'bottom',
            horizontal: 'right',
          }}
          transformOrigin={{
            vertical: 'top',
            horizontal: 'right',
          }}
        >
          <Box sx={{ px: 2, py: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Signed in as
            </Typography>
            <Typography variant="body1" fontWeight={600}>
              {user?.email}
            </Typography>
          </Box>
          <Divider />
          <MenuItem onClick={handleSettings}>
            <ListItemIcon>
              <SettingsIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Settings</ListItemText>
          </MenuItem>
          {isAdmin && (
            <>
              <MenuItem onClick={handleAdminPanel}>
                <ListItemIcon>
                  <AdminIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>User Management</ListItemText>
              </MenuItem>
              <MenuItem onClick={handleTenantManagement}>
                <ListItemIcon>
                  <BusinessIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Tenant Management</ListItemText>
              </MenuItem>
              <MenuItem onClick={handleSchedulerDashboard}>
                <ListItemIcon>
                  <ScheduleIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Scheduler Dashboard</ListItemText>
              </MenuItem>
              <MenuItem onClick={handleDataBatches}>
                <ListItemIcon>
                  <StorageIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Data Batches</ListItemText>
              </MenuItem>
              <MenuItem onClick={handleLLMConfiguration}>
                <ListItemIcon>
                  <LLMIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>LLM Configuration</ListItemText>
              </MenuItem>
              <MenuItem onClick={handleSiteSettings}>
                <ListItemIcon>
                  <SettingsIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Site Settings</ListItemText>
              </MenuItem>
            </>
          )}
          <MenuItem onClick={handleHelp}>
            <ListItemIcon>
              <HelpIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Help & Support</ListItemText>
          </MenuItem>
          <Divider />
          <MenuItem onClick={handleLogout}>
            <ListItemIcon>
              <LogoutIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Logout</ListItemText>
          </MenuItem>
        </Menu>

        {/* Page Content */}
        <Box sx={{
          p: { xs: 2, sm: 3 }, // Less padding on mobile
          flexGrow: 1,
          backgroundColor: 'white',
          width: '100%',
          maxWidth: '100%', // Prevent overflow
          overflowX: 'hidden', // Prevent horizontal scroll
        }}>
          {children}
        </Box>
      </Box>
    </Box>
  );
}

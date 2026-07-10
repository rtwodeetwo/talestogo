import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';

import Layout from './Layout';
import Dashboard from '../pages/Dashboard';
import Queries from '../pages/manage/Queries';
import Competitors from '../pages/manage/Competitors';
import Descriptors from '../pages/manage/Descriptors';
import BrandInfo from '../pages/manage/BrandInfo';
import ManageBrands from '../pages/manage/ManageBrands';
import ReportsPage from '../pages/ReportsPage';
import CollectAndAnalyze from '../pages/CollectAndAnalyze';
import Settings from '../pages/Settings';
import UserManagement from '../pages/admin/UserManagement';
import TenantManagement from '../pages/admin/TenantManagement';
import LLMConfiguration from '../pages/admin/LLMConfiguration';
import SiteSettings from '../pages/admin/SiteSettings';
import UserBrandData from '../pages/admin/UserBrandData';
import AdminBatches from '../pages/admin/AdminBatches';
import AdminSchedulerDashboard from '../pages/AdminSchedulerDashboard';
import SentimentAnalysis from '../pages/analytics/SentimentAnalysis';
import PositioningAnalysis from '../pages/analytics/PositioningAnalysis';
import ShareOfVoice from '../pages/analytics/ShareOfVoice';
import BrandMentions from '../pages/analytics/BrandMentions';
import DescriptorAnalysis from '../pages/analytics/DescriptorAnalysis';
import CompetitorThreats from '../pages/analytics/CompetitorThreats';
import Recommendations from '../pages/analytics/Recommendations';
import HowTalesWorks from '../pages/HowTalesWorks';
import Help from '../pages/Help';
import Login from '../pages/auth/Login';
import Register from '../pages/auth/Register';
import InviteAccept from '../pages/auth/InviteAccept';
import { TenantProvider } from '../contexts/TenantContext';
import { TenantThemeProvider } from './TenantThemeProvider';
import { TaskStatusBanner } from './TaskStatusBanner';
import { ImpersonationBanner } from './ImpersonationBanner';
import ProtectedRoute from './ProtectedRoute';
import { useAuth } from '../contexts/AuthContext';

// Inner component that has access to TenantContext
const AppRoutes: React.FC = () => {
  return (
    <TenantThemeProvider>
      <ImpersonationBanner />
      <TaskStatusBanner />
      <Routes>
        {/* Public Routes */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/invite/accept" element={<InviteAccept />} />

        {/* Protected Routes */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout>
                <Dashboard />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* Analytics Routes */}
        <Route
          path="/analytics/brand-mentions"
          element={
            <ProtectedRoute>
              <Layout>
                <BrandMentions />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/analytics/positioning"
          element={
            <ProtectedRoute>
              <Layout>
                <PositioningAnalysis />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/analytics/share-of-voice"
          element={
            <ProtectedRoute>
              <Layout>
                <ShareOfVoice />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/analytics/descriptors"
          element={
            <ProtectedRoute>
              <Layout>
                <DescriptorAnalysis />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/analytics/sentiment"
          element={
            <ProtectedRoute>
              <Layout>
                <SentimentAnalysis />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/analytics/threats"
          element={
            <ProtectedRoute>
              <Layout>
                <CompetitorThreats />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/analytics/recommendations"
          element={
            <ProtectedRoute>
              <Layout>
                <Recommendations />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* Manage Route - redirect to brand-info */}
        <Route path="/manage" element={<Navigate to="/manage/brands" replace />} />

        {/* Data Management Routes */}
        <Route
          path="/manage/brands"
          element={
            <ProtectedRoute>
              <Layout>
                <ManageBrands />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/manage/queries"
          element={
            <ProtectedRoute>
              <Layout>
                <Queries />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/manage/descriptors"
          element={
            <ProtectedRoute>
              <Layout>
                <Descriptors />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/manage/competitors"
          element={
            <ProtectedRoute>
              <Layout>
                <Competitors />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/manage/brand-info"
          element={
            <ProtectedRoute>
              <Layout>
                <BrandInfo />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* Collect & Analyze Route */}
        <Route
          path="/collect-analyze"
          element={
            <ProtectedRoute>
              <Layout>
                <CollectAndAnalyze />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* Legacy routes - redirect to new consolidated page */}
        <Route path="/data" element={<Navigate to="/collect-analyze" replace />} />
        <Route path="/scheduled-tasks" element={<Navigate to="/collect-analyze" replace />} />
        <Route path="/data-analysis" element={<Navigate to="/collect-analyze" replace />} />

        {/* Settings Route */}
        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <Layout>
                <Settings />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* How Tales Works */}
        <Route
          path="/how-tales-works"
          element={
            <ProtectedRoute>
              <Layout>
                <HowTalesWorks />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* Help Route */}
        <Route
          path="/help"
          element={
            <ProtectedRoute>
              <Layout>
                <Help />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* Reports Route */}
        <Route
          path="/reports"
          element={
            <ProtectedRoute>
              <Layout>
                <ReportsPage />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* Admin Routes - use /settings prefix to avoid conflict with /admin API routes */}
        <Route
          path="/settings/users"
          element={
            <ProtectedRoute requireAdmin>
              <Layout>
                <UserManagement />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings/tenants"
          element={
            <ProtectedRoute requireAdmin>
              <Layout>
                <TenantManagement />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings/llm-configuration"
          element={
            <ProtectedRoute requireAdmin>
              <Layout>
                <LLMConfiguration />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings/users/:userId/brands/:brandId"
          element={
            <ProtectedRoute requireAdmin>
              <Layout>
                <UserBrandData />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings/scheduler"
          element={
            <ProtectedRoute requireAdmin>
              <Layout>
                <AdminSchedulerDashboard />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings/batches"
          element={
            <ProtectedRoute requireAdmin>
              <Layout>
                <AdminBatches />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings/site"
          element={
            <ProtectedRoute requireAdmin>
              <Layout>
                <SiteSettings />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* Catch-all redirect */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </TenantThemeProvider>
  );
};

export const AppContent: React.FC = () => {
  const { user } = useAuth();

  return (
    <TenantProvider isAdmin={user?.is_admin || false}>
      <AppRoutes />
    </TenantProvider>
  );
};

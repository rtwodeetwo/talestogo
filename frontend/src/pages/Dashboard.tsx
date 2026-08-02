import { useState, useEffect, useRef } from 'react';
import { Box, Typography, Grid, Card, CardContent, Paper, CircularProgress, Button, Alert, Snackbar, Table, TableBody, TableCell, TableRow, IconButton } from '@mui/material';
import {
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  SentimentSatisfied as SentimentIcon,
  Visibility as VisibilityIcon,
  Label as LabelIcon,
  CloudDownload as CollectionIcon,
  Analytics as AnalysisIcon,
  Warning as WarningIcon,
  Download as DownloadIcon,
} from '@mui/icons-material';
import html2canvas from 'html2canvas';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { PieChart, Pie, Cell, Tooltip, Legend, BarChart, Bar, XAxis, YAxis, CartesianGrid, LabelList } from 'recharts';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { useBrand } from '../contexts/BrandContext';
import BrandedLoader from '../components/BrandedLoader';
import { useTaskStatus } from '../contexts/TaskStatusContext';
import BatchSelector, { type CollectionBatch } from '../components/BatchSelector';
import ChartContainer from '../components/ChartContainer';
import { useResponsiveValue } from '../utils/responsive';
import { formatDateEST } from '../utils/dateUtils';

/** What the backend excluded from the metrics, and why.
 *
 * Surfacing these is what lets a failed collection be told apart from a real
 * drop in visibility. Previously an unanalyzed response was counted as "brand
 * not mentioned", so a bad collection night looked identical to bad news.
 */
interface DataQuality {
  total_rows: number;
  counted: number;
  branded_excluded: number;
  unanalyzed_excluded: number;
  invalid_enum_excluded: number;
  orphan_query_excluded: number;
}

interface DashboardMetrics {
  // Rates are null when there is nothing to divide by. That is deliberately
  // distinct from 0, which means "measured, and genuinely zero".
  mention_rate: number | null;
  mention_count: number;
  total_responses: number;
  positive_sentiment: number | null;
  descriptor_match: number | null;
  share_of_voice: number | null;
  leadership_visibility: number | null;
  positioning_average: number | null;
  change_mention_rate: number;
  change_sentiment: number;
  change_descriptor: number;
  change_share_of_voice: number;
  change_high_threats: number | null;
  change_leadership_visibility: number;
  leading_position: string;
  data_quality?: DataQuality;
  collection_date?: string;
  previous_collection_date?: string;
  comparison_mode?: string;
  // False when the baseline period contains no data at all, so there is
  // nothing to compare against and no trend arrow should be drawn.
  previous_period_has_data?: boolean;
  period_label?: string;
  previous_period_label?: string;
}

/** Render a rate, distinguishing "no data" from zero.
 *
 * The backend reports one decimal place; we show whole percentages on the
 * tiles, but a null must never round to 0.
 */
const formatPct = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : `${Math.round(value)}%`;

export default function Dashboard() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { activeBrand, brands, loading: brandLoading } = useBrand();
  const { tasks } = useTaskStatus();
  const dashboardRef = useRef<HTMLDivElement>(null);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
    open: false,
    message: '',
    severity: 'info',
  });
  const [collectionStatus, setCollectionStatus] = useState<'idle' | 'running'>('idle');
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  // Comparison mode: 'batch' (default, batch-over-batch), 'month' (month-over-month),
  // or 'quarter' (quarter-over-quarter). periodStart ("YYYY-MM-DD") pins a specific
  // month/quarter; null means the latest complete period.
  const [comparisonMode, setComparisonMode] = useState<'batch' | 'month' | 'quarter'>('batch');
  const [periodStart, setPeriodStart] = useState<string | null>(null);
  const [dismissedTaskId, setDismissedTaskId] = useState<number | null>(null);

  // Minimum loading time to ensure smooth UX
  const [minLoadingComplete, setMinLoadingComplete] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setMinLoadingComplete(true), 2000);
    return () => clearTimeout(timer);
  }, []);

  const brandName = activeBrand?.brand_name || 'Your Brand';

  // Responsive chart heights and sizes
  const sentimentChartHeight = useResponsiveValue(200, 250, 300);
  const sentimentOuterRadius = useResponsiveValue(60, 80, 100);
  const positioningChartHeight = useResponsiveValue(220, 240, 240);

  // Function to download dashboard as PNG
  const handleDownloadDashboard = async () => {
    if (dashboardRef.current) {
      try {
        // Add a small delay to ensure all content is rendered
        await new Promise(resolve => setTimeout(resolve, 100));

        const canvas = await html2canvas(dashboardRef.current, {
          backgroundColor: '#ffffff',
          scale: 2, // Higher quality
          allowTaint: true,
          useCORS: true,
          scrollY: -window.scrollY,
          scrollX: -window.scrollX,
        });

        // Format date as MM_DD_YYYY
        const now = new Date();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        const year = now.getFullYear();
        const dateStr = `${month}_${day}_${year}`;

        // Format brand name (replace spaces with underscores, remove special chars)
        const brandNameFormatted = brandName.replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_]/g, '');

        const link = document.createElement('a');
        link.download = `KeyMetrics_${brandNameFormatted}_${dateStr}.png`;
        link.href = canvas.toDataURL('image/png');
        link.click();
      } catch (error) {
        console.error('Error generating dashboard screenshot:', error);
        setSnackbar({
          open: true,
          message: 'Failed to download dashboard',
          severity: 'error',
        });
      }
    }
  };

  // Query to check if user has any brand info at all
  const { data: brandList } = useQuery({
    queryKey: ['brand-list'],
    queryFn: async () => {
      const response = await api.get('/brand-info/');
      return response.data;
    },
  });

  // Fetch batches to set default to latest
  const { data: batches, isLoading: batchesLoading } = useQuery({
    queryKey: ['collection-batches', activeBrand?.id],
    queryFn: async () => {
      const params = activeBrand?.id ? { brand_id: activeBrand.id } : {};
      const response = await api.get('/batches/', { params });
      return response.data;
    },
    enabled: !!activeBrand,
  });

  // Track if we've initialized the batch selection for this brand
  const [batchInitialized, setBatchInitialized] = useState(false);

  // Reset batch initialization when brand changes
  useEffect(() => {
    setBatchInitialized(false);
    setSelectedBatchId(null);
    setComparisonMode('batch');
    setPeriodStart(null);
  }, [activeBrand?.id]);

  // Fetch the list of complete months/quarters that have data, for the dropdown.
  const { data: availablePeriods } = useQuery({
    queryKey: ['available-periods', activeBrand?.id],
    queryFn: async () => {
      const params = activeBrand?.id ? { brand_id: activeBrand.id } : {};
      const response = await api.get('/api/analytics/available-periods', { params });
      return response.data as {
        months: { period_start: string; label: string }[];
        quarters: { period_start: string; label: string }[];
      };
    },
    enabled: !!activeBrand,
  });

  // Set default to latest batch when batches load
  // IMPORTANT: Include batchesLoading to ensure we wait for the query to complete
  useEffect(() => {
    // Don't initialize until batches query has completed loading
    if (batchesLoading) {
      return;
    }

    // Skip if already initialized for this brand
    if (batchInitialized) {
      return;
    }

    if (batches && batches.length > 0) {
      // Sort by started_at descending and pick the first (most recent)
      const sortedBatches = [...batches].sort((a: any, b: any) =>
        new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
      );
      setSelectedBatchId(sortedBatches[0].id);
      setBatchInitialized(true);
    } else if (batches !== undefined) {
      // No batches available (empty array) - mark as initialized so we can show empty state
      setBatchInitialized(true);
    }
  }, [batches, batchesLoading, batchInitialized]);


  // REMOVED: Redundant task status polling - now handled by TaskStatusContext
  // This was causing database connection pool exhaustion by polling every 3-30 seconds
  // TaskStatusContext already provides global task status with optimized polling

  // Fetch dashboard metrics - only after brand is loaded and batch selection is initialized
  const { data: metrics, isLoading: metricsLoading, error } = useQuery<DashboardMetrics>({
    queryKey: ['dashboard-metrics', activeBrand?.id, selectedBatchId, comparisonMode, periodStart],
    queryFn: async () => {
      const params = comparisonMode !== 'batch'
        ? { period: comparisonMode, ...(periodStart ? { period_start: periodStart } : {}) }
        : (selectedBatchId ? { batch_id: selectedBatchId } : {});
      const response = await api.get('/api/analytics/dashboard', { params });
      return response.data;
    },
    // Only fetch metrics after brand is loaded and batch selection is initialized
    enabled: !!activeBrand && batchInitialized,
  });

  // Combined loading state - wait for brand context to finish AND have an active brand,
  // then wait for batches to initialize, then wait for metrics to actually load
  const isLoading = !minLoadingComplete || brandLoading || !activeBrand || batchesLoading || !batchInitialized || metricsLoading || !metrics;

  // Fetch sentiment breakdown - only after brand is loaded and batch selection is initialized
  const { data: sentimentData } = useQuery({
    queryKey: ['sentiment-breakdown', activeBrand?.id, selectedBatchId, comparisonMode, periodStart],
    queryFn: async () => {
      const params = comparisonMode !== 'batch'
        ? { period: comparisonMode, ...(periodStart ? { period_start: periodStart } : {}) }
        : (selectedBatchId ? { batch_id: selectedBatchId } : {});
      const response = await api.get('/api/analytics/sentiment/breakdown', { params });
      return response.data;
    },
    enabled: !!activeBrand && batchInitialized,
  });

  // Fetch share of voice - only after brand is loaded and batch selection is initialized
  const { data: shareOfVoice } = useQuery({
    queryKey: ['share-of-voice-dashboard', activeBrand?.id, selectedBatchId, comparisonMode, periodStart],
    queryFn: async () => {
      const params = comparisonMode !== 'batch'
        ? { period: comparisonMode, ...(periodStart ? { period_start: periodStart } : {}) }
        : (selectedBatchId ? { batch_id: selectedBatchId } : {});
      const response = await api.get('/api/analytics/share-of-voice', { params });
      return response.data;
    },
    enabled: !!activeBrand && batchInitialized,
  });

  // Fetch positioning data - only after brand is loaded and batch selection is initialized
  const { data: positioningData } = useQuery({
    queryKey: ['positioning-dashboard', activeBrand?.id, selectedBatchId, comparisonMode, periodStart],
    queryFn: async () => {
      const params = comparisonMode !== 'batch'
        ? { period: comparisonMode, ...(periodStart ? { period_start: periodStart } : {}) }
        : (selectedBatchId ? { batch_id: selectedBatchId } : {});
      const response = await api.get('/api/analytics/positioning/breakdown', { params });
      return response.data;
    },
    enabled: !!activeBrand && batchInitialized,
  });

  // Fetch competitor threats (calculated server-side) - only after brand is loaded and batch selection is initialized
  const { data: competitorThreats } = useQuery({
    queryKey: ['competitor-threats-dashboard', activeBrand?.id, selectedBatchId, comparisonMode, periodStart],
    queryFn: async () => {
      const params = comparisonMode !== 'batch'
        ? { period: comparisonMode, ...(periodStart ? { period_start: periodStart } : {}) }
        : (selectedBatchId ? { batch_id: selectedBatchId } : {});
      const response = await api.get('/api/analytics/competitor-threats', { params });
      return response.data;
    },
    enabled: !!activeBrand && batchInitialized,
  });

  // Collection mutation
  const collectionMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/tasks/run-collection/');
      return response.data;
    },
    onSuccess: (data) => {
      setCollectionStatus('running');
      setSnackbar({
        open: true,
        message: data.message + ' ' + (data.note || ''),
        severity: 'success',
      });
      // Refresh metrics and check status periodically
      const checkInterval = setInterval(() => {
        queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] });
        queryClient.invalidateQueries({ queryKey: ['responses'] });
      }, 5000);

      // Assume collection completes after 60 seconds and stop checking
      setTimeout(() => {
        clearInterval(checkInterval);
        setCollectionStatus('idle');
        queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] });
        queryClient.invalidateQueries({ queryKey: ['responses'] });
        setSnackbar({
          open: true,
          message: 'Collection completed! Dashboard has been updated.',
          severity: 'success',
        });
      }, 60000);
    },
    onError: (error: any) => {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Failed to start collection',
        severity: 'error',
      });
    },
  });

  // Analysis mutation
  const analysisMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/tasks/run-analysis/');
      return response.data;
    },
    onSuccess: async (data) => {
      setSnackbar({
        open: true,
        message: data.message + ' ' + (data.note || ''),
        severity: 'info',
      });

      // Wait for charts to render
      setTimeout(async () => {
        queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] });
        queryClient.invalidateQueries({ queryKey: ['responses'] });

      }, 3000); // Wait 3 seconds for charts to fully render
    },
    onError: (error: any) => {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Failed to start analysis',
        severity: 'error',
      });
    },
  });

  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };

  // Show onboarding when brand context has finished loading but user has no brands yet.
  // Without this check, isLoading stays true forever because !activeBrand is always true.
  if (!brandLoading && brands.length === 0) {
    return (
      <Box sx={{ p: 4, textAlign: 'center' }}>
        <Typography variant="h4" gutterBottom>
          Welcome to TALES
        </Typography>
        <Typography variant="body1" color="textSecondary" sx={{ mb: 3 }}>
          Get started by adding your first brand to monitor.
        </Typography>
        <Box>
          <a href="/manage/brand-info?new=true" style={{ textDecoration: 'none' }}>
            <Box
              component="button"
              sx={{
                px: 3, py: 1.5, fontSize: '1rem', cursor: 'pointer',
                backgroundColor: 'primary.main', color: 'white',
                border: 'none', borderRadius: 1,
                '&:hover': { backgroundColor: 'primary.dark' },
              }}
            >
              Add Your First Brand
            </Box>
          </a>
        </Box>
      </Box>
    );
  }

  if (isLoading) {
    return <BrandedLoader message="Loading dashboard..." />;
  }

  if (error) {
    return (
      <Box>
        <Typography variant="h2" gutterBottom color="error">
          Error Loading Dashboard
        </Typography>
        <Typography>
          Unable to load dashboard metrics. Please make sure the backend server is running.
        </Typography>
      </Box>
    );
  }

  if (!metrics) {
    return null;
  }

  // In a period-over-period mode (month or quarter), compare against the named
  // previous period (e.g. "vs May 2026" / "vs Q1 2026"); otherwise use "vs last period".
  const isPeriodMode = comparisonMode !== 'batch';
  // A period with no collection in it is not a period where every metric was
  // zero. Comparing against one used to render the current value as if it were
  // the size of the change.
  const hasComparison = !isPeriodMode || metrics.previous_period_has_data !== false;
  const periodSuffix = isPeriodMode && metrics.previous_period_label
    ? ` vs ${metrics.previous_period_label}`
    : ' vs last period';

  // Format change indicators
  const formatChange = (value: number, previousDate?: string) => {
    if (!hasComparison) {
      return (
        <Typography variant="body2" color="text.secondary">
          No data for {metrics.previous_period_label ?? 'the previous period'}
        </Typography>
      );
    }
    if (value === 0) return null;
    const sign = value > 0 ? '↑' : '↓';
    const color = value > 0 ? 'success.main' : 'error.main';
    let dateText: string;
    if (isPeriodMode) {
      dateText = periodSuffix;
    } else if (previousDate) {
      dateText = ` vs ${formatDateEST(previousDate, 'short')}`;
    } else {
      dateText = ' vs last period';
    }
    return (
      <Typography variant="body2" color={color}>
        {sign} {value > 0 ? '+' : ''}{Math.round(value)}%{dateText}
      </Typography>
    );
  };

  // Use competitor threats from API (already calculated server-side)
  const threats = competitorThreats || [];
  const highThreatCount = threats.filter((c: any) => c.threat_level === 'High').length;
  const mediumThreatCount = threats.filter((c: any) => c.threat_level === 'Medium').length;

  // Get the first running task from global task status
  const runningTask = tasks.find(task => task.status === 'running');

  return (
    <Box>
      {/* Task Progress Indicator */}
      {runningTask && dismissedTaskId !== runningTask.id && (
        <Alert
          severity="info"
          sx={{ mb: 3 }}
          onClose={() => setDismissedTaskId(runningTask.id)}
        >
          <Box display="flex" alignItems="center" gap={2}>
            <CircularProgress size={20} />
            <Box flex={1}>
              <Typography variant="body2" fontWeight="bold">
                {runningTask.task_type === 'analysis' ? 'Analysis & Report Generation' : runningTask.task_type}
              </Typography>
              <Typography variant="caption">
                {runningTask.message || `Processing ${runningTask.processed_items} of ${runningTask.total_items} items...`}
              </Typography>
            </Box>
          </Box>
        </Alert>
      )}

      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'space-between', alignItems: { xs: 'flex-start', sm: 'center' }, flexDirection: { xs: 'column', sm: 'row' }, gap: 2 }}>
        <Box>
          <Typography variant="h2" component="h1">
            Key Metrics Dashboard
          </Typography>
          <Typography variant="subtitle1" color="primary" sx={{ fontWeight: 600, mt: 0.5 }}>
            {brandName}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: { xs: 1, sm: 2 }, alignItems: 'center', flexWrap: 'wrap', width: { xs: '100%', sm: 'auto' } }}>
          <Box sx={{ minWidth: { xs: '100%', sm: 250, md: 300 }, flexGrow: { xs: 1, sm: 0 } }}>
            <BatchSelector
              selectedBatchId={selectedBatchId}
              onBatchChange={(id) => { setComparisonMode('batch'); setPeriodStart(null); setSelectedBatchId(id); }}
              showAllOption={true}
              periodOptions={availablePeriods}
              selectedPeriod={comparisonMode !== 'batch' && periodStart ? { type: comparisonMode, start: periodStart } : null}
              onPeriodChange={(type, start) => { setComparisonMode(type); setPeriodStart(start); setSelectedBatchId(null); }}
              label="Filter by Collection"
            />
          </Box>
          <Button
            variant="outlined"
            startIcon={<DownloadIcon sx={{ display: { xs: 'none', sm: 'inline' } }} />}
            onClick={handleDownloadDashboard}
            size="small"
            sx={{ minWidth: { xs: 44, sm: 'auto' }, px: { xs: 1, sm: 2 } }}
          >
            <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>
              Download Dashboard as Image
            </Box>
            <DownloadIcon sx={{ display: { xs: 'inline', sm: 'none' } }} />
          </Button>
        </Box>
      </Box>

      {/* Collection Status Banner */}
      {collectionStatus === 'running' && (
        <Alert severity="info" sx={{ mb: 3 }} icon={<CircularProgress size={20} />}>
          <Typography variant="body1" fontWeight={600}>
            Collection in Progress
          </Typography>
          <Typography variant="body2">
            The system is collecting responses from LLM platforms. This may take a few minutes.
            The dashboard will automatically refresh with new data.
          </Typography>
        </Alert>
      )}

      {/* Dashboard Content Wrapper for Screenshot */}
      <Box ref={dashboardRef} id="dashboard-main" sx={{ p: 2 }}>
        {/* Show message only if user has no brands set up at all */}
        {brands.length === 0 && (
          <Paper sx={{ p: 3, mb: 4, backgroundColor: 'info.light' }}>
            <Typography variant="h6" gutterBottom>
              New to TALES?
            </Typography>
            <Typography>
              Click on <strong>Customize</strong> on the left and start adding information about your brands!
            </Typography>
          </Paper>
        )}

        {/* KPI Cards */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ height: '100%', border: '1px solid #e0e0e0', boxShadow: 'none' }}>
            <CardContent sx={{ height: '100%' }}>
              <Box display="flex" alignItems="center" justifyContent="space-between">
                <Box>
                  <Typography color="textSecondary" gutterBottom variant="body2">
                    Brand Mentions {isPeriodMode
                      ? (metrics.period_label ? `in ${metrics.period_label}` : '')
                      : (metrics.collection_date && `on ${formatDateEST(metrics.collection_date, 'short')}`)}
                  </Typography>
                  <Typography variant="h4" component="div" color="primary">
                    {formatPct(metrics.mention_rate)}
                  </Typography>
                  {formatChange(metrics.change_mention_rate, metrics.previous_collection_date)}
                </Box>
{metrics.change_mention_rate >= 0 ? (
                  <TrendingUpIcon sx={{
                    fontSize: 48,
                    color: metrics.change_mention_rate > 0 ? '#58A13B' : '#003e60'
                  }} />
                ) : (
                  <TrendingDownIcon sx={{
                    fontSize: 48,
                    color: '#EA4A4A'
                  }} />
                )}
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ height: '100%', border: '1px solid #e0e0e0', boxShadow: 'none' }}>
            <CardContent sx={{ height: '100%' }}>
              <Box display="flex" alignItems="center" justifyContent="space-between">
                <Box>
                  <Typography color="textSecondary" gutterBottom variant="body2">
                    Threats Summary
                  </Typography>
                  <Typography variant="h4" component="div" color="primary">
                    {highThreatCount ?? 0}
                  </Typography>
                  {metrics.change_high_threats !== null && metrics.change_high_threats !== undefined ? (
                    metrics.change_high_threats === 0 ? (
                      <Typography variant="body2" color="textSecondary">
                        No change{periodSuffix}
                      </Typography>
                    ) : (
                      <Typography variant="body2" color={metrics.change_high_threats > 0 ? 'error.main' : 'success.main'}>
                        {metrics.change_high_threats > 0 ? '↑' : '↓'} {metrics.change_high_threats > 0 ? '+' : ''}{metrics.change_high_threats}{periodSuffix}
                      </Typography>
                    )
                  ) : (
                    <Typography variant="body2" color="textSecondary">
                      High threat competitors
                    </Typography>
                  )}
                </Box>
                <WarningIcon sx={{ fontSize: 48, color: metrics.change_high_threats !== null && metrics.change_high_threats !== 0 ? (metrics.change_high_threats > 0 ? '#EA4A4A' : '#58A13B') : '#EA4A4A' }} />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ height: '100%', border: '1px solid #e0e0e0', boxShadow: 'none' }}>
            <CardContent sx={{ height: '100%' }}>
              <Box display="flex" alignItems="center" justifyContent="space-between">
                <Box>
                  <Typography color="textSecondary" gutterBottom variant="body2">
                    Target Descriptor Adoption
                  </Typography>
                  <Typography variant="h4" component="div" color="primary">
                    {formatPct(metrics.descriptor_match)}
                  </Typography>
                  {formatChange(metrics.change_descriptor)}
                </Box>
                <LabelIcon sx={{ fontSize: 48, color: metrics.change_descriptor > 0 ? '#58A13B' : metrics.change_descriptor < 0 ? '#EA4A4A' : '#80A1D4' }} />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ height: '100%', border: '1px solid #e0e0e0', boxShadow: 'none' }}>
            <CardContent sx={{ height: '100%' }}>
              <Box display="flex" alignItems="center" justifyContent="space-between">
                <Box>
                  <Typography color="textSecondary" gutterBottom variant="body2">
                    Share of Voice
                  </Typography>
                  <Typography variant="h4" component="div" color="primary">
                    {formatPct(metrics.share_of_voice)}
                  </Typography>
                  {metrics.change_share_of_voice === 0 ? (
                    <Typography variant="body2" color="textSecondary">
                      No change{periodSuffix}
                    </Typography>
                  ) : (
                    <Typography variant="body2" color={metrics.change_share_of_voice > 0 ? 'success.main' : 'error.main'}>
                      {metrics.change_share_of_voice > 0 ? '↑' : '↓'} {metrics.change_share_of_voice > 0 ? '+' : ''}{Math.round(metrics.change_share_of_voice)}%{periodSuffix}
                    </Typography>
                  )}
                </Box>
                <VisibilityIcon sx={{ fontSize: 48, color: metrics.change_share_of_voice > 0 ? '#58A13B' : metrics.change_share_of_voice < 0 ? '#EA4A4A' : '#003e60' }} />
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Charts Section */}
      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Paper id="dashboard-sentiment-chart" sx={{ p: { xs: 2, sm: 3 }, height: { xs: 320, sm: 360, md: 400 }, border: '1px solid #e0e0e0', boxShadow: 'none' }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
              <Typography variant="h6">
                Sentiment Breakdown
              </Typography>
              <Box sx={{ textAlign: 'right' }}>
                <Typography variant="body2" color="textSecondary">
                  {formatPct(metrics.positive_sentiment)} Positive
                </Typography>
                {metrics.change_sentiment !== 0 && (
                  <Typography variant="caption" color={metrics.change_sentiment > 0 ? 'success.main' : 'error.main'}>
                    {metrics.change_sentiment > 0 ? '↑' : '↓'} {metrics.change_sentiment > 0 ? '+' : ''}{Math.round(metrics.change_sentiment)}%{periodSuffix}
                  </Typography>
                )}
              </Box>
            </Box>
            {sentimentData && sentimentData.total > 0 ? (
              <Box sx={{ display: 'flex', flexDirection: { xs: 'column', sm: 'row' }, alignItems: 'center', height: { xs: 260, sm: 300, md: 340 }, gap: { xs: 1, sm: 2 } }}>
                {/* Legend on the left/top */}
                <Box sx={{ display: 'flex', flexDirection: { xs: 'row', sm: 'column' }, flexWrap: { xs: 'wrap', sm: 'nowrap' }, gap: 1, mr: { xs: 0, sm: 2 }, mb: { xs: 1, sm: 0 }, justifyContent: { xs: 'center', sm: 'flex-start' } }}>
                  {[
                    { name: 'Very Positive', value: sentimentData.very_positive_pct || 0, color: '#116C29' },
                    { name: 'Positive', value: sentimentData.positive_pct || 0, color: '#58A13B' },
                    { name: 'Neutral', value: sentimentData.neutral_pct || 0, color: '#9FA8DA' },
                    { name: 'Mixed', value: sentimentData.mixed_pct || 0, color: '#75C9C8' },
                    { name: 'Negative', value: sentimentData.negative_pct || 0, color: '#E04320' },
                  ].filter(item => item.value > 0).map((item) => (
                    <Box key={item.name} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <Box sx={{ width: 12, height: 12, backgroundColor: item.color, borderRadius: '2px' }} />
                      <Typography variant="body2" sx={{ fontSize: { xs: '11px', sm: '12px', md: '13px' }, whiteSpace: 'nowrap' }}>
                        {item.name}: {Math.round(item.value)}%
                      </Typography>
                    </Box>
                  ))}
                </Box>
                {/* Pie chart on the right/bottom - bigger on larger screens */}
                <ChartContainer width="100%" height={sentimentChartHeight}>
                  <PieChart>
                    <Pie
                      data={[
                        { name: 'Very Positive', value: sentimentData.very_positive_pct || 0, fill: '#116C29' },
                        { name: 'Positive', value: sentimentData.positive_pct || 0, fill: '#58A13B' },
                        { name: 'Neutral', value: sentimentData.neutral_pct || 0, fill: '#9FA8DA' },
                        { name: 'Mixed', value: sentimentData.mixed_pct || 0, fill: '#75C9C8' },
                        { name: 'Negative', value: sentimentData.negative_pct || 0, fill: '#E04320' },
                      ].filter(item => item.value > 0)}
                      cx="50%"
                      cy="50%"
                      outerRadius={sentimentOuterRadius}
                      dataKey="value"
                    >
                    </Pie>
                    <Tooltip formatter={(value) => `${Math.round(Number(value))}%`} />
                  </PieChart>
                </ChartContainer>
              </Box>
            ) : (
              <Box sx={{ height: { xs: 220, sm: 240 }, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Typography color="textSecondary">No sentiment data available</Typography>
              </Box>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper id="dashboard-positioning-chart" sx={{ p: { xs: 2, sm: 3 }, height: { xs: 280, sm: 300 }, border: '1px solid #e0e0e0', boxShadow: 'none' }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
              <Typography variant="h6">
                Positioning Distribution
              </Typography>
              <Box sx={{ textAlign: 'right' }}>
                <Typography variant="body2" color="textSecondary">
                  {/* Read from the dashboard payload, not the share-of-voice
                      response. The two used different formulas: this tile showed
                      Leader + Top 3 + Featured while the arrow below it tracked
                      Leader alone, so the number and its direction of travel
                      were measuring different things. */}
                  {`${formatPct(metrics.leadership_visibility)} Leadership Visibility`}
                </Typography>
                {metrics.change_leadership_visibility !== 0 && (
                  <Typography variant="caption" color={metrics.change_leadership_visibility > 0 ? 'success.main' : 'error.main'}>
                    {metrics.change_leadership_visibility > 0 ? '↑' : '↓'} {metrics.change_leadership_visibility > 0 ? '+' : ''}{Math.round(metrics.change_leadership_visibility)}%{periodSuffix}
                  </Typography>
                )}
              </Box>
            </Box>
            {positioningData && positioningData.total > 0 ? (
              (() => {
                const total = positioningData.total;
                const leaderPct = total > 0 ? Math.round((positioningData.leader || 0) / total * 100) : 0;
                const featuredPct = total > 0 ? Math.round((positioningData.featured || 0) / total * 100) : 0;
                const listedPct = total > 0 ? Math.round((positioningData.listed || 0) / total * 100) : 0;
                const notMentionedPct = total > 0 ? Math.round((positioningData.not_mentioned || 0) / total * 100) : 0;

                const chartData = [
                  { position: 'Leader ★', fullName: 'Leader (contributes to Leadership Visibility)', percentage: leaderPct, fill: '#116C29', isLeadership: true },
                  { position: 'Featured ★', fullName: 'Featured (contributes to Leadership Visibility)', percentage: featuredPct, fill: '#75C9C8', isLeadership: true },
                  { position: 'Listed', fullName: 'Listed', percentage: listedPct, fill: '#80A1D4', isLeadership: false },
                  { position: 'Not Mentioned', fullName: 'Not Mentioned', percentage: notMentionedPct, fill: '#003e60', isLeadership: false },
                ];

                const maxValue = Math.max(leaderPct, featuredPct, listedPct, notMentionedPct);
                const minYAxis = maxValue + 5;
                // Round up to next 10 or 25
                let roundedMax;
                if (minYAxis <= 25) {
                  roundedMax = 25;
                } else if (minYAxis <= 50) {
                  roundedMax = 50;
                } else if (minYAxis <= 75) {
                  roundedMax = 75;
                } else {
                  roundedMax = 100;
                }

                return (
                <ChartContainer width="100%" height={positioningChartHeight}>
                  <BarChart
                    data={chartData}
                    margin={{ top: 20, right: 20, left: 10, bottom: 50 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="position"
                      angle={-35}
                      textAnchor="end"
                      height={60}
                      tick={{ fontSize: 11 }}
                    />
                    <YAxis
                      domain={[0, roundedMax]}
                      tickFormatter={(value) => `${value}%`}
                      tick={{ fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(value: number, name: string, props: any) => [
                        `${value}%`,
                        props.payload.fullName || name
                      ]}
                    />
                    <Bar dataKey="percentage">
                      {chartData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.fill} />
                      ))}
                      <LabelList
                        dataKey="percentage"
                        position="top"
                        formatter={(value) => `${value}%`}
                        style={{ fontSize: 11, fontWeight: 500 }}
                      />
                    </Bar>
                  </BarChart>
                </ChartContainer>
                );
              })()
            ) : (
              <Box sx={{ height: { xs: 220, sm: 240 }, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Typography color="textSecondary">No positioning data available</Typography>
              </Box>
            )}
          </Paper>
        </Grid>

      </Grid>
      </Box>

      {/* Snackbar for notifications */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={handleCloseSnackbar}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert onClose={handleCloseSnackbar} severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}

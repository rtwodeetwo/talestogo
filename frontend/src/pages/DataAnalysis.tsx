import { useState } from 'react';
import {
  Box,
  Typography,
  Button,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  CircularProgress,
  Alert,
  Snackbar,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  TextField,
  Radio,
  RadioGroup,
  FormControlLabel,
  FormControl,
} from '@mui/material';
import {
  Analytics as AnalysisIcon,
  Visibility as ViewIcon,
  Download as DownloadIcon,
  Close as CloseIcon,
} from '@mui/icons-material';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import ReactMarkdown from 'react-markdown';
import TaskProgressIndicator from '../components/TaskProgressIndicator';

export default function DataAnalysis() {
  const queryClient = useQueryClient();
  const [showProgress, setShowProgress] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
    open: false,
    message: '',
    severity: 'info',
  });
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');
  const [analysisMode, setAnalysisMode] = useState<'latest' | 'date-range'>('latest');


  // Analysis mutation (for latest data only)
  const analysisMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/tasks/run-analysis/');
      return response.data;
    },
    onSuccess: (data) => {
      setShowProgress(true);
      setSnackbar({
        open: true,
        message: data.message + ' ' + (data.note || ''),
        severity: 'info',
      });
    },
    onError: (error: any) => {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Failed to start analysis',
        severity: 'error',
      });
    },
  });

  // Rerun analysis mutation
  const rerunAnalysisMutation = useMutation({
    mutationFn: async () => {
      const params = new URLSearchParams();
      if (startDate) params.append('start_date', startDate);
      if (endDate) params.append('end_date', endDate);
      const response = await api.post(`/tasks/rerun-analysis/?${params.toString()}`);
      return response.data;
    },
    onSuccess: (data) => {
      setShowProgress(true);
      setSnackbar({
        open: true,
        message: data.message + ' ' + (data.note || ''),
        severity: 'info',
      });
      // Clear date filters after successful submission
      setStartDate('');
      setEndDate('');
    },
    onError: (error: any) => {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Failed to start re-analysis',
        severity: 'error',
      });
    },
  });

  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };



  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 4 }}>
        <Typography variant="h2" component="h1">
          Data Analysis
        </Typography>
      </Box>

      {/* Run Analysis Section */}
      <Paper sx={{ p: 3, mb: 4, backgroundColor: '#f5f5f5' }}>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3, fontWeight: 600 }}>
          Analyze collected responses to extract mentions, sentiment, positioning, competitors and descriptors.
        </Typography>

        <FormControl component="fieldset" fullWidth>
          <RadioGroup
            value={analysisMode}
            onChange={(e) => {
              setAnalysisMode(e.target.value as 'latest' | 'date-range');
              if (e.target.value === 'latest') {
                setStartDate('');
                setEndDate('');
              }
            }}
          >
            <FormControlLabel
              value="latest"
              control={<Radio />}
              label={
                <Box>
                  <Typography variant="body1" fontWeight={500}>
                    Analyze Latest Data
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Analyze all responses collected on the most recent collection date
                  </Typography>
                </Box>
              }
            />
            <FormControlLabel
              value="date-range"
              control={<Radio />}
              label={
                <Box>
                  <Typography variant="body1" fontWeight={500}>
                    Analyze Custom Date Range
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Select a specific date range to analyze
                  </Typography>
                </Box>
              }
              sx={{ mt: 2 }}
            />
          </RadioGroup>
        </FormControl>

        {analysisMode === 'date-range' && (
          <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', mt: 3, mb: 2, ml: 4 }}>
            <TextField
              label="Start Date"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              InputLabelProps={{
                shrink: true,
              }}
              sx={{ width: 200 }}
            />
            <TextField
              label="End Date"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              InputLabelProps={{
                shrink: true,
              }}
              sx={{ width: 200 }}
            />
            {(startDate || endDate) && (
              <Button
                variant="text"
                size="small"
                onClick={() => {
                  setStartDate('');
                  setEndDate('');
                }}
              >
                Clear Dates
              </Button>
            )}
          </Box>
        )}

        {analysisMode === 'date-range' && (startDate || endDate) && (
          <Alert severity="info" sx={{ mb: 2, ml: 4 }}>
            {startDate && endDate
              ? `Will analyze responses from ${startDate} to ${endDate}`
              : startDate
              ? `Will analyze responses from ${startDate} onwards`
              : `Will analyze responses through ${endDate}`}
          </Alert>
        )}

        <Box sx={{ mt: 3, display: 'flex' }}>
          <Button
            variant="contained"
            color="secondary"
            size="large"
            startIcon={<AnalysisIcon />}
            onClick={() => {
              if (analysisMode === 'latest') {
                analysisMutation.mutate();
              } else {
                rerunAnalysisMutation.mutate();
              }
            }}
            disabled={analysisMutation.isPending || rerunAnalysisMutation.isPending}
          >
            {analysisMutation.isPending || rerunAnalysisMutation.isPending
              ? 'Running Analysis...'
              : 'Run Analysis'}
          </Button>
        </Box>
      </Paper>

      {/* Progress Indicator */}
      {showProgress && (
        <TaskProgressIndicator
          onComplete={() => {
            setShowProgress(false);
            queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] });
            queryClient.invalidateQueries({ queryKey: ['responses'] });
            queryClient.invalidateQueries({ queryKey: ['responses-dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['sentiment-analysis'] });
            queryClient.invalidateQueries({ queryKey: ['sentiment-breakdown'] });
            queryClient.invalidateQueries({ queryKey: ['share-of-voice'] });
            queryClient.invalidateQueries({ queryKey: ['share-of-voice-dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['positioning-analysis'] });
            queryClient.invalidateQueries({ queryKey: ['positioning-dashboard'] });
          }}
        />
      )}


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

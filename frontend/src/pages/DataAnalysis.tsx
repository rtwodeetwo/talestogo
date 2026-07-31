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

interface Report {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  report_content: string;
  total_responses: number;
  mention_rate?: number;
  google_doc_url?: string;
}

export default function DataAnalysis() {
  const queryClient = useQueryClient();
  const [showProgress, setShowProgress] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
    open: false,
    message: '',
    severity: 'info',
  });
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [selectedReport, setSelectedReport] = useState<Report | null>(null);
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');
  const [analysisMode, setAnalysisMode] = useState<'latest' | 'date-range'>('latest');

  // Fetch reports
  const { data: reports, isLoading } = useQuery<Report[]>({
    queryKey: ['reports'],
    queryFn: async () => {
      const response = await api.get('/reports/');
      return response.data;
    },
  });

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

  const handleViewInBrowser = (report: Report) => {
    setSelectedReport(report);
    setViewDialogOpen(true);
  };

  const handleDownloadWord = async (report: Report) => {
    try {
      const response = await api.get(`/reports/${report.id}/export/word`, {
        responseType: 'blob',
      });

      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${report.title}.docx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      setSnackbar({
        open: true,
        message: 'Word document with charts downloaded successfully',
        severity: 'success',
      });
    } catch (error) {
      setSnackbar({
        open: true,
        message: 'Failed to download Word document',
        severity: 'error',
      });
    }
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
          Analyze collected responses and generate a comprehensive report with AI-powered insights.
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
              : 'Run Analysis & Generate Report'}
          </Button>
        </Box>
      </Paper>

      {/* Progress Indicator */}
      {showProgress && (
        <TaskProgressIndicator
          onComplete={() => {
            setShowProgress(false);
            queryClient.invalidateQueries({ queryKey: ['reports'] });
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

      {/* Report Archive */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          Report Archive
        </Typography>

        {isLoading ? (
          <Box display="flex" justifyContent="center" alignItems="center" minHeight="200px">
            <CircularProgress />
          </Box>
        ) : reports && reports.length > 0 ? (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell><strong>Report</strong></TableCell>
                  <TableCell align="right"><strong>Actions</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {reports.map((report) => (
                  <TableRow key={report.id} hover>
                    <TableCell>{report.title}</TableCell>
                    <TableCell align="right">
                      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                        <Button
                          variant="outlined"
                          size="small"
                          startIcon={<ViewIcon />}
                          onClick={() => handleViewInBrowser(report)}
                        >
                          View
                        </Button>
                        <Button
                          variant="contained"
                          size="small"
                          startIcon={<DownloadIcon />}
                          onClick={() => handleDownloadWord(report)}
                          sx={{ bgcolor: '#003e60', '&:hover': { bgcolor: '#80a1d4' } }}
                        >
                          Word
                        </Button>
                      </Box>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Box sx={{ py: 4, textAlign: 'center' }}>
            <Typography variant="body1" color="text.secondary">
              No reports generated yet. Click "Run Analysis" to create your first report.
            </Typography>
          </Box>
        )}
      </Paper>

      {/* View Report Dialog */}
      <Dialog
        open={viewDialogOpen}
        onClose={() => setViewDialogOpen(false)}
        maxWidth="lg"
        fullWidth
        PaperProps={{
          sx: { height: '90vh' }
        }}
      >
        <DialogTitle>
          <Box display="flex" justifyContent="space-between" alignItems="center">
            <Typography variant="h6">{selectedReport?.title}</Typography>
            <IconButton onClick={() => setViewDialogOpen(false)} size="small">
              <CloseIcon />
            </IconButton>
          </Box>
        </DialogTitle>
        <DialogContent dividers>
          <Box sx={{
            '& h1': { fontSize: '2rem', fontWeight: 'bold', mb: 2, mt: 3 },
            '& h2': { fontSize: '1.5rem', fontWeight: 'bold', mb: 2, mt: 2 },
            '& h3': { fontSize: '1.25rem', fontWeight: 'bold', mb: 1.5, mt: 1.5 },
            '& p': { mb: 2 },
            '& ul, & ol': { mb: 2, pl: 3 },
            '& table': {
              width: '100%',
              borderCollapse: 'collapse',
              mb: 2,
              '& th, & td': {
                border: '1px solid #ddd',
                padding: '8px',
                textAlign: 'left'
              },
              '& th': {
                backgroundColor: '#f5f5f5',
                fontWeight: 'bold'
              }
            },
            '& code': {
              backgroundColor: '#f5f5f5',
              padding: '2px 6px',
              borderRadius: '4px',
              fontFamily: 'monospace'
            },
            '& pre': {
              backgroundColor: '#f5f5f5',
              padding: '12px',
              borderRadius: '4px',
              overflow: 'auto',
              mb: 2
            }
          }}>
            {selectedReport && (
              <ReactMarkdown>{selectedReport.report_content}</ReactMarkdown>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => handleDownloadWord(selectedReport!)}
            variant="contained"
            sx={{ bgcolor: '#003e60', color: 'white', '&:hover': { bgcolor: '#80a1d4' } }}
          >
            Word
          </Button>
          <Button onClick={() => setViewDialogOpen(false)} variant="contained">
            Close
          </Button>
        </DialogActions>
      </Dialog>

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

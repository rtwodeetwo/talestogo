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
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Alert,
  Snackbar,
} from '@mui/material';
import { CloudDownload as CollectionIcon, Analytics as AnalysisIcon, Download as DownloadIcon } from '@mui/icons-material';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import { formatDateEST } from '../utils/dateUtils';
import TaskProgressIndicator from '../components/TaskProgressIndicator';

interface Response {
  id: number;
  query_id: string;
  platform: string;
  response_text: string;
  timestamp: string;
  analyzed_at: string | null;
  brand_mentioned: string | null;
  sentiment: string | null;
}

export default function Data() {
  const queryClient = useQueryClient();
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [selectedResponse, setSelectedResponse] = useState<Response | null>(null);
  const [showProgress, setShowProgress] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({
    open: false,
    message: '',
    severity: 'info',
  });

  // Fetch responses
  const { data: responses, isLoading, error } = useQuery<Response[]>({
    queryKey: ['responses'],
    queryFn: async () => {
      const response = await api.get('/responses/');
      return response.data;
    },
    retry: false,
  });

  // Collection mutation
  const collectionMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/tasks/run-collection/');
      return response.data;
    },
    onSuccess: (data) => {
      setShowProgress(true);
      setSnackbar({
        open: true,
        message: data.message + ' ' + (data.note || ''),
        severity: 'success',
      });
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
    onSuccess: (data) => {
      setShowProgress(true);
      setSnackbar({
        open: true,
        message: data.message + ' Analysis will populate Mentioned and Sentiment columns.',
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

  const handleOpenConfirmDialog = () => {
    setConfirmDialogOpen(true);
  };

  const handleConfirmCollection = () => {
    setConfirmDialogOpen(false);
    collectionMutation.mutate();
  };

  const handleCancelCollection = () => {
    setConfirmDialogOpen(false);
  };

  const handleCloseSnackbar = () => {
    setSnackbar({ ...snackbar, open: false });
  };

  const handleDownloadExcel = async () => {
    try {
      const response = await api.get('/responses/export/excel', {
        responseType: 'blob',
      });

      // Create a blob URL and trigger download
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;

      // Extract filename from Content-Disposition header or use default
      const contentDisposition = response.headers['content-disposition'];
      let filename = 'AI_Responses.xlsx';
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename=(.+)/);
        if (filenameMatch && filenameMatch[1]) {
          filename = filenameMatch[1].replace(/['"]/g, '');
        }
      }

      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

      setSnackbar({
        open: true,
        message: 'Excel file downloaded successfully',
        severity: 'success',
      });
    } catch (error: any) {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Failed to download Excel file',
        severity: 'error',
      });
    }
  };

  const handleRowClick = (response: Response) => {
    setSelectedResponse(response);
  };

  const handleCloseResponseDialog = () => {
    setSelectedResponse(null);
  };

  const getSentimentColor = (sentiment: string | null): 'success' | 'primary' | 'default' | 'warning' | 'error' => {
    if (!sentiment) return 'default';
    switch (sentiment) {
      case 'Very Positive':
        return 'success';
      case 'Positive':
        return 'primary';
      case 'Neutral':
        return 'default';
      case 'Negative':
        return 'warning';
      case 'Very Negative':
        return 'error';
      case 'Mixed':
        return 'warning';
      default:
        return 'default';
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 4 }}>
        <Typography variant="h2" component="h1">
          Data Collection
        </Typography>
        <Box sx={{ display: 'flex', gap: 2 }}>
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={handleDownloadExcel}
            disabled={!responses || responses.length === 0}
            sx={{
              borderColor: '#80A1D4',
              color: '#80A1D4',
              '&:hover': {
                borderColor: '#6B8BC0',
                backgroundColor: 'rgba(128, 161, 212, 0.04)',
              },
            }}
          >
            Download Excel
          </Button>
          <Button
            variant="contained"
            startIcon={<CollectionIcon />}
            onClick={handleOpenConfirmDialog}
            disabled={collectionMutation.isPending}
            sx={{
              backgroundColor: '#80A1D4',
              '&:hover': {
                backgroundColor: '#6B8BC0',
              },
            }}
          >
            {collectionMutation.isPending ? 'Collecting...' : 'Collect Data'}
          </Button>
          <Button
            variant="contained"
            startIcon={<AnalysisIcon />}
            onClick={() => analysisMutation.mutate()}
            disabled={analysisMutation.isPending || !responses || responses.length === 0}
            sx={{
              backgroundColor: '#003e60',
              '&:hover': {
                backgroundColor: '#554866',
              },
            }}
          >
            {analysisMutation.isPending ? 'Analyzing...' : 'Analyze Data'}
          </Button>
        </Box>
      </Box>

      <Typography variant="body1" color="text.secondary" sx={{ mb: 4 }}>
        View all responses collected from LLM platforms. Click "Collect Data" to gather new responses, then "Analyze Data" to populate the Mentioned and Sentiment columns.
      </Typography>

      {/* Progress Indicator */}
      {showProgress && (
        <TaskProgressIndicator
          onComplete={() => {
            setShowProgress(false);
            queryClient.invalidateQueries({ queryKey: ['responses'] });
            queryClient.invalidateQueries({ queryKey: ['responses-dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['dashboard-metrics'] });
            queryClient.invalidateQueries({ queryKey: ['sentiment-analysis'] });
            queryClient.invalidateQueries({ queryKey: ['sentiment-breakdown'] });
            queryClient.invalidateQueries({ queryKey: ['share-of-voice'] });
            queryClient.invalidateQueries({ queryKey: ['share-of-voice-dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['positioning-analysis'] });
            queryClient.invalidateQueries({ queryKey: ['positioning-dashboard'] });
            queryClient.invalidateQueries({ queryKey: ['reports'] });
          }}
        />
      )}

      {/* Responses Table */}
      <Paper sx={{ p: 3 }}>
        {error ? (
          <Box sx={{ py: 4, textAlign: 'center' }}>
            <Alert severity="error">
              Failed to load responses. Please try refreshing the page.
            </Alert>
          </Box>
        ) : isLoading ? (
          <Box display="flex" justifyContent="center" alignItems="center" minHeight="300px">
            <CircularProgress />
          </Box>
        ) : responses && responses.length > 0 ? (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell><strong>Platform</strong></TableCell>
                  <TableCell><strong>Query</strong></TableCell>
                  <TableCell><strong>Response Text</strong></TableCell>
                  <TableCell><strong>Collected</strong></TableCell>
                  <TableCell><strong>Mentioned</strong></TableCell>
                  <TableCell><strong>Sentiment</strong></TableCell>
                  <TableCell><strong>Status</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {responses.map((response) => (
                  <TableRow
                    key={response.id}
                    hover
                    onClick={() => handleRowClick(response)}
                    sx={{ cursor: 'pointer' }}
                  >
                    <TableCell>{response.platform}</TableCell>
                    <TableCell sx={{ maxWidth: 200 }}>
                      <Typography variant="body2" noWrap>
                        {response.query_id}
                      </Typography>
                    </TableCell>
                    <TableCell sx={{ maxWidth: 400 }}>
                      <Typography
                        variant="body2"
                        sx={{
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: '-webkit-box',
                          WebkitLineClamp: 3,
                          WebkitBoxOrient: 'vertical',
                        }}
                      >
                        {response.response_text || '-'}
                      </Typography>
                    </TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      {response.timestamp ? formatDateEST(response.timestamp, 'full') : '-'}
                    </TableCell>
                    <TableCell>
                      {response.brand_mentioned ? (
                        <Chip
                          label={response.brand_mentioned}
                          color={response.brand_mentioned === 'Yes' ? 'success' : response.brand_mentioned === 'Indirect' ? 'primary' : 'default'}
                          size="small"
                        />
                      ) : (
                        '-'
                      )}
                    </TableCell>
                    <TableCell>
                      {response.sentiment ? (
                        <Chip
                          label={response.sentiment}
                          color={getSentimentColor(response.sentiment)}
                          size="small"
                        />
                      ) : response.analyzed_at ? (
                        <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                          Brand not mentioned
                        </Typography>
                      ) : (
                        '-'
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={response.analyzed_at ? 'Analyzed' : 'Pending'}
                        color={response.analyzed_at ? 'success' : 'warning'}
                        size="small"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Box sx={{ py: 4, textAlign: 'center' }}>
            <Typography variant="body1" color="text.secondary">
              No responses collected yet. Click "Collect Data" to start gathering responses from LLM platforms.
            </Typography>
          </Box>
        )}
      </Paper>

      {/* Confirmation Dialog */}
      <Dialog
        open={confirmDialogOpen}
        onClose={handleCancelCollection}
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-description"
      >
        <DialogTitle id="confirm-dialog-title">
          Confirm Data Collection
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="confirm-dialog-description">
            Are you sure you want to run data collection? This will query all configured LLM platforms
            and may take a few minutes to complete.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelCollection} color="inherit">
            Cancel
          </Button>
          <Button onClick={handleConfirmCollection} variant="contained" color="primary" autoFocus>
            Confirm
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

      {/* Response Detail Dialog */}
      <Dialog
        open={Boolean(selectedResponse)}
        onClose={handleCloseResponseDialog}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          Response Details
        </DialogTitle>
        <DialogContent>
          {selectedResponse && (
            <Box sx={{ pt: 1 }}>
              <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                Platform
              </Typography>
              <Typography variant="body1" gutterBottom>
                {selectedResponse.platform}
              </Typography>

              <Typography variant="subtitle2" color="text.secondary" gutterBottom sx={{ mt: 2 }}>
                Query
              </Typography>
              <Typography variant="body1" gutterBottom>
                {selectedResponse.query_id}
              </Typography>

              <Typography variant="subtitle2" color="text.secondary" gutterBottom sx={{ mt: 2 }}>
                Response Text
              </Typography>
              <Paper sx={{ p: 2, backgroundColor: 'background.default' }}>
                <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap' }}>
                  {selectedResponse.response_text || 'No response text available'}
                </Typography>
              </Paper>

              <Box sx={{ display: 'flex', gap: 2, mt: 2 }}>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Collected
                  </Typography>
                  <Typography variant="body2">
                    {selectedResponse.timestamp ? formatDateEST(selectedResponse.timestamp, 'full') : '-'}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Brand Mentioned
                  </Typography>
                  <Typography variant="body2">
                    {selectedResponse.brand_mentioned || '-'}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Sentiment
                  </Typography>
                  <Typography variant="body2">
                    {selectedResponse.sentiment || '-'}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Status
                  </Typography>
                  <Typography variant="body2">
                    {selectedResponse.analyzed_at ? 'Analyzed' : 'Pending'}
                  </Typography>
                </Box>
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseResponseDialog}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

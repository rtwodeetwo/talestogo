import { useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  Card,
  CardContent,
  CardActions,
  Button,
  Divider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  Alert,
  CircularProgress,
  Snackbar,
  Menu,
  MenuItem,
  Chip,
} from '@mui/material';
import {
  Description as WordIcon,
  Download as DownloadIcon,
  Delete as DeleteIcon,
  Refresh as RefreshIcon,
  Assessment as AssessmentIcon,
  TableChart as SpreadsheetIcon,
} from '@mui/icons-material';
import { DataGrid, GridActionsCellItem } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { api } from '../services/api';
import { formatDateEST } from '../utils/dateUtils';

interface Report {
  id: number;
  title: string;
  report_content: string;
  report_type?: string;
  period_label?: string;
  start_date?: string;
  end_date?: string;
  total_responses: number;
  mention_rate?: number;
  google_doc_url?: string;
  created_at: string;
  updated_at: string;
}

const formatReportType = (reportType?: string) => {
  if (!reportType) return '';
  if (reportType === 'all_data') return 'All Data';
  return reportType.charAt(0).toUpperCase() + reportType.slice(1);
};

export default function ReportsPage() {
  const queryClient = useQueryClient();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [reportToDelete, setReportToDelete] = useState<Report | null>(null);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState('');
  const [generateMenuAnchor, setGenerateMenuAnchor] = useState<null | HTMLElement>(null);

  // Fetch reports
  const { data: reports = [], isLoading } = useQuery({
    queryKey: ['reports'],
    queryFn: async () => {
      const response = await api.get<Report[]>('/reports/');
      return response.data;
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async (reportId: number) => {
      await api.delete(`/reports/${reportId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      setDeleteDialogOpen(false);
      setReportToDelete(null);
    },
  });

  // Generate a quarterly or annual report from existing analyzed data.
  // Monthly reports stay on the automated schedule, so the menu offers only
  // quarterly and annual.
  const generatePeriodReportMutation = useMutation({
    mutationFn: async (reportType: 'quarterly' | 'annual') => {
      const response = await api.post('/tasks/generate-period-report/', { report_type: reportType });
      return response.data;
    },
    onSuccess: (data) => {
      setSnackbarMessage(data.message || 'Report generation started. This may take several minutes.');
      setSnackbarOpen(true);
      // Refresh reports list after a delay
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['reports'] });
      }, 5000);
    },
    onError: (error: any) => {
      setSnackbarMessage(error.response?.data?.detail || 'Failed to start report generation');
      setSnackbarOpen(true);
    },
  });

  const handleGenerateChoice = (reportType: 'quarterly' | 'annual') => {
    setGenerateMenuAnchor(null);
    generatePeriodReportMutation.mutate(reportType);
  };

  const handleDeleteClick = (report: Report) => {
    setReportToDelete(report);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = () => {
    if (reportToDelete) {
      deleteMutation.mutate(reportToDelete.id);
    }
  };

  const handleCancelDelete = () => {
    setDeleteDialogOpen(false);
    setReportToDelete(null);
  };

  const handleDownloadWord = async (report: Report) => {
    try {
      const response = await api.get(`/reports/${report.id}/export/word`, {
        responseType: 'blob',
      });
      const url = URL.createObjectURL(response.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${report.title.replace(/[^a-z0-9]/gi, '_')}.docx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error: any) {
      console.error('Error downloading Word document:', error);
      alert(`Failed to download Word document: ${error.response?.data?.detail || error.message}`);
    }
  };

  const handleDownloadCSV = async (report: Report) => {
    try {
      const response = await api.get(`/reports/${report.id}/export/csv`, {
        responseType: 'blob',
      });
      const url = URL.createObjectURL(response.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${report.title.replace(/[^a-z0-9]/gi, '_')}_data.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error: any) {
      console.error('Error downloading CSV:', error);
      alert(`Failed to download data: ${error.response?.data?.detail || error.message}`);
    }
  };

  // Sort reports by created_at descending
  const sortedReports = [...reports].sort((a, b) =>
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  const latestReport = sortedReports[0];
  const archivedReports = sortedReports.slice(1);

  const columns: GridColDef<Report>[] = [
    {
      field: 'id',
      headerName: 'ID',
      width: 70,
    },
    {
      field: 'title',
      headerName: 'Report Title',
      flex: 1,
      minWidth: 250,
    },
    {
      field: 'report_type',
      headerName: 'Type',
      width: 110,
      valueFormatter: (params) => formatReportType(params as string | undefined),
    },
    {
      field: 'period_label',
      headerName: 'Period',
      width: 140,
    },
    {
      field: 'created_at',
      headerName: 'Created',
      width: 180,
      valueFormatter: (params) => {
        return formatDateEST(params, 'full');
      },
    },
    {
      field: 'total_responses',
      headerName: 'Responses',
      width: 120,
      align: 'center',
      headerAlign: 'center',
    },
    {
      field: 'download_data',
      type: 'actions',
      headerName: 'Download Data',
      width: 130,
      getActions: (params) => [
        <GridActionsCellItem
          key="csv"
          icon={<SpreadsheetIcon />}
          label="Download Data (CSV)"
          onClick={() => handleDownloadCSV(params.row)}
        />,
      ],
    },
    {
      field: 'download_report',
      type: 'actions',
      headerName: 'Download Report',
      width: 140,
      getActions: (params) => [
        <GridActionsCellItem
          key="word"
          icon={<WordIcon />}
          label="Download Report (Word)"
          onClick={() => handleDownloadWord(params.row)}
        />,
      ],
    },
    {
      field: 'actions',
      type: 'actions',
      headerName: 'Actions',
      width: 80,
      getActions: (params) => [
        <GridActionsCellItem
          key="delete"
          icon={<DeleteIcon />}
          label="Delete"
          onClick={() => handleDeleteClick(params.row)}
        />,
      ],
    },
  ];

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" component="h1">
          Reports
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <Button
            variant="outlined"
            color="primary"
            startIcon={generatePeriodReportMutation.isPending ? <CircularProgress size={16} /> : <AssessmentIcon />}
            onClick={(e) => setGenerateMenuAnchor(e.currentTarget)}
            disabled={generatePeriodReportMutation.isPending}
            size="small"
          >
            {generatePeriodReportMutation.isPending ? 'Generating...' : 'Generate Report'}
          </Button>
          <Menu
            anchorEl={generateMenuAnchor}
            open={Boolean(generateMenuAnchor)}
            onClose={() => setGenerateMenuAnchor(null)}
          >
            <MenuItem onClick={() => handleGenerateChoice('quarterly')}>
              Quarterly (last complete quarter)
            </MenuItem>
            <MenuItem onClick={() => handleGenerateChoice('annual')}>
              Annual (last complete year)
            </MenuItem>
          </Menu>
          <IconButton
            color="primary"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['reports'] })}
            title="Refresh"
          >
            <RefreshIcon />
          </IconButton>
        </Box>
      </Box>

      {reports.length === 0 ? (
        <Alert severity="info">
          No reports generated yet. Go to Collect & Analyze to generate your first report.
        </Alert>
      ) : (
        <>
          {/* Latest Report Section */}
          {latestReport && (
            <Box sx={{ mb: 4 }}>
              <Typography variant="h5" sx={{ mb: 2, fontWeight: 600, color: 'primary.main' }}>
                Latest Report
              </Typography>
              <Card
                sx={{
                  borderLeft: '4px solid',
                  borderLeftColor: 'primary.main',
                  boxShadow: 3,
                  '&:hover': {
                    boxShadow: 6,
                  },
                }}
              >
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    {latestReport.title}
                  </Typography>
                  {(latestReport.report_type || latestReport.period_label) && (
                    <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                      {latestReport.report_type && (
                        <Chip label={formatReportType(latestReport.report_type)} size="small" color="primary" variant="outlined" />
                      )}
                      {latestReport.period_label && (
                        <Chip label={latestReport.period_label} size="small" variant="outlined" />
                      )}
                    </Box>
                  )}
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Created: {formatDateEST(latestReport.created_at, 'full')}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Total Responses: {latestReport.total_responses}
                  </Typography>
                </CardContent>
                <Divider />
                <CardActions sx={{ justifyContent: 'flex-end', p: 2, gap: 1 }}>
                  <Button
                    variant="outlined"
                    startIcon={<SpreadsheetIcon />}
                    onClick={() => handleDownloadCSV(latestReport)}
                    size="small"
                  >
                    Data
                  </Button>
                  <Button
                    variant="contained"
                    startIcon={<WordIcon />}
                    onClick={() => handleDownloadWord(latestReport)}
                    size="small"
                  >
                    Report
                  </Button>
                </CardActions>
              </Card>
            </Box>
          )}

          {/* Reports Archive Section */}
          {archivedReports.length > 0 && (
            <Box>
              <Typography variant="h5" sx={{ mb: 2, fontWeight: 600 }}>
                Report Archive
              </Typography>
              <Paper sx={{ height: 500, width: '100%' }}>
                <DataGrid
                  rows={archivedReports}
                  columns={columns}
                  initialState={{
                    pagination: {
                      paginationModel: { pageSize: 10, page: 0 },
                    },
                    sorting: {
                      sortModel: [{ field: 'created_at', sort: 'desc' }],
                    },
                  }}
                  pageSizeOptions={[10, 25, 50]}
                  disableRowSelectionOnClick
                  sx={{
                    '& .MuiDataGrid-cell': {
                      py: 1,
                    },
                  }}
                />
              </Paper>
            </Box>
          )}
        </>
      )}

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteDialogOpen}
        onClose={handleCancelDelete}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Delete Report</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete this report?
          </Typography>
          {reportToDelete && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="body2" color="text.secondary">
                Title: {reportToDelete.title}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Created: {formatDateEST(reportToDelete.created_at, 'full')}
              </Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelDelete}>Cancel</Button>
          <Button
            onClick={handleConfirmDelete}
            color="error"
            variant="contained"
            disabled={deleteMutation.isPending}
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar for notifications */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={6000}
        onClose={() => setSnackbarOpen(false)}
        message={snackbarMessage}
      />
    </Box>
  );
}

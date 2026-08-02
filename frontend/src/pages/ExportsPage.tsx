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
  Alert,
  CircularProgress,
  Snackbar,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material';
import {
  TableChart as SpreadsheetIcon,
  Download as DownloadIcon,
} from '@mui/icons-material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { useBrand } from '../contexts/BrandContext';

/**
 * Data exports.
 *
 * Tales does not generate written reports. This page lists the periods that
 * actually have collected data and lets you download the underlying responses
 * as a spreadsheet.
 *
 * The spreadsheet includes every response in the period, along with the flags
 * needed to reproduce any dashboard number from the rows: filter on
 * "Counted In Metrics" and you get exactly the population behind the figure,
 * and "Excluded Because" says what happened to the rest.
 */

type PeriodKind = 'month' | 'quarter';

interface Period {
  period_start: string;
  label: string;
}

interface AvailablePeriods {
  months: Period[];
  quarters: Period[];
}

export default function ExportsPage() {
  const { activeBrand } = useBrand();
  const [kind, setKind] = useState<PeriodKind>('month');
  const [downloading, setDownloading] = useState<string | null>(null);
  const [snackbar, setSnackbar] = useState<string | null>(null);

  const { data: periods, isLoading } = useQuery({
    queryKey: ['available-periods', activeBrand?.id],
    queryFn: async () => {
      const params = activeBrand?.id ? { brand_id: activeBrand.id } : {};
      const response = await api.get<AvailablePeriods>(
        '/api/analytics/available-periods', { params });
      return response.data;
    },
    enabled: !!activeBrand,
  });

  const download = async (period: 'month' | 'quarter' | 'all', periodStart?: string,
                          label?: string) => {
    const key = periodStart ?? 'all';
    setDownloading(key);
    try {
      const response = await api.get('/exports/responses.csv', {
        params: { period, period_start: periodStart },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const a = document.createElement('a');
      a.href = url;
      const safe = (label ?? 'All Data').replace(/[^a-z0-9]/gi, '_');
      a.download = `${(activeBrand?.brand_name ?? 'Brand').replace(/[^a-z0-9]/gi, '_')}_${safe}_data.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (error: any) {
      // The backend returns a blob even on error, so the detail message has to
      // be read back out of it rather than off response.data directly.
      let detail = error?.message ?? 'Download failed';
      try {
        const text = await error?.response?.data?.text?.();
        if (text) detail = JSON.parse(text).detail ?? detail;
      } catch {
        /* keep the generic message */
      }
      setSnackbar(detail);
    } finally {
      setDownloading(null);
    }
  };

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  const rows = kind === 'month' ? periods?.months ?? [] : periods?.quarters ?? [];

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Data Exports
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Download the collected responses for a period as a spreadsheet. Each file
          includes every response, plus columns showing which rows are behind the
          dashboard figures and why any others were excluded.
        </Typography>
      </Box>

      <Card sx={{ mb: 4, borderLeft: '4px solid', borderLeftColor: 'primary.main' }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            All data
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Every response collected for {activeBrand?.brand_name ?? 'this brand'}, with no
            date filter.
          </Typography>
        </CardContent>
        <Divider />
        <CardActions sx={{ justifyContent: 'flex-end', p: 2 }}>
          <Button
            variant="contained"
            size="small"
            startIcon={downloading === 'all'
              ? <CircularProgress size={16} color="inherit" />
              : <SpreadsheetIcon />}
            disabled={downloading !== null}
            onClick={() => download('all')}
          >
            Download all data
          </Button>
        </CardActions>
      </Card>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 600 }}>
          By period
        </Typography>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={kind}
          onChange={(_, value) => value && setKind(value)}
        >
          <ToggleButton value="month">Months</ToggleButton>
          <ToggleButton value="quarter">Quarters</ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {rows.length === 0 ? (
        <Alert severity="info">
          No complete {kind === 'month' ? 'months' : 'quarters'} with data yet. A period
          appears here once it has finished and contains collected responses.
        </Alert>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Period</TableCell>
                <TableCell align="right">Spreadsheet</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((period) => (
                <TableRow key={period.period_start} hover>
                  <TableCell>
                    <Chip label={period.label} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      startIcon={downloading === period.period_start
                        ? <CircularProgress size={14} />
                        : <DownloadIcon />}
                      disabled={downloading !== null}
                      onClick={() => download(kind, period.period_start, period.label)}
                    >
                      Download
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Snackbar
        open={snackbar !== null}
        autoHideDuration={6000}
        onClose={() => setSnackbar(null)}
        message={snackbar}
      />
    </Box>
  );
}

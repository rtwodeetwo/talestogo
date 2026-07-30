import React, { useEffect, useRef } from 'react';
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  ListSubheader,
  CircularProgress,
  Typography,
} from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { CalendarMonth } from '@mui/icons-material';
import { useBrand } from '../contexts/BrandContext';

export interface CollectionBatch {
  id: number;
  batch_name: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  total_queries: number;
  total_responses: number;
  platforms: string | null;
  description: string | null;
}

export interface PeriodOption {
  period_start: string;  // "YYYY-MM-DD", first day of the period
  label: string;         // e.g. "June 2026" or "FY2026 Q3"
}

export interface SelectedPeriod {
  type: 'month' | 'quarter';
  start: string;         // matches a PeriodOption.period_start
}

interface BatchSelectorProps {
  selectedBatchId: number | null;
  onBatchChange: (batchId: number | null, batch?: CollectionBatch | null) => void;
  showAllOption?: boolean;
  label?: string;
  autoSelectLatest?: boolean;
  /** Selectable month/quarter periods for period-over-period comparison. */
  periodOptions?: { months?: PeriodOption[]; quarters?: PeriodOption[] };
  /** The currently active period, or null when a batch / All Data is selected. */
  selectedPeriod?: SelectedPeriod | null;
  /** Called when the user picks a specific month or quarter. */
  onPeriodChange?: (type: 'month' | 'quarter', start: string) => void;
}

const BatchSelector: React.FC<BatchSelectorProps> = ({
  selectedBatchId,
  onBatchChange,
  showAllOption = true,
  label = 'Collection Batch',
  autoSelectLatest = false,
  periodOptions,
  selectedPeriod = null,
  onPeriodChange,
}) => {
  const { activeBrand } = useBrand();
  const hasAutoSelected = useRef(false);
  const lastBrandId = useRef<number | null>(null);

  const { data: batches, isLoading, error } = useQuery<CollectionBatch[]>({
    queryKey: ['collection-batches', activeBrand?.id],
    queryFn: async () => {
      const params = activeBrand?.id ? { brand_id: activeBrand.id } : {};
      const response = await api.get('/batches/', { params });
      return response.data;
    },
    enabled: !!activeBrand, // Only fetch when there's an active brand
  });

  // Auto-select latest batch when enabled and batches are loaded
  useEffect(() => {
    // Reset auto-select flag when brand changes
    if (activeBrand?.id !== lastBrandId.current) {
      hasAutoSelected.current = false;
      lastBrandId.current = activeBrand?.id ?? null;
    }

    if (autoSelectLatest && !isLoading && batches && batches.length > 0 && !hasAutoSelected.current) {
      // Sort by started_at descending and pick the first (most recent)
      const sortedBatches = [...batches].sort((a, b) =>
        new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
      );
      onBatchChange(sortedBatches[0].id, sortedBatches[0]);
      hasAutoSelected.current = true;
    }
  }, [autoSelectLatest, batches, isLoading, onBatchChange, activeBrand?.id]);

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    // Display collection start date and time in EST for clear identification
    // This helps distinguish between multiple collections on the same day
    const dateStr = date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      timeZone: 'America/New_York'
    });
    const timeStr = date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'America/New_York'
    });
    return `${dateStr} at ${timeStr}`;
  };

  // Sort batches by started_at descending (most recent first)
  const sortedBatches = batches ? [...batches].sort((a, b) =>
    new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
  ) : [];

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 200 }}>
        <CircularProgress size={20} />
        <Typography variant="body2" color="text.secondary">
          Loading batches...
        </Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Typography variant="body2" color="error">
        Error loading batches
      </Typography>
    );
  }

  if (!batches || batches.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No collection batches available
      </Typography>
    );
  }

  const quarters = periodOptions?.quarters ?? [];
  const months = periodOptions?.months ?? [];

  // Encoded Select value for the active selection.
  const selectValue = selectedPeriod
    ? `${selectedPeriod.type}:${selectedPeriod.start}`
    : (selectedBatchId ?? '');

  // Get the display value shown in the closed Select.
  const getDisplayValue = () => {
    if (selectedPeriod) {
      const list = selectedPeriod.type === 'quarter' ? quarters : months;
      const match = list.find(p => p.period_start === selectedPeriod.start);
      if (match) return match.label;
    }
    if (selectedBatchId === null || selectedBatchId === undefined) {
      return 'All Data';
    }
    const selectedBatch = sortedBatches.find(b => b.id === selectedBatchId);
    return selectedBatch ? formatDate(selectedBatch.started_at) : '';
  };

  return (
    <FormControl fullWidth size="small">
      <InputLabel id="batch-selector-label">{label}</InputLabel>
      <Select
        labelId="batch-selector-label"
        id="batch-selector"
        value={selectValue}
        label={label}
        onChange={(e) => {
          const value = String(e.target.value);
          if (value.startsWith('quarter:')) {
            onPeriodChange?.('quarter', value.slice('quarter:'.length));
            return;
          }
          if (value.startsWith('month:')) {
            onPeriodChange?.('month', value.slice('month:'.length));
            return;
          }
          const batchId = value === '' ? null : Number(value);
          const batch = batchId ? sortedBatches.find(b => b.id === batchId) : null;
          onBatchChange(batchId, batch);
        }}
        startAdornment={
          <CalendarMonth sx={{ ml: 1, mr: 0.5, color: 'text.secondary', fontSize: 20 }} />
        }
        renderValue={() => (
          <Typography variant="body2" fontWeight={500}>
            {getDisplayValue()}
          </Typography>
        )}
      >
        {quarters.length > 0 && (
          <ListSubheader disableSticky>Quarter over Quarter</ListSubheader>
        )}
        {quarters.map((p) => (
          <MenuItem key={`quarter:${p.period_start}`} value={`quarter:${p.period_start}`}>
            <Typography variant="body2">{p.label}</Typography>
          </MenuItem>
        ))}
        {months.length > 0 && (
          <ListSubheader disableSticky>Month over Month</ListSubheader>
        )}
        {months.map((p) => (
          <MenuItem key={`month:${p.period_start}`} value={`month:${p.period_start}`}>
            <Typography variant="body2">{p.label}</Typography>
          </MenuItem>
        ))}
        {sortedBatches.length > 0 && (
          <ListSubheader disableSticky>Collections</ListSubheader>
        )}
        {sortedBatches.map((batch) => (
          <MenuItem key={batch.id} value={batch.id}>
            <Typography variant="body2">
              {formatDate(batch.started_at)}
            </Typography>
          </MenuItem>
        ))}
        {showAllOption && (
          <MenuItem value="">
            <Typography variant="body2" fontWeight={600}>
              All Data
            </Typography>
          </MenuItem>
        )}
      </Select>
    </FormControl>
  );
};

export default BatchSelector;

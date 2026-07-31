import { Box, Typography, Paper, CircularProgress, Alert, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Button } from '@mui/material';
import { Download as DownloadIcon } from '@mui/icons-material';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import { api } from '../../services/api';
import { useRef, useState } from 'react';
import BatchSelector from '../../components/BatchSelector';
import ChartContainer from '../../components/ChartContainer';
import { usePlatformConfig } from '../../contexts/PlatformContext';

export default function DescriptorAnalysis() {
  const tableRef = useRef<HTMLDivElement>(null);
  const llmChartRef = useRef<HTMLDivElement>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  const { platformColors } = usePlatformConfig();

  const { data: descriptors, isLoading, error } = useQuery({
    queryKey: ['descriptors'],
    queryFn: async () => {
      const response = await api.get('/descriptors/');
      return response.data;
    },
  });

  const { data: responses } = useQuery({
    queryKey: ['responses', selectedBatchId],
    queryFn: async () => {
      const params = selectedBatchId ? { batch_id: selectedBatchId } : {};
      const response = await api.get('/responses/', { params });
      return response.data;
    },
  });

  // Fetch LLM breakdown data (same collection filter as the Target Descriptors table)
  const { data: llmData, isLoading: llmLoading, error: llmError } = useQuery({
    queryKey: ['descriptors-by-llm', selectedBatchId],
    queryFn: async () => {
      const params = selectedBatchId ? { batch_id: selectedBatchId } : {};
      const response = await api.get('/api/analytics/descriptors-by-llm', { params });
      return response.data;
    },
  });

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error">
        Failed to load descriptor analysis. Please try again later.
      </Alert>
    );
  }

  // Count descriptor occurrences in responses where brand is mentioned
  const descriptorCounts = new Map<string, number>();
  let brandMentionCount = 0;

  if (responses && Array.isArray(responses)) {
    responses.forEach((response: any) => {
      // Only count descriptors from responses where the brand is mentioned
      if (response.brand_mentioned === 'Yes') {
        brandMentionCount++;
        if (response.descriptors) {
          const descList = response.descriptors.split(',').map((d: string) => d.trim());
          descList.forEach((desc: string) => {
            if (desc) {
              descriptorCounts.set(desc, (descriptorCounts.get(desc) || 0) + 1);
            }
          });
        }
      }
    });
  }

  // Convert to array and sort by count
  const descriptorStats = Array.from(descriptorCounts.entries())
    .map(([name, count]) => ({
      name,
      count,
      percentage: brandMentionCount > 0 ? Math.round((count / brandMentionCount) * 100) : 0
    }))
    .sort((a, b) => b.count - a.count);

  // Top 10 for chart
  const chartData = descriptorStats.slice(0, 10);

  // Prepare sorted data for table display and downloads
  const sortedDescriptorsData = descriptors
    ? descriptors
        .map((desc: any) => {
          const usage = descriptorCounts.get(desc.descriptor) || 0;
          const usageRate = brandMentionCount > 0 ? Math.round((usage / brandMentionCount) * 100) : 0;
          const isUsed = usage > 0;

          let status = 'Not Used';
          if (usage > 0) {
            if (Number(usageRate) >= 20) {
              status = 'Strong';
            } else if (Number(usageRate) >= 10) {
              status = 'Moderate';
            } else {
              status = 'Weak';
            }
          }

          return { desc, usage, usageRate, isUsed, status };
        })
        .sort((a: any, b: any) => Number(b.usageRate) - Number(a.usageRate))
    : [];

  const handleDownloadCSV = () => {
    if (!sortedDescriptorsData || sortedDescriptorsData.length === 0) return;

    const csvHeaders = ['Used with Brand', 'Target Descriptor', 'Mentions', 'Usage Rate', 'Status'];
    const csvRows = sortedDescriptorsData.map((item: any) => [
      item.isUsed ? 'Yes' : 'No',
      `"${item.desc.descriptor.replace(/"/g, '""')}"`,
      item.usage,
      `${item.usageRate}%`,
      item.status
    ]);

    const csvContent = [
      csvHeaders.join(','),
      ...csvRows.map((row: (string | number)[]) => row.join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const today = new Date();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    const year = today.getFullYear();
    const dateStr = `${month}_${day}_${year}`;

    link.download = `TargetDescriptors_${dateStr}.csv`;
    link.href = URL.createObjectURL(blob);
    link.click();
    URL.revokeObjectURL(link.href);
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h2" component="h1">
          Descriptor Analysis
        </Typography>
        <Box sx={{ minWidth: 300 }}>
          <BatchSelector
            selectedBatchId={selectedBatchId}
            onBatchChange={setSelectedBatchId}
            showAllOption={true}
            label="Filter by Collection"
            autoSelectLatest={true}
          />
        </Box>
      </Box>

      {/* Explanatory Text */}
      <Paper sx={{ p: 3, mb: 4, backgroundColor: '#f9f9f9' }}>
        <Typography variant="body1">
          <strong>Descriptors</strong> are the specific words and phrases AI systems use to characterize your brand. TALES identifies descriptors by analyzing the language patterns in AI responses where your brand is mentioned, tracking which adjectives and descriptive terms appear most frequently. Understanding your descriptor profile reveals how AI models perceive and present your brand identity, helping you align your messaging strategy with how you're actually being described in AI-generated content.
        </Typography>
      </Paper>

      {/* Target Descriptors - Consolidated Table */}
      <Paper sx={{ p: 4, mb: 4 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h6">
            Your Target Descriptors
          </Typography>
          <Box display="flex" gap={1}>
            <Button
              variant="outlined"
              startIcon={<DownloadIcon />}
              onClick={handleDownloadCSV}
              size="small"
              disabled={!descriptors || descriptors.length === 0}
            >
              Spreadsheet
            </Button>
          </Box>
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Track your ideal brand descriptors. Green checkmarks (✓) show descriptors found in AI responses where your brand is mentioned. Usage Rate indicates what percentage
          of brand mentions include each descriptor. Status reflects performance: Strong (≥20% usage), Moderate (10-20%), Weak (&lt;10%), or Not Used (0%).
        </Typography>
        {descriptors && descriptors.length > 0 ? (
          <TableContainer ref={tableRef}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Used with Brand</TableCell>
                  <TableCell>Target Descriptor</TableCell>
                  <TableCell align="right">Mentions</TableCell>
                  <TableCell align="right">Usage Rate</TableCell>
                  <TableCell>Status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {sortedDescriptorsData.map((item: any, index: number) => {
                  const { desc, usage, usageRate, isUsed, status } = item;

                  let statusColor = '#EA4A4A'; // Red for not used
                  if (status === 'Strong') {
                    statusColor = '#75C9C8'; // High - TALES teal
                  } else if (status === 'Moderate') {
                    statusColor = '#80A1D4'; // Medium - TALES blue
                  } else if (status === 'Weak') {
                    statusColor = '#003e60'; // Low - TALES purple
                  }

                  return (
                    <TableRow key={index}>
                      <TableCell>
                        {isUsed ? (
                          <Box sx={{ color: '#58A13B', fontSize: '24px', fontWeight: 'bold' }}>✓</Box>
                        ) : (
                          <Box sx={{ color: '#EA4A4A', fontSize: '24px' }}>✗</Box>
                        )}
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" fontWeight={isUsed ? 'bold' : 'normal'}>
                          {desc.descriptor}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" fontWeight={isUsed ? 'bold' : 'normal'}>
                          {usage}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" fontWeight={isUsed ? 'bold' : 'normal'}>
                          {usageRate}%
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Typography
                          variant="body2"
                          sx={{
                            color: statusColor,
                            fontWeight: 'bold'
                          }}
                        >
                          {status}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Alert severity="info">
            No target descriptors defined yet. Add them in the Customize → Descriptors section.
          </Alert>
        )}
      </Paper>

      {/* LLM Breakdown - Top Descriptors by Platform */}
      {llmData && llmData.length > 0 && (
        <Paper sx={{ p: 4 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Box>
              <Typography variant="h6">
                Top Descriptors by LLM Platform
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Most frequently used descriptors in responses mentioning your brand, by AI platform (Top 5), for the collection selected above
              </Typography>
            </Box>
          </Box>

          <Box ref={llmChartRef} sx={{ backgroundColor: 'white', p: 2, border: '1px solid #e0e0e0', mt: 2 }}>
            {llmData.map((platformData: any, index: number) => (
              <Box key={index} sx={{ mb: 4 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                  <Box
                    sx={{
                      width: 16,
                      height: 16,
                      borderRadius: '50%',
                      backgroundColor: platformColors[platformData.platform] || '#003e60'
                    }}
                  />
                  <Typography variant="h6">{platformData.platform}</Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                    ({platformData.total_mentions} total mentions)
                  </Typography>
                </Box>
                {platformData.descriptors && platformData.descriptors.length > 0 ? (
                  <TableContainer>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell><strong>Rank</strong></TableCell>
                          <TableCell><strong>Descriptor</strong></TableCell>
                          <TableCell align="right"><strong>Count</strong></TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {platformData.descriptors.map((desc: any, descIndex: number) => (
                          <TableRow key={descIndex}>
                            <TableCell>{descIndex + 1}</TableCell>
                            <TableCell>{desc.descriptor}</TableCell>
                            <TableCell align="right">{desc.count}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    No descriptors found for this platform
                  </Typography>
                )}
              </Box>
            ))}
          </Box>
        </Paper>
      )}
    </Box>
  );
}

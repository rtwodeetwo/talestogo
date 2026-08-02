import { useMemo, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  ButtonGroup,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  IconButton,
  LinearProgress,
  Menu,
  MenuItem,
  Paper,
  Snackbar,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  ArrowDropDown as ArrowDropDownIcon,
  Delete as DeleteIcon,
  ExpandLess as ExpandLessIcon,
  ExpandMore as ExpandMoreIcon,
  InfoOutlined as InfoOutlinedIcon,
  Search as SearchIcon,
} from '@mui/icons-material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../services/api';
import { useBrand } from '../../contexts/BrandContext';

/**
 * Investigations.
 *
 * The dashboard says the mention rate fell twelve points. This page says why:
 * whether it was one platform re-ranking, a competitor's announcement, a single
 * query flipping, or a collection that partly failed.
 *
 * Two things about the presentation are load-bearing.
 *
 * Limitations are shown as information, not as an error. A deployment with no
 * web-search key still gets a full investigation of its own data, and saying
 * "external causes were not checked" is honest reporting rather than a fault.
 *
 * The agent trace is one click away on every card. An investigation's
 * conclusions are only worth anything if the evidence behind them can be read,
 * so every tool call the agent made, and every one that failed, is on show.
 */

type ComparisonMode = 'month' | 'quarter' | 'batch';

interface InvestigationSummary {
  id: number;
  title: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed';
  trigger_type: string;
  comparison_mode: string;
  current_period_label: string | null;
  previous_period_label: string | null;
  current_batch_id: number | null;
  previous_batch_id: number | null;
  total_tool_calls: number;
  has_limitations: boolean;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

interface InvestigationDetail extends InvestigationSummary {
  summary: string | null;
  key_findings: string | null;
  recommended_actions: string | null;
  limitations: string | null;
  trigger_metrics: string | null;
  error_message: string | null;
  total_tokens_used: number;
}

interface ToolInvocation {
  id: number;
  sequence: number;
  tool_name: string;
  tool_input_json: string | null;
  tool_output_json: string | null;
  status: string;
  error: string | null;
  duration_ms: number | null;
}

interface Limitation {
  limitation: string;
  impact: string;
}

const MODE_LABELS: Record<ComparisonMode, string> = {
  month: 'Month over month',
  quarter: 'Quarter over quarter',
  batch: 'Latest collection',
};

const STATUS_COLORS: Record<string, 'default' | 'info' | 'success' | 'error'> = {
  pending: 'default',
  running: 'info',
  completed: 'success',
  failed: 'error',
};

/**
 * Render **bold** without dangerouslySetInnerHTML.
 *
 * Investigation summaries are written by a model from query text and collected
 * AI responses. Both can contain anything at all, including markup an attacker
 * planted in a page a platform then quoted back. Turning that into React nodes
 * rather than HTML is what keeps it inert.
 */
function renderInline(text: string, keyPrefix: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>;
    }
    return <span key={`${keyPrefix}-${index}`}>{part}</span>;
  });
}

function Markdownish({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).filter((p) => p.trim());
  return (
    <>
      {paragraphs.map((paragraph, index) => (
        <Typography key={index} variant="body2" sx={{ mb: 1.5, lineHeight: 1.7 }}>
          {renderInline(paragraph.trim(), `p${index}`)}
        </Typography>
      ))}
    </>
  );
}

function parseList(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function parseLimitations(raw: string | null): Limitation[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item && typeof item.limitation === 'string');
  } catch {
    return [];
  }
}

function periodChip(record: InvestigationSummary): string {
  if (record.current_period_label && record.previous_period_label) {
    return `${record.current_period_label} vs ${record.previous_period_label}`;
  }
  if (record.current_batch_id) {
    return `Collection ${record.current_batch_id} vs ${record.previous_batch_id ?? '?'}`;
  }
  return record.comparison_mode;
}

function AgentTrace({ investigationId }: { investigationId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['investigation-trace', investigationId],
    queryFn: async () => {
      const response = await api.get<ToolInvocation[]>(
        `/api/investigations/${investigationId}/tool-invocations`);
      return response.data;
    },
  });

  if (isLoading) return <CircularProgress size={20} />;
  if (!data || data.length === 0) {
    return <Typography variant="body2" color="text.secondary">No tool calls recorded.</Typography>;
  }

  return (
    <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 420 }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell>#</TableCell>
            <TableCell>Tool</TableCell>
            <TableCell>Arguments</TableCell>
            <TableCell>Result</TableCell>
            <TableCell align="right">ms</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {data.map((call) => (
            <TableRow key={call.id} hover>
              <TableCell>{call.sequence}</TableCell>
              <TableCell>
                <Chip
                  size="small"
                  label={call.tool_name}
                  color={call.status === 'failed' ? 'error' : 'default'}
                  variant={call.status === 'failed' ? 'filled' : 'outlined'}
                />
              </TableCell>
              <TableCell sx={{ maxWidth: 200 }}>
                <Typography variant="caption" sx={{ wordBreak: 'break-all' }}>
                  {call.tool_input_json}
                </Typography>
              </TableCell>
              <TableCell sx={{ maxWidth: 420 }}>
                <Typography
                  variant="caption"
                  color={call.status === 'failed' ? 'error' : 'text.secondary'}
                  sx={{ display: 'block', maxHeight: 90, overflow: 'auto',
                        wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}
                >
                  {call.status === 'failed' ? call.error : call.tool_output_json}
                </Typography>
              </TableCell>
              <TableCell align="right">{call.duration_ms ?? ''}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function InvestigationCard({ record, onDelete }: {
  record: InvestigationSummary;
  onDelete: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showTrace, setShowTrace] = useState(false);

  const { data: detail } = useQuery({
    queryKey: ['investigation-detail', record.id, record.status],
    queryFn: async () => {
      const response = await api.get<InvestigationDetail>(
        `/api/investigations/${record.id}`);
      return response.data;
    },
    enabled: expanded,
  });

  const findings = parseList(detail?.key_findings ?? null);
  const actions = parseList(detail?.recommended_actions ?? null);
  const limitations = parseLimitations(detail?.limitations ?? null);
  const running = record.status === 'pending' || record.status === 'running';

  return (
    <Card sx={{ mb: 2 }} variant="outlined">
      {running && <LinearProgress />}
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              {record.title ?? (running
                ? 'Investigating…'
                : record.status === 'failed'
                  ? 'Investigation failed'
                  : 'Untitled investigation')}
            </Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 1 }}>
              <Chip size="small" label={record.status}
                    color={STATUS_COLORS[record.status] ?? 'default'} />
              <Chip size="small" variant="outlined"
                    label={record.trigger_type === 'auto' ? 'automatic' : 'manual'} />
              <Chip size="small" variant="outlined" label={periodChip(record)} />
              <Chip size="small" variant="outlined"
                    label={`${record.total_tool_calls} tool ${
                      record.total_tool_calls === 1 ? 'call' : 'calls'}`} />
              {record.has_limitations && (
                <Chip size="small" color="info" variant="outlined"
                      icon={<InfoOutlinedIcon />} label="has limitations" />
              )}
            </Box>
            <Typography variant="caption" color="text.secondary"
                        sx={{ display: 'block', mt: 1 }}>
              {new Date(record.created_at).toLocaleString()}
            </Typography>
          </Box>
          <Tooltip title="Delete">
            <IconButton size="small" onClick={() => onDelete(record.id)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <IconButton size="small" onClick={() => setExpanded(!expanded)}>
            {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </IconButton>
        </Box>

        <Collapse in={expanded} unmountOnExit>
          <Divider sx={{ my: 2 }} />

          {detail?.error_message && (
            <Alert severity="error" sx={{ mb: 2 }}>{detail.error_message}</Alert>
          )}

          {limitations.length > 0 && (
            /* Deliberately 'info', not 'warning'. A missing web-search key
               degrades a run; it does not break it, and showing it as a fault
               would misrepresent a perfectly good investigation. */
            <Alert severity="info" icon={<InfoOutlinedIcon />} sx={{ mb: 2 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                What this investigation could not check
              </Typography>
              {limitations.map((item, index) => (
                <Typography key={index} variant="body2" sx={{ mb: 0.5 }}>
                  <strong>{item.limitation}.</strong> {item.impact}
                </Typography>
              ))}
            </Alert>
          )}

          {findings.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                Key findings
              </Typography>
              <Box component="ol" sx={{ pl: 3, m: 0 }}>
                {findings.map((finding, index) => (
                  <li key={index}>
                    <Typography variant="body2" sx={{ mb: 0.75, lineHeight: 1.7 }}>
                      {renderInline(finding, `f${index}`)}
                    </Typography>
                  </li>
                ))}
              </Box>
            </Box>
          )}

          {actions.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                Recommended actions
              </Typography>
              <Box component="ul" sx={{ pl: 3, m: 0 }}>
                {actions.map((action, index) => (
                  <li key={index}>
                    <Typography variant="body2" sx={{ mb: 0.75, lineHeight: 1.7 }}>
                      {renderInline(action, `a${index}`)}
                    </Typography>
                  </li>
                ))}
              </Box>
            </Box>
          )}

          {detail?.summary && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                Summary
              </Typography>
              <Markdownish text={detail.summary} />
            </Box>
          )}

          {running && !detail?.summary && (
            <Typography variant="body2" color="text.secondary">
              The agent is gathering evidence. This usually takes a few minutes.
            </Typography>
          )}

          <Button size="small" onClick={() => setShowTrace(!showTrace)}>
            {showTrace ? 'Hide agent trace' : 'Show agent trace'}
          </Button>
          <Collapse in={showTrace} unmountOnExit>
            <Box sx={{ mt: 1.5 }}>
              <Typography variant="caption" color="text.secondary"
                          sx={{ display: 'block', mb: 1 }}>
                Every piece of evidence the agent looked at, in order. Calls shown
                in red did not run, so their absence of a result is not a finding.
              </Typography>
              <AgentTrace investigationId={record.id} />
            </Box>
          </Collapse>
        </Collapse>
      </CardContent>
    </Card>
  );
}

export default function Investigations() {
  const { activeBrand } = useBrand();
  const queryClient = useQueryClient();
  const [snackbar, setSnackbar] = useState<string | null>(null);
  const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null);
  const menuButton = useRef<HTMLDivElement>(null);

  const { data: investigations, isLoading } = useQuery({
    queryKey: ['investigations', activeBrand?.id],
    queryFn: async () => {
      const response = await api.get<InvestigationSummary[]>('/api/investigations/');
      return response.data;
    },
    enabled: !!activeBrand,
    // Poll only while something is actually in flight, then stop. A page left
    // open on a finished list should not keep asking.
    refetchInterval: (query) => {
      const rows = query.state.data as InvestigationSummary[] | undefined;
      const busy = rows?.some((r) => r.status === 'pending' || r.status === 'running');
      return busy ? 5000 : false;
    },
  });

  const trigger = useMutation({
    mutationFn: async (mode: ComparisonMode) => {
      const response = await api.post('/api/investigations/trigger',
                                      { comparison_mode: mode });
      return response.data;
    },
    onSuccess: (data) => {
      setSnackbar(data?.message ?? 'Investigation started');
      queryClient.invalidateQueries({ queryKey: ['investigations'] });
    },
    onError: (error: any) => {
      // The backend explains exactly why a comparison could not be built (an
      // empty baseline period, a brand with only one collection). Throwing that
      // away for a generic "Request failed" would leave the user with no idea
      // what to do next.
      setSnackbar(error?.response?.data?.detail ?? error?.message ?? 'Could not start');
    },
  });

  const remove = useMutation({
    mutationFn: async (id: number) => api.delete(`/api/investigations/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['investigations'] }),
    onError: () => setSnackbar('Could not delete that investigation'),
  });

  const anyRunning = useMemo(
    () => investigations?.some((r) => r.status === 'pending' || r.status === 'running'),
    [investigations]);

  const start = (mode: ComparisonMode) => {
    setMenuAnchor(null);
    trigger.mutate(mode);
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between',
                 alignItems: 'flex-start', mb: 3, gap: 2, flexWrap: 'wrap' }}>
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            Investigations
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 720 }}>
            An investigation explains why the numbers moved between two periods.
            It reads the same figures the dashboard shows, drills into the queries
            and platforms that changed, checks whether the data was complete, and
            writes up what it found with the evidence attached.
          </Typography>
        </Box>
        <ButtonGroup variant="contained" ref={menuButton}>
          <Button
            startIcon={trigger.isPending
              ? <CircularProgress size={16} color="inherit" />
              : <SearchIcon />}
            disabled={!activeBrand || trigger.isPending}
            onClick={() => start('month')}
          >
            Investigate this month
          </Button>
          <Button
            size="small"
            disabled={!activeBrand || trigger.isPending}
            onClick={() => setMenuAnchor(menuButton.current)}
          >
            <ArrowDropDownIcon />
          </Button>
        </ButtonGroup>
        <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)}
              onClose={() => setMenuAnchor(null)}>
          {(['month', 'quarter', 'batch'] as ComparisonMode[]).map((mode) => (
            <MenuItem key={mode} onClick={() => start(mode)}>
              {MODE_LABELS[mode]}
            </MenuItem>
          ))}
        </Menu>
      </Box>

      {anyRunning && (
        <Alert severity="info" sx={{ mb: 2 }}>
          An investigation is running. It takes a few minutes; this page updates
          itself.
        </Alert>
      )}

      {isLoading ? (
        <Box display="flex" justifyContent="center" py={6}>
          <CircularProgress />
        </Box>
      ) : !investigations || investigations.length === 0 ? (
        <Alert severity="info">
          No investigations yet. Start one above, or wait for a collection to
          raise one automatically when a metric moves past its threshold.
        </Alert>
      ) : (
        investigations.map((record) => (
          <InvestigationCard key={record.id} record={record}
                             onDelete={(id) => remove.mutate(id)} />
        ))
      )}

      <Snackbar
        open={snackbar !== null}
        autoHideDuration={8000}
        onClose={() => setSnackbar(null)}
        message={snackbar}
      />
    </Box>
  );
}

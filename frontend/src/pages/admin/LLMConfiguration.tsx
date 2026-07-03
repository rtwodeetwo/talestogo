import React, { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Paper,
  Typography,
  Button,
  TextField,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  IconButton,
  Card,
  CardContent,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Switch,
  FormControlLabel,
  Tooltip,
  Chip,
  CircularProgress,
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  PlayArrow as TestIcon,
  Info as InfoIcon,
  Check as CheckIcon,
  Close as CloseIcon,
} from '@mui/icons-material';
import { llmProvidersAPI } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { usePlatformConfig } from '../../contexts/PlatformContext';

interface LLMProvider {
  id: number;
  tenant_id: number | null;
  provider_key: string;
  display_name: string;
  api_type: string;
  api_endpoint: string | null;
  model_name: string;
  env_var_name: string | null;
  api_version: string | null;
  bing_connection_name?: string | null;
  color: string;
  sort_order: number;
  is_enabled: boolean;
  use_for_analysis: boolean;
  supports_web_search: boolean;
  api_key_source: string;
  api_key_present?: boolean;
  resolved_env_var?: string | null;
  created_at: string;
  updated_at: string;
}

const API_TYPE_OPTIONS = [
  { value: 'openai', label: 'OpenAI', description: 'GPT-4, GPT-3.5, etc.', envVar: 'OPENAI_API_KEY' },
  { value: 'anthropic', label: 'Anthropic', description: 'Claude models', envVar: 'ANTHROPIC_API_KEY' },
  { value: 'google', label: 'Google', description: 'Gemini models', envVar: 'GEMINI_API_KEY' },
  { value: 'azure', label: 'Azure OpenAI', description: 'GPT-4o, GPT-4, etc. on Azure', envVar: 'AZURE_OPENAI_API_KEY' },
  { value: 'openai_compatible', label: 'OpenAI Compatible', description: 'Perplexity, local models, etc.', envVar: 'PERPLEXITY_API_KEY' },
  { value: 'bing_v7', label: 'Bing Search v7', description: 'Web search; pairs with the analysis LLM. State of the LLMs only.', envVar: 'BING_SEARCH_V7_API_KEY' },
  { value: 'azure_foundry_agents', label: 'Azure AI Foundry Agents', description: 'Azure-native grounded web search using Foundry Agents + Grounding with Bing Search. Auth via Azure Entra ID.', envVar: 'AZURE_AI_PROJECT_ENDPOINT' },
];

const DEFAULT_COLORS = [
  '#10a37f', // ChatGPT green
  '#d97706', // Claude orange
  '#4285f4', // Google blue
  '#20808d', // Perplexity teal
  '#9333ea', // Purple
  '#dc2626', // Red
];

const MAX_PROVIDERS = 6;

const LLMConfiguration: React.FC = () => {
  const { isAdmin } = useAuth();
  const { refreshPlatforms } = usePlatformConfig();

  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Create/Edit dialog
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<LLMProvider | null>(null);
  const [formData, setFormData] = useState({
    provider_key: '',
    display_name: '',
    api_type: 'openai',
    api_endpoint: '',
    model_name: '',
    env_var_name: '',
    api_version: '',
    bing_connection_name: '',
    color: '#666666',
    is_enabled: true,
    use_for_analysis: false,
    supports_web_search: false,
  });

  // Test connection state
  const [testingId, setTestingId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { success: boolean; message: string }>>({});

  useEffect(() => {
    if (isAdmin) {
      loadProviders();
    }
  }, [isAdmin]);

  const loadProviders = async () => {
    setLoading(true);
    setError('');

    try {
      const data = await llmProvidersAPI.getProviders();
      setProviders(data);
    } catch (err: any) {
      console.error('Failed to load LLM providers:', err);
      setError('Failed to load LLM providers');
    } finally {
      setLoading(false);
    }
  };

  const getEnvVarForProvider = (apiType: string, envVarName: string | null): string => {
    if (envVarName) return envVarName;
    const option = API_TYPE_OPTIONS.find(o => o.value === apiType);
    return option?.envVar || '';
  };

  const handleOpenDialog = (provider?: LLMProvider) => {
    if (provider) {
      setEditingProvider(provider);
      setFormData({
        provider_key: provider.provider_key,
        display_name: provider.display_name,
        api_type: provider.api_type,
        api_endpoint: provider.api_endpoint || '',
        model_name: provider.model_name,
        env_var_name: provider.env_var_name || '',
        api_version: provider.api_version || '',
        bing_connection_name: provider.bing_connection_name || '',
        color: provider.color,
        is_enabled: provider.is_enabled,
        use_for_analysis: provider.use_for_analysis,
        supports_web_search: provider.supports_web_search,
      });
    } else {
      setEditingProvider(null);
      // Auto-assign a color for new providers
      const usedColors = providers.map(p => p.color);
      const availableColor = DEFAULT_COLORS.find(c => !usedColors.includes(c)) || '#666666';
      setFormData({
        provider_key: '',
        display_name: '',
        api_type: 'openai',
        api_endpoint: '',
        model_name: '',
        env_var_name: '',
        api_version: '',
        bing_connection_name: '',
        color: availableColor,
        is_enabled: true,
        use_for_analysis: providers.length === 0, // First provider defaults to analysis
        supports_web_search: false,
      });
    }
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setEditingProvider(null);
  };

  // Auto-populate provider_key from display_name
  const handleDisplayNameChange = (value: string) => {
    setFormData(prev => ({
      ...prev,
      display_name: value,
      // Only auto-populate provider_key if creating new and key is empty or matches previous auto-generated
      provider_key: !editingProvider && (!prev.provider_key || prev.provider_key === prev.display_name.toLowerCase().replace(/[^a-z0-9]/g, '_'))
        ? value.toLowerCase().replace(/[^a-z0-9]/g, '_')
        : prev.provider_key,
    }));
  };

  // Auto-set web search capability based on API type and endpoint
  const handleApiTypeChange = (value: string) => {
    const isWebSearchType =
      value === 'google' ||
      value === 'bing_v7' ||
      value === 'azure_foundry_agents' ||
      (value === 'openai_compatible' && formData.api_endpoint.toLowerCase().includes('perplexity'));
    setFormData(prev => ({
      ...prev,
      api_type: value,
      supports_web_search: isWebSearchType,
      // Clear env_var_name if switching to a default type
      env_var_name: '',
    }));
  };

  const handleEndpointChange = (value: string) => {
    const isPerplexity = formData.api_type === 'openai_compatible' && value.toLowerCase().includes('perplexity');
    setFormData(prev => ({
      ...prev,
      api_endpoint: value,
      supports_web_search:
        prev.api_type === 'google' ||
        prev.api_type === 'bing_v7' ||
        prev.api_type === 'azure_foundry_agents' ||
        isPerplexity,
    }));
  };

  const handleSubmit = async () => {
    setError('');
    setSuccess('');

    if (!formData.display_name || !formData.provider_key || !formData.model_name) {
      setError('Display name, provider key, and model name are required');
      return;
    }

    if (providers.length >= MAX_PROVIDERS && !editingProvider) {
      setError(`Maximum of ${MAX_PROVIDERS} LLM providers allowed`);
      return;
    }

    try {
      if (editingProvider) {
        // Update existing provider
        const updateData: any = {
          display_name: formData.display_name,
          api_type: formData.api_type,
          api_endpoint: formData.api_endpoint || null,
          model_name: formData.model_name,
          env_var_name: formData.env_var_name || null,
          api_version: formData.api_version || null,
          bing_connection_name: formData.bing_connection_name || null,
          color: formData.color,
          is_enabled: formData.is_enabled,
          use_for_analysis: formData.use_for_analysis,
          supports_web_search: formData.supports_web_search,
        };
        await llmProvidersAPI.updateProvider(editingProvider.id, updateData);
        setSuccess(`Provider "${formData.display_name}" updated successfully`);
      } else {
        // Create new provider
        await llmProvidersAPI.createProvider({
          provider_key: formData.provider_key,
          display_name: formData.display_name,
          api_type: formData.api_type,
          api_endpoint: formData.api_endpoint || undefined,
          model_name: formData.model_name,
          env_var_name: formData.env_var_name || undefined,
          api_version: formData.api_version || undefined,
          bing_connection_name: formData.bing_connection_name || undefined,
          color: formData.color,
          sort_order: providers.length,
          is_enabled: formData.is_enabled,
          use_for_analysis: formData.use_for_analysis,
          supports_web_search: formData.supports_web_search,
        });
        setSuccess(`Provider "${formData.display_name}" created successfully`);
      }

      handleCloseDialog();
      await loadProviders();
      refreshPlatforms(); // Refresh platform colors in context
    } catch (err: any) {
      console.error('Failed to save provider:', err);
      setError(err.response?.data?.detail || 'Failed to save provider');
    }
  };

  const handleDelete = async (provider: LLMProvider) => {
    if (!window.confirm(`Are you sure you want to delete "${provider.display_name}"? This cannot be undone.`)) {
      return;
    }

    try {
      await llmProvidersAPI.deleteProvider(provider.id);
      setSuccess(`Provider "${provider.display_name}" deleted successfully`);
      await loadProviders();
      refreshPlatforms();
    } catch (err: any) {
      console.error('Failed to delete provider:', err);
      setError(err.response?.data?.detail || 'Failed to delete provider');
    }
  };

  const handleTest = async (provider: LLMProvider) => {
    setTestingId(provider.id);
    setTestResults(prev => ({ ...prev, [provider.id]: { success: false, message: 'Testing...' } }));

    try {
      const result = await llmProvidersAPI.testProvider(provider.id);
      setTestResults(prev => ({
        ...prev,
        [provider.id]: { success: result.success, message: result.message },
      }));
    } catch (err: any) {
      setTestResults(prev => ({
        ...prev,
        [provider.id]: { success: false, message: err.response?.data?.detail || 'Test failed' },
      }));
    } finally {
      setTestingId(null);
    }
  };

  if (!isAdmin) {
    return (
      <Container maxWidth="lg" sx={{ mt: 4 }}>
        <Alert severity="error">You must be an admin to access this page.</Alert>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4" component="h1">
            LLM Configuration
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Configure up to {MAX_PROVIDERS} LLM providers for data collection and analysis
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => handleOpenDialog()}
          disabled={providers.length >= MAX_PROVIDERS}
        >
          Add LLM
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {success && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess('')}>
          {success}
        </Alert>
      )}

      {/* Info box about two-part setup process */}
      <Alert severity="info" sx={{ mb: 3 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Setting up LLM providers is a two-part process:
        </Typography>
        <Typography variant="body2" component="div" sx={{ mb: 1 }}>
          <strong>Part 1 (Environment):</strong> API keys are set as <strong>environment variables</strong> on the server &mdash;
          in your hosting platform's settings (e.g., the Railway or Render dashboard) or a <code>.env</code> file for Docker
          (e.g., <code>GEMINI_API_KEY=your-key</code>, <code>ANTHROPIC_API_KEY=your-key</code>).
          Redeploy or restart the server after adding keys.
        </Typography>
        <Typography variant="body2" component="div" sx={{ mb: 1 }}>
          <strong>Part 2 (This Page):</strong> Configure display settings for each provider (name, model, color, options).
          API keys are NOT entered here.
        </Typography>
        <Typography variant="body2" sx={{ mt: 1 }}>
          <strong>Tip:</strong> Configure at least <strong>Google Gemini</strong> or <strong>Perplexity</strong> for web search capability
          (required for "State of the LLMs" reports).
        </Typography>
      </Alert>

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      ) : providers.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="h6" color="text.secondary" gutterBottom>
            No LLMs Configured
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Before adding a provider here, set the API key as an environment variable on the server &mdash; in your hosting platform's settings (Railway/Render dashboard) or a <code>.env</code> file for Docker.
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Example: <code>GEMINI_API_KEY=AIzaSy...</code> or <code>ANTHROPIC_API_KEY=sk-ant-...</code>
          </Typography>
        </Paper>
      ) : (
        <Grid container spacing={3}>
          {providers.map((provider) => (
            <Grid item xs={12} md={6} key={provider.id}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      <Box
                        sx={{
                          width: 48,
                          height: 48,
                          bgcolor: provider.color,
                          borderRadius: 1,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <Typography variant="h6" sx={{ color: 'white', fontWeight: 'bold' }}>
                          {provider.display_name.charAt(0)}
                        </Typography>
                      </Box>
                      <Box>
                        <Typography variant="h6" component="div">
                          {provider.display_name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {provider.model_name}
                        </Typography>
                      </Box>
                    </Box>
                    <Box>
                      <Tooltip title="Test Connection">
                        <IconButton
                          onClick={() => handleTest(provider)}
                          disabled={testingId === provider.id}
                          size="small"
                        >
                          {testingId === provider.id ? (
                            <CircularProgress size={20} />
                          ) : (
                            <TestIcon />
                          )}
                        </IconButton>
                      </Tooltip>
                      <IconButton onClick={() => handleOpenDialog(provider)} size="small">
                        <EditIcon />
                      </IconButton>
                      <IconButton onClick={() => handleDelete(provider)} color="error" size="small">
                        <DeleteIcon />
                      </IconButton>
                    </Box>
                  </Box>

                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
                    <Chip
                      size="small"
                      label={API_TYPE_OPTIONS.find(o => o.value === provider.api_type)?.label || provider.api_type}
                      variant="outlined"
                    />
                    {provider.is_enabled ? (
                      <Chip size="small" label="Enabled" color="success" />
                    ) : (
                      <Chip size="small" label="Disabled" color="default" />
                    )}
                    {provider.use_for_analysis && (
                      <Chip size="small" label="Analysis" color="primary" />
                    )}
                    {provider.supports_web_search && (
                      <Chip size="small" label="Web Search" color="info" />
                    )}
                  </Box>

                  {(() => {
                    if (provider.api_type === 'azure_foundry_agents') {
                      return (
                        <Box sx={{ mb: 1 }}>
                          <Chip size="small" label="Auth: Azure Entra ID" color="info" variant="filled" />
                          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                            Authenticated via DefaultAzureCredential (managed identity, az login, or service principal env vars)
                          </Typography>
                        </Box>
                      );
                    }
                    const envVar = provider.resolved_env_var || getEnvVarForProvider(provider.api_type, provider.env_var_name);
                    const present = provider.api_key_present === true;
                    return (
                      <Box sx={{ mb: 1 }}>
                        <Chip
                          size="small"
                          label={present ? 'API key detected' : 'No API key found'}
                          color={present ? 'success' : 'error'}
                          variant={present ? 'filled' : 'outlined'}
                        />
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                          {present
                            ? `Key loaded from environment variable ${envVar}`
                            : `No key in environment variable ${envVar}. Set it in your deployment environment (Railway/Render settings or a .env file for Docker), then redeploy/restart. API keys are NOT entered on this page.`}
                        </Typography>
                      </Box>
                    );
                  })()}

                  {provider.api_endpoint && (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                      Endpoint: {provider.api_endpoint}
                    </Typography>
                  )}

                  {testResults[provider.id] && (
                    <Alert
                      severity={testResults[provider.id].success ? 'success' : 'error'}
                      sx={{ mt: 1 }}
                      icon={testResults[provider.id].success ? <CheckIcon /> : <CloseIcon />}
                    >
                      {testResults[provider.id].message}
                    </Alert>
                  )}
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* Create/Edit Provider Dialog */}
      <Dialog open={dialogOpen} onClose={handleCloseDialog} maxWidth="sm" fullWidth>
        <DialogTitle>
          {editingProvider ? 'Edit LLM' : 'Add LLM'}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <TextField
              fullWidth
              label="Display Name"
              value={formData.display_name}
              onChange={(e) => handleDisplayNameChange(e.target.value)}
              required
              sx={{ mb: 2 }}
              helperText="Name shown in charts and reports (e.g., 'ChatGPT', 'Claude 3.5')"
            />

            <TextField
              fullWidth
              label="Provider Key"
              value={formData.provider_key}
              onChange={(e) => setFormData({ ...formData, provider_key: e.target.value })}
              required
              disabled={!!editingProvider}
              sx={{ mb: 2 }}
              helperText="Unique identifier (e.g., 'chatgpt', 'claude'). Cannot be changed after creation."
            />

            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>API Type</InputLabel>
              <Select
                value={formData.api_type}
                label="API Type"
                onChange={(e) => handleApiTypeChange(e.target.value)}
              >
                {API_TYPE_OPTIONS.map(option => (
                  <MenuItem key={option.value} value={option.value}>
                    <Box>
                      <Typography>{option.label}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {option.description}
                      </Typography>
                    </Box>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <TextField
              fullWidth
              label={
                formData.api_type === 'azure' || formData.api_type === 'azure_foundry_agents'
                  ? 'Deployment Name'
                  : formData.api_type === 'bing_v7'
                  ? 'Identifier (label only)'
                  : 'Model Name'
              }
              value={formData.model_name}
              onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
              required
              sx={{ mb: 2 }}
              helperText={
                formData.api_type === 'azure'
                  ? "Azure deployment name (the deployment you created in Azure OpenAI Studio, e.g., 'gpt-4o-prod')"
                  : formData.api_type === 'azure_foundry_agents'
                  ? "Model deployment name in the Foundry project (must support Grounding with Bing Search)."
                  : formData.api_type === 'bing_v7'
                  ? "Not used by Bing v7 (no LLM call). Set anything you like — used as a label in charts/logs (e.g., 'bing')."
                  : "Model identifier (e.g., 'gpt-4o', 'claude-3-haiku-20240307', 'gemini-2.0-flash')"
              }
            />

            {(formData.api_type === 'openai_compatible') && (
              <TextField
                fullWidth
                label="API Endpoint"
                value={formData.api_endpoint}
                onChange={(e) => handleEndpointChange(e.target.value)}
                sx={{ mb: 2 }}
                helperText="Custom endpoint URL (e.g., 'https://api.perplexity.ai')"
              />
            )}

            {(formData.api_type === 'azure') && (
              <>
                <TextField
                  fullWidth
                  label="Azure Resource URL"
                  value={formData.api_endpoint}
                  onChange={(e) => setFormData({ ...formData, api_endpoint: e.target.value })}
                  required
                  sx={{ mb: 2 }}
                  helperText="e.g., 'https://your-resource.openai.azure.com/' (from Azure Portal)"
                />
                <TextField
                  fullWidth
                  label="API Version"
                  value={formData.api_version}
                  onChange={(e) => setFormData({ ...formData, api_version: e.target.value })}
                  required
                  sx={{ mb: 2 }}
                  placeholder="2024-10-21"
                  helperText="Azure OpenAI api_version (see Microsoft docs for current stable values)"
                />
              </>
            )}

            {(formData.api_type === 'bing_v7') && (
              <TextField
                fullWidth
                label="Bing Search v7 Endpoint"
                value={formData.api_endpoint}
                onChange={(e) => setFormData({ ...formData, api_endpoint: e.target.value })}
                required
                sx={{ mb: 2 }}
                placeholder="https://api.bing.microsoft.com/"
                helperText="Bing v7 REST endpoint. Bing v7 retrieves search results only — synthesis is done by whichever provider you flag use_for_analysis=True."
              />
            )}

            {(formData.api_type === 'azure_foundry_agents') && (
              <>
                <TextField
                  fullWidth
                  label="Azure AI Foundry Project Endpoint"
                  value={formData.api_endpoint}
                  onChange={(e) => setFormData({ ...formData, api_endpoint: e.target.value })}
                  required
                  sx={{ mb: 2 }}
                  helperText="Your AI Foundry project endpoint (from Azure AI Foundry Studio → Project → Overview)."
                />
                <TextField
                  fullWidth
                  label="Bing Connection Name"
                  value={formData.bing_connection_name}
                  onChange={(e) => setFormData({ ...formData, bing_connection_name: e.target.value })}
                  required
                  sx={{ mb: 2 }}
                  helperText="Foundry project connection name for Grounding with Bing Search (AI Foundry → Project → Connections tab)."
                />
                <Alert severity="info" sx={{ mb: 2 }}>
                  <Typography variant="body2" sx={{ mb: 0.5 }}>
                    <strong>Authentication:</strong> Azure AI Foundry Agents uses Azure Entra ID (DefaultAzureCredential). No API key is stored.
                  </Typography>
                  <Typography variant="body2" component="div">
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      <li>Local dev: run <code>az login</code></li>
                      <li>System-assigned managed identity: no extra config needed</li>
                      <li>User-assigned managed identity: set <code>AZURE_CLIENT_ID</code></li>
                      <li>Service principal: set <code>AZURE_CLIENT_ID</code> + <code>AZURE_TENANT_ID</code> + <code>AZURE_CLIENT_SECRET</code></li>
                    </ul>
                  </Typography>
                </Alert>
              </>
            )}

            {/* Environment Variable Name - for custom providers (hidden for azure_foundry_agents which uses no API key) */}
            {formData.api_type !== 'azure_foundry_agents' && (
              <TextField
                fullWidth
                label="Environment Variable Name (optional)"
                value={formData.env_var_name}
                onChange={(e) => setFormData({ ...formData, env_var_name: e.target.value })}
                sx={{ mb: 2 }}
                placeholder={API_TYPE_OPTIONS.find(o => o.value === formData.api_type)?.envVar || ''}
                helperText={
                  formData.env_var_name
                    ? `Will read API key from: ${formData.env_var_name}`
                    : `Default: ${API_TYPE_OPTIONS.find(o => o.value === formData.api_type)?.envVar || 'Unknown'}. Override for custom providers (e.g., MISTRAL_API_KEY).`
                }
              />
            )}

            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Chart Color
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <TextField
                  type="color"
                  value={formData.color}
                  onChange={(e) => setFormData({ ...formData, color: e.target.value })}
                  sx={{ width: 80 }}
                  InputProps={{ sx: { height: 40 } }}
                />
                <Typography variant="body2" color="text.secondary">
                  {formData.color}
                </Typography>
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                  {DEFAULT_COLORS.map(color => (
                    <Box
                      key={color}
                      onClick={() => setFormData({ ...formData, color })}
                      sx={{
                        width: 24,
                        height: 24,
                        bgcolor: color,
                        borderRadius: 0.5,
                        cursor: 'pointer',
                        border: formData.color === color ? '2px solid #000' : '1px solid #ccc',
                      }}
                    />
                  ))}
                </Box>
              </Box>
            </Box>

            <Box sx={{ mb: 2 }}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.is_enabled}
                    onChange={(e) => setFormData({ ...formData, is_enabled: e.target.checked })}
                  />
                }
                label="Enabled for Data Collection"
              />
              <Typography variant="caption" color="text.secondary" display="block" sx={{ ml: 6 }}>
                When enabled, queries will be sent to this LLM during data collection
              </Typography>
            </Box>

            <Box sx={{ mb: 2 }}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.use_for_analysis}
                    onChange={(e) => setFormData({ ...formData, use_for_analysis: e.target.checked })}
                  />
                }
                label="Use for Analysis"
              />
              <Typography variant="caption" color="text.secondary" display="block" sx={{ ml: 6 }}>
                Designate this LLM for analyzing responses and generating reports
              </Typography>
            </Box>

            <Box sx={{ mb: 2 }}>
              <FormControlLabel
                control={
                  <Switch
                    checked={formData.supports_web_search}
                    onChange={(e) => setFormData({ ...formData, supports_web_search: e.target.checked })}
                  />
                }
                label={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    Supports Web Search
                    <Tooltip title="Required for 'State of the LLMs' report section. Google Gemini and Perplexity support this.">
                      <InfoIcon fontSize="small" color="action" />
                    </Tooltip>
                  </Box>
                }
              />
              <Typography variant="caption" color="text.secondary" display="block" sx={{ ml: 6 }}>
                Enable if this provider can perform live web searches (Gemini with grounding, Perplexity)
              </Typography>
            </Box>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Cancel</Button>
          <Button
            onClick={handleSubmit}
            variant="contained"
            disabled={!formData.display_name || !formData.provider_key || !formData.model_name}
          >
            {editingProvider ? 'Update LLM' : 'Add LLM'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default LLMConfiguration;

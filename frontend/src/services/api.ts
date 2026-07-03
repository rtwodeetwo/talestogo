import axios from 'axios';

// API Base URL - points to the FastAPI backend.
// Resolution order:
//   1. VITE_API_URL build-time env var (set explicitly when frontend and
//      backend are deployed to different origins)
//   2. localhost:8000 when running the Vite dev server (ports 5173/5177)
//   3. same-origin (default for the standard docker-compose deployment
//      where the backend serves the built frontend)
const API_BASE_URL = (() => {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }

  if (
    (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') &&
    (window.location.port === '5173' || window.location.port === '5177')
  ) {
    return 'http://localhost:8000';
  }

  return window.location.origin;
})();

// Token storage keys
const TOKEN_KEY = 'tales_access_token';
const USER_KEY = 'tales_user';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,  // Required for CORS with credentials
});

// Request interceptor to add JWT token to all requests
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    // Debug: log the full URL being requested
    const fullUrl = `${config.baseURL}${config.url}`;
    console.log('[API] Request:', config.method?.toUpperCase(), fullUrl);
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);

    // Handle 401 Unauthorized - token expired or invalid
    if (error.response?.status === 401) {
      // Clear auth data
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);

      // Redirect to login if not already there
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login';
      }
    }

    return Promise.reject(error);
  }
);

// Authentication API functions
export const authAPI = {
  login: async (email: string, password: string) => {
    const response = await api.post('/auth/login', { email, password });
    const { access_token } = response.data;

    // Store token
    localStorage.setItem(TOKEN_KEY, access_token);

    // Fetch and store user data
    const userResponse = await api.get('/auth/me');
    localStorage.setItem(USER_KEY, JSON.stringify(userResponse.data));

    return userResponse.data;
  },

  googleLogin: async (googleToken: string) => {
    const response = await api.post('/auth/google', { token: googleToken });
    const { access_token } = response.data;

    // Store token
    localStorage.setItem(TOKEN_KEY, access_token);

    // Fetch and store user data
    const userResponse = await api.get('/auth/me');
    localStorage.setItem(USER_KEY, JSON.stringify(userResponse.data));

    return userResponse.data;
  },

  microsoftLogin: async (microsoftToken: string) => {
    const response = await api.post('/auth/microsoft', { token: microsoftToken });
    const { access_token } = response.data;

    // Store token
    localStorage.setItem(TOKEN_KEY, access_token);

    // Fetch and store user data
    const userResponse = await api.get('/auth/me');
    localStorage.setItem(USER_KEY, JSON.stringify(userResponse.data));

    return userResponse.data;
  },

  register: async (email: string, password: string, full_name?: string, organization?: string) => {
    const response = await api.post('/auth/register', {
      email,
      password,
      full_name,
      organization,
    });
    return response.data;
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },

  getCurrentUser: async () => {
    const response = await api.get('/auth/me');
    localStorage.setItem(USER_KEY, JSON.stringify(response.data));
    return response.data;
  },

  updateProfile: async (data: {
    full_name?: string;
    organization?: string;
  }) => {
    const response = await api.put('/auth/me', data);
    localStorage.setItem(USER_KEY, JSON.stringify(response.data));
    return response.data;
  },

  getStoredUser: () => {
    const userStr = localStorage.getItem(USER_KEY);
    return userStr ? JSON.parse(userStr) : null;
  },

  getStoredToken: () => {
    return localStorage.getItem(TOKEN_KEY);
  },

  isAuthenticated: () => {
    return !!localStorage.getItem(TOKEN_KEY);
  },
};

// Admin API functions
export const adminAPI = {
  // User management
  listUsers: async () => {
    const response = await api.get('/admin/users');
    return response.data;
  },

  getUser: async (userId: number) => {
    const response = await api.get(`/admin/users/${userId}`);
    return response.data;
  },

  inviteUser: async (email: string, full_name?: string, organization?: string) => {
    const response = await api.post('/admin/users/invite', {
      email,
      full_name,
      organization,
    });
    return response.data;
  },

  createInvitation: async (email: string, full_name: string, organization?: string, tenant_id?: number) => {
    const response = await api.post('/admin/users/create-invite', {
      email,
      full_name,
      organization,
      tenant_id,
    });
    return response.data;
  },

  updateUserStatus: async (userId: number, data: { is_active?: boolean; is_admin?: boolean }) => {
    const response = await api.put(`/admin/users/${userId}`, data);
    return response.data;
  },

  deleteUser: async (userId: number) => {
    const response = await api.delete(`/admin/users/${userId}`);
    return response.data;
  },

  sendInvitationEmail: async (userId: number) => {
    const response = await api.post(`/admin/users/${userId}/send-invitation`);
    return response.data;
  },

  // Brand management
  listAllBrands: async () => {
    const response = await api.get('/admin/brands');
    return response.data;
  },

  getUserBrands: async (userId: number) => {
    const response = await api.get(`/admin/users/${userId}/brands`);
    return response.data;
  },

  getBrand: async (brandId: number) => {
    const response = await api.get(`/admin/brands/${brandId}`);
    return response.data;
  },

  updateBrand: async (brandId: number, data: any) => {
    const response = await api.put(`/admin/brands/${brandId}`, data);
    return response.data;
  },

  // Query management
  getUserBrandQueries: async (userId: number, brandId: number) => {
    const response = await api.get(`/admin/users/${userId}/brands/${brandId}/queries`);
    return response.data;
  },

  createQuery: async (userId: number, brandId: number, data: any) => {
    const response = await api.post(`/admin/users/${userId}/brands/${brandId}/queries`, data);
    return response.data;
  },

  updateQuery: async (userId: number, brandId: number, queryId: string, data: any) => {
    const response = await api.put(`/admin/users/${userId}/brands/${brandId}/queries/${queryId}`, data);
    return response.data;
  },

  deleteQuery: async (userId: number, brandId: number, queryId: string) => {
    const response = await api.delete(`/admin/users/${userId}/brands/${brandId}/queries/${queryId}`);
    return response.data;
  },

  // Descriptor management
  getUserBrandDescriptors: async (userId: number, brandId: number) => {
    const response = await api.get(`/admin/users/${userId}/brands/${brandId}/descriptors`);
    return response.data;
  },

  createDescriptor: async (userId: number, brandId: number, data: any) => {
    const response = await api.post(`/admin/users/${userId}/brands/${brandId}/descriptors`, data);
    return response.data;
  },

  updateDescriptor: async (userId: number, brandId: number, descriptorId: number, data: any) => {
    const response = await api.put(`/admin/users/${userId}/brands/${brandId}/descriptors/${descriptorId}`, data);
    return response.data;
  },

  deleteDescriptor: async (userId: number, brandId: number, descriptorId: number) => {
    const response = await api.delete(`/admin/users/${userId}/brands/${brandId}/descriptors/${descriptorId}`);
    return response.data;
  },

  // Competitor management
  getUserBrandCompetitors: async (userId: number, brandId: number) => {
    const response = await api.get(`/admin/users/${userId}/brands/${brandId}/competitors`);
    return response.data;
  },

  createCompetitor: async (userId: number, brandId: number, data: any) => {
    const response = await api.post(`/admin/users/${userId}/brands/${brandId}/competitors`, data);
    return response.data;
  },

  updateCompetitor: async (userId: number, brandId: number, competitorId: number, data: any) => {
    const response = await api.put(`/admin/users/${userId}/brands/${brandId}/competitors/${competitorId}`, data);
    return response.data;
  },

  deleteCompetitor: async (userId: number, brandId: number, competitorId: number) => {
    const response = await api.delete(`/admin/users/${userId}/brands/${brandId}/competitors/${competitorId}`);
    return response.data;
  },

  // Bulk upload
  uploadQueries: async (userId: number, brandId: number, formData: FormData) => {
    const response = await api.post(`/admin/users/${userId}/brands/${brandId}/queries/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  uploadDescriptors: async (userId: number, brandId: number, formData: FormData) => {
    const response = await api.post(`/admin/users/${userId}/brands/${brandId}/descriptors/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  uploadCompetitors: async (userId: number, brandId: number, formData: FormData) => {
    const response = await api.post(`/admin/users/${userId}/brands/${brandId}/competitors/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  // Tenant management
  listTenants: async () => {
    const response = await api.get('/tenants/');
    return response.data;
  },

  createTenant: async (data: {
    tenant_name: string;
    subdomain?: string;
    logo_url?: string;
    primary_color?: string;
    secondary_color?: string;
    custom_domain?: string;
  }) => {
    const response = await api.post('/tenants/', data);
    return response.data;
  },

  updateTenant: async (tenantId: number, data: {
    tenant_name?: string;
    subdomain?: string;
    logo_url?: string;
    primary_color?: string;
    secondary_color?: string;
    custom_domain?: string;
  }) => {
    const response = await api.put(`/tenants/${tenantId}`, data);
    return response.data;
  },

  deleteTenant: async (tenantId: number) => {
    const response = await api.delete(`/tenants/${tenantId}`);
    return response.data;
  },
};

// Brand Management API functions
export const brandsAPI = {
  // Get all brands for current user
  getAllBrands: async () => {
    const response = await api.get('/brands/');
    return response.data;
  },

  // Get a specific brand by ID
  getBrand: async (brandId: number) => {
    const response = await api.get(`/brands/${brandId}`);
    return response.data;
  },

  // Transfer brand to another user
  transferBrand: async (brandId: number, email: string) => {
    const response = await api.post(`/brands/${brandId}/transfer`, { email });
    return response.data;
  },

  // Remove brand (transfer to admin)
  removeBrand: async (brandId: number) => {
    const response = await api.post(`/brands/${brandId}/remove`);
    return response.data;
  },

  // Delete brand (admin only)
  deleteBrand: async (brandId: number) => {
    const response = await api.delete(`/brands/${brandId}`);
    return response.data;
  },

  // Get users brand is shared with
  getBrandShares: async (brandId: number) => {
    const response = await api.get(`/brands/${brandId}/shares`);
    return response.data;
  },
};

// LLM Provider Configuration API functions (admin)
export const llmProvidersAPI = {
  // Get all LLM providers
  getProviders: async () => {
    const response = await api.get('/admin/llm-providers');
    return response.data;
  },

  // Create new LLM provider
  createProvider: async (data: {
    provider_key: string;
    display_name: string;
    api_type: string;
    api_endpoint?: string;
    model_name: string;
    env_var_name?: string;
    api_version?: string;
    bing_connection_name?: string;
    color?: string;
    sort_order?: number;
    is_enabled?: boolean;
    use_for_analysis?: boolean;
    supports_web_search?: boolean;
  }) => {
    const response = await api.post('/admin/llm-providers', data);
    return response.data;
  },

  // Update LLM provider
  updateProvider: async (providerId: number, data: {
    display_name?: string;
    api_type?: string;
    api_endpoint?: string;
    model_name?: string;
    env_var_name?: string;
    api_version?: string;
    bing_connection_name?: string | null;
    color?: string;
    sort_order?: number;
    is_enabled?: boolean;
    use_for_analysis?: boolean;
    supports_web_search?: boolean;
  }) => {
    const response = await api.put(`/admin/llm-providers/${providerId}`, data);
    return response.data;
  },

  // Delete LLM provider
  deleteProvider: async (providerId: number) => {
    const response = await api.delete(`/admin/llm-providers/${providerId}`);
    return response.data;
  },

  // Test LLM provider connection
  testProvider: async (providerId: number) => {
    const response = await api.post(`/admin/llm-providers/${providerId}/test`);
    return response.data;
  },
};

// Site Configuration API
export const siteConfigAPI = {
  // Get current site configuration
  getConfig: async () => {
    const response = await api.get('/admin/site-config');
    return response.data;
  },

  // Update site configuration
  updateConfig: async (data: {
    site_url?: string;
    admin_email?: string;
    site_name?: string;
  }) => {
    const response = await api.put('/admin/site-config', data);
    return response.data;
  },
};

export default api;

import React, { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import { authAPI } from '../services/api';

interface User {
  id: number;
  email: string;
  full_name?: string;
  organization?: string;
  is_admin: boolean;
  is_active: boolean;
  is_invited: boolean;
  oauth_provider?: string | null;
  created_at: string;
  updated_at: string;
  gemini_api_key?: string;
  openai_api_key?: string;
  anthropic_api_key?: string;
  perplexity_api_key?: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  googleLogin: (googleToken: string) => Promise<void>;
  microsoftLogin: (microsoftToken: string) => Promise<void>;
  register: (email: string, password: string, full_name?: string, organization?: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  isAuthenticated: boolean;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Load user from localStorage on mount
  useEffect(() => {
    const loadUser = async () => {
      const storedUser = authAPI.getStoredUser();
      const token = authAPI.getStoredToken();

      if (storedUser && token) {
        // Use stored user immediately to avoid delay
        setUser(storedUser);

        // Refresh user data from server in background to catch any server-side changes
        // (e.g., admin changing user status, profile updates from another session)
        try {
          const freshUser = await authAPI.getCurrentUser();
          setUser(freshUser);
        } catch (error) {
          console.error('Failed to refresh user:', error);
          // If refresh fails, clear auth (token likely expired)
          authAPI.logout();
          setUser(null);
        }
      }

      setLoading(false);
    };

    loadUser();
  }, []);

  const login = async (email: string, password: string) => {
    try {
      const userData = await authAPI.login(email, password);
      setUser(userData);
    } catch (error) {
      console.error('Login failed:', error);
      throw error;
    }
  };

  const googleLogin = async (googleToken: string) => {
    try {
      const userData = await authAPI.googleLogin(googleToken);
      setUser(userData);
    } catch (error) {
      console.error('Google login failed:', error);
      throw error;
    }
  };

  const microsoftLogin = async (microsoftToken: string) => {
    try {
      const userData = await authAPI.microsoftLogin(microsoftToken);
      setUser(userData);
    } catch (error) {
      console.error('Microsoft login failed:', error);
      throw error;
    }
  };

  const register = async (email: string, password: string, full_name?: string, organization?: string) => {
    try {
      await authAPI.register(email, password, full_name, organization);
      // Note: User is not automatically logged in after registration
      // They need admin approval first
    } catch (error) {
      console.error('Registration failed:', error);
      throw error;
    }
  };

  const logout = () => {
    authAPI.logout();
    setUser(null);
  };

  const refreshUser = async () => {
    try {
      const freshUser = await authAPI.getCurrentUser();
      setUser(freshUser);
    } catch (error) {
      console.error('Failed to refresh user:', error);
      throw error;
    }
  };

  const value: AuthContextType = {
    user,
    loading,
    login,
    googleLogin,
    microsoftLogin,
    register,
    logout,
    refreshUser,
    isAuthenticated: !!user,
    isAdmin: user?.is_admin || false,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

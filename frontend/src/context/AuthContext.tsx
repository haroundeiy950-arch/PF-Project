import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, tokenStore, userStore } from "../api";
import type { User } from "../types";

interface AuthContextValue {
  user: User | null;
  token: string | null;
  ready: boolean;
  busy: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => userStore.get());
  const [token, setToken] = useState<string | null>(() => tokenStore.get());
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  const clearSession = useCallback(() => {
    tokenStore.clear();
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    const handler = () => clearSession();
    window.addEventListener("sentinel:unauthorized", handler);
    return () => window.removeEventListener("sentinel:unauthorized", handler);
  }, [clearSession]);

  useEffect(() => {
    let active = true;
    if (!tokenStore.get()) {
      setReady(true);
      return;
    }
    api.auth
      .me()
      .then((response) => {
        if (!active) return;
        const permissions = (response as User & { permissions?: string[] }).permissions;
        const nextUser: User = {
          ...response,
          role: {
            ...response.role,
            permissions: permissions ?? response.role?.permissions ?? [],
          },
        };
        setUser(nextUser);
        userStore.set(nextUser);
      })
      .catch(() => {
        if (active) clearSession();
      })
      .finally(() => {
        if (active) setReady(true);
      });
    return () => {
      active = false;
    };
  }, [clearSession]);

  const login = useCallback(async (username: string, password: string) => {
    setBusy(true);
    try {
      const response = await api.auth.login(username.trim().toLowerCase(), password);
      tokenStore.set(response.access_token);
      userStore.set(response.user);
      setToken(response.access_token);
      setUser(response.user);
    } finally {
      setBusy(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      if (tokenStore.get()) await api.auth.logout();
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const refresh = useCallback(async () => {
    try {
      const response = await api.auth.me();
      const permissions = (response as User & { permissions?: string[] }).permissions;
      const nextUser: User = {
        ...response,
        role: {
          ...response.role,
          permissions: permissions ?? response.role?.permissions ?? [],
        },
      };
      setUser(nextUser);
      userStore.set(nextUser);
    } catch {
      clearSession();
    }
  }, [clearSession]);

  const can = useCallback(
    (permission: string) => {
      const permissions = user?.role?.permissions ?? [];
      return permissions.includes(permission) || permissions.includes("*");
    },
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ user, token, ready, busy, login, logout, refresh, can }),
    [user, token, ready, busy, login, logout, refresh, can],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

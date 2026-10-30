import React, { createContext, useContext, useState } from "react";

export type Role = "analyst" | "admin";

export interface User {
  username: string;
  role: Role;
}

interface AuthContextType {
  user: User | null;
  login: (username: string, role: Role, token?: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  login: () => {},
  logout: () => {},
  isAuthenticated: false,
});

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(() => {
    const savedUser = localStorage.getItem("fraudengine_user");
    if (savedUser) {
      try {
        return JSON.parse(savedUser);
      } catch (e) {
        return null;
      }
    }
    // Default logged in as demo analyst for immediate interactive evaluation
    return { username: "analyst", role: "analyst" };
  });

  const login = (username: string, role: Role, token?: string) => {
    const newUser = { username, role };
    setUser(newUser);
    localStorage.setItem("fraudengine_user", JSON.stringify(newUser));
    if (token) {
      localStorage.setItem("fraudengine_token", token);
    }
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem("fraudengine_user");
    localStorage.removeItem("fraudengine_token");
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        login,
        logout,
        isAuthenticated: !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);

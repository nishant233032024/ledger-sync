"use client";

import { useEffect, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { clearAccessToken, getAccessToken, SESSION_EXPIRED_EVENT } from "@/lib/api";
import { LedgerDashboard, LoginPanel } from "@/components/ledger-dashboard";

export default function HomePage() {
  const [authenticated, setAuthenticated] = useState(false);
  const [ready, setReady] = useState(false);
  const client = useQueryClient();

  useEffect(() => {
    setAuthenticated(Boolean(getAccessToken()));
    setReady(true);
    const expired = () => { client.clear(); setAuthenticated(false); };
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  }, [client]);

  if (!ready) return <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">Loading LedgerSync...</div>;
  if (!authenticated) {
    return <LoginPanel onLogin={() => setAuthenticated(true)} />;
  }
  return <LedgerDashboard onLogout={() => { clearAccessToken(); client.clear(); setAuthenticated(false); }} />;
}

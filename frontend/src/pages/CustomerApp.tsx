import React, { useState, useEffect } from "react";
import {
  AlertCircle,
  ArrowDownLeft,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Copy,
  DollarSign,
  HelpCircle,
  Lock,
  LogOut,
  RefreshCw,
  Send,
  Shield,
  ShieldAlert,
  Smartphone,
  User,
  Users,
  Wifi,
  XCircle,
  Zap,
} from "lucide-react";
import { cn } from "../lib/utils";

interface RecipientItem {
  account_id: string;
  display_name: string;
  is_bot?: boolean;
}

interface ParticipantMe {
  account_id: string;
  display_name: string;
  balance: number;
  device_id: string;
  network_prefix: string;
  masked_ip: string;
  role_card?: {
    role_id: string;
    title: string;
    badge: string;
    instructions: string;
    suggested_target?: string;
    suggested_amount?: number;
    network_hint?: string;
  };
  consent_timestamp?: number;
}

interface TransferItem {
  txn_id: string;
  sender_id: string;
  sender_name?: string;
  receiver_id: string;
  receiver_name?: string;
  amount: number;
  note?: string;
  status: "PROCESSED" | "HELD" | "DECLINED";
  timestamp: number;
}

interface SavedAccount {
  account_id: string;
  display_name: string;
  session_token: string;
  room_code: string;
}

export const CustomerApp: React.FC = () => {
  // Room & Onboarding State
  const [roomCode, setRoomCode] = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("room") || localStorage.getItem("sandbox_room_code") || "";
  });
  const [joinToken, setJoinToken] = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("token") || localStorage.getItem("sandbox_join_token") || "";
  });
  const [displayName, setDisplayName] = useState<string>(() => {
    return localStorage.getItem("sandbox_display_name") || "";
  });
  const [consentAccepted, setConsentAccepted] = useState<boolean>(false);
  const [isJoined, setIsJoined] = useState<boolean>(false);
  const [isJoining, setIsJoining] = useState<boolean>(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  // Participant Account State
  const [currentAccount, setCurrentAccount] = useState<ParticipantMe | null>(null);
  const [sessionToken, setSessionToken] = useState<string>(() => {
    return localStorage.getItem("sandbox_session_token") || "";
  });
  const [recipients, setRecipients] = useState<RecipientItem[]>([]);
  const [transfers, setTransfers] = useState<TransferItem[]>([]);
  const [isOfflineMode, setIsOfflineMode] = useState<boolean>(false);

  // Multi-Account Switcher on 1 Device (Item 12)
  const [savedAccounts, setSavedAccounts] = useState<SavedAccount[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("sandbox_saved_accounts") || "[]");
    } catch {
      return [];
    }
  });
  const [showAccountSwitcher, setShowAccountSwitcher] = useState<boolean>(false);

  // Transfer Form State
  const [recipientId, setRecipientId] = useState<string>("");
  const [amount, setAmount] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [notice, setNotice] = useState<{
    type: "success" | "held" | "declined" | "error";
    title: string;
    message: string;
    amount?: number;
  } | null>(null);

  // Active view tab in mobile app
  const [activeTab, setActiveTab] = useState<"send" | "history">("send");
  const [showRoleDetails, setShowRoleDetails] = useState<boolean>(true);

  // Generate / retrieve persistent device ID (Item 12)
  const getDeviceId = () => {
    let devId = localStorage.getItem("sandbox_device_id");
    if (!devId) {
      devId = `DEV_${Math.random().toString(36).substring(2, 8).toUpperCase()}`;
      localStorage.setItem("sandbox_device_id", devId);
    }
    return devId;
  };

  // Coarse fingerprint (Item 12)
  const getCoarseFingerprint = () => {
    const str = `${navigator.userAgent}|${navigator.language}|${screen.width}x${screen.height}|${Intl.DateTimeFormat().resolvedOptions().timeZone}`;
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = (hash << 5) - hash + str.charCodeAt(i);
      hash |= 0;
    }
    return `FP_${Math.abs(hash).toString(16).toUpperCase()}`;
  };

  // Check saved session on mount
  useEffect(() => {
    const savedAccount = localStorage.getItem("sandbox_account");
    const savedRoom = localStorage.getItem("sandbox_room_code");
    const savedToken = localStorage.getItem("sandbox_session_token");
    if (savedAccount && savedRoom && savedToken) {
      try {
        const parsed = JSON.parse(savedAccount);
        setCurrentAccount(parsed);
        setRoomCode(savedRoom);
        setSessionToken(savedToken);
        setIsJoined(true);
      } catch (e) {}
    }
  }, []);

  // Poll participant-specific state and recipients through the gateway (Item 10)
  useEffect(() => {
    if (!isJoined || !roomCode || !sessionToken) return;

    const fetchState = async () => {
      try {
        // 1. Fetch own account state
        const meRes = await fetch(`/api/v1/live/rooms/${roomCode.toUpperCase()}/me?token=${sessionToken}`, {
          headers: { Authorization: `Bearer ${sessionToken}` },
        });

        if (meRes.ok) {
          const meData = await meRes.json();
          if (meData.participant) {
            setCurrentAccount(meData.participant);
            localStorage.setItem("sandbox_account", JSON.stringify(meData.participant));
          }
          if (meData.transfers) {
            setTransfers(meData.transfers);
          }
        } else if (meRes.status === 403 || meRes.status === 404) {
          // Token expired or room wiped
          setIsJoined(false);
          setCurrentAccount(null);
          localStorage.removeItem("sandbox_account");
          localStorage.removeItem("sandbox_session_token");
          setJoinError("Room session expired or room was wiped with zero residue.");
        }

        // 2. Fetch recipients (display names only, never balances)
        const recRes = await fetch(`/api/v1/live/rooms/${roomCode.toUpperCase()}/recipients`);
        if (recRes.ok) {
          const recData = await recRes.json();
          setRecipients(recData || []);
        }

        // 3. Health check for offline mode warning
        const healthRes = await fetch("/api/v1/demo/health");
        if (healthRes.ok) {
          const h = await healthRes.json();
          setIsOfflineMode(!h.redpanda?.healthy || !!h.offline_warning);
        }
      } catch (e) {}
    };

    fetchState();
    const interval = setInterval(fetchState, 3000);
    return () => clearInterval(interval);
  }, [isJoined, roomCode, sessionToken]);

  // Handle Join Room (Item 13)
  const handleJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roomCode.trim() || !displayName.trim()) {
      setJoinError("Please enter both Room Code and your Display Name.");
      return;
    }
    if (!consentAccepted) {
      setJoinError("You must tick the consent checkbox to participate in the simulation.");
      return;
    }

    setIsJoining(true);
    setJoinError(null);

    try {
      const devId = getDeviceId();
      const fp = getCoarseFingerprint();
      const res = await fetch(`/api/v1/live/rooms/${roomCode.trim().toUpperCase()}/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: displayName.trim(),
          device_id: devId,
          coarse_fingerprint: fp,
          consent_accepted: true,
          join_token: joinToken.trim() || undefined,
          network_label: "Campus-WiFi",
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to join room");
      }

      const data = await res.json();
      setCurrentAccount(data.participant);
      setSessionToken(data.session_token);
      setIsJoined(true);

      const saved: SavedAccount = {
        account_id: data.participant.account_id,
        display_name: data.participant.display_name,
        session_token: data.session_token,
        room_code: roomCode.trim().toUpperCase(),
      };

      const updatedSaved = [...savedAccounts.filter((a) => a.account_id !== saved.account_id), saved];
      setSavedAccounts(updatedSaved);
      localStorage.setItem("sandbox_saved_accounts", JSON.stringify(updatedSaved));

      localStorage.setItem("sandbox_room_code", roomCode.trim().toUpperCase());
      localStorage.setItem("sandbox_display_name", displayName.trim());
      localStorage.setItem("sandbox_session_token", data.session_token);
      localStorage.setItem("sandbox_account", JSON.stringify(data.participant));
    } catch (err: any) {
      setJoinError(err.message || "Failed to join sandbox room. Ensure server is running.");
    } finally {
      setIsJoining(false);
    }
  };

  // Switch to another account on the same device (Item 12)
  const handleSwitchAccount = (account: SavedAccount) => {
    setRoomCode(account.room_code);
    setDisplayName(account.display_name);
    setSessionToken(account.session_token);
    setShowAccountSwitcher(false);
    // Reload state
    localStorage.setItem("sandbox_room_code", account.room_code);
    localStorage.setItem("sandbox_session_token", account.session_token);
    // Fast fetch me
    fetch(`/api/v1/live/rooms/${account.room_code}/me?token=${account.session_token}`, {
      headers: { Authorization: `Bearer ${account.session_token}` },
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.participant) {
          setCurrentAccount(d.participant);
          localStorage.setItem("sandbox_account", JSON.stringify(d.participant));
          setIsJoined(true);
        }
      })
      .catch(() => {});
  };

  // Handle Leave / Logout
  const handleLeave = () => {
    localStorage.removeItem("sandbox_account");
    localStorage.removeItem("sandbox_session_token");
    setIsJoined(false);
    setCurrentAccount(null);
  };

  // Quick fill from Role Card
  const applyRoleSuggestion = () => {
    if (!currentAccount?.role_card) return;
    const { suggested_target, suggested_amount } = currentAccount.role_card;
    if (suggested_target) {
      const target = recipients.find(
        (p) =>
          p.account_id === suggested_target ||
          p.display_name.toUpperCase().includes(suggested_target.toUpperCase())
      );
      if (target) {
        setRecipientId(target.account_id);
      } else {
        const fallback = recipients.find((p) => p.account_id !== currentAccount.account_id);
        if (fallback) setRecipientId(fallback.account_id);
      }
    }
    if (suggested_amount) {
      setAmount(String(suggested_amount));
    }
  };

  // Handle Transfer Submission (Item 10 & 14)
  const handleTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentAccount || !recipientId) return;

    const numAmount = Number(amount);
    if (isNaN(numAmount) || numAmount <= 0) {
      setNotice({
        type: "error",
        title: "Invalid Amount",
        message: "Please enter a transfer amount greater than ₹0.",
      });
      return;
    }

    if (numAmount > currentAccount.balance) {
      setNotice({
        type: "error",
        title: "Insufficient Balance",
        message: `Your balance is ₹${currentAccount.balance.toLocaleString()}. You cannot transfer ₹${numAmount.toLocaleString()}.`,
      });
      return;
    }

    setIsSubmitting(true);
    setNotice(null);

    const idempotencyKey = `IDEMP_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;

    try {
      const res = await fetch("/api/v1/live/transfer", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${sessionToken}`,
        },
        body: JSON.stringify({
          room_code: roomCode.toUpperCase(),
          sender_id: currentAccount.account_id,
          receiver_id: recipientId,
          amount: numAmount,
          note: note.trim(),
          session_token: sessionToken,
          idempotency_key: idempotencyKey,
          device_id: currentAccount.device_id,
        }),
      });

      const data = await res.json();

      if (data.status === "PROCESSED") {
        setNotice({
          type: "success",
          title: "Payment Processed",
          message: data.customer_message || "Transfer completed successfully.",
          amount: numAmount,
        });
        if (data.sender_balance !== undefined) {
          setCurrentAccount((prev) => (prev ? { ...prev, balance: data.sender_balance } : null));
        }
        setAmount("");
        setNote("");
      } else if (data.status === "HELD") {
        setNotice({
          type: "held",
          title: "Payment Under Review",
          message:
            data.customer_message ||
            "Transfer held for routine verification by bank compliance systems.",
          amount: numAmount,
        });
      } else {
        setNotice({
          type: "declined",
          title: "Payment Declined",
          message: data.customer_message || "Transfer was declined by bank risk controls.",
          amount: numAmount,
        });
      }

      // Add to local transfers list
      const recipientObj = recipients.find((p) => p.account_id === recipientId);
      const newTx: TransferItem = {
        txn_id: data.txn_id || `TXN_${Date.now()}`,
        sender_id: currentAccount.account_id,
        sender_name: currentAccount.display_name,
        receiver_id: recipientId,
        receiver_name: recipientObj?.display_name || recipientId,
        amount: numAmount,
        note: note.trim(),
        status: data.status,
        timestamp: Date.now(),
      };
      setTransfers((prev) => [newTx, ...prev]);
    } catch (err: any) {
      setNotice({
        type: "error",
        title: "Network Error",
        message: err.message || "Could not reach bank server. Please verify connection.",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const otherRecipients = recipients.filter(
    (p) => p.account_id !== currentAccount?.account_id
  );

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col font-sans max-w-md mx-auto shadow-2xl relative border-x border-slate-800">
      {/* ─────────────────────────────────────────────────────────────
          PERSISTENT TOP SIMULATION BANNER & OFFLINE WARNING (Item 1)
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-amber-500 text-slate-950 px-3 py-1.5 text-center text-[11px] font-bold tracking-wide uppercase flex items-center justify-center gap-1.5 shadow-sm sticky top-0 z-50">
        <Lock className="w-3.5 h-3.5" />
        <span>Simulation: Virtual Money Only • No Real Bank Connections</span>
      </div>

      {isOfflineMode && (
        <div className="bg-red-600 text-white px-3 py-1.5 text-center text-[10px] font-mono font-bold uppercase tracking-wider flex items-center justify-center gap-1.5 sticky top-7 z-40">
          <span className="w-2 h-2 rounded-full bg-white animate-ping" />
          <span>NOT KAFKA: in-process simulation</span>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          VIEW 1: ONBOARDING / JOIN ROOM (Item 13)
      ───────────────────────────────────────────────────────────── */}
      {!isJoined ? (
        <div className="flex-1 p-6 flex flex-col justify-center space-y-5">
          <div className="text-center space-y-1.5">
            <div className="w-14 h-14 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center mx-auto text-indigo-400 shadow-lg shadow-indigo-600/20">
              <Shield className="w-7 h-7" />
            </div>
            <h1 className="text-2xl font-black tracking-tight text-white">Live Sandbox Bank</h1>
            <p className="text-xs text-slate-400">
              Audience Multi-Device Fraud Ring Demonstration
            </p>
          </div>

          <form onSubmit={handleJoin} className="bg-slate-850 p-5 rounded-2xl border border-slate-800 space-y-4 shadow-xl">
            {joinError && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{joinError}</span>
              </div>
            )}

            <div>
              <label className="text-xs font-semibold text-slate-300">Room Code</label>
              <input
                type="text"
                value={roomCode}
                onChange={(e) => setRoomCode(e.target.value.toUpperCase())}
                placeholder="e.g. MULE42"
                maxLength={10}
                required
                className="w-full mt-1.5 p-2.5 rounded-xl bg-slate-900 border border-slate-700 font-mono text-center text-lg tracking-widest font-bold text-indigo-400 uppercase focus:outline-none focus:border-indigo-500 transition-all"
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-300">Your Display Name</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="e.g. Member B or Student"
                maxLength={20}
                required
                className="w-full mt-1.5 p-2.5 rounded-xl bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none focus:border-indigo-500 transition-all"
              />
              <p className="text-[10px] text-slate-500 mt-1">
                Display name only. Never enter real account or personal details.
              </p>
            </div>

            {/* Mandatory Participant Consent Box (Item 13) */}
            <div className="p-3 rounded-xl bg-slate-900/90 border border-slate-800 space-y-2">
              <label className="flex items-start gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={consentAccepted}
                  onChange={(e) => setConsentAccepted(e.target.checked)}
                  className="mt-0.5 rounded border-slate-700 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-[11px] text-slate-300 leading-snug">
                  <strong className="text-white">Consent Notice:</strong> I understand that to demonstrate real-time fraud detection, this demo captures my random device ID, browser type, and masked network prefix (/24). All session data is immediately and permanently deleted when the room is wiped.
                </span>
              </label>
            </div>

            <button
              type="submit"
              disabled={isJoining || !consentAccepted}
              className="w-full py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 font-bold text-sm text-white shadow-lg shadow-indigo-600/30 transition-all disabled:opacity-40 flex items-center justify-center gap-2"
            >
              {isJoining ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Joining Sandbox...</span>
                </>
              ) : (
                <>
                  <Smartphone className="w-4 h-4" />
                  <span>Enter Live Sandbox</span>
                </>
              )}
            </button>
          </form>

          {/* Account Switcher on Join Screen (Item 12) */}
          {savedAccounts.length > 0 && (
            <div className="p-3 rounded-xl bg-slate-850 border border-slate-800 space-y-2">
              <span className="text-[11px] font-bold text-slate-400 block">Existing Accounts on this Phone:</span>
              <div className="space-y-1">
                {savedAccounts.map((acc, i) => (
                  <button
                    key={i}
                    onClick={() => handleSwitchAccount(acc)}
                    className="w-full text-left p-2 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-750 text-xs flex items-center justify-between transition-all"
                  >
                    <span className="font-semibold text-slate-200">{acc.display_name}</span>
                    <span className="font-mono text-[10px] text-indigo-400">Room {acc.room_code}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="text-center text-[10px] text-slate-500 space-y-1">
            <p>Every participant starts with ₹10,000 virtual balance.</p>
            <p>Device ID: <span className="font-mono text-slate-400">{getDeviceId()}</span></p>
          </div>
        </div>
      ) : (
        /* ─────────────────────────────────────────────────────────────
            VIEW 2: ACTIVE BANKING INTERFACE (Item 10 & 12)
        ───────────────────────────────────────────────────────────── */
        <div className="flex-1 flex flex-col justify-between">
          <div>
            {/* Header Strip with Account Switcher */}
            <div className="p-3 border-b border-slate-800 flex items-center justify-between bg-slate-900/60 backdrop-blur-md">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                  <User className="w-4 h-4" />
                </div>
                <div>
                  <div className="flex items-center gap-1.5">
                    <h3 className="font-bold text-sm text-white leading-tight">
                      {currentAccount?.display_name}
                    </h3>
                    <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      Room {roomCode}
                    </span>
                  </div>
                  <p className="text-[10px] font-mono text-slate-400">
                    {currentAccount?.account_id}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-1.5">
                {/* Account Switcher Button (Item 12) */}
                <button
                  onClick={() => setShowAccountSwitcher(!showAccountSwitcher)}
                  className="px-2 py-1 rounded-lg text-[10px] font-mono bg-slate-800 hover:bg-slate-700 text-indigo-400 border border-slate-700 transition-all"
                  title="Switch or add accounts on this phone to test shared device links"
                >
                  Switch Phone User
                </button>
                <button
                  onClick={handleLeave}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition-all"
                  title="Leave Sandbox Room"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Account Switcher Dropdown (Item 12) */}
            {showAccountSwitcher && (
              <div className="p-3 bg-slate-850 border-b border-slate-800 space-y-2 text-xs">
                <div className="flex items-center justify-between text-slate-300 font-bold">
                  <span>Accounts on this Phone (Shared Device):</span>
                  <button onClick={() => setShowAccountSwitcher(false)} className="text-slate-400">✕</button>
                </div>
                <div className="space-y-1">
                  {savedAccounts.map((acc, i) => (
                    <button
                      key={i}
                      onClick={() => handleSwitchAccount(acc)}
                      className={cn(
                        "w-full text-left p-2 rounded-lg border text-xs flex items-center justify-between transition-all",
                        acc.account_id === currentAccount?.account_id
                          ? "bg-indigo-600/20 border-indigo-500 text-indigo-300 font-bold"
                          : "bg-slate-900 border-slate-800 hover:bg-slate-800 text-slate-300"
                      )}
                    >
                      <span>{acc.display_name}</span>
                      <span className="font-mono text-[10px]">
                        {acc.account_id === currentAccount?.account_id ? "Active" : "Switch"}
                      </span>
                    </button>
                  ))}
                  <button
                    onClick={() => {
                      setShowAccountSwitcher(false);
                      setIsJoined(false);
                      setDisplayName("");
                    }}
                    className="w-full py-1.5 text-center text-[11px] font-bold text-indigo-400 hover:underline"
                  >
                    + Join Another Account on this Phone (Shared Device Link)
                  </button>
                </div>
              </div>
            )}

            {/* Virtual Balance Card */}
            <div className="p-4">
              <div className="p-4 rounded-2xl bg-gradient-to-br from-indigo-900/40 via-slate-850 to-slate-900 border border-indigo-500/20 shadow-xl space-y-2 relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-10">
                  <Shield className="w-24 h-24 text-indigo-400" />
                </div>
                <div className="flex items-center justify-between text-xs text-indigo-300 font-medium">
                  <span>Virtual Balance</span>
                  <span className="flex items-center gap-1 text-[10px] font-mono text-emerald-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Live Ledger
                  </span>
                </div>
                <h2 className="text-3xl font-black tracking-tight text-white font-mono">
                  ₹{(currentAccount?.balance || 0).toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </h2>
                <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-1 border-t border-slate-800/60">
                  <span>Masked IP: {currentAccount?.masked_ip || "103.45.67.x"}</span>
                  <span>Device: {currentAccount?.device_id || "DEV_PHONE"}</span>
                </div>
              </div>
            </div>

            {/* Role Card Accordion */}
            {currentAccount?.role_card && (
              <div className="px-4 pb-2">
                <div className="p-3.5 rounded-xl border border-amber-500/30 bg-amber-500/5 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Zap className="w-4 h-4 text-amber-400 animate-pulse" />
                      <span className="text-xs font-bold text-amber-400 uppercase tracking-wide">
                        Role: {currentAccount.role_card.badge}
                      </span>
                    </div>
                    <button
                      onClick={() => setShowRoleDetails(!showRoleDetails)}
                      className="text-[10px] text-amber-300 underline font-semibold"
                    >
                      {showRoleDetails ? "Hide" : "View Steps"}
                    </button>
                  </div>

                  {showRoleDetails && (
                    <div className="space-y-2 pt-1 border-t border-amber-500/10 text-xs">
                      <p className="text-slate-200 leading-relaxed">
                        {currentAccount.role_card.instructions}
                      </p>
                      {currentAccount.role_card.network_hint && (
                        <p className="text-[11px] font-mono text-amber-300/80">
                          Network: {currentAccount.role_card.network_hint}
                        </p>
                      )}
                      <button
                        onClick={applyRoleSuggestion}
                        className="py-1 px-2.5 rounded-lg bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[11px] font-bold hover:bg-amber-500/30 transition-all flex items-center gap-1"
                      >
                        <span>Autofill Role Form</span>
                        <span>(₹{currentAccount.role_card.suggested_amount || 0})</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Notification Banner */}
            {notice && (
              <div className="px-4 pb-2">
                <div
                  className={cn(
                    "p-3 rounded-xl border flex items-start gap-2.5 text-xs shadow-md",
                    notice.type === "success" && "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
                    notice.type === "held" && "bg-amber-500/10 border-amber-500/30 text-amber-300",
                    notice.type === "declined" && "bg-rose-500/10 border-rose-500/30 text-rose-300",
                    notice.type === "error" && "bg-red-500/10 border-red-500/30 text-red-300"
                  )}
                >
                  {notice.type === "success" && <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400 mt-0.5" />}
                  {notice.type === "held" && <Clock className="w-4 h-4 shrink-0 text-amber-400 mt-0.5" />}
                  {notice.type === "declined" && <XCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />}
                  {notice.type === "error" && <AlertCircle className="w-4 h-4 shrink-0 text-red-400 mt-0.5" />}
                  <div>
                    <h4 className="font-bold">{notice.title}</h4>
                    <p className="opacity-90 leading-snug">{notice.message}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Tabs Switcher */}
            <div className="px-4 pt-1">
              <div className="grid grid-cols-2 p-1 rounded-xl bg-slate-850 border border-slate-800 text-xs font-semibold">
                <button
                  onClick={() => setActiveTab("send")}
                  className={cn(
                    "py-2 rounded-lg transition-all",
                    activeTab === "send" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"
                  )}
                >
                  Send Payment
                </button>
                <button
                  onClick={() => setActiveTab("history")}
                  className={cn(
                    "py-2 rounded-lg transition-all",
                    activeTab === "history" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"
                  )}
                >
                  Activity ({transfers.length})
                </button>
              </div>
            </div>

            {/* TAB CONTENT: SEND */}
            {activeTab === "send" && (
              <form onSubmit={handleTransfer} className="p-4 space-y-3.5">
                <div>
                  <label className="text-xs font-semibold text-slate-300">Recipient</label>
                  <select
                    value={recipientId}
                    onChange={(e) => setRecipientId(e.target.value)}
                    required
                    className="w-full mt-1.5 p-3 rounded-xl bg-slate-850 border border-slate-750 text-sm text-white focus:outline-none focus:border-indigo-500 transition-all font-mono"
                  >
                    <option value="">Select a participant or merchant...</option>
                    {otherRecipients.map((p) => (
                      <option key={p.account_id} value={p.account_id}>
                        {p.display_name} {p.is_bot ? "(Merchant/Bot)" : ""}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-xs font-semibold text-slate-300">Transfer Amount (₹)</label>
                  <div className="relative mt-1.5">
                    <span className="absolute left-3.5 top-3 text-slate-400 font-mono text-base font-bold">₹</span>
                    <input
                      type="number"
                      step="any"
                      min="1"
                      max="50000"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder="0.00"
                      required
                      className="w-full pl-8 p-3 rounded-xl bg-slate-850 border border-slate-750 font-mono text-lg font-bold text-white focus:outline-none focus:border-indigo-500 transition-all"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs font-semibold text-slate-300">Transfer Note (Optional)</label>
                  <input
                    type="text"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="e.g. Lunch split or invoice settlement"
                    maxLength={50}
                    className="w-full mt-1.5 p-2.5 rounded-xl bg-slate-850 border border-slate-750 text-xs text-white focus:outline-none focus:border-indigo-500 transition-all"
                  />
                </div>

                <button
                  type="submit"
                  disabled={isSubmitting || !recipientId || !amount}
                  className="w-full py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 font-bold text-sm text-white shadow-lg shadow-indigo-600/30 transition-all disabled:opacity-40 flex items-center justify-center gap-2"
                >
                  {isSubmitting ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Scoring & Processing...</span>
                    </>
                  ) : (
                    <>
                      <Send className="w-4 h-4" />
                      <span>Send Virtual Funds</span>
                    </>
                  )}
                </button>
              </form>
            )}

            {/* TAB CONTENT: HISTORY */}
            {activeTab === "history" && (
              <div className="p-4 space-y-2">
                {transfers.length === 0 ? (
                  <p className="text-center py-12 text-xs text-slate-500 italic">
                    No transfers executed yet in this room session.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {transfers.map((tx, idx) => {
                      const isOutgoing = tx.sender_id === currentAccount?.account_id;
                      return (
                        <div
                          key={idx}
                          className="p-3 rounded-xl bg-slate-850 border border-slate-800 flex items-center justify-between text-xs"
                        >
                          <div className="flex items-center gap-2.5">
                            <div
                              className={cn(
                                "w-7 h-7 rounded-lg flex items-center justify-center",
                                isOutgoing ? "bg-rose-500/10 text-rose-400" : "bg-emerald-500/10 text-emerald-400"
                              )}
                            >
                              {isOutgoing ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownLeft className="w-4 h-4" />}
                            </div>
                            <div>
                              <p className="font-bold text-white">
                                {isOutgoing ? `To: ${tx.receiver_name || tx.receiver_id}` : `From: ${tx.sender_name || tx.sender_id}`}
                              </p>
                              <p className="text-[10px] text-slate-400 font-mono">
                                {new Date(tx.timestamp).toLocaleTimeString()}
                              </p>
                            </div>
                          </div>
                          <div className="text-right">
                            <p className={cn("font-mono font-bold text-sm", isOutgoing ? "text-rose-400" : "text-emerald-400")}>
                              {isOutgoing ? "-" : "+"}₹{tx.amount.toLocaleString()}
                            </p>
                            <span
                              className={cn(
                                "text-[9px] font-mono px-1.5 py-0.2 rounded uppercase",
                                tx.status === "PROCESSED" && "bg-emerald-500/10 text-emerald-400",
                                tx.status === "HELD" && "bg-amber-500/10 text-amber-400",
                                tx.status === "DECLINED" && "bg-rose-500/10 text-rose-400"
                              )}
                            >
                              {tx.status}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Footer note */}
          <div className="p-3 text-center text-[10px] text-slate-500 border-t border-slate-800">
            Participant surface isolated via secure gateway token.
          </div>
        </div>
      )}
    </div>
  );
};

export default CustomerApp;

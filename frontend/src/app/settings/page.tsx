"use client";

import { useState, useEffect, useCallback } from "react";
import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Key, Plus, Trash2, Eye, EyeOff, CheckCircle, XCircle, Loader2, ArrowLeft } from "lucide-react";
import { Button } from "@/src/components/ui/button";

interface APIKey {
  id: string;
  provider: string;
  model_name: string;
  base_url: string;
  api_key: string;
  is_active: boolean;
}

const PROVIDERS = [
  { value: "openrouter", label: "OpenRouter", defaultModel: "google/gemini-2.5-flash", defaultUrl: "https://openrouter.ai/api/v1" },
  { value: "gemini", label: "Google Gemini", defaultModel: "gemini-2.5-flash", defaultUrl: "" },
  { value: "anthropic", label: "Anthropic (Claude)", defaultModel: "claude-sonnet-4-6", defaultUrl: "https://api.anthropic.com/v1" },
  { value: "groq", label: "Groq", defaultModel: "llama-4-scout-17b-16e-instruct", defaultUrl: "https://api.groq.com/openai/v1" },
  { value: "deepseek", label: "DeepSeek", defaultModel: "deepseek-chat", defaultUrl: "https://api.deepseek.com/v1" },
  { value: "openai", label: "OpenAI", defaultModel: "gpt-4o", defaultUrl: "https://api.openai.com/v1" },
];

export default function SettingsPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [keys, setKeys] = useState<APIKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newKey, setNewKey] = useState({ provider: "openrouter", api_key: "", model_name: "", base_url: "" });
  const [showApiKey, setShowApiKey] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<Record<string, { valid: boolean; message: string }>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login");
    }
  }, [status, router]);

  const fetchKeys = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/user/keys", {
        headers: { Authorization: `Bearer ${session?.user?.email || ""}` },
      });
      if (res.ok) {
        const data = await res.json();
        setKeys(data.keys || []);
      }
    } catch (err) {
      console.error("Failed to fetch keys:", err);
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    if (session) fetchKeys();
  }, [session, fetchKeys]);

  const handleAddKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKey.api_key.trim()) return;

    setSaving(true);
    try {
      const provider = PROVIDERS.find(p => p.value === newKey.provider);
      const res = await fetch("/api/v1/user/keys", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session?.user?.email || ""}`,
        },
        body: JSON.stringify({
          provider: newKey.provider,
          api_key: newKey.api_key,
          model_name: newKey.model_name || provider?.defaultModel || "",
          base_url: newKey.base_url || provider?.defaultUrl || "",
        }),
      });

      if (res.ok) {
        setShowAddForm(false);
        setNewKey({ provider: "openrouter", api_key: "", model_name: "", base_url: "" });
        fetchKeys();
      } else {
        const data = await res.json();
        alert(`Failed to add key: ${data.detail}`);
      }
    } catch (err) {
      alert("Failed to add key");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteKey = async (keyId: string) => {
    if (!confirm("Are you sure you want to delete this key?")) return;

    try {
      const res = await fetch(`/api/v1/user/keys/${keyId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${session?.user?.email || ""}` },
      });
      if (res.ok) {
        fetchKeys();
      }
    } catch (err) {
      alert("Failed to delete key");
    }
  };

  const handleTestKey = async (keyId: string) => {
    setTestResults(prev => ({ ...prev, [keyId]: { valid: false, message: "Testing..." } }));
    try {
      const res = await fetch(`/api/v1/user/keys/${keyId}/test`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session?.user?.email || ""}` },
      });
      if (res.ok) {
        const data = await res.json();
        setTestResults(prev => ({ ...prev, [keyId]: { valid: data.valid, message: data.message } }));
      }
    } catch (err) {
      setTestResults(prev => ({ ...prev, [keyId]: { valid: false, message: "Test failed" } }));
    }
  };

  const handleProviderChange = (provider: string) => {
    const p = PROVIDERS.find(p => p.value === provider);
    setNewKey({
      provider,
      api_key: "",
      model_name: p?.defaultModel || "",
      base_url: p?.defaultUrl || "",
    });
  };

  if (status === "loading" || loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-primary">
        <Loader2 className="h-6 w-6 animate-spin text-accent-blue" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border-subtle bg-bg-secondary">
        <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-6">
          <div className="flex items-center gap-4">
            <button onClick={() => router.push("/dashboard")} className="text-text-muted hover:text-text-primary transition-colors">
              <ArrowLeft className="h-4 w-4" />
            </button>
            <h1 className="text-sm font-semibold text-text-primary">API Key Settings</h1>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-text-muted">{session.user?.name}</span>
            <Button variant="ghost" size="sm" onClick={() => signOut({ callbackUrl: "/" })}>
              Sign Out
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-6 py-8">
        {/* Info Banner */}
        <div className="mb-8 rounded-xl border border-accent-blue/30 bg-accent-blue/10 p-4">
          <h3 className="text-sm font-medium text-accent-blue mb-1">Bring Your Own API Keys</h3>
          <p className="text-xs text-text-secondary">
            Add your own API keys to run unlimited research queries. Without keys, you share the system defaults
            which have daily rate limits. Your keys are stored securely in Postgres.
          </p>
        </div>

        {/* Add Key Button */}
        {!showAddForm && (
          <Button onClick={() => setShowAddForm(true)} className="mb-6">
            <Plus className="mr-2 h-4 w-4" />
            Add API Key
          </Button>
        )}

        {/* Add Key Form */}
        {showAddForm && (
          <div className="mb-8 rounded-xl border border-border-subtle bg-bg-secondary p-6">
            <h3 className="text-sm font-medium text-text-primary mb-4">Add New API Key</h3>
            <form onSubmit={handleAddKey} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">Provider</label>
                <select
                  value={newKey.provider}
                  onChange={(e) => handleProviderChange(e.target.value)}
                  className="w-full rounded-lg border border-border-subtle bg-bg-tertiary px-3 py-2 text-sm text-text-primary focus:border-accent-blue focus:outline-none"
                >
                  {PROVIDERS.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">API Key</label>
                <input
                  type="password"
                  value={newKey.api_key}
                  onChange={(e) => setNewKey({ ...newKey, api_key: e.target.value })}
                  placeholder="sk-or-v1-... or sk-ant-..."
                  className="w-full rounded-lg border border-border-subtle bg-bg-tertiary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none"
                  required
                />
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-text-secondary">Model Name (optional)</label>
                <input
                  type="text"
                  value={newKey.model_name}
                  onChange={(e) => setNewKey({ ...newKey, model_name: e.target.value })}
                  placeholder={PROVIDERS.find(p => p.value === newKey.provider)?.defaultModel}
                  className="w-full rounded-lg border border-border-subtle bg-bg-tertiary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none"
                />
              </div>

              {newKey.provider !== "gemini" && (
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-text-secondary">Base URL (optional)</label>
                  <input
                    type="text"
                    value={newKey.base_url}
                    onChange={(e) => setNewKey({ ...newKey, base_url: e.target.value })}
                    placeholder={PROVIDERS.find(p => p.value === newKey.provider)?.defaultUrl}
                    className="w-full rounded-lg border border-border-subtle bg-bg-tertiary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-blue focus:outline-none"
                  />
                </div>
              )}

              <div className="flex items-center gap-3 pt-2">
                <Button type="submit" disabled={saving || !newKey.api_key.trim()}>
                  {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Key className="mr-2 h-4 w-4" />}
                  Add Key
                </Button>
                <Button type="button" variant="ghost" onClick={() => setShowAddForm(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          </div>
        )}

        {/* Keys List */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-text-primary">Your Keys ({keys.length})</h3>
          {keys.length === 0 ? (
            <div className="rounded-xl border border-border-subtle bg-bg-secondary p-8 text-center">
              <Key className="mx-auto h-8 w-8 text-text-muted mb-3" />
              <p className="text-sm text-text-muted">No API keys added yet.</p>
              <p className="text-xs text-text-muted mt-1">Add a key above to get started, or use the system defaults.</p>
            </div>
          ) : (
            keys.map((key) => (
              <div key={key.id} className="rounded-xl border border-border-subtle bg-bg-secondary p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-bg-tertiary">
                      <Key className="h-4 w-4 text-accent-blue" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-text-primary">
                          {PROVIDERS.find(p => p.value === key.provider)?.label || key.provider}
                        </span>
                        {key.is_active && (
                          <span className="rounded-full bg-accent-green/20 px-1.5 py-0.5 text-[10px] font-medium text-accent-green">
                            Active
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-text-muted">
                        {key.model_name && <span>{key.model_name}</span>}
                        {key.base_url && <span className="ml-2">• {key.base_url}</span>}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleTestKey(key.id)}
                      title="Test key"
                    >
                      {testResults[key.id] ? (
                        testResults[key.id].valid ? (
                          <CheckCircle className="h-4 w-4 text-accent-green" />
                        ) : (
                          <XCircle className="h-4 w-4 text-accent-red" />
                        )
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteKey(key.id)}
                      title="Delete key"
                    >
                      <Trash2 className="h-4 w-4 text-accent-red" />
                    </Button>
                  </div>
                </div>
                {testResults[key.id] && (
                  <div className={`mt-2 rounded-lg px-3 py-2 text-xs ${
                    testResults[key.id].valid
                      ? "bg-accent-green/10 text-accent-green"
                      : "bg-accent-red/10 text-accent-red"
                  }`}>
                    {testResults[key.id].message}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

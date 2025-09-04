"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Camera, Loader2, Save, Shield, CheckCircle2, AlertCircle } from "lucide-react";
import RequireAuth from "@/app/lib/requireAuth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import api from "@/app/lib/api";

type ProfileDTO = {
  username: string;
  email?: string | null;
  display_name?: string | null;
  bio?: string | null;
  timezone?: string | null;
  organization?: string | null;
  job_title?: string | null;
  notify_email_reports?: boolean | null;
  avatar_url?: string | null;
};

const cn = (...xs: Array<string | false | null | undefined>) => xs.filter(Boolean).join(" ");
const isStrong = (p: string) => p.length >= 12 && /[A-Z]/.test(p) && /[a-z]/.test(p) && /\d/.test(p);

export default function ProfilePage() {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const [username, setUsername] = useState<string>("");
  const [email, setEmail] = useState<string>("");
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [tz, setTz] = useState("");
  const [org, setOrg] = useState("");
  const [role, setRole] = useState("");
  const [notifyEmailReports, setNotifyEmailReports] = useState(false);

  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarLocal, setAvatarLocal] = useState<string | null>(null);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [avatarProgress, setAvatarProgress] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const pwMismatch = useMemo(() => confirmPw.length > 0 && newPw !== confirmPw, [newPw, confirmPw]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        // Make sure CSRF cookie exists
        await api.get("/auth/csrf/");
        const { data } = await api.get<ProfileDTO>("/auth/profile/");
        setUsername(data.username);
        setEmail(data.email ?? "");
        setDisplayName(data.display_name ?? "");
        setBio(data.bio ?? "");
        setTz(data.timezone ?? "");
        setOrg(data.organization ?? "");
        setRole(data.job_title ?? "");
        setNotifyEmailReports(Boolean(data.notify_email_reports));
        setAvatarUrl(data.avatar_url ?? null);
      } catch (e: any) {
        setErr(e?.message || "Failed to load profile");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const clearSoon = () => window.setTimeout(() => { setOk(null); setErr(null); }, 2000);

  const handleSaveProfile = async () => {
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      await api.get("/auth/csrf/");
      await api.patch("/auth/profile/", {
        email,
        display_name: displayName,
        bio,
        timezone: tz,
        organization: org,
        job_title: role,
        notify_email_reports: notifyEmailReports,
      });
      setOk("Profile updated");
    } catch (e: any) {
      setErr(e?.response?.data?.error || e?.message || "Failed to save profile");
    } finally {
      setBusy(false);
      clearSoon();
    }
  };

  const handlePickAvatar = () => fileInputRef.current?.click();

  const handleAvatarChange = async (file: File | null) => {
    if (!file) return;
    setAvatarProgress(0);
    setAvatarUploading(true);
    setErr(null);
    setOk(null);
    try {
      await api.get("/auth/csrf/");

      // local preview
      const previewUrl = URL.createObjectURL(file);
      setAvatarLocal(previewUrl);

      const fd = new FormData();
      fd.append("avatar", file);

      const { data } = await api.post<{ avatar_url: string }>(
        "/auth/profile/avatar/",
        fd,
        {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: (evt) => {
            if (evt.total) setAvatarProgress(Math.round((evt.loaded / evt.total) * 100));
          },
        }
      );
      setAvatarUrl(data.avatar_url);
      setOk("Profile photo updated");
    } catch (e: any) {
      setErr(e?.response?.data?.error || e?.message || "Avatar upload failed");
      setAvatarLocal(null);
    } finally {
      setAvatarUploading(false);
      clearSoon();
    }
  };

  const handleChangePassword = async () => {
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      if (!currentPw || !newPw) throw new Error("Please complete the password fields");
      if (pwMismatch) throw new Error("New passwords do not match");
      if (!isStrong(newPw)) throw new Error("Choose a stronger password (min 12, mixed case, number)");

      await api.get("/auth/csrf/");
      await api.post("/auth/change-password/", {
        current_password: currentPw,
        new_password: newPw,
      });

      setOk("Password changed");
      setCurrentPw(""); setNewPw(""); setConfirmPw("");
    } catch (e: any) {
      setErr(e?.response?.data?.error || e?.message || "Failed to change password");
    } finally {
      setBusy(false);
      clearSoon();
    }
  };

  return (
    <RequireAuth>
      <div className="min-h-screen">
        <div className="mx-auto w-full max-w-5xl space-y-6">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl md:text-3xl font-bold">Your Profile</h1>
          </div>

          {(err || ok) && (
            <div className="space-y-2">
              {err && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{err}</AlertDescription>
                </Alert>
              )}
              {ok && (
                <Alert>
                  <CheckCircle2 className="h-4 w-4" />
                  <AlertDescription>{ok}</AlertDescription>
                </Alert>
              )}
            </div>
          )}

          <Card>
            <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <CardTitle>Profile</CardTitle>
                <CardDescription>Manage your account information and photo</CardDescription>
              </div>
              {loading && (
                <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading…
                </div>
              )}
            </CardHeader>

            <CardContent className="grid gap-6 md:grid-cols-[180px,1fr]">
              {/* Avatar */}
              <div className="flex flex-col items-center gap-3">
                <div className="relative">
                  <div className="h-32 w-32 rounded-full overflow-hidden ring-2 ring-border bg-muted">
                    {avatarLocal || avatarUrl ? (
                      <img src={(avatarLocal ?? avatarUrl) as string} alt="Profile" className="h-full w-full object-cover" />
                    ) : (
                      <div className="h-full w-full grid place-items-center text-4xl font-semibold">
                        {(displayName || username || "U").charAt(0).toUpperCase()}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={handlePickAvatar}
                    className={cn("absolute bottom-0 right-0 grid h-10 w-10 place-items-center rounded-full border bg-white",
                                  "shadow-sm hover:bg-gray-50 transition")}
                    title="Change photo"
                    disabled={avatarUploading}
                  >
                    {avatarUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={(e) => handleAvatarChange(e.target.files?.[0] ?? null)}
                    className="hidden"
                  />
                  {avatarUploading && (
                    <div className="mt-2 text-xs text-muted-foreground text-center">
                      Uploading… {avatarProgress}%
                    </div>
                  )}
                </div>
              </div>

              {/* Fields */}
              <div className="grid gap-4">
                <div className="grid gap-2">
                  <label className="text-sm text-muted-foreground">Full name</label>
                  <input
                    className="w-full rounded-md border px-3 py-2"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Your name"
                  />
                </div>

                <div className="grid gap-2">
                  <label className="text-sm text-muted-foreground">Email</label>
                  <input
                    className="w-full rounded-md border px-3 py-2"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    name="cc_profile_email"
                    autoComplete="off"
                  />
                </div>

                <div className="grid gap-2 md:grid-cols-2 md:gap-4">
                  <div className="grid gap-2">
                    <label className="text-sm text-muted-foreground">Organization</label>
                    <input
                      className="w-full rounded-md border px-3 py-2"
                      value={org}
                      onChange={(e) => setOrg(e.target.value)}
                      placeholder="Company or team"
                    />
                  </div>
                  <div className="grid gap-2">
                    <label className="text-sm text-muted-foreground">Job title</label>
                    <input
                      className="w-full rounded-md border px-3 py-2"
                      value={role}
                      onChange={(e) => setRole(e.target.value)}
                      placeholder="e.g., Portfolio Manager"
                    />
                  </div>
                </div>

                <div className="grid gap-2">
                  <label className="text-sm text-muted-foreground">Timezone</label>
                  <input
                    className="w-full rounded-md border px-3 py-2"
                    value={tz}
                    onChange={(e) => setTz(e.target.value)}
                    placeholder="e.g., America/New_York"
                  />
                </div>

                <div className="grid gap-2">
                  <label className="text-sm text-muted-foreground">Bio</label>
                  <textarea
                    className="w-full rounded-md border px-3 py-2"
                    rows={3}
                    value={bio}
                    onChange={(e) => setBio(e.target.value)}
                    placeholder="Tell us a bit about your focus..."
                  />
                </div>

                <div className="flex items-center gap-3 pt-1">
                  <input
                    id="notify-email-reports"
                    type="checkbox"
                    className="h-4 w-4"
                    checked={notifyEmailReports}
                    onChange={(e) => setNotifyEmailReports(e.target.checked)}
                  />
                  <label htmlFor="notify-email-reports" className="text-sm">
                    Email me weekly portfolio analytics reports
                  </label>
                </div>

                <div className="pt-2">
                  <Button onClick={handleSaveProfile} disabled={busy || loading}>
                    {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
                    Save changes
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Change Password</CardTitle>
              <CardDescription>Use a unique passphrase (12+ chars, mixed case and numbers)</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-2 md:grid-cols-3 md:gap-4">
                <div className="grid gap-2">
                  <label className="text-sm text-muted-foreground">Current password</label>
                  <input className="w-full rounded-md border px-3 py-2" type="password"
                         value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
                </div>
                <div className="grid gap-2">
                  <label className="text-sm text-muted-foreground">New password</label>
                  <input
                    className={cn("w-full rounded-md border px-3 py-2",
                                   newPw ? (isStrong(newPw) ? "border-green-300" : "border-amber-300") : "")}
                    type="password"
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                    placeholder="At least 12 characters"
                  />
                </div>
                <div className="grid gap-2">
                  <label className="text-sm text-muted-foreground">Confirm new password</label>
                  <input
                    className={cn("w-full rounded-md border px-3 py-2",
                                   confirmPw ? (pwMismatch ? "border-red-300" : "border-green-300") : "")}
                    type="password"
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                  />
                </div>
              </div>

              {pwMismatch && (
                <div className="text-sm text-destructive flex items-center gap-2">
                  <AlertCircle className="h-4 w-4" /> New passwords do not match
                </div>
              )}

              <div>
                <Button
                  variant="destructive"
                  onClick={handleChangePassword}
                  disabled={busy || !currentPw || !newPw || !confirmPw || pwMismatch}
                >
                  {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Shield className="mr-2 h-4 w-4" />}
                  Update password
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </RequireAuth>
  );
}

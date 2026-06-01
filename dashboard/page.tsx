"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, BarChart3, BookOpen, Bot, CheckCircle2, Clock, FileText, Filter, GitBranch, Loader2, RefreshCw, Save, ScrollText, Search, Shield, Sparkles, Zap } from "lucide-react";
import { LoginGate } from "@/components/auth/LoginGate";

type Tab = "skills" | "proposals" | "reports" | "constitution" | "analytics";
type Report = { date: string; size: number; size_kb: number };
type Proposal = {
  file: string; status: string; risk: string; score: number; title: string; source: string; url: string;
  action_count?: number; last_event?: string; approved_at?: string; implemented_at?: string; verified_at?: string;
  exec_status?: string;
  impact_scope?: string; target_skills?: string[]; impact_bullets?: string[];
};
type SkillItem = { name: string; category: string; file?: string; rating?: number; composite?: number; verdict?: string; reason?: string; issues?: string[]; size_kb?: number; body_lines?: number; description?: string };
type SkillFocus = { total: number; needs_work: number; keep: number; verdicts: Record<string, number>; priorities: SkillItem[] };
type Stats = {
  reports: number; proposals: number; constitution_exists: boolean; status: Record<string, number>; risk: Record<string, number>; score_avg: number;
  actionable?: number; blocked?: number; last_verified?: string;
};
type ExecLog = { ts: string; level: string; message: string; action_idx?: number; status?: string };
type ExecSummary = { running: boolean; actions_total: number; actions_done: number; actions_failed: number; last_message: string; last_updated: string | null };
type ExecCheck = { name: string; ok: boolean; details: string[] };

const statusMeta: Record<string, { label: string; cls: string }> = {
  pending: { label: "待审批", cls: "border-amber-400/40 bg-amber-400/10 text-amber-200" },
  approved: { label: "已批准", cls: "border-sky-400/40 bg-sky-400/10 text-sky-200" },
  implementing: { label: "实施中", cls: "border-violet-400/40 bg-violet-400/10 text-violet-200" },
  implemented: { label: "已实施", cls: "border-blue-400/40 bg-blue-400/10 text-blue-200" },
  verified: { label: "已验证", cls: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" },
  failed: { label: "失败", cls: "border-red-400/40 bg-red-400/10 text-red-200" },
  rejected: { label: "已拒绝", cls: "border-zinc-500/60 bg-zinc-500/10 text-zinc-300" },
  deferred: { label: "已搁置", cls: "border-slate-400/40 bg-slate-400/10 text-slate-300" },
};
const riskCls: Record<string, string> = { high: "text-red-300", medium: "text-orange-300", low: "text-emerald-300" };
const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: "skills", label: "技能内化", icon: <Sparkles className="h-4 w-4" /> },
  { key: "proposals", label: "提案管理", icon: <GitBranch className="h-4 w-4" /> },
  { key: "reports", label: "学习报告", icon: <BookOpen className="h-4 w-4" /> },
  { key: "constitution", label: "宪法", icon: <Shield className="h-4 w-4" /> },
  { key: "analytics", label: "分析", icon: <BarChart3 className="h-4 w-4" /> },
];

function auth() { return "Basic " + btoa("admin:" + (sessionStorage.getItem("admin_pwd") || "")); }
function Badge({ status }: { status: string }) { const m = statusMeta[status] || { label: status || "unknown", cls: "border-zinc-600 bg-zinc-800 text-zinc-300" }; return <span className={`rounded-full border px-2 py-0.5 text-xs ${m.cls}`}>{m.label}</span>; }

/* ── Simple markdown → HTML renderer ── */
function renderMarkdown(md: string): string {
  if (!md) return "";
  let html = md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, url) => {
      if (/^(javascript|data|vbscript):/i.test(url)) return match;
      return `<a href="${url}" target="_blank" rel="noopener">${text}</a>`;
    })
    .replace(/```(\w*)\n?([\s\S]*?)```/g, "<pre><code>$2</code></pre>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^&gt; (.+)$/gm, "<blockquote>$1</blockquote>")
    .replace(/^---$/gm, "<hr>")
    .replace(/^\|(.+)\|$/gm, (line) => {
      const cells = line.split("|").filter(c => c.trim()).map(c => c.trim());
      if (cells.every(c => /^:?-{3,}:?$/.test(c))) return "";
      return `<tr>${cells.map(c => `<td>${c}</td>`).join("")}</tr>`;
    })
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br>");
  return `<p>${html}</p>`;
}

export default function EvolutionPage() {
  const [authenticated, setAuthenticated] = useState(false);
  const [active, setActive] = useState<Tab>("skills");
  const [reports, setReports] = useState<Report[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [report, setReport] = useState("");
  const [selectedProposal, setSelectedProposal] = useState<Proposal | null>(null);
  const [proposalBody, setProposalBody] = useState("");
  const [constitution, setConstitution] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterSearch, setFilterSearch] = useState("");
  const [skillFocus, setSkillFocus] = useState<SkillFocus | null>(null);

  // ── Execution log state ──
  const [execLogs, setExecLogs] = useState<ExecLog[]>([]);
  const [execSummary, setExecSummary] = useState<ExecSummary | null>(null);
  const [execRunning, setExecRunning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Feedback impact state ──
  const [impactData, setImpactData] = useState<null | { impact: any; before: any; after: any; has_data: boolean }>(null);

  const loadEvolution = useCallback(async (date?: string) => {
    setLoading(true); setMessage("");
    try {
      const url = "/api/evolution?_=" + Date.now() + (date ? "&date=" + encodeURIComponent(date) : "");
      const r = await fetch(url, { headers: { Authorization: auth() } });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      setReports(d.reports || []); setProposals(d.proposals || []); setReport(d.latest || ""); setSkillFocus(d.skill_focus || null);
      if (!date && d.reports?.[0]?.date) setSelectedDate(d.reports[0].date);
      return d;
    } catch (e: any) {
      setMessage("加载失败: " + (e.message || "未知错误"));
      return null;
    } finally { setLoading(false); }
  }, []);
  const loadStats = useCallback(async () => { try { const r = await fetch("/api/evolution/stats?_=" + Date.now(), { headers: { Authorization: auth() } }); if (r.ok) setStats(await r.json()); } catch {} }, []);
  const loadConstitution = useCallback(async () => { try { const r = await fetch("/api/constitution?_=" + Date.now(), { headers: { Authorization: auth() } }); if (r.ok) setConstitution((await r.json()).content || ""); } catch {} }, []);

  const loadExecLogs = useCallback(async (file: string) => {
    try {
      const r = await fetch("/api/proposal/" + encodeURIComponent(file) + "/exec-logs?_=" + Date.now(), { headers: { Authorization: auth() } });
      if (!r.ok) return;
      const d = await r.json();
      setExecLogs(d.logs || []);
      setExecSummary(d.summary || null);
      setExecRunning(d.is_running === true || d.summary?.running === true);
    } catch {}
  }, []);

  const loadImpact = useCallback(async (file: string) => {
    try {
      const r = await fetch("/api/proposal/" + encodeURIComponent(file) + "/impact?_=" + Date.now(), { headers: { Authorization: auth() } });
      if (!r.ok) return;
      const d = await r.json();
      setImpactData(d);
    } catch {
      setImpactData(null);
    }
  }, []);

  // Auto-poll execution logs when running
  useEffect(() => {
    if (execRunning && selectedProposal?.file) {
      pollRef.current = setInterval(() => {
        loadExecLogs(selectedProposal.file);
      }, 3000);
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [execRunning, selectedProposal?.file, loadExecLogs]);

  useEffect(() => { if (sessionStorage.getItem("admin_pwd")) setAuthenticated(true); }, []);
  useEffect(() => { if (authenticated) { loadEvolution(); loadStats(); loadConstitution(); } }, [authenticated, loadEvolution, loadStats, loadConstitution]);

  const selectedStatus = selectedProposal?.status || "";
  const counts = useMemo(() => ({
    pending: proposals.filter(p => p.status === "pending").length,
    approved: proposals.filter(p => p.status === "approved").length,
    implementing: proposals.filter(p => p.status === "implementing").length,
    verified: proposals.filter(p => p.status === "verified").length,
    deferred: proposals.filter(p => p.status === "deferred").length,
  }), [proposals]);

  const filteredProposals = useMemo(() => proposals.filter(p => {
    if (filterStatus && p.status !== filterStatus) return false;
    if (filterSearch && !p.title.toLowerCase().includes(filterSearch.toLowerCase()) && !p.file.toLowerCase().includes(filterSearch.toLowerCase())) return false;
    return true;
  }), [proposals, filterStatus, filterSearch]);

  async function openProposal(p: Proposal) {
    setSelectedProposal(p); setNote(""); setMessage(""); setProposalBody("加载中..."); setImpactData(null);
    try {
      const r = await fetch("/api/proposal/" + encodeURIComponent(p.file) + "?_=" + Date.now(), { headers: { Authorization: auth() } });
      const d = await r.json();
      setProposalBody(r.ok ? d.content || "" : d.error || "加载失败");
      setSelectedProposal(prev => prev ? { ...prev, action_count: d.actions?.length ?? prev.action_count, last_event: d.last_event || prev.last_event, exec_status: d.exec_status } : prev);
      // Load exec logs
      await loadExecLogs(p.file);
      // Load feedback impact
      await loadImpact(p.file);
    } catch (e: any) { setProposalBody("加载失败: " + (e.message || "网络错误")); }
  }
  async function internalizeSkill(skillName: string) {
    if (!skillName) return;
    setLoading(true); setMessage("");
    try {
      const r = await fetch("/api/skill/internalize", {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: auth() },
        body: JSON.stringify({ name: skillName }),
      });
      const d = await r.json();
      setMessage(d.ok ? `✅ 内化任务已创建: ${skillName}` : d.error || "内化失败");
      if (d.ok) { await loadEvolution(selectedDate); await loadStats(); }
    } catch (e: any) { setMessage("网络错误: " + (e.message || "")); }
    finally { setLoading(false); }
  }
  async function proposalExec() {
    if (!selectedProposal) return;
    const file = encodeURIComponent(selectedProposal.file);
    setLoading(true); setMessage("");
    try {
      const r = await fetch(`/api/proposal/${file}/exec`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: auth() }, body: JSON.stringify({}) });
      const d = await r.json();
      if (d.ok) {
        setMessage(`⚡ 自动实施已启动 — ${d.count} 项行动`);
        setSelectedProposal(prev => prev ? { ...prev, status: "implementing" } : null);
        setExecRunning(true);
        // Load logs immediately
        await loadExecLogs(selectedProposal.file);
      } else {
        setMessage(d.error || "操作失败");
      }
      const refreshed = await loadEvolution(selectedDate); await loadStats();
      const latest = refreshed?.proposals?.find((p: Proposal) => p.file === selectedProposal.file);
      setSelectedProposal(prev => prev ? { ...(latest || prev), status: d.status || latest?.status || "implementing" } : null);
    } catch (e: any) {
      setMessage("网络错误: " + (e.message || ""));
    } finally {
      setLoading(false);
    }
  }
  async function autoVerify() {
    if (!selectedProposal) return;
    const file = encodeURIComponent(selectedProposal.file);
    setLoading(true); setMessage("");
    try {
      const r = await fetch(`/api/proposal/${file}/auto-verify`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: auth() }, body: JSON.stringify({}) });
      const d = await r.json();
      if (d.ok) {
        const statusLabel = d.passed ? "✅ 验证通过" : "❌ 验证失败";
        setMessage(`${statusLabel} — ${d.checks?.length || 0} 项检查`);
        setSelectedProposal(prev => prev ? { ...prev, status: d.status } : null);
      } else {
        setMessage(d.error || "验证失败");
      }
      const refreshed = await loadEvolution(selectedDate); await loadStats();
      const updated = refreshed?.proposals?.find((p: Proposal) => p.file === selectedProposal.file) || selectedProposal;
      setSelectedProposal(prev => prev ? { ...(updated || prev), status: d.status || updated.status } : null);
      await loadExecLogs(selectedProposal.file);
    } catch (e: any) {
      setMessage("网络错误: " + (e.message || ""));
    } finally {
      setLoading(false);
    }
  }
  async function proposalAction(action: "approve" | "reject" | "defer" | "implement" | "verify" | "fail") {
    if (!selectedProposal) return;
    const file = encodeURIComponent(selectedProposal.file);
    const endpointMap: Record<string, string> = { approve: "approve", reject: "approve", defer: "defer", implement: "implement", verify: "verify", fail: "verify" };
    const url = `/api/proposal/${file}/${endpointMap[action]}`;
    let body: Record<string, unknown> = { note };
    if (action === "approve") body = { status: "approved", comment: note };
    else if (action === "reject") body = { status: "rejected", comment: note };
    else if (action === "fail") body = { ok: false, note };
    setLoading(true); setMessage("");
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", Authorization: auth() }, body: JSON.stringify(body) });
      const d = await r.json();
      setMessage(d.ok ? `状态已更新为 ${statusMeta[d.status]?.label || d.status}` : d.error || "操作失败");
      const refreshed = await loadEvolution(selectedDate); await loadStats();
      const updated = refreshed?.proposals?.find((p: Proposal) => p.file === selectedProposal.file) || selectedProposal;
      await openProposal({ ...updated, status: d.status || updated.status });
    } catch (e: any) { setMessage("网络错误: " + (e.message || "")); }
    finally { setLoading(false); }
  }
  async function saveConstitution() {
    const r = await fetch("/api/constitution", { method: "POST", headers: { "Content-Type": "application/json", Authorization: auth() }, body: JSON.stringify({ content: constitution }) });
    setMessage(r.ok ? "宪法已保存" : "保存失败"); await loadStats();
  }

  if (!authenticated) return <LoginGate title="Hermes 进化系统 V3" description="请输入管理员密码" onAuthenticated={() => setAuthenticated(true)} />;

  return <main className="min-h-screen bg-[#090d14] p-3 sm:p-5 text-slate-200">
    <div className="mx-auto max-w-7xl space-y-4 sm:space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/[0.03] p-4 sm:p-5 shadow-2xl shadow-black/20">
        <div><h1 className="flex items-center gap-2 text-xl sm:text-2xl font-semibold text-white"><Activity className="text-cyan-300" /> Hermes 进化系统 V3</h1><p className="mt-1 text-xs sm:text-sm text-slate-400">优先内化已有技能 → 提案说明影响 → 自动实施 → 自动验证</p></div>
        <button onClick={() => { loadEvolution(selectedDate); loadStats(); }} className="flex items-center gap-2 rounded-lg border border-white/10 bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700"><RefreshCw className="h-4 w-4" />刷新</button>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat icon={<Sparkles />} label="我的技能" value={skillFocus?.total ?? "—"} />
        <Stat icon={<Bot />} label="待内化" value={skillFocus?.needs_work ?? "—"} />
        <Stat icon={<GitBranch />} label="外部提案" value={stats?.proposals ?? proposals.length} />
        <Stat icon={<CheckCircle2 />} label="已验证" value={counts.verified} />
      </section>

      <nav className="flex flex-wrap gap-1 sm:gap-2 rounded-2xl border border-white/10 bg-white/[0.03] p-1.5 sm:p-2">
        {tabs.map(t => <button key={t.key} onClick={() => setActive(t.key)} className={`flex items-center gap-1.5 sm:gap-2 rounded-xl px-3 sm:px-4 py-2 text-xs sm:text-sm ${active === t.key ? "bg-cyan-400/15 text-cyan-200" : "text-slate-400 hover:bg-white/5"}`}>{t.icon}{t.label}</button>)}
      </nav>

      <div className={`grid gap-4 sm:gap-5 ${
        (active === "reports" || active === "proposals")
        ? (active === "reports"
          ? "lg:grid-cols-[220px_minmax(0,1fr)]"
          : "lg:grid-cols-[minmax(0,1fr)_350px]")
        : "lg:grid-cols-[minmax(0,1fr)]"
      }`}>
        {/* ── Left: Report List (reports tab only) ── */}
        {active === "reports" && (
        <aside className="rounded-2xl border border-white/10 bg-white/[0.03] p-3 sm:p-4 order-1">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white"><BookOpen className="h-4 w-4" />报告列表</h2>
          <div className="max-h-[60vh] space-y-1.5 overflow-auto">
            {reports.map(r => <button key={r.date} onClick={() => { setSelectedDate(r.date); loadEvolution(r.date); }} className={`w-full rounded-lg border px-3 py-2 text-left text-xs sm:text-sm ${selectedDate === r.date ? "border-cyan-400/60 bg-cyan-400/10 text-cyan-100" : "border-white/10 bg-slate-900/60 text-slate-300 hover:bg-slate-800"}`}>{r.date}<span className="float-right text-xs text-slate-500">{r.size_kb}KB</span></button>)}
          </div>
        </aside>
        )}

        {/* ── Center: Content ── */}
        <section className="min-w-0 rounded-2xl border border-white/10 bg-white/[0.03] p-3 sm:p-4 order-3 lg:order-2">
          {active === "skills" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-cyan-400/20 bg-cyan-400/10 p-4">
                <h2 className="flex items-center gap-2 text-base font-semibold text-cyan-100"><Sparkles className="h-4 w-4" />技能内化优先队列</h2>
                <p className="mt-2 text-sm leading-6 text-slate-300">这里把“我的技能”放在进化系统第一优先级：先审计现有技能，找出需改进/合并/删除/待审查项，再进入实施与验证闭环。外部提案只作为补充来源。</p>
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <MiniStat label="技能总数" value={skillFocus?.total ?? 0} />
                  <MiniStat label="待内化" value={skillFocus?.needs_work ?? 0} />
                  <MiniStat label="高质量保留" value={skillFocus?.keep ?? 0} />
                  <MiniStat label="提案补充" value={proposals.length} />
                </div>
              </div>
              <div className="grid gap-3">
                {(skillFocus?.priorities || []).map(s => (
                  <div key={s.name} className="rounded-xl border border-white/10 bg-slate-950/60 p-4">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-white">{s.name}</span>
                      <span className="rounded-full border border-white/10 bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300">{s.category || "uncategorized"}</span>
                      <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-[10px] text-amber-200">{s.verdict || "REVIEW"}</span>
                      <span className="ml-auto text-xs text-cyan-200">评分 {s.composite ?? s.rating ?? 0}</span>
                    </div>
                    <p className="text-sm leading-6 text-slate-300">{s.reason || s.description || "等待进一步审查"}</p>
                    {s.issues && s.issues.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-orange-200">{s.issues.slice(0, 4).map((i, idx) => <li key={idx}>{i}</li>)}</ul>}
                    <div className="mt-3 flex items-center justify-between">
                      <span className="text-xs text-slate-500">内化动作：补齐触发条件、步骤、坑点与验证方式；完成后重新审计并写回技能质量分。</span>
                      <button onClick={() => internalizeSkill(s.name)}
                        className="flex items-center gap-1 rounded-lg bg-cyan-500/20 px-3 py-1.5 text-xs text-cyan-200 hover:bg-cyan-500/30 transition-colors">
                        <Zap className="h-3 w-3" />开始内化
                      </button>
                    </div>
                  </div>
                ))}
                {(!skillFocus || skillFocus.priorities.length === 0) && <div className="py-12 text-center text-sm text-slate-500">暂无技能审计数据</div>}
              </div>
            </div>
          )}
          {active === "reports" && (
            <div>
              <h2 className="mb-4 text-base font-semibold text-white">学习报告 {selectedDate || ""}</h2>
              {loading ? <div className="py-8 text-center text-sm text-slate-500">加载中...</div> :
                <article className="prose prose-invert prose-sm max-w-none text-sm leading-7 text-slate-300 [&_h1]:mb-4 [&_h1]:text-xl [&_h1]:font-semibold [&_h1]:text-white [&_h1]:border-b [&_h1]:border-white/10 [&_h1]:pb-3 [&_h2]:mb-3 [&_h2]:mt-6 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-cyan-200 [&_h3]:mb-2 [&_h3]:mt-4 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-white [&_a]:text-cyan-300 [&_a]:underline [&_blockquote]:border-l-3 [&_blockquote]:border-slate-600 [&_blockquote]:pl-3 [&_blockquote]:text-slate-400 [&_blockquote]:my-2 [&_code]:rounded [&_code]:bg-slate-800 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-xs [&_code]:text-emerald-300 [&_pre]:my-3 [&_pre]:rounded-lg [&_pre]:bg-slate-950 [&_pre]:p-3 [&_pre]:text-xs [&_pre]:overflow-x-auto [&_hr]:my-4 [&_hr]:border-white/10 [&_table]:w-full [&_table]:text-xs [&_td]:border [&_td]:border-white/10 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-white/10 [&_th]:bg-slate-900 [&_th]:px-2 [&_th]:py-1"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(report) }} />}
            </div>
          )}
          {active === "proposals" && (
            <div>
              <h2 className="mb-4 text-base font-semibold text-white">提案管理</h2>
              {/* Filters */}
              <div className="mb-4 flex flex-wrap gap-2">
                <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-slate-900/60 px-3 py-1.5 text-sm">
                  <Filter className="h-3.5 w-3.5 text-slate-400" />
                  <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="bg-transparent text-slate-200 outline-none text-xs">
                    <option value="">全部状态</option>
                    {Object.entries(statusMeta).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                  </select>
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-slate-900/60 px-3 py-1.5 text-sm flex-1 min-w-[140px]">
                  <Search className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                  <input value={filterSearch} onChange={e => setFilterSearch(e.target.value)} placeholder="搜索提案..." className="w-full bg-transparent text-slate-200 outline-none text-xs" />
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {filteredProposals.map(p => <button key={p.file} onClick={() => openProposal(p)} className={`rounded-xl border p-3 sm:p-4 text-left transition-colors ${selectedProposal?.file === p.file ? "border-cyan-400/60 bg-cyan-400/10" : "border-white/10 bg-slate-950/60 hover:border-cyan-400/50"}`}><div className="mb-2 flex flex-wrap items-center gap-2"><Badge status={p.status} /><span className={`text-xs ${riskCls[p.risk] || "text-slate-400"}`}>{p.risk}</span><span className="text-xs text-slate-500">⭐{p.score}</span><span className="rounded-full bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">行动 {p.action_count ?? 0}</span><span className="rounded-full bg-cyan-400/10 px-1.5 py-0.5 text-[10px] text-cyan-200">{p.impact_scope || "系统提案"}</span>{p.exec_status === "running" && <Loader2 className="h-3 w-3 animate-spin text-violet-300" />}</div><div className="font-medium text-white text-sm">{p.title}</div><div className="mt-1 text-xs text-slate-500 truncate">{p.impact_bullets?.[0] || p.last_event || p.file}</div></button>)}
                {filteredProposals.length === 0 && <div className="col-span-2 py-12 text-center text-sm text-slate-500">暂无匹配提案</div>}
              </div>
            </div>
          )}
          {active === "constitution" && (
            <div>
              <h2 className="mb-4 text-base font-semibold text-white">Hermes 宪法</h2>
              <textarea value={constitution} onChange={e => setConstitution(e.target.value)} className="min-h-[50vh] w-full rounded-xl border border-white/10 bg-slate-950 p-4 font-mono text-sm text-slate-200 outline-none focus:border-cyan-400/60" />
              <button onClick={saveConstitution} className="mt-3 flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400"><Save className="h-4 w-4" />保存宪法</button>
            </div>
          )}
          {active === "analytics" && (
            <div>
              <h2 className="mb-4 text-base font-semibold text-white">进化分析</h2>
              <div className="grid gap-4 sm:grid-cols-2">
                <Chart title="状态分布" data={stats?.status || {}} />
                <Chart title="风险分布" data={stats?.risk || {}} />
                <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4"><div className="text-sm text-slate-400">平均评分</div><div className="mt-2 text-4xl font-bold text-cyan-200">{stats?.score_avg ?? 0}</div></div>
                <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4"><div className="text-sm text-slate-400">可实施 / 阻塞</div><div className="mt-2 text-3xl font-bold text-emerald-200">{stats?.actionable ?? 0}<span className="mx-2 text-slate-600">/</span><span className="text-amber-200">{stats?.blocked ?? 0}</span></div><div className="mt-2 text-xs text-slate-500">最近验证：{stats?.last_verified || "暂无"}</div></div>
              </div>
            </div>
          )}
          {message && <div className="mt-4 rounded-lg border border-cyan-400/30 bg-cyan-400/10 p-3 text-sm text-cyan-100">{message}</div>}
        </section>

        {/* ── Right: Proposal Detail + Execution Logs (proposals tab only) ── */}
        {active === "proposals" && (
        <aside className="rounded-2xl border border-white/10 bg-white/[0.03] p-3 sm:p-4 order-2 lg:order-3 max-h-[85vh] overflow-y-auto">
          {selectedProposal ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2"><Badge status={selectedStatus} /><span className={`text-xs ${riskCls[selectedProposal.risk] || "text-slate-400"}`}>风险 {selectedProposal.risk}</span><span className="text-xs text-slate-400">行动 {selectedProposal.action_count ?? 0}</span>{execRunning && <Loader2 className="h-3 w-3 animate-spin text-violet-300" />}</div>

              <div className="rounded-xl border border-cyan-400/20 bg-cyan-400/10 p-3">
                <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-cyan-100"><Sparkles className="h-3 w-3" />这条提案改善什么</h3>
                <div className="mb-2 text-xs text-slate-300">范围：<span className="text-cyan-200">{selectedProposal.impact_scope || "系统提案"}</span></div>
                {selectedProposal.target_skills && selectedProposal.target_skills.length > 0 && <div className="mb-2 flex flex-wrap gap-1">{selectedProposal.target_skills.map(s => <span key={s} className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] text-cyan-200">{s}</span>)}</div>}
                {selectedProposal.impact_bullets && selectedProposal.impact_bullets.length > 0 ? <ul className="list-disc space-y-1 pl-4 text-xs leading-5 text-slate-300">{selectedProposal.impact_bullets.map((b, i) => <li key={i}>{b}</li>)}</ul> : <div className="text-xs text-slate-500">未识别到明确的 Hermes/技能改善点，建议先转入“技能内化”队列补齐目标与验证标准。</div>}
              </div>

              {/* ── Execution Log Panel ── */}
              {(execLogs.length > 0 || execRunning || execSummary) && (
                <div className="rounded-xl border border-violet-400/20 bg-slate-950/80 p-2">
                  <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-violet-200">
                    <Bot className="h-3 w-3" />执行日志
                    {execRunning && <span className="ml-auto flex items-center gap-1 text-[10px] text-violet-300"><Loader2 className="h-2.5 w-2.5 animate-spin" />运行中</span>}
                    {execSummary && !execRunning && execSummary.actions_total > 0 && (
                      <span className="ml-auto text-[10px] text-slate-400">
                        {execSummary.actions_done}/{execSummary.actions_total} ✓
                        {execSummary.actions_failed > 0 && <span className="ml-1 text-red-300">{execSummary.actions_failed} ✗</span>}
                      </span>
                    )}
                  </h3>
                  <div className="max-h-40 overflow-y-auto space-y-0.5">
                    {execSummary && execSummary.actions_total > 0 && (
                      <div className="mb-1 flex gap-1 text-[10px]">
                        <span className="text-emerald-300">完成 {execSummary.actions_done}</span>
                        {execSummary.actions_failed > 0 && <span className="text-red-300">失败 {execSummary.actions_failed}</span>}
                        <span className="text-slate-500">共 {execSummary.actions_total}</span>
                      </div>
                    )}
                    {execLogs.slice(0, 30).map((log, i) => (
                      <div key={i} className={`flex gap-1 text-[10px] leading-4 font-mono ${log.level === "error" || log.level === "action_error" ? "text-red-300" : log.level === "warn" ? "text-amber-300" : log.level === "action_start" ? "text-cyan-200" : log.level === "action_done" ? "text-emerald-300" : "text-slate-400"}`}>
                        <span className="shrink-0 w-14 text-slate-600">{log.ts?.slice(11, 19) || ""}</span>
                        <span className="break-all">{log.message}</span>
                      </div>
                    ))}
                    {execLogs.length === 0 && execRunning && (
                      <div className="flex items-center gap-1 text-[10px] text-slate-500"><Loader2 className="h-2.5 w-2.5 animate-spin" />等待执行开始...</div>
                    )}
                  </div>
                </div>
              )}

              {/* ── Feedback Impact Assessment ── */}
              {impactData?.has_data && impactData.impact && (
                <div className="rounded-xl border border-emerald-400/20 bg-slate-950/80 p-2">
                  <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-emerald-200">
                    <BarChart3 className="h-3 w-3" />效果评估
                    <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      impactData.impact.overall === "positive" ? "bg-emerald-400/20 text-emerald-200" :
                      impactData.impact.overall === "negative" ? "bg-red-400/20 text-red-200" :
                      "bg-slate-400/20 text-slate-300"
                    }`}>
                      {impactData.impact.overall === "positive" ? "正向" :
                       impactData.impact.overall === "negative" ? "负向" : "中性"}
                    </span>
                  </h3>
                  <div className="space-y-1 text-[10px]">
                    {impactData.impact.details?.map((d: any, i: number) => (
                      <div key={i} className="flex items-center justify-between rounded bg-slate-900/50 px-2 py-1">
                        <span className="text-slate-400">{d.label}</span>
                        <span className={
                          d.change === "improved" ? "text-emerald-300" :
                          d.change === "degraded" ? "text-red-300" : "text-slate-500"
                        }>
                          {d.change === "improved" ? "↑ 改善" :
                           d.change === "degraded" ? "↓ 退化" :
                           d.change === "unknown" ? "— 未知" : "→ 持平"}
                        </span>
                      </div>
                    ))}
                    {impactData.before?.mem_mb > 0 && (
                      <div className="mt-1 flex justify-between text-[9px] text-slate-500">
                        <span>内存: {impactData.before.mem_mb}MB → {impactData.after?.mem_mb || "?"}MB</span>
                        <span>负载: {impactData.before.load_1m || "?"} → {impactData.after?.load_1m || "?"}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              <pre className="max-h-[28vh] overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs leading-6 text-slate-300">{proposalBody}</pre>
              <textarea value={note} onChange={e => setNote(e.target.value)} placeholder="审批/实施/验证备注" className="h-14 w-full rounded-lg border border-white/10 bg-slate-950 p-2 text-sm outline-none focus:border-cyan-400/60" />
              <div className="grid grid-cols-2 gap-1.5 sm:gap-2">
                <Action onClick={() => proposalAction("approve")} disabled={selectedStatus !== "pending"}>批准</Action>
                <Action onClick={() => proposalAction("reject")} disabled={selectedStatus !== "pending"} danger>拒绝</Action>
                <Action onClick={() => proposalAction("defer")} disabled={selectedStatus !== "pending"} icon={<Clock className="h-4 w-4" />}>搁置</Action>
                <Action onClick={proposalExec} disabled={selectedStatus !== "approved" || loading} icon={<Bot className="h-4 w-4" />}>自动实施</Action>
                <Action onClick={() => proposalAction("implement")} disabled={!["approved", "failed"].includes(selectedStatus)}>手动完成</Action>
                <Action onClick={autoVerify} disabled={!["implementing", "implemented", "failed"].includes(selectedStatus) || loading} icon={<Zap className="h-4 w-4" />}>自动验证</Action>
              </div>
              <div className="grid grid-cols-2 gap-1.5 sm:gap-2">
                <Action onClick={() => proposalAction("verify")} disabled={selectedStatus !== "implemented"}>验证通过</Action>
                <Action onClick={() => proposalAction("fail")} disabled={selectedStatus !== "implemented"} danger>验证失败</Action>
              </div>
            </div>
          ) : <div className="py-16 text-center text-sm text-slate-500">选择一个提案查看闭环操作</div>}
        </aside>
        )}
      </div>
    </div>
  </main>;
}

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) { return <div className="rounded-lg border border-white/10 bg-slate-950/50 p-3"><div className="text-lg font-semibold text-white">{value}</div><div className="text-[11px] text-slate-500">{label}</div></div>; }
function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) { return <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3 sm:p-4"><div className="mb-2 h-5 w-5 text-cyan-300">{icon}</div><div className="text-xl sm:text-2xl font-semibold text-white">{value}</div><div className="text-xs text-slate-500">{label}</div></div>; }
function Chart({ title, data }: { title: string; data: Record<string, number> }) { return <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4"><h3 className="mb-3 text-sm text-white">{title}</h3>{Object.keys(data).length ? Object.entries(data).map(([k, v]) => <div key={k} className="mb-2 flex items-center justify-between text-sm"><span className="text-slate-400">{statusMeta[k]?.label || k}</span><span className="text-cyan-200">{v}</span></div>) : <div className="text-sm text-slate-500">暂无数据</div>}</div>; }
function Action({ children, onClick, disabled, danger, icon }: { children: React.ReactNode; onClick: () => void; disabled?: boolean; danger?: boolean; icon?: React.ReactNode }) { return <button onClick={onClick} disabled={disabled} className={`flex items-center justify-center gap-1 rounded-lg px-2 sm:px-3 py-2 text-xs sm:text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 ${danger ? "bg-red-500/20 text-red-100 hover:bg-red-500/30" : "bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"}`}>{icon || <CheckCircle2 className="h-3.5 w-3.5 sm:h-4 sm:w-4" />}{children}</button>; }

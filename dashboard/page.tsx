"use client";
import { useEffect, useState, useCallback } from "react";

interface Report { date: string; size: number; size_kb: number }
interface Proposal { file: string; status: string; risk: string; score: number; title: string; source: string; url: string }

function getAuth() { return "Basic " + btoa("admin:" + (sessionStorage.getItem("admin_pwd") || "tqqadmin")); }

function renderMd(md: string): string {
  let h = md
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^> (.*)$/gm, '<blockquote>$1</blockquote>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>');
  return '<p>' + h + '</p>';
}

const STATUS_ICONS: Record<string, string> = {
  pending: "⏳", approved: "✅", rejected: "❌", implementing: "🔧",
  implemented: "📦", verified: "🎯", failed: "💥", rolled_back: "↩️",
};

const RISK_COLORS: Record<string, string> = {
  high: "#f85149", medium: "#d29922", low: "#3fb950",
};

export default function EvolutionPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [content, setContent] = useState("");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [constExists, setConstExists] = useState(false);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [detailFile, setDetailFile] = useState("");
  const [detailContent, setDetailContent] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [approveComment, setApproveComment] = useState("");
  const [approving, setApproving] = useState(false);
  const [approveResult, setApproveResult] = useState("");

  const load = useCallback(async (date?: string) => {
    setLoading(true);
    try {
      let url = "/api/evolution?_=" + Date.now();
      if (date) url += "&date=" + encodeURIComponent(date);
      const r = await fetch(url, { headers: { Authorization: getAuth() } });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      setReports(d.reports || []);
      setContent(d.latest || "");
      setProposals(d.proposals || []);
      setConstExists(d.constitution_exists);
      setTotal(d.total || 0);
    } catch { setContent("⚠️ 加载失败，请检查网络或刷新重试"); }
    setLoading(false);
  }, []);

  const loadDetail = async (file: string) => {
    setDetailFile(file);
    setDetailLoading(true);
    setDetailContent("");
    setApproveComment("");
    setApproveResult("");
    try {
      const r = await fetch("/api/proposal/" + encodeURIComponent(file) + "?_=" + Date.now(), { headers: { Authorization: getAuth() } });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      setDetailContent(d.content || "");
    } catch { setDetailContent("⚠️ 加载失败"); }
    setDetailLoading(false);
  };

  const doApprove = async (status: string) => {
    if (!detailFile) return;
    setApproving(true);
    setApproveResult("");
    try {
      const r = await fetch("/api/proposal/" + encodeURIComponent(detailFile) + "/approve?_=" + Date.now(), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: getAuth() },
        body: JSON.stringify({ status, comment: approveComment }),
      });
      const d = await r.json();
      if (d.ok) {
        setApproveResult(status === "approved" ? "✅ 已通过" : "❌ 已拒绝");
        setApproveComment("");
        load();
        const r2 = await fetch("/api/proposal/" + encodeURIComponent(detailFile) + "?_=" + Date.now(), { headers: { Authorization: getAuth() } });
        if (r2.ok) { const d2 = await r2.json(); setDetailContent(d2.content || ""); }
      } else {
        setApproveResult("❌ " + (d.error || "操作失败"));
      }
    } catch {
      setApproveResult("❌ 网络错误");
    }
    setApproving(false);
  };

  useEffect(() => { load(); }, [load]);

  const pendingCount = proposals.filter(p => p.status === "pending").length;
  const approvedCount = proposals.filter(p => p.status === "approved").length;

  return (
    <div style={s.page}>
      <h1 style={s.h1}>🧠 Hermes 进化日志</h1>
      <div style={s.stats}>
        <div style={s.statCard}>
          <div style={s.statNum}>{total}</div>
          <div style={s.statLabel}>学习报告</div>
        </div>
        <div style={s.statCard}>
          <div style={s.statNum}>{proposals.length}</div>
          <div style={s.statLabel}>提案</div>
        </div>
        <div style={s.statCard}>
          <div style={{...s.statNum, color: pendingCount ? "#d29922" : "var(--color-text-muted)"}}>{pendingCount}</div>
          <div style={s.statLabel}>待审批</div>
        </div>
        <div style={s.statCard}>
          <div style={s.statNum}>{constExists ? "✅" : "❌"}</div>
          <div style={s.statLabel}>宪法</div>
        </div>
      </div>

      <div style={s.main}>
        {/* Left: report list */}
        <div style={s.left}>
          <div style={s.sectionTitle}>📅 报告列表</div>
          <div style={s.dateList}>
            {reports.map(r => (
              <button key={r.date} onClick={() => { setSelectedDate(r.date); load(r.date); }}
                style={{...s.dateBtn, ...(selectedDate === r.date ? s.dateBtnActive : {})}}>
                {r.date} <span style={{fontSize:10,color:"var(--color-text-dim)"}}>{r.size_kb}KB</span>
              </button>
            ))}
            {reports.length === 0 && <div style={s.empty}>暂无报告</div>}
          </div>
        </div>

        {/* Center: report content */}
        <div style={s.center}>
          <div style={s.sectionTitle}>
            📄 {selectedDate || "最新报告"}
            <button onClick={() => load()} style={s.refreshBtn}>🔄</button>
          </div>
          {loading ? <div style={s.empty}>加载中...</div> :
            content ? <div style={s.reportBox} dangerouslySetInnerHTML={{__html: renderMd(content)}} /> :
            <div style={s.empty}>📭 今日无新发现</div>}
        </div>

        {/* Right: proposals */}
        <div style={s.right}>
          <div style={s.sectionTitle}>📋 提案 ({proposals.length})</div>
          <div style={s.proposalList}>
            {proposals.map(p => (
              <button key={p.file} onClick={() => loadDetail(p.file)}
                style={{...s.propBtn, borderColor: RISK_COLORS[p.risk] || "var(--color-border)"}}>
                <div style={s.propTop}>
                  <span>{STATUS_ICONS[p.status] || "❓"}</span>
                  <span style={{fontSize:11, color: RISK_COLORS[p.risk] || "var(--color-text-muted)"}}>{p.risk}</span>
                  <span style={{fontSize:11, color:"var(--color-text-dim)"}}>⭐{p.score}</span>
                </div>
                <div style={s.propTitle}>{p.title}</div>
                <div style={s.propDate}>{p.source}</div>
              </button>
            ))}
            {proposals.length === 0 && <div style={s.empty}>暂无提案</div>}
          </div>
        </div>
      </div>

      {/* Detail modal */}
      {detailFile && (
        <div style={s.modal} onClick={() => setDetailFile("")}>
          <div style={s.modalBox} onClick={e => e.stopPropagation()}>
            <div style={s.modalHeader}>
              <span>📋 提案详情</span>
              <button onClick={() => { setDetailFile(""); setApproveComment(""); setApproveResult(""); }} style={s.modalClose}>✕</button>
            </div>
            <div style={s.modalBody}>
              {detailLoading ? <div style={s.empty}>加载中...</div> :
                <div dangerouslySetInnerHTML={{__html: renderMd(detailContent)}} />}
              <div style={{borderTop:"1px solid var(--color-border)",marginTop:16,paddingTop:16}}>
                <div style={{fontSize:13,fontWeight:600,color:"var(--color-text-primary)",marginBottom:8}}>✍️ 审批意见</div>
                <textarea value={approveComment} onChange={e => setApproveComment(e.target.value)}
                  placeholder="输入审批意见（可选）..."
                  style={{width:"100%",minHeight:60,padding:10,borderRadius:6,border:"1px solid var(--color-border)",background:"var(--color-bg-primary)",color:"var(--color-text-primary)",fontSize:13,resize:"vertical",fontFamily:"inherit",boxSizing:"border-box"}} />
                <div style={{display:"flex",gap:8,marginTop:10}}>
                  <button onClick={() => doApprove("approved")} disabled={approving}
                    style={{flex:1,padding:"10px",borderRadius:6,border:"none",background:"var(--color-accent-green)",color:"#fff",cursor:approving?"default":"pointer",fontWeight:600,fontSize:13}}>
                    {approving ? "..." : "✅ 通过"}
                  </button>
                  <button onClick={() => doApprove("rejected")} disabled={approving}
                    style={{flex:1,padding:"10px",borderRadius:6,border:"1px solid var(--color-error-border)",background:"transparent",color:"var(--color-accent-red)",cursor:approving?"default":"pointer",fontWeight:600,fontSize:13}}>
                    {approving ? "..." : "❌ 拒绝"}
                  </button>
                </div>
                {approveResult && <div style={{marginTop:8,fontSize:13,textAlign:"center",color:approveResult.includes("✅")?"var(--color-accent-green)":"var(--color-accent-red)"}}>{approveResult}</div>}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  page: { minHeight:"100vh", background:"var(--color-bg-primary)", color:"var(--color-text-secondary)", padding:"40px 20px", fontFamily:"-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" },
  h1: { fontSize:24, fontWeight:600, color:"var(--color-text-primary)", marginBottom:20 },
  stats: { display:"flex", gap:12, marginBottom:24 },
  statCard: { flex:1, background:"var(--color-bg-secondary)", border:"1px solid var(--color-border)", borderRadius:10, padding:16, textAlign:"center" },
  statNum: { fontSize:28, fontWeight:700, color:"var(--color-accent-blue)" },
  statLabel: { fontSize:12, color:"var(--color-text-muted)", marginTop:4 },
  main: { display:"flex", gap:16 },
  left: { width:180, flexShrink:0 },
  center: { flex:1, minWidth:0 },
  right: { width:260, flexShrink:0 },
  sectionTitle: { fontSize:14, fontWeight:600, color:"var(--color-text-primary)", marginBottom:12, display:"flex", justifyContent:"space-between", alignItems:"center" },
  dateList: { display:"flex", flexDirection:"column", gap:4, maxHeight:"60vh", overflowY:"auto" },
  dateBtn: { display:"block", width:"100%", padding:"8px 12px", borderRadius:6, border:"1px solid var(--color-border)", background:"var(--color-bg-secondary)", color:"var(--color-text-secondary)", cursor:"pointer", fontSize:12, textAlign:"left" as const },
  dateBtnActive: { borderColor:"var(--color-accent-blue)", color:"var(--color-accent-blue)", background:"rgba(88,166,255,0.08)" },
  refreshBtn: { background:"none", border:"none", cursor:"pointer", fontSize:14, color:"var(--color-text-muted)" },
  reportBox: { background:"var(--color-bg-secondary)", border:"1px solid var(--color-border)", borderRadius:10, padding:24, fontSize:14, lineHeight:1.7, maxHeight:"65vh", overflowY:"auto" },
  proposalList: { display:"flex", flexDirection:"column", gap:6, maxHeight:"60vh", overflowY:"auto" },
  propBtn: { display:"block", width:"100%", padding:"10px 12px", borderRadius:8, border:"1px solid var(--color-border)", borderLeftWidth:3, background:"var(--color-bg-secondary)", cursor:"pointer", textAlign:"left" as const },
  propTop: { display:"flex", gap:8, alignItems:"center", marginBottom:4 },
  propTitle: { fontSize:12, fontWeight:600, color:"var(--color-text-primary)", marginBottom:2, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" as const },
  propDate: { fontSize:10, color:"var(--color-text-dim)" },
  empty: { textAlign:"center", color:"var(--color-text-dim)", padding:20, fontSize:13 },
  modal: { position:"fixed", inset:0, background:"rgba(0,0,0,0.6)", display:"flex", alignItems:"center", justifyContent:"center", zIndex:100 },
  modalBox: { background:"var(--color-bg-secondary)", border:"1px solid var(--color-border)", borderRadius:12, width:"90%", maxWidth:700, maxHeight:"80vh", overflow:"hidden", display:"flex", flexDirection:"column" as const },
  modalHeader: { display:"flex", justifyContent:"space-between", alignItems:"center", padding:"14px 20px", borderBottom:"1px solid var(--color-border)", fontSize:15, fontWeight:600, color:"var(--color-text-primary)" },
  modalClose: { background:"none", border:"none", color:"var(--color-text-muted)", cursor:"pointer", fontSize:18 },
  modalBody: { padding:20, overflowY:"auto", fontSize:13, lineHeight:1.7 },
};

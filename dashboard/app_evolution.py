# Flask routes for Hermes Self-Evolution dashboard
# Include these in your gateway-dashboard/app.py

@app.route("/api/evolution")
@require_auth
def api_evolution():
    """Return learning report list + latest report content + proposals."""
    learn_dir = os.path.expanduser("~/.hermes/learnings")
    reports = []
    if os.path.isdir(learn_dir):
        for f in sorted(os.listdir(learn_dir), reverse=True):
            if f.endswith(".md") and f != "INDEX.md":
                path = os.path.join(learn_dir, f)
                size = os.path.getsize(path)
                reports.append({
                    "date": f.replace(".md", ""),
                    "size": size,
                    "size_kb": round(size / 1024, 1),
                })

    # Load latest report content
    latest_content = ""
    if reports:
        latest_path = os.path.join(learn_dir, reports[0]["date"] + ".md")
        try:
            with open(latest_path) as fp:
                latest_content = fp.read()
        except Exception:
            pass

    # Load specific date if requested (safe: only allow YYYY-MM-DD format)
    req_date = request.args.get("date", "")
    if req_date:
        import re
        if re.match(r'^\d{4}-\d{2}-\d{2}$', req_date):
            date_path = os.path.join(learn_dir, req_date + ".md")
            if os.path.isfile(date_path):
                try:
                    with open(date_path, encoding="utf-8") as fp:
                        latest_content = fp.read()
                except Exception:
                    pass

    # Load proposals
    proposals = []
    proposals_dir = os.path.expanduser("~/.hermes/proposals")
    if os.path.isdir(proposals_dir):
        for fname in sorted(os.listdir(proposals_dir), reverse=True):
            if fname in ("INDEX.md", "TEMPLATE.md") or not fname.endswith(".md"):
                continue
            fpath = os.path.join(proposals_dir, fname)
            try:
                with open(fpath) as fp:
                    pcontent = fp.read()
            except Exception:
                continue
            # Parse YAML frontmatter
            pstatus = "unknown"
            prisk = "unknown"
            pscore = 0
            psource = ""
            purl = ""
            if pcontent.startswith("---"):
                end = pcontent.find("---", 3)
                if end > 0:
                    for line in pcontent[3:end].split("\n"):
                        line = line.strip()
                        if line.startswith("status:"):
                            pstatus = line.split(":", 1)[1].strip()
                        elif line.startswith("risk:"):
                            prisk = line.split(":", 1)[1].strip()
                        elif line.startswith("score:"):
                            try: pscore = int(line.split(":", 1)[1].strip())
                            except: pass
                        elif line.startswith("source_report:"):
                            psource = line.split(":", 1)[1].strip()
                        elif line.startswith("source_url:"):
                            purl = line.split(":", 1)[1].strip()
            # Extract title
            ptitle = "未命名"
            for line in pcontent.split("\n"):
                if line.startswith("# ") and "📋" in line:
                    ptitle = line[2:].replace("📋 ", "").strip()[:60]
                    break
            proposals.append({
                "file": fname,
                "status": pstatus,
                "risk": prisk,
                "score": pscore,
                "title": ptitle,
                "source": psource,
                "url": purl,
            })

    return jsonify({
        "reports": reports[:30],
        "total": len(reports),
        "latest": latest_content,
        "constitution_exists": os.path.exists(os.path.expanduser("~/.hermes/CONSTITUTION.md")),
        "proposals": proposals,
    })


@app.route("/admin/evolution")
@require_auth
def admin_evolution():
    return render_template_string(

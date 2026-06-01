# Proposal Pipeline — Hermes Learner V3.1

## Complete Self-Loop

```  
03:00 ── hermes-learner.service (systemd timer)  
         ├── Collect from AI HOT + GitHub + Arxiv  
         ├── Score & dedup  
         ├── Write daily report ~/.hermes/learnings/YYYY-MM-DD.md  
         ├── Generate proposals ~/.hermes/proposals/*.md (if score ≥7)  
         └── Update INDEX.md + health dashboard  
  
05:00 ── absorb-learnings-to-soul (agent cron, daily)  
         ├── Read new learnings via absorb_learnings.sh  
         ├── Agent evaluates → patches SOUL.md (append-only)  
         └── Updates marker file  
  
06:00 ── review-proposals (agent cron, daily)  
         ├── List pending proposals via list_pending_proposals.sh  
         ├── Agent reads each proposal  
         ├── Approves/rejects/defers  
         ├── Updates frontmatter status  
         └── Appends to REVIEWED.md  
```

## Proposal File Structure

```
~/.hermes/proposals/
├── INDEX.md           # Status-summary index, auto-updated
├── REVIEWED.md        # Human + AI review decision log
├── TEMPLATE.md        # Template for new proposals
├── 2026-05-25_slug_hash.md   # Individual proposals
```

### Frontmatter Fields

```yaml
---
status: pending          # pending → approved → implementing → implemented → verified
                         #        → rejected  → deferred
risk: medium             # low / medium / high
source_report: 2026-05-25
source_url: https://...
score: 7
category: GitHub 热榜     # Source type for filtering
approved_at: ~
implemented_at: ~
verified_at: ~
failure_reason: ~        # Filled when implementation fails
rollback_sha: ~          # Git SHA rolled back to
---
```

## File Locations

| Path | Purpose |
|------|---------|
| `/etc/systemd/system/hermes-learner.service` | Systemd oneshot service |
| `/etc/systemd/system/hermes-learner.timer` | Daily 03:00 timer |
| `~/.hermes/scripts/learn_eval_propose.sh` | Main learner script |
| `~/.hermes/scripts/absorb_learnings.sh` | Data collector for SOUL absorb |
| `~/.hermes/scripts/list_pending_proposals.sh` | Data collector for proposal review |
| `~/.hermes/learnings/` | Daily reports |
| `~/.hermes/learnings/seen_items.json` | Dedup across runs |
| `~/.hermes/proposals/` | Generated proposals |

## Cron Jobs (Hermes internal)

```bash
hermes cron list       # View all
hermes cron remove JOB_ID   # Remove a cron job
hermes cron run JOB_ID      # Test-run immediately
```

| ID | Name | Schedule | Type |  
|----|------|----------|------|  
| daily | absorb-learnings-to-soul | `0 5 * * *` (每日 05:00) | agent-mode (script output → agent acts) |  
| daily | review-proposals | `0 6 * * *` (每日 06:00) | agent-mode (script output → agent acts) |

## Health Dashboard

The `format_report()` function now injects a `## 📊 系统健康` table after the daily overview, showing:
- Pending / approved / rejected / deferred / implementing / implemented / verified / failed counts
- Total proposals
- Warning if pending > 50

## Proposal Dedup

`save_proposals()` in `hermes_learner.py`:
1. Scans existing proposals for `status: pending/approved/verified`
2. Extracts action texts (`- **ACTION** │ benefit: ...` pattern)
3. If ALL actions of a new finding exist, skips it
4. Otherwise marks the new actions as seen and writes

## Manual Debugging

```bash
# Test full pipeline (dry run)
cd ~/.hermes && python3 scripts/hermes_learner.py --dry-run

# Test single source
python3 scripts/hermes_learner.py --dry-run --source aihot
python3 scripts/hermes_learner.py --dry-run --source trending
python3 scripts/hermes_learner.py --dry-run --source arxiv

# Check systemd timer
systemctl list-timers --no-pager | grep learner

# View last run output
journalctl -u hermes-learner.service --no-pager
```

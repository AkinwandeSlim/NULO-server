# Nomba Integration — Implementation Tracker

> **Status**: ACTIVE development, deferred start until **June 24, 2026**

---

## 🎯 Overview

Nomba Virtual Accounts integration for NuloAfrica — enables multi-frequency rental payments (annual, semi-annual, quarterly, monthly) via virtual bank accounts.

## 📅 Timeline

| Milestone | Date | Status |
|---|---|---|
| Initial scaffold (service classes) | Pre-June 2026 | ✅ Done |
| Hackathon PRD drafted | Pre-June 2026 | ✅ Done |
| **Implementation start** | **June 24, 2026** | ⏳ Waiting |
| DB migrations + routes | TBD | ⏳ Pending |
| Webhook receiver | TBD | ⏳ Pending |
| Client UI integration | TBD | ⏳ Pending |
| Reconciliation engine wiring | TBD | ⏳ Pending |

---

## 📂 Current Codebase State

### Existing Service Files (DO NOT DELETE)

All 3 files have **STATUS banners** in their docstrings.

| File | Status | Purpose |
|---|---|---|
| `server/app/services/nomba_client.py` | ✅ Scaffolded | Nomba API client wrapper |
| `server/app/services/payment_scheduler.py` | ✅ Scaffolded | Multi-frequency payment calendar |
| `server/app/services/reconciliation.py` | ✅ Scaffolded | Payment reconciliation engine |

### Missing Components (TO BE CREATED)

| File | Purpose | Priority |
|---|---|---|
| `server/app/routes/nomba.py` | FastAPI router for Nomba endpoints | P1 |
| DB migration: `virtual_accounts` | Store per-agreement virtual accounts | P1 |
| DB migration: `virtual_account_transfers` | Track inbound payments | P1 |
| DB migration: `payment_reconciliation_log` | Audit trail for matches | P1 |
| Register router in `server/app/main.py` | Wire endpoint to FastAPI | P1 |
| `client/lib/api/payments.ts` updates | Handle Nomba response shapes | P1 |
| Webhook receiver endpoint | Receive Nomba transfer notifications | P1 |
| Cron job / scheduler | Run periodic reconciliation | P2 |

---

## 📚 Reference Documents

| Document | Path |
|---|---|
| Master Nomba PRD | [docs/prd/MASTER_PRD_NOMBA_INTEGRATION.md](docs/prd/MASTER_PRD_NOMBA_INTEGRATION.md) |
| Hackathon PRD Final | [docs/prd/NULOAFRICA_NOMBA_PRD_HACKATHON_FINAL.md](docs/prd/NULOAFRICA_NOMBA_PRD_HACKATHON_FINAL.md) |
| Nomba vs Paystack Comparison | [docs/architecture/PAYSTACK_NOMBA_COMPARISON.md](docs/architecture/PAYSTACK_NOMBA_COMPARISON.md) |
| Paystack Architecture Audit | [docs/architecture/PAYSTACK_ARCHITECTURE_AUDIT.md](docs/architecture/PAYSTACK_ARCHITECTURE_AUDIT.md) |

---

## 🔑 Environment Variables Required

```bash
# .env (add these when starting implementation)
NOMBA_API_KEY=<your-nomba-api-key>
NOMBA_SECRET_KEY=<your-nomba-secret-key>
NOMBA_API_URL=https://api.nomba.com/v1
NOMBA_MERCHANT_ID=<your-merchant-id>
NOMBA_WEBHOOK_SECRET=<webhook-signing-secret>
```

---

## ✅ Pre-Start Checklist (Before June 24)

- [ ] Review MASTER_PRD_NOMBA_INTEGRATION.md sections 6.1–6.3
- [ ] Confirm Nomba sandbox credentials from hackathon organizers
- [ ] Decide on payment frequency defaults per PRD
- [ ] Plan database schema (virtual_accounts, etc.)
- [ ] Design webhook signature verification
- [ ] Sketch client UI for showing virtual account numbers to tenants

---

## 🚫 DO NOT

- ❌ **Do not delete the 3 Nomba service files** — they're needed
- ❌ **Do not integrate into main routes yet** — wait for June 24
- ❌ **Do not add the router to main.py** — would expose unimplemented endpoints
- ❌ **Do not run migrations** — schema not finalized

---

## 📞 Decision Points

When implementation starts, key questions to resolve:

1. **Webhook receiver location**: New route file or extend `payments.py`?
2. **Virtual account lifecycle**: Created on agreement activation or application approval?
3. **Reconciliation cadence**: Real-time, hourly, or daily cron?
4. **Multi-frequency defaults**: Make frequency landlord-configurable per agreement?
5. **Paystack fallback**: Keep Paystack as backup or migrate fully to Nomba?

---

*Last updated: June 19, 2026*
*Next review: June 24, 2026 (implementation kickoff)*

# `dev_tests/` — Development & Testing Sandbox

**Purpose**: This directory contains test files, demo scripts, and experimental code that is **NOT part of production**.

## ⚠️ Important Rules

1. **NEVER** import from this directory in production code (`app/`, `routes/`, `services/`)
2. **NEVER** reference these files in deployment scripts or CI/CD
3. These files are excluded from the build via `.gitignore`
4. Only accessible in development (`DEBUG=True`)

## 📂 Structure

```
dev_tests/
├── api/           # FastAPI test routers (formerly app/api/test/)
├── scripts/       # Standalone test scripts (test_*.py)
├── utils/         # Utility/helper scripts (check_*.py, create_*.py, debug_*.py)
├── sql/           # SQL test/seed files
└── README.md      # This file
```

## 🚫 Excluded from Production

The `dev_tests/` directory is added to `.gitignore` to prevent accidental deployment.

## 🧪 When to Use

- Testing AI integrations
- Debugging database connections
- Creating test data
- QA testing without affecting production

## 🗑️ When to Remove

- After a feature is tested and promoted to production
- When the test data is no longer relevant
- Before major releases to keep the repo clean

## 📝 Adding New Test Files

1. Choose appropriate subdirectory (api/scripts/utils/sql)
2. Document the purpose in file docstring
3. **DO NOT** add to production routing or imports

## 🔒 Security Note

Some files in this directory (like `generate_qa_token.py`) contain sensitive information.
Never commit real tokens or credentials to this directory.

---

**Last Updated**: Phase P1.1-Server Remediation (June 2026)
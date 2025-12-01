#!/bin/bash
# =============================================================================
# Install Git Hooks
# =============================================================================
# Run this script after cloning the repository to set up security hooks.
# Usage: ./scripts/install-hooks.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="$PROJECT_DIR/.git/hooks"

echo "🔧 Installing git hooks..."

# Create hooks directory if it doesn't exist
mkdir -p "$HOOKS_DIR"

# Create the pre-commit hook
cat > "$HOOKS_DIR/pre-commit" << 'HOOK_CONTENT'
#!/bin/bash
# =============================================================================
# PRE-COMMIT HOOK: Prevent accidental API key commits
# =============================================================================

set -e

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'
BOLD='\033[1m'

echo ""
echo -e "${BOLD}🔒 Security Check: Scanning for API keys...${NC}"

PATTERNS=(
    'AIza[0-9A-Za-z_-]{35}'
    'api[_-]?key["\s]*[:=]["\s]*["\x27][A-Za-z0-9_-]{20,}["\x27]'
    'AKIA[0-9A-Z]{16}'
    'BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY'
)

FOUND_SECRETS=0
ISSUES=""

STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)

if [ -z "$STAGED_FILES" ]; then
    echo -e "${GREEN}✓ No files to check${NC}"
    exit 0
fi

for FILE in $STAGED_FILES; do
    if [[ "$FILE" =~ \.(png|jpg|jpeg|gif|ico|pdf|zip|gz|tar|woff|woff2|ttf|eot)$ ]]; then
        continue
    fi

    if [ ! -f "$FILE" ]; then
        continue
    fi

    for PATTERN in "${PATTERNS[@]}"; do
        MATCHES=$(git show ":$FILE" 2>/dev/null | grep -nE "$PATTERN" 2>/dev/null || true)
        if [ -n "$MATCHES" ]; then
            FOUND_SECRETS=1
            ISSUES="${ISSUES}\n${RED}✗ ${FILE}${NC}\n"
            while IFS= read -r line; do
                LINE_NUM=$(echo "$line" | cut -d: -f1)
                PREVIEW=$(echo "$line" | cut -d: -f2- | head -c 60)
                ISSUES="${ISSUES}  Line ${LINE_NUM}: ${PREVIEW}...${NC}\n"
            done <<< "$MATCHES"
        fi
    done
done

# Check for .env files (but allow .env.example templates)
ENV_FILES=$(echo "$STAGED_FILES" | grep -E '^\.env' | grep -v '\.env\.example$' || true)
if [ -n "$ENV_FILES" ]; then
    FOUND_SECRETS=1
    for FILE in $ENV_FILES; do
        ISSUES="${ISSUES}\n${RED}✗ ${FILE}${NC} - .env files should NEVER be committed!\n"
    done
fi

if [ $FOUND_SECRETS -eq 1 ]; then
    echo ""
    echo -e "${RED}${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}${BOLD}║  🚨 COMMIT BLOCKED: Potential secrets detected!            ║${NC}"
    echo -e "${RED}${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
    echo -e "${YELLOW}Issues found:${NC}"
    echo -e "$ISSUES"
    echo -e "${YELLOW}Use ${BOLD}git commit --no-verify${NC}${YELLOW} to bypass (with caution!)${NC}"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ No secrets detected${NC}"
exit 0
HOOK_CONTENT

chmod +x "$HOOKS_DIR/pre-commit"

echo "✅ Pre-commit hook installed successfully!"
echo ""
echo "The hook will now scan for API keys before each commit."
echo "If you need to bypass it (not recommended), use: git commit --no-verify"

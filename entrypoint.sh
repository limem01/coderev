#!/bin/bash
set -e

echo "🔍 CodeRev AI Code Review"
echo "========================="

# Check for required environment variables
if [[ -z "$ANTHROPIC_API_KEY" && -z "$OPENAI_API_KEY" ]]; then
    echo "❌ Error: Either ANTHROPIC_API_KEY or OPENAI_API_KEY must be set"
    exit 1
fi

if [[ -z "$GITHUB_TOKEN" ]]; then
    echo "❌ Error: GITHUB_TOKEN is required"
    exit 1
fi

# Parse environment variables
MODEL="${CODEREV_MODEL:-claude-3-sonnet-20240229}"
FOCUS="${CODEREV_FOCUS:-bugs,security,performance}"
FAIL_ON="${CODEREV_FAIL_ON:-}"
POST_REVIEW="${CODEREV_POST_REVIEW:-true}"
MAX_FILES="${CODEREV_MAX_FILES:-20}"
IGNORE_PATTERNS="${CODEREV_IGNORE_PATTERNS:-*.test.*,*.spec.*,*.min.js,*.min.css}"
REVIEW_EVENT="${CODEREV_REVIEW_EVENT:-auto}"

# Get PR information from GitHub event
if [[ -f "$GITHUB_EVENT_PATH" ]]; then
    PR_NUMBER=$(jq -r '.pull_request.number // .number // empty' "$GITHUB_EVENT_PATH")
    REPO_FULL_NAME=$(jq -r '.repository.full_name // empty' "$GITHUB_EVENT_PATH")
    BASE_SHA=$(jq -r '.pull_request.base.sha // empty' "$GITHUB_EVENT_PATH")
    HEAD_SHA=$(jq -r '.pull_request.head.sha // empty' "$GITHUB_EVENT_PATH")
else
    echo "❌ Error: GITHUB_EVENT_PATH not found"
    exit 1
fi

if [[ -z "$PR_NUMBER" ]]; then
    echo "❌ Error: Could not determine PR number. This action must run on pull_request events."
    exit 1
fi

echo "📋 PR #${PR_NUMBER} in ${REPO_FULL_NAME}"
echo "📝 Model: ${MODEL}"
echo "🎯 Focus: ${FOCUS}"

# Get the list of changed files
CHANGED_FILES=$(curl -s -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/${REPO_FULL_NAME}/pulls/${PR_NUMBER}/files" | \
    jq -r '.[].filename')

if [[ -z "$CHANGED_FILES" ]]; then
    echo "ℹ️ No files changed in this PR"
    echo "score=100" >> "$GITHUB_OUTPUT"
    echo "issues_count=0" >> "$GITHUB_OUTPUT"
    echo "critical_count=0" >> "$GITHUB_OUTPUT"
    echo "high_count=0" >> "$GITHUB_OUTPUT"
    echo "medium_count=0" >> "$GITHUB_OUTPUT"
    echo "low_count=0" >> "$GITHUB_OUTPUT"
    exit 0
fi

# Filter files based on ignore patterns
filter_files() {
    local files="$1"
    local patterns="$2"
    
    IFS=',' read -ra PATTERN_ARRAY <<< "$patterns"
    
    while IFS= read -r file; do
        local skip=false
        for pattern in "${PATTERN_ARRAY[@]}"; do
            pattern=$(echo "$pattern" | xargs) # trim whitespace
            if [[ "$file" == $pattern ]]; then
                skip=true
                break
            fi
        done
        if [[ "$skip" == false ]]; then
            echo "$file"
        fi
    done <<< "$files"
}

FILTERED_FILES=$(filter_files "$CHANGED_FILES" "$IGNORE_PATTERNS")

# Limit number of files
if [[ "$MAX_FILES" -gt 0 ]]; then
    FILTERED_FILES=$(echo "$FILTERED_FILES" | head -n "$MAX_FILES")
fi

FILE_COUNT=$(echo "$FILTERED_FILES" | grep -c . || echo "0")
echo "📁 Reviewing ${FILE_COUNT} files"

# Create a temporary config file
CONFIG_FILE=$(mktemp /tmp/coderev_config.XXXXXX.toml)
cat > "$CONFIG_FILE" << EOF
[coderev]
model = "$MODEL"
focus = [$(echo "$FOCUS" | sed 's/,/", "/g' | sed 's/^/"/' | sed 's/$/"/' )]

[github]
token = "$GITHUB_TOKEN"
EOF

# Set the API key based on model type
if [[ "$MODEL" == gpt-* ]]; then
    export CODEREV_API_KEY="$OPENAI_API_KEY"
    echo "provider = \"openai\"" >> "$CONFIG_FILE"
else
    export CODEREV_API_KEY="$ANTHROPIC_API_KEY"
fi

# Clone the repo and checkout the PR
cd "$GITHUB_WORKSPACE" || exit 1

# Build coderev command arguments
FOCUS_ARGS=""
IFS=',' read -ra FOCUS_ARRAY <<< "$FOCUS"
for f in "${FOCUS_ARRAY[@]}"; do
    FOCUS_ARGS="$FOCUS_ARGS --focus $(echo $f | xargs)"
done

FAIL_ON_ARG=""
if [[ -n "$FAIL_ON" ]]; then
    FAIL_ON_ARG="--fail-on $FAIL_ON"
fi

# Run the review using the PR command
echo ""
echo "🤖 Running AI code review..."
echo ""

# Create output file for JSON results
OUTPUT_FILE=$(mktemp /tmp/coderev_output.XXXXXX.json)

# Run coderev pr command
PR_URL="https://github.com/${REPO_FULL_NAME}/pull/${PR_NUMBER}"
POST_FLAG=""
if [[ "$POST_REVIEW" == "true" ]]; then
    POST_FLAG="--post-comments"
fi

set +e
coderev pr "$PR_URL" \
    $FOCUS_ARGS \
    --format json \
    $POST_FLAG \
    2>&1 | tee /tmp/coderev_log.txt

CODEREV_EXIT_CODE=${PIPESTATUS[0]}
set -e

# Parse the JSON output from the log
REVIEW_JSON=$(grep -o '{.*}' /tmp/coderev_log.txt | tail -1 || echo '{}')

# Extract metrics from the review
SCORE=$(echo "$REVIEW_JSON" | jq -r '.score // 0')
ISSUES_COUNT=$(echo "$REVIEW_JSON" | jq -r '.issues | length // 0')
CRITICAL_COUNT=$(echo "$REVIEW_JSON" | jq -r '[.issues[]? | select(.severity == "critical")] | length // 0')
HIGH_COUNT=$(echo "$REVIEW_JSON" | jq -r '[.issues[]? | select(.severity == "high")] | length // 0')
MEDIUM_COUNT=$(echo "$REVIEW_JSON" | jq -r '[.issues[]? | select(.severity == "medium")] | length // 0')
LOW_COUNT=$(echo "$REVIEW_JSON" | jq -r '[.issues[]? | select(.severity == "low")] | length // 0')

# Output to GitHub Actions
echo ""
echo "📊 Review Results"
echo "================"
echo "  Score: ${SCORE}/100"
echo "  Total Issues: ${ISSUES_COUNT}"
echo "    Critical: ${CRITICAL_COUNT}"
echo "    High: ${HIGH_COUNT}"
echo "    Medium: ${MEDIUM_COUNT}"
echo "    Low: ${LOW_COUNT}"

# Set outputs
echo "score=${SCORE}" >> "$GITHUB_OUTPUT"
echo "issues_count=${ISSUES_COUNT}" >> "$GITHUB_OUTPUT"
echo "critical_count=${CRITICAL_COUNT}" >> "$GITHUB_OUTPUT"
echo "high_count=${HIGH_COUNT}" >> "$GITHUB_OUTPUT"
echo "medium_count=${MEDIUM_COUNT}" >> "$GITHUB_OUTPUT"
echo "low_count=${LOW_COUNT}" >> "$GITHUB_OUTPUT"

# Get review URL if posted
if [[ "$POST_REVIEW" == "true" ]]; then
    REVIEW_URL="${PR_URL}#pullrequestreview"
    echo "review_url=${REVIEW_URL}" >> "$GITHUB_OUTPUT"
    echo ""
    echo "✅ Review posted to PR"
fi

# Cleanup
rm -f "$CONFIG_FILE" "$OUTPUT_FILE"

# Check fail condition
if [[ -n "$FAIL_ON" ]]; then
    case "$FAIL_ON" in
        critical)
            [[ "$CRITICAL_COUNT" -gt 0 ]] && exit 1
            ;;
        high)
            [[ "$CRITICAL_COUNT" -gt 0 || "$HIGH_COUNT" -gt 0 ]] && exit 1
            ;;
        medium)
            [[ "$CRITICAL_COUNT" -gt 0 || "$HIGH_COUNT" -gt 0 || "$MEDIUM_COUNT" -gt 0 ]] && exit 1
            ;;
        low)
            [[ "$ISSUES_COUNT" -gt 0 ]] && exit 1
            ;;
    esac
fi

echo ""
echo "✨ CodeRev complete!"
exit 0

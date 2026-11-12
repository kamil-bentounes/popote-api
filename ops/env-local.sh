#!/usr/bin/env bash
# Écrit .env depuis la pile Supabase locale (clés de démonstration, pas des secrets).
set -euo pipefail
cd "$(dirname "$0")/.."
eval "$(npx supabase status -o env 2>/dev/null | grep -E '^(API_URL|ANON_KEY|SERVICE_ROLE_KEY)=')"
cat > .env <<ENV
VITE_SUPABASE_URL=$API_URL
VITE_SUPABASE_ANON_KEY=$ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY
POPOTE_ENV=local
ENV
echo ".env écrit pour $API_URL"

#!/usr/bin/env bash
# Essai de bout en bout de sauvegarde.sh contre la pile Supabase LOCALE (déjà démarrée ; ce script ne la
# lance, ne l'arrête et ne la réinitialise pas). Une clé `age` jetable, un seau d'essai et deux objets :
# on sauvegarde en mode --local-seulement, puis on déchiffre et on vérifie. Tout est effacé à la sortie.
#
#   bash ops/env-local.sh && bash ops/sauvegarde/essai-local.sh
#
# Demande : age, age-keygen, un client PostgreSQL 17 (pg_dump, pg_dumpall, pg_restore, psql), node, curl.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# Cet essai écrit dans la base visée (un seau, deux objets) : il ne vise que la pile locale.
export PGHOST=${PGHOST:-127.0.0.1} PGPORT=${PGPORT:-54322} PGUSER=${PGUSER:-postgres}
export PGPASSWORD=${PGPASSWORD:-postgres} PGDATABASE=${PGDATABASE:-postgres}
case "$PGHOST" in 127.0.0.1 | localhost) ;; *) echo "essai-local: pile locale seulement (PGHOST=$PGHOST)" >&2; exit 2 ;; esac
set -a; . ./.env; set +a
export SUPABASE_URL=$VITE_SUPABASE_URL SUPABASE_SECRET_KEY=$SUPABASE_SERVICE_ROLE_KEY
case "$SUPABASE_URL" in http://127.0.0.1:* | http://localhost:*) ;; *) echo "essai-local: pile locale seulement" >&2; exit 2 ;; esac

travail=$(mktemp -d)
seau=essai-sauvegarde-$$
api() { # api <méthode> <chemin> [curl…] ; une clé JWT locale va en apikey et en Bearer
  local methode=$1 chemin=$2; shift 2
  curl -fsS -X "$methode" -H "apikey: $SUPABASE_SECRET_KEY" -H "Authorization: Bearer $SUPABASE_SECRET_KEY" \
    "$SUPABASE_URL/storage/v1$chemin" "$@"
}
nettoie() {
  api DELETE "/object/$seau/dossier/un.txt" > /dev/null 2>&1 || true
  api DELETE "/object/$seau/deux.bin" > /dev/null 2>&1 || true
  api DELETE "/bucket/$seau" > /dev/null 2>&1 || true
  rm -rf "$travail"
}
trap nettoie EXIT

ok() { echo "essai-local: ok  - $1"; }
ko() { echo "essai-local: KO  - $1" >&2; exit 1; }

# --- La préparation : une clé jetable, un seau, deux objets ------------------------------------------
age-keygen -o "$travail/cle.txt" 2> /dev/null
age-keygen -y "$travail/cle.txt" > "$travail/destinataires.txt"
age-keygen -o "$travail/autre-cle.txt" 2> /dev/null
marque=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf 'contenu-un-%s' "$marque" > "$travail/un.txt"
head -c 3000 /dev/urandom > "$travail/deux.bin"
api POST /bucket -H 'Content-Type: application/json' -d "{\"id\":\"$seau\",\"name\":\"$seau\",\"public\":false}" > /dev/null
api POST "/object/$seau/dossier/un.txt" -H 'Content-Type: text/plain' --data-binary "@$travail/un.txt" > /dev/null
api POST "/object/$seau/deux.bin" -H 'Content-Type: application/octet-stream' --data-binary "@$travail/deux.bin" > /dev/null

# --- La sauvegarde --------------------------------------------------------------------------------------
export CIBLE=essai DESTINATAIRES=$travail/destinataires.txt
bash ops/sauvegarde/sauvegarde.sh --local-seulement "$travail/sortie" > "$travail/journal.txt" 2>&1 ||
  { cat "$travail/journal.txt" >&2; ko "la sauvegarde a échoué"; }
archives=("$travail"/sortie/*)
archive=${archives[0]}
[[ ${#archives[@]} -eq 1 && "$archive" == */popote-*.tar.age && -s "$archive" ]] || ko "il fallait une seule archive popote-<date>.tar.age non vide"
ok "une archive non vide, nommée popote-<date>.tar.age"

# --- Elle se déchiffre, et elle contient le dump, les comptes et les fichiers ----------------------------
mkdir "$travail/clair"
age -d -i "$travail/cle.txt" "$archive" | tar -x -C "$travail/clair" --no-same-owner
for f in base.dump roles.sql comptes.txt meta.txt seaux/index.jsonl; do
  [ -f "$travail/clair/$f" ] || ko "absent de l'archive : $f"
done
ok "déchiffrée avec la clé jetable : dump, rôles, comptes, méta, index des fichiers"
pg_restore -l < "$travail/clair/base.dump" > "$travail/liste.txt"
grep -q ' TABLE DATA public ' "$travail/liste.txt" || ko "le dump n'a pas de données de public"
grep -q ' TABLE DATA auth users ' "$travail/liste.txt" || ko "le dump n'a pas auth.users"
ok "le dump liste les données de public et d'auth"
for schema in public auth storage; do
  grep -q "^$schema\." "$travail/clair/comptes.txt" || ko "aucun compte pour $schema"
done
objets=$(awk -F'\t' '$1 == "storage.objects" { print $2 }' "$travail/clair/comptes.txt")
[ "$objets" -ge 2 ] && [ "$objets" = "$(wc -l < "$travail/clair/seaux/index.jsonl")" ] ||
  ko "le manifeste dit $objets objets, l'index en liste $(wc -l < "$travail/clair/seaux/index.jsonl")"
ok "le manifeste compte les trois schémas et $objets objets, autant que l'index"
cmp "$travail/un.txt" "$travail/clair/seaux/fichiers/$seau/dossier/un.txt" || ko "un.txt copié diffère de l'original"
cmp "$travail/deux.bin" "$travail/clair/seaux/fichiers/$seau/deux.bin" || ko "deux.bin copié diffère de l'original"
ok "les deux fichiers du seau d'essai sont retrouvés à l'identique"

# --- Rien en clair, ni dans l'archive, ni dans le journal ------------------------------------------------
! grep -qa "$marque" "$archive" || ko "le contenu d'un fichier est lisible dans l'archive"
! age -d -i "$travail/autre-cle.txt" "$archive" > /dev/null 2>&1 || ko "une autre clé déchiffre l'archive"
ok "contenu illisible dans l'archive ; une autre clé ne la déchiffre pas"
! grep -aqE "$marque|un\.txt|deux\.bin|@|$seau" "$travail/journal.txt" || ko "le journal contient une donnée"
grep -q '^sauvegarde:   public\.' "$travail/journal.txt" || ko "le journal ne donne pas les comptes"
ok "le journal donne des tailles et des comptes, aucune valeur ni nom d'objet"

# --- Les refus ------------------------------------------------------------------------------------------
refus() { # refus <description> <motif attendu dans le message> <VAR=valeur…>
  local description=$1 motif=$2; shift 2
  if env "$@" bash ops/sauvegarde/sauvegarde.sh --local-seulement "$travail/refus" > "$travail/refus.txt" 2>&1; then
    ko "$description : la sauvegarde aurait dû échouer"
  fi
  grep -q "$motif" "$travail/refus.txt" || { cat "$travail/refus.txt" >&2; ko "$description : message inattendu"; }
  ok "$description"
}
echo 'AGE-SECRET-KEY-1NOTAREALKEY' > "$travail/privee.txt"
: > "$travail/vide.txt"
refus "destinataires absents" "introuvables ou vides" DESTINATAIRES="$travail/absent.txt"
refus "destinataires vides" "introuvables ou vides" DESTINATAIRES="$travail/vide.txt"
refus "clé privée parmi les destinataires" "clé privée" DESTINATAIRES="$travail/privee.txt"
refus "cible inconnue" "prod ou essai" CIBLE=recette
refus "variable manquante" "variables manquantes : PGPASSWORD" PGPASSWORD=
[ ! -e "$travail/refus" ] || ko "un refus a laissé une sortie"
echo "essai-local: tout est vert"

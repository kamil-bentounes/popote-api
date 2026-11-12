#!/usr/bin/env bash
# Essai de restauration (spec § 5.4, amendement 8) : rejoue une sauvegarde DÉCHIFFRÉE sur une pile Supabase
# LOCALE NEUVE, puis compare chaque compte au manifeste. Tout écart fait échouer.
#
#   restaure.sh <dossier de la sauvegarde déchiffrée et extraite>
#
# La pile (`supabase start`) a déjà appliqué les migrations du dépôt. Ce script :
#   1. vérifie que la pile est locale, neuve, et au niveau des migrations du dépôt ;
#   2. vide les tables à restaurer (les migrations y ont pu semer des lignes) ;
#   3. `pg_restore --data-only --disable-triggers` en `supabase_admin` (super-utilisateur local) des
#      données de `public` et d'`auth`, et de `storage.buckets` seulement ;
#   4. redépose les fichiers par l'API Storage locale, qui recrée `storage.objects` ;
#   5. compare les comptes au manifeste.
# Ne sont pas restaurées : `auth.schema_migrations` et les tables propres à Storage (sauf `buckets`) :
# elles appartiennent aux services de la pile, qui les tiennent à jour.
#
# Lit (défauts : la pile locale) : PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE, SUPABASE_URL,
# SUPABASE_SECRET_KEY (obligatoire : la clé de service locale, `supabase status -o env`).
# Le journal ne contient que des noms de tables et des totaux : jamais le compte d'une table.
set -euo pipefail
umask 077

racine=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
dossier=${1:-}
[ -d "$dossier" ] || { echo "usage : $0 <dossier de la sauvegarde extraite>" >&2; exit 2; }
dossier=$(cd "$dossier" && pwd)

echoue() { echo "restauration: $*" >&2; exit 1; }

export PGHOST=${PGHOST:-127.0.0.1} PGPORT=${PGPORT:-54322} PGUSER=${PGUSER:-supabase_admin}
export PGPASSWORD=${PGPASSWORD:-postgres} PGDATABASE=${PGDATABASE:-postgres}
export SUPABASE_URL=${SUPABASE_URL:-http://127.0.0.1:54321}
[ -n "${SUPABASE_SECRET_KEY:-}" ] || echoue "SUPABASE_SECRET_KEY manquante (clé de service de la pile locale)"
export SUPABASE_SECRET_KEY

# Ce script vide des tables : il ne vise jamais autre chose qu'une pile locale. Pas de contournement.
case "$PGHOST" in 127.0.0.1 | localhost | ::1) ;; *) echoue "PGHOST doit désigner la pile locale" ;; esac
case "$SUPABASE_URL" in http://127.0.0.1[:/]* | http://localhost[:/]*) ;; *) echoue "SUPABASE_URL doit désigner la pile locale" ;; esac

for outil in pg_restore psql node awk; do command -v "$outil" > /dev/null || echoue "outil absent : $outil"; done
for f in base.dump comptes.txt meta.txt seaux/index.jsonl; do
  [ -f "$dossier/$f" ] || echoue "absent de la sauvegarde : $f"
done

travail=$(mktemp -d)
trap 'rm -rf "$travail"' EXIT
# (Les NOTICE de TRUNCATE ... CASCADE n'apprennent rien : on ne garde que les avertissements.)
sql() { PGOPTIONS='-c client_min_messages=warning' psql --no-psqlrc -X -q -A -t -F $'\t' -v ON_ERROR_STOP=1 "$@"; }

# --- Ce que la sauvegarde contient, et ce qu'on en restaure -------------------------------------------
# Les noms viennent d'une archive : on n'en accepte que la forme d'un identifiant simple.
awk -F'\t' '$1 !~ /^(public|auth|storage)\.[A-Za-z0-9_]+$/ || $2 !~ /^[0-9]+$/ { bad = 1 } END { exit bad }' \
  "$dossier/comptes.txt" || echoue "le manifeste contient une ligne qui n'est pas « schéma.table<TAB>compte »"
# À restaurer : public et auth, sauf auth.schema_migrations, et storage.buckets.
LC_ALL=C sort "$dossier/comptes.txt" > "$travail/manifeste.txt"
awk -F'\t' '$1 ~ /^(public|auth)\./ && $1 != "auth.schema_migrations" || $1 == "storage.buckets" { print $1 }' \
  "$travail/manifeste.txt" > "$travail/a-restaurer.txt"
# À comparer : ces tables, plus storage.objects (recréée par l'API Storage).
awk -F'\t' '$1 ~ /^(public|auth)\./ && $1 != "auth.schema_migrations" || $1 == "storage.buckets" || $1 == "storage.objects"' \
  "$travail/manifeste.txt" > "$travail/attendu.txt"
[ -s "$travail/a-restaurer.txt" ] || echoue "rien à restaurer dans le manifeste"
grep -qx 'storage.objects' <(cut -f1 "$travail/attendu.txt") || echoue "storage.objects absent du manifeste"

# --- 1. La pile : neuve, au niveau des migrations du dépôt ---------------------------------------------
appliquees=$(sql -c "select count(*) from supabase_migrations.schema_migrations") ||
  echoue "la pile ne répond pas, ou n'a pas de table de migrations"
attendues=$(find "$racine/supabase/migrations" -maxdepth 1 -name '*.sql' | wc -l)
[ "$appliquees" = "$attendues" ] || echoue "$appliquees migrations appliquées, $attendues dans le dépôt : pile à refaire"
[ "$(sql -c "select count(*) from storage.objects")" = 0 ] || echoue "storage.objects n'est pas vide : la pile n'est pas neuve"

# Chaque table à restaurer doit exister dans la pile ; l'inverse (une table de plus dans la pile) n'est
# qu'un avertissement : le dépôt peut être en avance sur la base sauvegardée.
absentes=()
while IFS= read -r table; do
  [ "$(sql -c "select to_regclass('$table') is not null")" = t ] || absentes+=("$table")
done < "$travail/a-restaurer.txt"
[ ${#absentes[@]} -eq 0 ] || echoue "tables de la sauvegarde absentes de la pile (migrations différentes) : ${absentes[*]}"
sql -c "select n.nspname || '.' || c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
         where n.nspname in ('public', 'auth') and c.relkind = 'r' and c.relname <> 'schema_migrations' order by 1" |
  LC_ALL=C sort | LC_ALL=C comm -23 - <(LC_ALL=C sort "$travail/a-restaurer.txt") > "$travail/en-plus.txt"
if [ -s "$travail/en-plus.txt" ]; then
  echo "restauration: avertissement, tables de la pile absentes de la sauvegarde : $(paste -sd' ' "$travail/en-plus.txt")"
fi
echo "restauration: pile neuve, $appliquees migrations, $(wc -l < "$travail/a-restaurer.txt") tables à restaurer"

# --- 2. Vider les tables à restaurer -------------------------------------------------------------------
liste_sql=$(awk -F. '{ printf "%s\"%s\".\"%s\"", sep, $1, $2; sep = ", " }' "$travail/a-restaurer.txt")
sql -c "truncate table $liste_sql cascade" > /dev/null

# --- 3. Les données, en supabase_admin -----------------------------------------------------------------
# On n'extrait de la table des matières du dump que les entrées voulues : données et valeurs de séquences
# de public et d'auth (sauf schema_migrations), et la table des seaux.
pg_restore --list "$dossier/base.dump" > "$travail/matieres.txt"
awk -v voulues="$travail/a-restaurer.txt" '
  BEGIN { while ((getline t < voulues) > 0) voulue[t] = 1 }
  # « 4242; 0 16385 TABLE DATA public household owner » et « …; 0 0 SEQUENCE SET public household_id_seq owner »
  $4 == "TABLE" && $5 == "DATA" { if (($6 "." $7) in voulue) { print; vues[$6 "." $7] = 1 } next }
  $4 == "SEQUENCE" && $5 == "SET" && ($6 == "public" || $6 == "auth") { print }
  END { for (t in voulue) if (!(t in vues)) print "ABSENTE " t > "/dev/stderr" }
' "$travail/matieres.txt" > "$travail/voulues.txt" 2> "$travail/absentes-du-dump.txt"
[ ! -s "$travail/absentes-du-dump.txt" ] || echoue "tables du manifeste sans données dans le dump : $(sed 's/^ABSENTE //' "$travail/absentes-du-dump.txt" | paste -sd' ')"

# Les messages de pg_restore peuvent citer une valeur (DETAIL, CONTEXT) : on ne montre que l'essentiel.
if ! pg_restore --data-only --disable-triggers --single-transaction --exit-on-error --no-owner \
      --use-list="$travail/voulues.txt" --dbname="$PGDATABASE" "$dossier/base.dump" 2> "$travail/pg_restore.err"; then
  grep -E '^pg_restore: error: [^:]*(:|$)' "$travail/pg_restore.err" | cut -c1-160 >&2 || true
  echoue "pg_restore a échoué (détails retenus : ils pourraient citer des valeurs)"
fi
echo "restauration: données de public et d'auth, et storage.buckets, restaurées"

# --- 4. Les fichiers, par l'API Storage -----------------------------------------------------------------
node "$racine/ops/sauvegarde/depose-seaux.mjs" "$dossier/seaux"

# --- 5. Les comptes, un par un ---------------------------------------------------------------------------
requete=$(awk -F'\t' '{ n = split($1, p, "."); printf "%sselect '\''%s'\'' as t, count(*) as c from \"%s\".\"%s\"", sep, $1, p[1], p[2]; sep = " union all " }' \
  "$travail/attendu.txt")
sql -c "select t, c from ($requete) x order by t" | LC_ALL=C sort > "$travail/obtenu.txt"
if ! diff <(LC_ALL=C sort "$travail/attendu.txt") "$travail/obtenu.txt" > "$travail/ecarts.txt"; then
  # Le journal d'un dépôt public ne montre pas de compte par table : seulement les tables en cause.
  echo "restauration: tables dont le compte diffère du manifeste : $(grep -E '^[<>]' "$travail/ecarts.txt" | cut -f1 | sed 's/^[<>] //' | LC_ALL=C sort -u | paste -sd' ')" >&2
  echoue "comptes différents du manifeste"
fi
echo "restauration: ok, $(wc -l < "$travail/obtenu.txt") tables comparées au manifeste, $(awk -F'\t' '{ n += $2 } END { print n + 0 }' "$travail/obtenu.txt") lignes au total, $(awk -F'\t' '$1 == "storage.objects" { print $2 }' "$travail/obtenu.txt") objets"

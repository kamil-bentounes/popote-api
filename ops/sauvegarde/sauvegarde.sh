#!/usr/bin/env bash
# Sauvegarde chiffrée de Popote (spec § 5.4) : la base, les rôles, les fichiers des seaux et un manifeste
# de comptes, le tout dans une archive chiffrée avec `age`. Rien n'est écrit en clair hors d'un dossier
# temporaire, effacé à la sortie.
#
#   sauvegarde.sh                          écrit s3://$S3_BUCKET/$CIBLE/popote-<date>.tar.age
#   sauvegarde.sh --local-seulement <dir>  écrit l'archive dans <dir> au lieu du seau (essais)
#
# Lit : CIBLE (prod ou essai) ; PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE (le pooler Supavisor en mode
# session, pas en mode transaction : `pg_export_snapshot` exige que la connexion reste la même) ;
# SUPABASE_URL SUPABASE_SECRET_KEY (les fichiers des seaux) ; S3_BUCKET S3_ACCESS_KEY S3_SECRET_KEY
# (sauf avec --local-seulement). Destinataires `age` : ops/sauvegarde/destinataires-$CIBLE.txt, ou le
# fichier de DESTINATAIRES (les essais). S3_ENDPOINT et S3_REGION valent Scaleway (fr-par) par défaut.
#
# Le journal ne contient que des tailles, des comptes et des noms de tables : jamais une valeur, jamais
# un nom d'objet. Pas de `set -x`.
set -euo pipefail
umask 077

racine=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
dossier_local=""
case "${1:-}" in
  "") ;;
  --local-seulement)
    dossier_local=${2:-}
    [ -n "$dossier_local" ] || { echo "usage : $0 [--local-seulement <dossier>]" >&2; exit 2; } ;;
  *) echo "usage : $0 [--local-seulement <dossier>]" >&2; exit 2 ;;
esac

echoue() { echo "sauvegarde: $*" >&2; exit 1; }

# --- Les entrées -------------------------------------------------------------------------------------
requises=(CIBLE PGHOST PGUSER PGPASSWORD PGDATABASE SUPABASE_URL SUPABASE_SECRET_KEY)
[ -n "$dossier_local" ] || requises+=(S3_BUCKET S3_ACCESS_KEY S3_SECRET_KEY)
manque=()
for nom in "${requises[@]}"; do [ -n "${!nom:-}" ] || manque+=("$nom"); done
[ ${#manque[@]} -eq 0 ] || echoue "variables manquantes : ${manque[*]}"
case "$CIBLE" in prod | essai) ;; *) echoue "CIBLE doit valoir prod ou essai" ;; esac
export PGPORT=${PGPORT:-5432} PGHOST PGUSER PGPASSWORD PGDATABASE

destinataires=${DESTINATAIRES:-$racine/ops/sauvegarde/destinataires-$CIBLE.txt}
[ -s "$destinataires" ] || echoue "destinataires introuvables ou vides : ${destinataires#"$racine"/}"
# Une clé privée posée ici par erreur chiffrerait pour rien et finirait dans l'historique git.
! grep -q 'AGE-SECRET-KEY' "$destinataires" || echoue "le fichier des destinataires contient une clé privée"
grep -Eq '^age1[a-z0-9]+$' "$destinataires" || echoue "aucune clé publique age1… dans le fichier des destinataires"

for outil in pg_dump pg_dumpall psql age node tar; do
  command -v "$outil" > /dev/null || echoue "outil absent : $outil"
done
[ -n "$dossier_local" ] || command -v aws > /dev/null || echoue "outil absent : aws"

jour=$(date -u +%Y-%m-%dT%H%MZ)
nom_archive=popote-$jour.tar.age
travail=$(mktemp -d)
sortie=$(mktemp -d)
snapshot_pid=""
nettoie() {
  [ -z "$snapshot_pid" ] || kill "$snapshot_pid" 2> /dev/null || true
  rm -rf "$travail" "$sortie"
}
trap nettoie EXIT

echo "sauvegarde: cible=$CIBLE, $nom_archive"

# --- Un seul instantané pour le dump et pour les comptes (amendement 8) -------------------------------
# Une transaction REPEATABLE READ tenue ouverte exporte son instantané ; `pg_dump --snapshot` le reprend ;
# les comptes sont lus dans cette même transaction. Les trois voient donc exactement les mêmes lignes.
coproc SNAP { exec psql --no-psqlrc -X -q -A -t -F $'\t' -v ON_ERROR_STOP=1; }
snapshot_pid=$SNAP_PID
dans_snapshot() { printf '%s\n' "$@" >&"${SNAP[1]}"; }
attend() { # lit la sortie de psql jusqu'à la ligne $1 ; rend ce qui précède
  local ligne
  while IFS= read -r -t 120 ligne <&"${SNAP[0]}"; do
    [ "$ligne" != "$1" ] || return 0
    printf '%s\n' "$ligne"
  done
  echoue "la transaction de l'instantané ne répond plus"
}

dans_snapshot "begin isolation level repeatable read read only;" \
  "select pg_export_snapshot();" "select 'FIN-INSTANTANE';"
instantane=$(attend FIN-INSTANTANE)
[[ "$instantane" =~ ^[0-9A-F]+-[0-9A-F]+-[0-9]+$ ]] || echoue "instantané introuvable"

dans_snapshot "\\o $travail/comptes.txt" \
  "select n.nspname || '.' || c.relname,
          (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', n.nspname, c.relname), false, true, '')))[1]::text
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public', 'auth', 'storage') and c.relkind = 'r'
    order by 1;" \
  "\\o" "select 'FIN-COMPTES';"
attend FIN-COMPTES > /dev/null
[ -s "$travail/comptes.txt" ] || echoue "aucun compte lu : manifeste vide"

# La liste des objets, dans le même instantané : la copie des fichiers est comparée à elle, nom et taille.
dans_snapshot "\\o $travail/objets.jsonl" \
  "select json_build_object('seau', bucket_id, 'nom', name, 'octets', (metadata->>'size')::bigint)::text
     from storage.objects order by bucket_id, name;" \
  "\\o" "select 'FIN-OBJETS';"
attend FIN-OBJETS > /dev/null
[ -f "$travail/objets.jsonl" ] || echoue "liste des objets de l'instantané introuvable"

pg_dump --format=custom --no-owner --lock-wait-timeout=60s --snapshot="$instantane" \
  --schema=public --schema=auth --schema=storage > "$travail/base.dump"
dans_snapshot "commit;"
kill "$snapshot_pid" 2> /dev/null || true
snapshot_pid=""

# Les rôles et leurs droits : utiles à la fiche de restauration, pas bloquants s'ils sont refusés.
if ! pg_dumpall --roles-only --no-role-passwords > "$travail/roles.sql" 2> /dev/null; then
  : > "$travail/roles.sql"
  echo "partiel : les rôles n'ont pas pu être lus (droits du rôle de connexion)" > "$travail/roles.note"
  echo "sauvegarde: rôles non sauvegardés (voir roles.note dans l'archive)"
fi

# --- Les fichiers des seaux ----------------------------------------------------------------------------
# Comparés, nom et taille, à la liste de `storage.objects` de l'instantané. Au premier écart (un objet
# remplacé pendant la copie), un seul nouvel essai de la copie ; au second, échec.
copie_des_seaux() {
  rm -rf "$travail/seaux" &&
    node "$racine/ops/sauvegarde/copie-seaux.mjs" "$travail/seaux" &&
    node "$racine/ops/sauvegarde/verifie-seaux.mjs" "$travail/seaux" "$travail/objets.jsonl"
}
if ! copie_des_seaux; then
  echo "sauvegarde: les fichiers copiés ne correspondent pas à l'instantané, nouvel essai de la copie"
  copie_des_seaux || echoue "les fichiers des seaux ne correspondent pas à l'instantané : un dépôt a eu lieu depuis, relancer"
fi

printf 'format=1\ndate=%s\ncible=%s\npg_dump=%s\n' "$jour" "$CIBLE" "$(pg_dump --version)" > "$travail/meta.txt"

# --- Le journal : des tailles, des comptes, des noms de tables ----------------------------------------
echo "sauvegarde: base.dump $(stat -c %s "$travail/base.dump") octets"
echo "sauvegarde: $(wc -l < "$travail/comptes.txt") tables, comptes :"
awk -F'\t' '{ printf "sauvegarde:   %s %s\n", $1, $2 }' "$travail/comptes.txt"

# --- Chiffrement, puis dépôt ---------------------------------------------------------------------------
fichiers=(base.dump roles.sql comptes.txt meta.txt seaux)
[ ! -e "$travail/roles.note" ] || fichiers+=(roles.note)
tar -C "$travail" -cf - "${fichiers[@]}" | age -R "$destinataires" -o "$sortie/$nom_archive"
taille=$(stat -c %s "$sortie/$nom_archive")
[ "$(head -c 21 "$sortie/$nom_archive")" = "age-encryption.org/v1" ] || echoue "l'archive n'est pas chiffrée"

if [ -n "$dossier_local" ]; then
  mkdir -p "$dossier_local"
  mv "$sortie/$nom_archive" "$dossier_local/$nom_archive"
  echo "sauvegarde: $nom_archive ($taille octets) écrite dans le dossier local"
  exit 0
fi

export AWS_ACCESS_KEY_ID=$S3_ACCESS_KEY AWS_SECRET_ACCESS_KEY=$S3_SECRET_KEY AWS_DEFAULT_REGION=${S3_REGION:-fr-par}
# Certains stockages compatibles S3 refusent les sommes de contrôle que l'AWS CLI ajoute désormais d'office.
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
point_acces=${S3_ENDPOINT:-https://s3.fr-par.scw.cloud}
cle_objet=$CIBLE/$nom_archive
aws s3 cp "$sortie/$nom_archive" "s3://$S3_BUCKET/$cle_objet" --endpoint-url "$point_acces" --only-show-errors
distant=$(aws s3api head-object --bucket "$S3_BUCKET" --key "$cle_objet" --endpoint-url "$point_acces" \
  --query ContentLength --output text)
[ "$distant" = "$taille" ] || echoue "taille déposée ($distant) différente de la taille locale ($taille)"
echo "sauvegarde: $nom_archive ($taille octets) déposée dans $S3_BUCKET/$CIBLE/"

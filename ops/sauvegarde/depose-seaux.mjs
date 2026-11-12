#!/usr/bin/env node
// Redépose dans l'API Storage les fichiers copiés par copie-seaux.mjs. Lit SUPABASE_URL et
// SUPABASE_SECRET_KEY. Les seaux doivent exister (`storage.buckets` est restauré avant) ; l'API
// recrée `storage.objects`.
//
//   node ops/sauvegarde/depose-seaux.mjs <dossier de la copie>
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { cheminSous } from './copie-seaux.mjs'
import { appeler, DELAI_OBJET_MS, ErreurStorage, lireEnvironnement, segments } from './storage.mjs'

export async function deposer(client, dossier) {
  const racine = resolve(dossier)
  const index = (await readFile(resolve(racine, 'index.jsonl'), 'utf8')).split('\n').filter(Boolean)
  const bilan = { objets: 0, octets: 0 }
  for (const ligne of index) {
    const { seau, nom, octets, type } = JSON.parse(ligne)
    const contenu = await readFile(cheminSous(racine, 'fichiers', seau, nom))
    if (contenu.length !== octets) throw new ErreurStorage(`fichier tronqué dans le seau ${seau}`)
    await appeler(client, 'POST', `/storage/v1/object/${encodeURIComponent(seau)}/${segments(nom)}`, {
      corps: contenu,
      entetes: { 'Content-Type': type ?? 'application/octet-stream', 'x-upsert': 'true' },
      libelle: `dépôt dans le seau ${seau}`,
      delai: DELAI_OBJET_MS,
    })
    bilan.objets++
    bilan.octets += octets
  }
  return bilan
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const dossier = process.argv[2]
  if (!dossier) {
    console.error('usage : node depose-seaux.mjs <dossier de la copie>')
    process.exit(2)
  }
  try {
    const bilan = await deposer(lireEnvironnement(), dossier)
    console.log(`fichiers: ${bilan.objets} objets redéposés, ${bilan.octets} octets`)
  } catch (erreur) {
    console.error(`dépôt des seaux : ${erreur.message}`)
    process.exit(1)
  }
}

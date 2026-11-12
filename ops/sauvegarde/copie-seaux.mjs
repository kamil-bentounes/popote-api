#!/usr/bin/env node
// Copie en clair les objets de tous les seaux Storage dans un dossier (le dump du schéma `storage`
// n'en garde que la description). Lit SUPABASE_URL et SUPABASE_SECRET_KEY.
//
//   node ops/sauvegarde/copie-seaux.mjs <dossier>
//
// Écrit <dossier>/fichiers/<seau>/<objet> et <dossier>/index.jsonl (une ligne par objet : seau, nom,
// octets, type). Le journal ne contient que des comptes et des tailles, jamais un nom d'objet.
import { createWriteStream } from 'node:fs'
import { appendFile, mkdir, readdir, stat, writeFile } from 'node:fs/promises'
import { dirname, resolve, sep } from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { pathToFileURL } from 'node:url'
import { appeler, ErreurStorage, lireEnvironnement, segments } from './storage.mjs'

export const TAILLE_PAGE = 1000

/** Les seaux du projet. Pas de pagination côté API ici : au-delà d'une page, on refuse plutôt que d'en oublier. */
export async function listerSeaux(client) {
  const reponse = await appeler(client, 'GET', `/storage/v1/bucket?limit=${TAILLE_PAGE}`, { libelle: 'liste des seaux' })
  const seaux = await reponse.json()
  if (seaux.length >= TAILLE_PAGE) throw new ErreurStorage('trop de seaux pour une seule page')
  return seaux.map((seau) => seau.name)
}

/** Tous les objets d'un seau, dossiers parcourus, par pages de 1 000. */
export async function* listerObjets(client, seau, prefixe = '', taille = TAILLE_PAGE) {
  for (let decalage = 0; ; decalage += taille) {
    const reponse = await appeler(client, 'POST', `/storage/v1/object/list/${encodeURIComponent(seau)}`, {
      corps: JSON.stringify({
        prefix: prefixe, limit: taille, offset: decalage, sortBy: { column: 'name', order: 'asc' },
      }),
      entetes: { 'Content-Type': 'application/json' },
      libelle: `liste du seau ${seau}`,
    })
    const page = await reponse.json()
    for (const element of page) {
      // Un dossier n'a pas d'identifiant : on descend, sans le compter comme un objet.
      if (element.id === null) yield* listerObjets(client, seau, `${prefixe}${element.name}/`, taille)
      else yield { nom: `${prefixe}${element.name}`, octets: element.metadata?.size, type: element.metadata?.mimetype }
    }
    if (page.length < taille) return
  }
}

/** Un chemin sous `racine`, ou une erreur : un nom d'objet ne sort jamais du dossier de copie. */
export function cheminSous(racine, ...parties) {
  const base = resolve(racine)
  const chemin = resolve(base, ...parties)
  if (!chemin.startsWith(base + sep)) throw new ErreurStorage('un nom d’objet sort du dossier de copie')
  return chemin
}

/** `seaux` limite la copie à ces seaux (les essais) ; sans lui, tous les seaux du projet. */
export async function copier(client, dossier, { seaux: retenus } = {}) {
  const racine = resolve(dossier)
  await mkdir(racine, { recursive: true })
  if ((await readdir(racine)).length > 0) throw new ErreurStorage('le dossier de copie doit être vide')
  await writeFile(resolve(racine, 'index.jsonl'), '')

  const bilan = { seaux: 0, objets: 0, octets: 0 }
  for (const seau of (await listerSeaux(client)).filter((nom) => !retenus || retenus.includes(nom))) {
    bilan.seaux++
    const racineSeau = cheminSous(resolve(racine, 'fichiers'), seau)
    await mkdir(racineSeau, { recursive: true })
    for await (const objet of listerObjets(client, seau)) {
      const cible = cheminSous(racineSeau, objet.nom)
      await mkdir(dirname(cible), { recursive: true })
      const reponse = await appeler(client, 'GET', `/storage/v1/object/${encodeURIComponent(seau)}/${segments(objet.nom)}`, {
        libelle: `téléchargement dans le seau ${seau}`,
      })
      await pipeline(Readable.fromWeb(reponse.body), createWriteStream(cible))
      const { size: octets } = await stat(cible)
      if (objet.octets !== undefined && objet.octets !== octets) {
        throw new ErreurStorage(`taille copiée différente de la taille annoncée dans le seau ${seau}`)
      }
      await appendFile(
        resolve(racine, 'index.jsonl'),
        `${JSON.stringify({ seau, nom: objet.nom, octets, type: objet.type ?? null })}\n`,
      )
      bilan.objets++
      bilan.octets += octets
    }
  }
  return bilan
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const dossier = process.argv[2]
  if (!dossier) {
    console.error('usage : node copie-seaux.mjs <dossier>')
    process.exit(2)
  }
  try {
    const bilan = await copier(lireEnvironnement(), dossier)
    console.log(`seaux: ${bilan.seaux} seaux, ${bilan.objets} objets, ${bilan.octets} octets`)
  } catch (erreur) {
    console.error(`copie des seaux : ${erreur.message}`)
    process.exit(1)
  }
}

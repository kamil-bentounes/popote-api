#!/usr/bin/env node
// Compare les fichiers copiés par copie-seaux.mjs à la liste de `storage.objects` prise DANS l'instantané
// de la base : mêmes seaux, mêmes noms, mêmes tailles. Le compte seul ne verrait pas un objet remplacé
// par un autre pendant la copie.
//
//   node ops/sauvegarde/verifie-seaux.mjs <dossier de la copie> <objets de l'instantané (JSON lignes)>
//
// Une ligne de l'instantané : {"seau": …, "nom": …, "octets": … | null}. Le journal ne donne que des
// comptes d'écarts, jamais un nom.
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const lignes = async (chemin) =>
  (await readFile(chemin, 'utf8')).split('\n').filter(Boolean).map((ligne) => JSON.parse(ligne))
const cle = ({ seau, nom }) => JSON.stringify([seau, nom])

/** @returns {{ manquants: number, enTrop: number, tailles: number }} */
export async function comparer(dossier, fichierInstantane) {
  const copies = new Map((await lignes(resolve(dossier, 'index.jsonl'))).map((objet) => [cle(objet), objet.octets]))
  const instantane = await lignes(fichierInstantane)
  const ecarts = { manquants: 0, enTrop: 0, tailles: 0 }
  const vus = new Set()
  for (const objet of instantane) {
    const identifiant = cle(objet)
    vus.add(identifiant)
    if (!copies.has(identifiant)) ecarts.manquants++
    // Un objet sans taille connue dans la base n'est pas comparé sur la taille.
    else if (objet.octets !== null && copies.get(identifiant) !== objet.octets) ecarts.tailles++
  }
  for (const identifiant of copies.keys()) if (!vus.has(identifiant)) ecarts.enTrop++
  return ecarts
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const [dossier, instantane] = process.argv.slice(2)
  if (!dossier || !instantane) {
    console.error('usage : node verifie-seaux.mjs <dossier de la copie> <objets de l’instantané>')
    process.exit(2)
  }
  try {
    const ecarts = await comparer(dossier, instantane)
    if (ecarts.manquants + ecarts.enTrop + ecarts.tailles > 0) {
      console.error(`fichiers: écart avec l'instantané : ${ecarts.manquants} manquants, ${ecarts.enTrop} en trop, ${ecarts.tailles} de taille différente`)
      process.exit(1)
    }
    console.log('fichiers: noms et tailles conformes à l\'instantané')
  } catch (erreur) {
    console.error(`vérification des fichiers : ${erreur.message}`)
    process.exit(1)
  }
}

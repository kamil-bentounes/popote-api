// node ops/inventaire.mjs ~/PERSO/smart-receipe-scheduler/src > docs/inventaire-surface.md
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const racine = process.argv[2]
const fichiers = []
const parcours = d => { for (const f of readdirSync(d)) { const p = join(d, f)
  if (statSync(p).isDirectory()) parcours(p)
  else if (/\.(ts|tsx)$/.test(f) && !/\.test\.tsx?$/.test(f)) fichiers.push(p) } }
parcours(racine)

const lignes = []
for (const f of fichiers) {
  const t = readFileSync(f, 'utf8')
  for (const m of t.matchAll(/\.from\(\s*['"`]([\w-]+)['"`]\s*\)([\s\S]{0,400}?)\.(select|insert|update|upsert|delete)\(/g))
    lignes.push(['table', m[1], m[3], relative(racine, f)])
  for (const m of t.matchAll(/\.rpc\(\s*['"`]([\w-]+)['"`]/g)) lignes.push(['rpc', m[1], 'appel', relative(racine, f)])
  for (const m of t.matchAll(/functions(?:\.invoke\(\s*|\/v1\/)['"`]?([\w-]+)/g)) lignes.push(['fonction', m[1], 'appel', relative(racine, f)])
  // Le front appelle ses fonctions par `callFunction('nom', …)`, `callFunctionPublique('nom', …)` ou `fn('nom')`.
  for (const m of t.matchAll(/\b(?:callFunction(?:Publique)?|fn)\s*(?:<[^()]*>)?\(\s*['"`]([\w-]+)['"`]/g)) lignes.push(['fonction', m[1], 'appel', relative(racine, f)])
  if (/\.channel\(/.test(t)) lignes.push(['temps réel', '-', 'abonnement', relative(racine, f)])
  // Le seau est un littéral, ou une constante du fichier (`const SEAU = 'photos-des-plats'`).
  for (const m of t.matchAll(/\.storage\s*\.from\(\s*(?:['"`]([\w-]+)['"`]|(\w+))/g)) {
    const nom = m[1] ?? t.match(new RegExp(`const ${m[2]}\\s*=\\s*['"\`]([\\w-]+)`))?.[1] ?? m[2]
    lignes.push(['stockage', nom, 'appel', relative(racine, f)])
  }
}
const tri = [...new Map(lignes.map(l => [l.join('|'), l])).values()].sort((a, b) => a.join().localeCompare(b.join()))
console.log('# Inventaire de la surface appelée par le front (avant le socle)\n')
console.log(`Produit par \`ops/inventaire.mjs\` le ${new Date().toISOString().slice(0, 10)}. Une ligne = une sorte d'appel dans un fichier.\n`)
console.log('| Sorte | Nom | Geste | Fichier |\n|---|---|---|---|')
for (const l of tri) console.log(`| ${l.join(' | ')} |`)
const compte = s => new Set(tri.filter(l => l[0] === s).map(l => l[1])).size
console.log(`\n**Totaux** : ${compte('table')} tables, ${compte('rpc')} fonctions SQL, ${compte('fonction')} fonctions Edge, ` +
  `${compte('stockage')} seaux, temps réel dans ${tri.filter(l => l[0] === 'temps réel').length} fichier(s).`)

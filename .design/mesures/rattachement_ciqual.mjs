import { readFileSync } from 'node:fs'
import { indexer, rattacher } from '../../worker/src/aliment.ts'
import { analyser } from '../../worker/src/ingredient.ts'
const ciqual = JSON.parse(readFileSync('seed/ciqual.json','utf8'))
const index = indexer(ciqual.map(a => ({ id: a.code, name: a.nom, state: a.etat })))

const UA = { 'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36','Accept-Language':'fr-FR,fr;q=0.9' }
function* walk(o){ if(Array.isArray(o)){for(const v of o) yield* walk(v);return}
  if(o&&typeof o==='object'){const t=o['@type']; if(t==='Recipe'||(Array.isArray(t)&&t.includes('Recipe'))) yield o; for(const v of Object.values(o)) yield* walk(v)} }
async function rec(u){ let h; try{h=await(await fetch(u,{headers:UA,signal:AbortSignal.timeout(30000)})).text()}catch{return null}
  for(const m of h.matchAll(/<script[^>]*application\/ld\+json[^>]*>([\s\S]*?)<\/script>/gi)){let d;try{d=JSON.parse(m[1].trim())}catch{continue};for(const r of walk(d))return r} return null }
const urls = readFileSync('sm.out','utf8')
  .split('\n').filter(l=>l.startsWith('URL|')).map(l=>l.split('|')[2])
const rs=[]; for(let i=0;i<urls.length;i+=12) rs.push(...(await Promise.all(urls.slice(i,i+12).map(rec))).filter(Boolean))

let n=0, ok=0; const rates=new Map(), scores=[]
for(const r of rs) for(const l of (r.recipeIngredient??[])){
  if(typeof l!=='string') continue
  const a=analyser(l); if(a.forme==='section'||!a.aliment) continue
  n++; const m=rattacher(a.aliment,index)
  if(m){ok++;scores.push(m.score)} else rates.set(a.aliment,(rates.get(a.aliment)??0)+1)
}
scores.sort((x,y)=>x-y)
console.log(`\n### RATTACHEMENT À CIQUAL — ${n} lignes d'ingrédients réelles\n`)
console.log(`  rattachées   : ${ok}/${n} = ${(100*ok/n).toFixed(1)} %`)
console.log(`  non rattachées : ${n-ok} · score médian des réussites : ${scores[Math.floor(scores.length/2)]?.toFixed(2)}`)
console.log(`\n  les plus fréquents parmi les ratés :`)
for(const [k,v] of [...rates].sort((a,b)=>b[1]-a[1]).slice(0,18)) console.log(`    ${String(v).padStart(3)}×  ${k.slice(0,58)}`)

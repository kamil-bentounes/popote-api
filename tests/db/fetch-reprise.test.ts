import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { describe, expect, it } from 'vitest'
import { estConnexionFermeeParLautreBout, fetchAvecReprise } from './helpers/fetch-reprise'

const erreurDeFetch = (code: string, message: string) =>
  new TypeError('fetch failed', { cause: Object.assign(new Error(message), { code }) })
const coupure = () => erreurDeFetch('UND_ERR_SOCKET', 'other side closed')

/** Un faux fetch qui suit un scénario : une erreur à lever, ou une réponse à rendre, appel après appel. */
function scenario(...etapes: (Error | string)[]) {
  const appels: Parameters<typeof fetch>[] = []
  const f = (async (...args: Parameters<typeof fetch>) => {
    appels.push(args)
    const etape = etapes[appels.length - 1]
    if (etape instanceof Error) throw etape
    return new Response(etape)
  }) as typeof fetch
  return { f, appels }
}

describe('la reprise d\'une connexion fermée par l\'autre bout', () => {
  it('reconnaît la coupure d\'undici, et elle seule', () => {
    expect(estConnexionFermeeParLautreBout(coupure())).toBe(true)
    expect(estConnexionFermeeParLautreBout(erreurDeFetch('ECONNREFUSED', 'connect ECONNREFUSED'))).toBe(false)
    expect(estConnexionFermeeParLautreBout(new TypeError('fetch failed'))).toBe(false)
    expect(estConnexionFermeeParLautreBout(Object.assign(new Error('x'), { cause: { code: 'UND_ERR_SOCKET' } })))
      .toBe(false)
  })

  it('rejoue une fois la requête coupée et rend la réponse du second essai', async () => {
    const { f, appels } = scenario(coupure(), 'ok')
    const reponse = await fetchAvecReprise(f)('http://exemple.test/', { method: 'POST', body: '{"a":1}' })
    expect(await reponse.text()).toBe('ok')
    expect(appels).toHaveLength(2)
    expect(appels[1]).toEqual(appels[0])
  })

  it('ne rejoue qu\'une fois : une seconde coupure remonte', async () => {
    const { f, appels } = scenario(coupure(), coupure(), 'jamais')
    await expect(fetchAvecReprise(f)('http://exemple.test/')).rejects.toThrow('fetch failed')
    expect(appels).toHaveLength(2)
  })

  it('ne rejoue pas une autre erreur', async () => {
    const { f, appels } = scenario(erreurDeFetch('ECONNREFUSED', 'connect ECONNREFUSED'), 'jamais')
    await expect(fetchAvecReprise(f)('http://exemple.test/')).rejects.toThrow('fetch failed')
    expect(appels).toHaveLength(1)
  })

  it('ne rejoue ni un corps en flux ni une Request : leur corps est déjà lu', async () => {
    const flux = scenario(coupure(), 'jamais')
    const corps = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('x')); c.close() } })
    const enFlux = { method: 'POST', body: corps, duplex: 'half' } as RequestInit
    await expect(fetchAvecReprise(flux.f)('http://exemple.test/', enFlux)).rejects.toThrow('fetch failed')
    expect(flux.appels).toHaveLength(1)

    const requete = scenario(coupure(), 'jamais')
    await expect(fetchAvecReprise(requete.f)(new Request('http://exemple.test/', { method: 'POST', body: 'x' })))
      .rejects.toThrow('fetch failed')
    expect(requete.appels).toHaveLength(1)
  })

  it('le fetch des tests reprend pour de vrai : un serveur coupe la première requête', async () => {
    let vues = 0
    const serveur = createServer((req, res) => {
      vues += 1
      if (vues === 1) { req.socket.destroy(); return }
      res.end('ok')
    })
    await new Promise<void>(pret => serveur.listen(0, '127.0.0.1', pret))
    const { port } = serveur.address() as AddressInfo
    try {
      const reponse = await fetch(`http://127.0.0.1:${port}/`, { method: 'POST', body: 'x' })
      expect(await reponse.text()).toBe('ok')
      expect(vues).toBe(2)
    } finally {
      await new Promise(fini => serveur.close(fini))
    }
  })
})

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './lib/supabase'
import { lienDeploye, useRoute } from './lib/route.ts'
import { garderLeRetour, prendreLeRetour, retourApresConnexion } from './lib/lien.ts'
import { SESSION_PERDUE } from './lib/session-perdue.ts'
import { LA_BASE_NE_REPOND_PAS, PAS_DE_RESEAU, classeLaPanne, estUnePanneDeReseau } from './lib/reseau.ts'
import { BandeauDePanne } from './ui/BandeauDePanne.tsx'
import { HorsLigne } from './pages/HorsLigne'
import { SignIn } from './pages/SignIn'
import { Password } from './pages/Password'
import { Onboarding } from './pages/Onboarding'
import { Targets } from './pages/Targets'
import { Settings } from './pages/Settings'
import { Rappels } from './pages/Rappels.tsx'
import { AcceptInvite } from './pages/AcceptInvite'
import { Rejoindre } from './pages/Rejoindre'
import { Hub } from './pages/Hub.tsx'
import { Budget } from './pages/Budget.tsx'
import { adresseDeMoisFausse } from './lib/budget/mois.ts'
import { Cloture } from './pages/Cloture.tsx'
import { Charges } from './pages/Charges.tsx'
import { BudgetReglages } from './pages/BudgetReglages.tsx'
import { Epargne } from './pages/Epargne.tsx'
import { MoisType } from './pages/MoisType.tsx'
import { ToutesLesCharges } from './pages/ToutesLesCharges.tsx'
import { Profil } from './pages/Profil.tsx'
import { Accueil } from './pages/Accueil.tsx'
import { Choisir } from './pages/Choisir.tsx'
import { Magasin } from './pages/Magasin.tsx'
import { Plan } from './pages/Plan.tsx'
import { Cuisine } from './pages/Cuisine.tsx'
import { Dressage } from './pages/Dressage.tsx'
import { Semaine } from './pages/Semaine.tsx'
import { Frigo } from './pages/Frigo.tsx'
import { Aliments } from './pages/Aliments.tsx'
import { Bilan } from './pages/Bilan.tsx'
import { Inventer } from './pages/Inventer.tsx'
import { Photo } from './pages/Photo.tsx'
import { Ticket } from './pages/Ticket.tsx'
import { Peser } from './pages/Peser.tsx'
import { Importer } from './pages/Importer.tsx'
import { AccepteAmi } from './pages/AccepteAmi.tsx'
import { Aide } from './ui/Aide.tsx'

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [foyer, setFoyer] = useState<string | null>(null)
  /* Quelqu'un qui vient d'accepter une invitation — ou de créer son foyer
     (0091) — n'a PAS de prénom : on ne le fabrique plus depuis son adresse — `thauba-1790147184836` finissait
     pré-rempli, validé sans regarder, puis lu sur chaque ligne de charge. Mais
     un prénom vide ne peut pas rester : c'est ce que l'autre lit. On mène donc
     au profil, une fois, avant le reste. */
  const [sansPrenom, setSansPrenom] = useState(false)
  /** Elle a choisi de le faire plus tard : on ne la ramène pas de force. */
  const [prenomRemis, setPrenomRemis] = useState(false)
  const [mdpPose, setMdpPose] = useState(true)
  const [pret, setPret] = useState(false)
  /** Le réseau (ou la base) ne répond pas : on ne sait PAS si la personne a un foyer. */
  const [panne, setPanne] = useState<'reseau' | 'base' | null>(null)
  /** La relecture a échoué alors que l'appli est déjà là : l'écran reste, on le dit à côté. */
  const [alerte, setAlerte] = useState<string | null>(null)
  /** Une lecture a déjà réussi avec une session : il y a un écran à ne pas démonter. */
  const appliLa = useRef(false)
  /** Sur un lien d'invitation : elle a dit avoir déjà un compte. */
  const [connexionDemandee, setConnexionDemandee] = useState(false)
  /** La session a disparu en cours de route (jeton retiré, compte supprimé ailleurs) : on le dit. */
  const [perdue, setPerdue] = useState(false)
  const sessionRef = useRef<Session | null>(null)
  const { ici, va, remplace, retour } = useRoute()
  /* Lu par `relire`, qui ne change pas à chaque écran : le retour gardé ne se rejoue que sur l'écran où l'on arrive. */
  const iciRef = useRef(ici)
  useEffect(() => { iciRef.current = ici }, [ici])

  /* Ce que la relecture a appris, écrit d'un coup (voir `relire`). */
  const applique = useCallback((r: {
    session: Session | null; foyer: string | null
    profil: { password_set: boolean; display_name: string | null } | null
    ratee: 'reseau' | 'base' | null; expiree: boolean
  }) => {
    if (r.expiree) {
      /* Le jeton est périmé côté serveur : la connexion, avec sa phrase. */
      appliLa.current = false
      sessionRef.current = null
      setSession(null); setFoyer(null); setPanne(null); setAlerte(null); setPerdue(true)
      setPret(true)
      return
    }
    if (r.ratee && appliLa.current) {
      /* ⚠️ Une relecture EN COURS D'USAGE (jeton rafraîchi, retour du réseau) qui tombe sur une
         panne ne remplace pas l'appli par « Hors ligne » : le formulaire à moitié rempli, la feuille
         ouverte s'en allaient avec. On garde l'écran et on dit la panne à côté. */
      setAlerte(r.ratee === 'reseau' ? PAS_DE_RESEAU : LA_BASE_NE_REPOND_PAS)
      return
    }
    setAlerte(null)
    setPanne(r.ratee)
    appliLa.current = !r.ratee && !!r.session
    if (r.session) setPerdue(false)
    /* Le lien d'un mail (`/frigo?sortir=…`) ouvert déconnecté : la connexion par mot de passe garde l'adresse,
       mais un lien de connexion par e-mail renvoie sur le chemin SEUL, et la requête se perdait. On la remet
       avant que l'écran se monte : `Frigo` lit sa requête une fois, au montage. */
    if (r.session && !r.ratee) {
      const retour = prendreLeRetour(iciRef.current, window.location.search)
      if (retour) remplace(retour)
    }
    sessionRef.current = r.session
    setSession(r.session)
    setFoyer(r.foyer)
    setMdpPose(r.profil ? !!r.profil.password_set : true)
    setSansPrenom(r.profil ? (r.profil.display_name ?? '').trim() === '' : false)
    setPret(true)
  }, [remplace])

  /* Le numéro de la DERNIÈRE relecture : une plus ancienne qui répond après
     elle n'a plus rien à dire. */
  const tour = useRef(0)
  const relire = useCallback(async () => {
    const ceTour = ++tour.current
    const { data, error: erreurSession } = await supabase.auth.getSession()
    /* ⚠️ On LIT tout, puis on ÉCRIT tout, d'un coup.
       La session était posée avant le foyer, qu'on attendait ensuite : le
       temps de cet aller-retour, l'écran croyait la personne connectée SANS
       foyer — et offrait à un membre, sur un lien d'invitation, de rejoindre
       un foyer qu'il a déjà (refus 409 au clic). Et plusieurs relectures se
       croisent — le montage, `INITIAL_SESSION`, `PASSWORD_RECOVERY` — : sans
       le numéro de tour, la plus lente gagnait, fût-elle la plus ancienne, et
       pouvait remettre « mot de passe posé » juste après qu'une
       réinitialisation l'avait retiré. */
    let hh: string | null = null
    let p: { password_set: boolean; display_name: string | null } | null = null
    let ratee: 'reseau' | 'base' | null = null
    let expiree = false
    /** Une erreur de lecture : session expirée (→ connexion), réseau coupé, ou base muette. */
    const note = (e: unknown, statut?: number) => {
      const c = classeLaPanne(e, statut)
      if (c === 'expiree') expiree = true
      else if (c === 'reseau' || ratee === null) ratee = c
    }
    if (!data.session) {
      /* ⚠️ `session: null` AVEC une erreur de réseau n'est pas « déconnecté ». Jeton de plus d'une
         heure + réseau coupé : auth-js ne peut pas le rafraîchir, rend `session: null` et la
         session reste en stockage. L'écran « Se connecter » arrivait sans un mot. */
      if (erreurSession && estUnePanneDeReseau(erreurSession)) ratee = 'reseau'
    } else {
      /* ⚠️ Une panne n'est pas « pas de foyer ». `current_household` d'une personne SANS foyer rend
         `data` nul SANS `error` : toute `error` (502, 503, 504, jeton expiré, délai dépassé, projet
         en pause) est donc une panne. Le `data` nul d'un `fetch` raté était lu comme « aucun
         foyer » : ouverte sans réseau, l'appli finissait, après vingt secondes d'« Un instant… »,
         sur « Il te faut une invitation » — à quelqu'un qui a un foyer. */
      const f = await supabase.rpc('current_household')
      if (f.error) note(f.error, f.status)
      hh = f.data ?? null
      // Tant que le mot de passe n'est pas posé, on n'entre pas : sinon la
      // personne repart sur un lien par mail à chaque connexion.
      const pr = await supabase.from('user_profile')
        .select('password_set, display_name').eq('id', data.session.user.id).maybeSingle()
      if (pr.error) note(pr.error, pr.status)
      p = pr.data
    }
    if (ceTour !== tour.current) return
    applique({ session: data.session, foyer: hh, profil: p, ratee, expiree })
  }, [applique])

  useEffect(() => {
    relire()
    const { data: sub } = supabase.auth.onAuthStateChange(async (evenement, s) => {
      /*
       * ⚠️ L'intention ne se garde PAS en mémoire React.
       *
       *    `PASSWORD_RECOVERY` n'est émis qu'UNE fois, au chargement où le
       *    fragment d'URL porte `type=recovery` — ensuite Supabase nettoie
       *    l'URL. Un état React mourait donc au premier rechargement, et
       *    l'ancien mot de passe redevenait valable : exactement le défaut
       *    qu'on croyait avoir corrigé. Et la barre de navigation de l'écran
       *    étant faite de liens `<a href>`, un simple clic rechargeait la page.
       *
       *    On l'écrit donc en BASE. La garde redevient `!mdpPose` seule : elle
       *    survit au rechargement et aux liens par construction, et il n'y a
       *    plus qu'une seule règle à tenir.
       */
      if (evenement === 'SIGNED_IN') setPerdue(false)
      if (evenement === 'PASSWORD_RECOVERY' && s?.user) {
        /* Le tour avance DÈS l'événement, avant l'écriture : la relecture
           d'`INITIAL_SESSION`, partie plus tôt, lirait encore « posé » et
           ouvrirait l'accueil le temps que l'écriture aboutisse. */
        tour.current++
        await supabase.from('user_profile')
          .update({ password_set: false }).eq('id', s.user.id)
      }
      relire()
    })
    /* `signOut` d'un autre onglet, jeton expiré : supabase-js le dit. Un jeton RETIRÉ du
       stockage, lui, ne dit rien — c'est la requête refusée qui l'apprend (`session-perdue.ts`). */
    const surSessionPerdue = () => {
      if (!sessionRef.current) return
      setPerdue(true)
      relire()
    }
    window.addEventListener(SESSION_PERDUE, surSessionPerdue)
    return () => { sub.subscription.unsubscribe(); window.removeEventListener(SESSION_PERDUE, surSessionPerdue) }
  }, [relire])

  /* Déconnectée sur un lien à requête : on garde le chemin ET la requête jusqu'après la connexion. */
  useEffect(() => {
    if (!pret || session || panne) return
    const vers = retourApresConnexion(ici, window.location.search)
    if (vers) garderLeRetour(vers)
  }, [pret, session, panne, ici])

  const ecran = (): ReactNode => {
  if (!pret) return <main className="min-h-dvh grid place-items-center text-doux">Un instant…</main>

  const invitation = ici.match(/^\/invite\/(.+)$/)
  const amitie = ici.match(/^\/ami\/(.+)$/)
  // La session d'un AUTRE foyer, où l'on est convié. Le seul chemin de l'app
  // qui porte un identifiant : « la » session de quelqu'un ne se devine pas.
  const sessionAmie = ici.match(/^\/cuisine\/(.+)$/)

  // L'ordre compte. Une invitation prime sur tout : sans cela, l'invité se voit
  // proposer de créer SON foyer au lieu de rejoindre celui qui l'attend.
  /* ⚠️ Le CHEMIN, jamais `window.location.href`.
     Le fragment venait avec : après un lien expiré, `#error=…otp_expired…`.
     Supabase colle `#access_token=…` derrière l'adresse de retour — deux `#`,
     et supabase-js, qui lit le premier, y trouvait l'erreur et refusait la
     session. Un seul lien mort condamnait tous les suivants : le 30 septembre,
     trois connexions acceptées par Supabase, trois sessions jetées ici. */
  /* ⚠️ Sans compte, un lien d'invitation SUFFIT (décision du 19/10/2026) :
     elle y choisit son mot de passe, et son compte naît. L'écran de connexion
     la renvoyait chercher un lien par mail, mort au bout d'une heure — cinq
     invitées n'ont jamais dépassé cette étape. */
  /* La panne d'abord, même sans session : `getSession` en panne de réseau rend `session: null`. */
  if (panne) return <HorsLigne reessayer={relire} panne={panne} />
  if (!session) {
    return invitation && !connexionDemandee
      ? <Rejoindre token={invitation[1]} connexion={() => setConnexionDemandee(true)} />
      : <SignIn redirectTo={lienDeploye(ici)}
                info={perdue ? 'Ta session a expiré : reconnecte-toi.' : undefined} />
  }
  if (invitation) {
    return <AcceptInvite token={invitation[1]} dejaChezToi={!!foyer} va={va}
                         compte={session.user.email ?? ''} />
  }
  if (!foyer) return <Onboarding onDone={relire} />
  // Tant qu'aucun mot de passe n'est posé, on n'entre pas — sinon on repart sur
  // un lien par mail à chaque connexion. Un retour de réinitialisation remet
  // `password_set` à faux, ce qui range les deux cas sous la même règle.
  if (!mdpPose) return <Password userId={session.user.id} onDone={relire} />
  /* ⚠️ APRÈS le mot de passe : elle vient d'arriver, sa date d'entrée et son
     revenu décident de tout le partage, et le hub ne lui en parle jamais. Cet
     écran-là est le sien ; il la mène ensuite où elle veut. */
  if (sansPrenom && !prenomRemis) {
    /* ⚠️ Une INVITATION à remplir, pas un mur.
       Avec `retour={relire}`, le bouton « ‹ Popote » recalculait `sansPrenom`,
       réaffichait le même écran, et il n'y avait plus aucune sortie. Un écran
       dont on ne sort pas est pire que le champ vide qu'il réclame : les
       écrans disent « Sans prénom » en attendant, et l'avatar du hub ramène
       ici quand elle veut. */
    return <Profil userId={session.user.id} onFini={relire}
                   retour={() => setPrenomRemis(true)} />
  }

  const moi = session.user.id
  // Retour à l'accueil plutôt qu'à l'historique du navigateur : un passage
  // ouvert depuis une notification n'a pas de page précédente.
  /* `/cuisine-accueil`, PAS `/` : depuis que `/` est le hub, un passage ouvert
     sans historique — par une notification, par un lien — déposait sur l'écran
     du choix entre univers au lieu de l'accueil de la cuisine. */
  const sortie = () => (window.history.length > 1 ? retour() : va('/cuisine-accueil'))

  // ⚠️ APRÈS le mot de passe et le foyer, à la différence d'une invitation de
  //    foyer : rejoindre des amis suppose qu'on a déjà un foyer à soi, et on
  //    n'entre jamais sans avoir posé son mot de passe.
  if (amitie) return <AccepteAmi jeton={amitie[1]} va={va} />
  if (sessionAmie) return <Cuisine userId={moi} va={va} cycleId={sessionAmie[1]} />

  /* `/stock` était « Ce que j'ai » : le frigo l'a remplacé (26/10/2026). On ne laisse pas un lien enregistré, une
     notification ou l'aide tomber sur le hub. Hors du `switch` exprès : un `case` ferait de `/stock` un écran à
     ranger dans l'aide (`aide.test.ts`), et ce n'en est plus un. */
  if (ici === '/stock') return <Redirige vers="/frigo" remplace={remplace} />

  /* Un mois donné du budget : la clôture y ramène, sur le mois qu'elle vient de
     fermer. `key` : sans elle, React garderait l'écran déjà monté, et son mois
     d'avant. */
  if (adresseDeMoisFausse(ici)) return <Redirige vers="/budget" remplace={remplace} />
  const moisVu = ici.match(/^\/budget\/(\d{4})-(0[1-9]|1[0-2])$/)
  if (moisVu) {
    return <Budget key={ici} userId={moi} va={va} remplace={remplace}
                   mois={`${moisVu[1]}-${moisVu[2]}-01`} />
  }

  /* La clôture d'un mois (§ 3.5). Comme `/invite/`, avant le `switch` : elle porte son
     mois dans l'adresse. Seuls les mois qui existent : `2026-13` retombe sur le hub, au
     lieu d'interroger la base avec une date fausse. `key` : sans elle, React garderait
     la page déjà montée, et son mois d'avant. */
  const aClore = ici.match(/^\/cloture\/(\d{4})-(0[1-9]|1[0-2])$/)
  if (aClore) {
    return <Cloture key={ici} userId={moi} va={va} mois={`${aClore[1]}-${aClore[2]}-01`}
                    retour={() => (window.history.length > 1 ? retour() : va('/budget'))} />
  }

  /* Toutes les charges, déjà filtrées sur une catégorie (et une personne) quand on vient de sa carte
     (`/toutes-les-charges/maison`, `/toutes-les-charges/maison/<id>`). */
  const tableau = ici.match(/^\/toutes-les-charges(?:\/([a-z_]+)(?:\/([0-9a-f-]{36}))?)?$/)
  if (tableau) {
    return <ToutesLesCharges key={ici} userId={moi} categorie={tableau[1]} qui={tableau[2]}
                             retour={() => (window.history.length > 1 ? retour() : va('/budget'))} />
  }

  switch (ici) {
    /* Les deux univers. `/` est le hub — il ne porte pas de barre du bas, c'est
       l'écran qu'on quitte immédiatement — et `/cuisine-accueil` est l'accueil
       de la cuisine, qui était `/` jusqu'ici. */
    case '/budget': return <Budget userId={moi} va={va} />
    case '/charges': return <Charges userId={moi} retour={() => va('/budget')} />
    case '/budget-reglages': return <BudgetReglages userId={moi} retour={() => va('/budget')} />
    case '/epargne': return <Epargne userId={moi} retour={() => va('/budget')} />
    case '/mois-type': return <MoisType userId={moi} va={va} retour={() => va('/budget')} />
    case '/profil':
      return <Profil userId={moi} onFini={() => va('/')} retour={() => va('/')} />
    case '/cuisine-accueil': return <Accueil userId={moi} va={va} />

    // Les quatre destinations permanentes.
    case '/semaine': return <Semaine userId={moi} va={va} remplace={remplace} />
    case '/frigo': return <Frigo userId={moi} va={va} />
    case '/bilan': return <Bilan va={va} userId={moi} />

    // Les passages du cycle : une seule sortie, pas de barre du bas.
    case '/choisir': return <Choisir retour={sortie} va={va} />
    case '/magasin': return <Magasin retour={sortie} va={va} />
    case '/plan': return <Plan retour={sortie} va={va} />
    case '/cuisine': return <Cuisine userId={moi} va={va} />
    case '/dressage': return <Dressage retour={sortie} va={va} userId={moi} />
    case '/inventer': return <Inventer userId={moi} retour={sortie} va={va} />
    case '/photo': return <Photo retour={sortie} va={va} />
    case '/ticket': return <Ticket retour={sortie} va={va} />
    case '/peser': return <Peser retour={sortie} />
    case '/importer': return <Importer retour={sortie} va={va} />

    // Nos aliments : depuis les réglages et la feuille de choix de la semaine.
    case '/aliments': return <Aliments va={va} />

    // Les réglages, hors cycle.
    case '/objectifs': return <Targets userId={moi} />
    case '/reglages': return <Settings va={va} />
    case '/rappels': return <Rappels userId={moi} retour={() => (window.history.length > 1 ? retour() : va('/reglages'))} />
    // Changer son mot de passe : l'écran existait, sans aucun chemin pour y
    // aller une fois le premier posé.
    case '/motdepasse':
      /* Le HUB, pas les réglages : quelqu'un qui vient de poser son mot de
         passe découvre l'application, et le hub porte le bandeau qui lui dit
         quoi faire. Une page de paramètres n'accueille personne. */
      return <Password userId={moi} onDone={() => va('/')} retour={() => va('/reglages')} />

    default: return <Hub userId={moi} va={va} />
  }
  }

  /* L'aide n'existe que dans l'appli installée : ni sur la connexion, ni sur un lien d'invitation, ni avant le
     mot de passe et le prénom — on n'y pose pas de question sur ce qu'on n'a pas encore vu. */
  const dansLAppli = !!session && !!foyer && mdpPose && !(sansPrenom && !prenomRemis) && !panne
    && !/^\/(invite|ami)\//.test(ici)

  return (
    <>
      {ecran()}
      {dansLAppli && session && <Aide userId={session.user.id} ici={ici} va={va} />}
      {alerte && <BandeauDePanne message={alerte} reessayer={relire} />}
    </>
  )
}

/**
 * Quitte une adresse qui ne se lit pas (`/budget/2026-13`, `/cloture/abc`) pour `vers`, sans
 * l'ajouter à l'historique : sans cela, le hub s'affichait sous l'adresse fautive, qui restait
 * telle quelle (comme un mois à venir, que `Budget` ramène déjà à `/budget`).
 */
function Redirige({ vers, remplace }: { vers: string; remplace: (v: string) => void }) {
  useEffect(() => { remplace(vers) }, [vers, remplace])
  return null
}

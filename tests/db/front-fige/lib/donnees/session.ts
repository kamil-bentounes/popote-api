/**
 * La session du dimanche : calcul du plan, puis son exécution (D5, D47 à D50).
 *
 * Le plan est calculé sur le téléphone puis PERSISTÉ. Deux raisons, et aucune
 * n'est de la performance : deux téléphones doivent voir la même chose (D50),
 * et reprendre après une interruption ne doit rien recalculer — sinon l'ordre
 * des gestes changerait sous les mains de celui qui cuisine.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ou, supabase } from '../supabase.ts'

/** `.in()` porte ses valeurs dans l'URL : au-delà d'environ 205 identifiants,
    la passerelle répond 414 plutôt que de tronquer. */
const PAR_PAQUET = 150

async function parPaquets<T>(ids: string[], lire: (lot: string[]) => Promise<T[]>): Promise<T[]> {
  const sortie: T[] = []
  for (let i = 0; i < ids.length; i += PAR_PAQUET) {
    sortie.push(...await lire(ids.slice(i, i + PAR_PAQUET)))
  }
  return sortie
}
import type { Ligne } from '../supabase.ts'
import { actionsDeLaSession } from '../plan/fusion.ts'
import type { Etape } from '../plan/fusion.ts'
import { appareilDuCatalogue } from '../plan/duree.ts'
import { planifie } from '../plan/ordonnance.ts'
import type { Plan, Ressources } from '../plan/types.ts'

export type Action = Ligne<'session_task'> & { recettes: string[]; dependDe: string[] }

export const CLE = {
  plan: (cycleId: string | undefined) => ['plan', cycleId] as const,
  appareilsSession: (cycleId: string | undefined) => ['session-appareils', cycleId] as const,
}

/** `suivre` : relire toutes les 5 s tant qu'une action est en cours — pendant la cuisine seulement. Après
    « J'ai fini », une action restée « en cours » faisait tourner la relecture toute la semaine sur l'accueil. */
export function usePlanEnregistre(cycleId: string | undefined, suivre = true) {
  return useQuery({
    queryKey: CLE.plan(cycleId),
    enabled: !!cycleId,
    queryFn: async (): Promise<Action[]> => {
      const taches = ou(await supabase.from('session_task').select('*')
        .eq('cycle_id', cycleId!).order('planned_start_min'))
      if (taches.length === 0) return []
      const ids = taches.map(t => t.id)
      const [liensRecettes, arcs] = await Promise.all([
        supabase.from('session_task_recipe').select('task_id, recipe:recipe_id(title)')
          .in('task_id', ids),
        supabase.from('session_task_dependency').select('task_id, depends_on_id')
          .in('task_id', ids),
      ])

      const parTache = new Map<string, string[]>()
      for (const l of ou(liensRecettes) as unknown as
        { task_id: string; recipe: { title: string | null } | null }[]) {
        if (!parTache.has(l.task_id)) parTache.set(l.task_id, [])
        if (l.recipe?.title) parTache.get(l.task_id)!.push(l.recipe.title)
      }
      const avant = new Map<string, string[]>()
      for (const a of ou(arcs)) {
        if (!avant.has(a.task_id)) avant.set(a.task_id, [])
        avant.get(a.task_id)!.push(a.depends_on_id)
      }
      return taches.map(t => ({
        ...t,
        recettes: parTache.get(t.id) ?? [],
        dependDe: avant.get(t.id) ?? [],
      }))
    },
    // Pendant la cuisine, l'autre téléphone coche : on rafraîchit souvent.
    staleTime: 3_000,
    refetchInterval: q => (suivre && q.state.data?.some(t => t.started_at && !t.done_at) ? 5_000 : false),
  })
}

export function useAppareilsDeLaSession(cycleId: string | undefined) {
  return useQuery({
    queryKey: CLE.appareilsSession(cycleId),
    enabled: !!cycleId,
    queryFn: async () => ou(await supabase.from('session_appliance').select('*')
      .eq('cycle_id', cycleId!)),
  })
}

/**
 * L'équipement de la DERNIÈRE session du foyer qui en avait un (code → capacité), hors la session
 * courante ; `{}` si le foyer n'a jamais rien choisi. C'est le point de départ de « Équipement du
 * jour » : on ne recoche pas ses huit appareils chaque dimanche. Le foyer est filtré à la main : la
 * lecture de `session_appliance` s'ouvre aussi aux sessions où l'on est convié.
 */
export async function lisLEquipementPrecedent(cycleId: string): Promise<Record<string, number>> {
  const foyer = ou(await supabase.rpc('current_household'))
  if (!foyer) return {}
  const [derniere] = ou(await supabase.from('cycle')
    .select('id, session_appliance!inner(appliance_code, capacity)')
    .eq('household_id', foyer).neq('id', cycleId)
    .order('week_of', { ascending: false }).order('created_at', { ascending: false })
    .limit(1))
  return Object.fromEntries((derniere?.session_appliance ?? [])
    .map(a => [a.appliance_code, a.capacity]))
}

export function useEquipementPrecedent(cycleId: string | undefined) {
  return useQuery({
    queryKey: [...CLE.appareilsSession(cycleId), 'precedent'] as const,
    enabled: !!cycleId,
    queryFn: () => lisLEquipementPrecedent(cycleId!),
    staleTime: 60_000,
  })
}

export function useChoisitAppareils() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ cycleId, codes }: { cycleId: string; codes: Record<string, number> }) => {
      const foyer = ou(await supabase.rpc('current_household'))
      if (!foyer) throw new Error('Aucun foyer.')
      ou(await supabase.from('session_appliance').delete().eq('cycle_id', cycleId).select())
      const lignes = Object.entries(codes)
        .filter(([, cap]) => cap > 0)
        .map(([code, capacity]) => ({
          cycle_id: cycleId, household_id: foyer, appliance_code: code, capacity,
        }))
      if (lignes.length === 0) return []
      return ou(await supabase.from('session_appliance').insert(lignes).select())
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

/** Charge les étapes des recettes choisies, prêtes pour la fusion. */
/** Exportée pour être éprouvée : c’est ELLE qui décide de ce que
    l’ordonnanceur voit, et son ordre est un invariant du produit. */
export async function etapesDuCycle(cycleId: string): Promise<Etape[]> {
  const choisies = ou(await supabase.from('cycle_recipe').select('recipe_id')
    .eq('cycle_id', cycleId))
  if (choisies.length === 0) return []
  const ids = choisies.map(c => c.recipe_id)

  // ⚠️ `.order('ordinal')` SEUL rendait les lignes ordinal-majeur, entrelacées
  //    entre recettes : « R1 émince, R2 émince, R1 cuit, R2 cuit… ». La boucle
  //    plus bas repart à zéro dès que la recette change, donc elle repartait à
  //    CHAQUE ligne, et aucune dépendance implicite ne survivait. L'ordonnanceur
  //    recevait un graphe entièrement plat — libre de placer « Enfournez » avant
  //    « Préparez la pâte ». Mesuré : 0 étape sur 6 gardait son prédécesseur.
  const lignes = ou(await supabase.from('recipe_step').select('*')
    .in('recipe_id', ids).order('recipe_id').order('ordinal'))

  // Les dépendances déclarées, filtrées sur les étapes du cycle. La table
  // entière se heurterait au plafond silencieux de 1 000 lignes, et un
  // sous-ensemble arbitraire d'arcs n'est pas reproductible d'un téléphone à
  // l'autre (D50) — le tirage semé de l'ordonnanceur n'y pourrait rien.
  const connues = new Set(lignes.map(e => e.id))
  const deps = lignes.length === 0 ? [] : await parPaquets([...connues], async lot =>
    ou(await supabase.from('recipe_step_dependency')
      .select('before_id, after_id').in('after_id', lot).order('before_id')))

  const avant = new Map<string, string[]>()
  for (const d of deps) {
    if (!connues.has(d.after_id) || !connues.has(d.before_id)) continue
    if (!avant.has(d.after_id)) avant.set(d.after_id, [])
    avant.get(d.after_id)!.push(d.before_id)
  }

  // À défaut de dépendance déclarée, l'ordre du texte fait foi : on ne bat pas
  // les cartes d'une recette sous prétexte que personne n'a saisi son graphe.
  const precedente = new Map<string, string | null>()
  let recette: string | null = null
  let derniere: string | null = null
  for (const e of lignes) {
    if (e.recipe_id !== recette) { recette = e.recipe_id; derniere = null }
    precedente.set(e.id, derniere)
    derniere = e.id
  }

  return lignes.map(e => ({
    id: e.id,
    recetteId: e.recipe_id,
    texte: e.text,
    ordinal: e.ordinal,
    dureeMin: e.duration_min === null ? null : Number(e.duration_min),
    verbe: e.verb,
    quantiteG: e.quantity_g === null ? null : Number(e.quantity_g),
    // Une recette inventée par un modèle écrit « plaque » ; l'ingestion écrit
    // « plaques ». `session_task.appliance_code` a une clé étrangère vers le
    // catalogue : sans cette normalisation, le plan refuse de s'enregistrer.
    appareil: appareilDuCatalogue(e.appliance_type),
    charge: e.load_type,
    dependDe: avant.get(e.id) ?? (precedente.get(e.id) ? [precedente.get(e.id)!] : []),
  }))
}

/**
 * Calcule un plan SANS l'enregistrer. Sert à l'arbitrage (D5) : on montre le
 * plan à four simple et le plan à four double, et on chiffre l'écart en minutes
 * plutôt que de trancher à la place des gens.
 */
export function useSimule(cycleId: string | undefined) {
  return useQuery({
    queryKey: ['simulation', cycleId],
    enabled: !!cycleId,
    queryFn: async () => {
      const [etapes, appareils, foyer] = await Promise.all([
        etapesDuCycle(cycleId!),
        supabase.from('session_appliance').select('*').eq('cycle_id', cycleId!),
        supabase.from('user_profile').select('id'),
      ])
      const actions = actionsDeLaSession(etapes)
      const capacites = Object.fromEntries(
        ou(appareils).map(a => [a.appliance_code, a.capacity]))
      const ressources: Ressources = {
        cuisiniers: Math.max(1, ou(foyer).length),
        appareils: capacites,
      }
      const base = planifie(actions, ressources, { graine: cycleId! })

      // Le même plan avec un four qui prendrait deux plats : l'écart est ce que
      // coûte l'appareil, en minutes. C'est le seul chiffre qui aide à trancher.
      const elargi = planifie(actions, {
        ...ressources,
        appareils: Object.fromEntries(
          Object.entries(capacites).map(([c, n]) => [c, Math.max(2, n)])),
      }, { graine: cycleId! })

      return {
        actions, base, elargi, ressources,
        // L'écart qui parle est celui du temps passé EN CUISINE : c'est lui
        // qu'on troque contre un deuxième plat au four.
        gainSiElargi: base.finEnCuisineMin - elargi.finEnCuisineMin,
      }
    },
  })
}

/** Le goulot : l'appareil qui occupe la plus grande part du chemin critique. */
export function goulot(plan: Plan): string | null {
  const sur = plan.taches.filter(t => plan.chemin.includes(t.id) && t.appareil)
  if (sur.length === 0) return null
  const parAppareil = new Map<string, number>()
  for (const t of sur) parAppareil.set(t.appareil!, (parAppareil.get(t.appareil!) ?? 0) + t.dureeMin)
  return [...parAppareil.entries()].sort((a, b) => b[1] - a[1])[0][0]
}

/** Enregistre le plan calculé. Écrase l'ancien : on ne fusionne pas deux plans. */
export function useEnregistrePlan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ cycleId, plan }: { cycleId: string; plan: Plan }) => {
      const foyer = ou(await supabase.rpc('current_household'))
      if (!foyer) throw new Error('Aucun foyer.')

      // Recalculer alors que la session a commencé effacerait ce qui est fait.
      const deja = ou(await supabase.from('session_task').select('id')
        .eq('cycle_id', cycleId).not('started_at', 'is', null).limit(1))
      if (deja.length > 0) throw new Error('La session a commencé : le plan ne se recalcule plus.')

      ou(await supabase.from('session_task').delete().eq('cycle_id', cycleId).select())

      /*
       * ⚠️ On ne reprend PLUS l'identifiant de l'étape de recette.
       *
       * `session_task.id` est une clé primaire globale. Reprendre l'id de
       * `recipe_step` rendait deux choses impossibles :
       *
       *  · **refaire une recette.** Le cycle de la semaine dernière garde ses
       *    `session_task` (clore un cycle ne les efface pas) ; recuisiner le
       *    même dahl levait un 23505, après que le `delete` avait déjà vidé le
       *    plan courant — l'écran restait en erreur, sans plan.
       *  · **cuisiner en même temps qu'un autre foyer.** Le second à enregistrer
       *    se prenait un 23505 sur une ligne qu'il ne peut même pas lire.
       *
       * La base génère donc l'identifiant, et `parTache` relie les liens de
       * recette et les dépendances aux lignes réellement écrites.
       */
      const lignes = plan.taches.map((t, i) => ({
        cycle_id: cycleId,
        household_id: foyer,
        label: t.label,
        verb: t.verbe,
        quantity_g: t.quantiteG,
        appliance_code: t.appareil,
        duration_min: t.dureeMin,
        is_active: t.actif,
        planned_start_min: t.debutMin,
        position: i,
      }))
      const posees = ou(await supabase.from('session_task').insert(lignes).select())

      // L'insert rend les lignes dans l'ordre envoyé : `position` fait le lien
      // entre la tâche du plan et l'identifiant que la base a choisi.
      const parPosition = new Map(posees.map(l => [l.position, l.id]))
      const idDe = (tache: string) => {
        const i = plan.taches.findIndex(x => x.id === tache)
        return i < 0 ? null : parPosition.get(i) ?? null
      }

      const liens = plan.taches.flatMap((t, i) =>
        t.recettes.map(recipe_id => ({
          task_id: parPosition.get(i)!, recipe_id, household_id: foyer,
        })))
      if (liens.length > 0) ou(await supabase.from('session_task_recipe').insert(liens).select())

      const arcs = plan.taches.flatMap((t, i) => t.dependDe
        .map(d => idDe(d))
        .filter((id): id is string => id !== null)
        .map(depends_on_id => ({
          task_id: parPosition.get(i)!, depends_on_id, household_id: foyer,
        })))
      if (arcs.length > 0) ou(await supabase.from('session_task_dependency').insert(arcs).select())

      return posees
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

/**
 * Prendre une action (D50) : elle passe à son nom, et l'horloge démarre. La
 * durée réelle est mesurée par la base (D48), jamais demandée.
 */
export function useCommenceAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, parQui }: { id: string; parQui?: string | null }) =>
      ou(await supabase.from('session_task').update({
        started_at: new Date().toISOString(),
        ...(parQui ? { assignee_id: parQui } : {}),
      }).eq('id', id).select().single()),
    onSuccess: () => qc.invalidateQueries(),
  })
}

export function useTermineAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      // Terminer sans avoir commencé arrive : on coche l'action qu'on a faite
      // sans toucher au téléphone. On pose alors le début à la durée prévue en
      // arrière — mieux qu'une mesure de zéro seconde qui fausserait D48.
      //
      // ⚠️ Chez SOI seulement. Dans la session d'un hôte, la base repose
      //    `started_at` à `now()` (0039) : un convive ne dicte pas une mesure
      //    qui ira nourrir les durées par défaut d'une autre cuisine. Le
      //    chemin ne s'atteint de toute façon pas — on ne termine là-bas qu'un
      //    geste qu'on a pris, donc déjà commencé.
      const t = ou(await supabase.from('session_task')
        .select('started_at, duration_min').eq('id', id).single())
      const fin = new Date()
      const debut = t.started_at
        ?? new Date(fin.getTime() - Number(t.duration_min) * 60_000).toISOString()
      return ou(await supabase.from('session_task').update({
        started_at: debut, done_at: fin.toISOString(),
      }).eq('id', id).select().single())
    },
    onSuccess: () => qc.invalidateQueries(),
  })
}

export type Avancement = {
  faites: number
  total: number
  ecoulesMin: number
  restantesMin: number
  enCours: Action[]
  suivantes: Action[]
}

/** Où en est la session, maintenant. L'écran de cuisine ne montre que ça. */
export function avancement(actions: Action[], debut: Date | null, maintenant = new Date()): Avancement {
  const faites = actions.filter(a => a.done_at)
  const enCours = actions.filter(a => a.started_at && !a.done_at)
  const restantes = actions.filter(a => !a.done_at)
  const finies = new Set(faites.map(a => a.id))

  return {
    faites: faites.length,
    total: actions.length,
    ecoulesMin: debut ? (maintenant.getTime() - debut.getTime()) / 60_000 : 0,
    restantesMin: restantes.reduce((s, a) => s + Number(a.duration_min), 0),
    enCours,
    // Ce qui peut être pris tout de suite : toutes dépendances levées. Le reste
    // n'a pas à encombrer l'écran de quelqu'un qui a les mains dans la farine.
    suivantes: restantes
      .filter(a => !a.started_at && a.dependDe.every(d => finies.has(d)))
      .sort((a, b) => Number(a.planned_start_min) - Number(b.planned_start_min))
      .slice(0, 3),
  }
}

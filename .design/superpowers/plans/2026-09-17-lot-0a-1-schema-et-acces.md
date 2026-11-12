# Lot 0a-1 — Schéma et accès — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer un projet Supabase en région UE dont l'isolation multi-foyers est **prouvée par des tests qui échouent quand on retire la RLS**, avec le schéma des trois classes, le flux d'invitation par e-mail, les profils et cibles nutritionnelles, le compteur de budget LLM, et l'export/suppression de compte.

**Architecture:** Postgres (Supabase) porte trois classes d'isolation — A référentiel en lecture seule, B catalogue partagé en écriture tracée, C données de foyer sous RLS stricte. `current_household()` en `SECURITY DEFINER` contourne la RLS de `user_profile` **par ownership de table** et évite la récursion. Un trigger `BEFORE UPDATE` porte ce que RLS ne sait pas exprimer. Le front est une PWA React minimale : une porte d'entrée et trois écrans.

**Tech Stack:** Supabase CLI (installé en devDependency) · **PostgreSQL 15+** (le CLI 2.x provisionne du 17 en local ; `unique nulls not distinct` exige ≥ 15, donc le projet distant aussi) · React + TypeScript + Vite (versions du template `react-ts` courant) · Vitest · `@supabase/supabase-js` · Edge Functions Deno · Resend

**Spec de référence :** `docs/superpowers/specs/2026-09-17-batch-cooking-app-design.md` **(v9)** — §5.0, §5.0.1, §5.1, §5.2, §5.3, §10, §11.

**Hors périmètre, explicitement :** peuplement des référentiels (0a-2), ingestion (0b), pesée (0c), optimiseur (lot 1) et tout le reste. Les tables de classe A et B sont **créées vides**.

---

## Deux pièges vérifiés empiriquement — lire avant de commencer

1. **`recipe.plannable` n'est PAS maintenue par trigger dans ce lot.** Le spec §5.3 l'exige, mais son calcul dépend des durées des *actions*, qui n'existent qu'au lot 0b. Ici la colonne est créée avec `default false` et **le trigger est explicitement reporté au lot 0b**. Ne pas l'implémenter à vide.
2. **La policy `select using (true)` de la classe B ignore `visibility` et `owner_household_id`.** Sans effet ici — les tables sont vides — mais elle devra être resserrée au lot 4, quand des recettes privées créées par un foyer existeront. La phrase « aucun foyer ne voit les données d'un autre » est donc vraie **pour les données de foyer (classe C)**, pas pour un catalogue partagé qui est vide.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `supabase/migrations/0001_class_c.sql` | DDL classe C — foyer. **En premier** : le socle de test en dépend. |
| `supabase/migrations/0002_class_a.sql` | DDL classe A — référentiel et infrastructure, 11 tables |
| `supabase/migrations/0003_class_b.sql` | DDL classe B — catalogue partagé, 4 tables + traçabilité |
| `supabase/migrations/0004_current_household.sql` | `current_household()` en `SECURITY DEFINER` + droits |
| `supabase/migrations/0005_policies.sql` | Les trois formes de policies RLS (§5.0.1) |
| `supabase/migrations/0006_triggers.sql` | Garde classe B · dénormalisation · `updated_at` |
| `supabase/migrations/0007_llm_budget.sql` | `llm_usage`, les deux plafonds, les deux fonctions |
| `supabase/migrations/0008_rgpd.sql` | Export et suppression de compte (§11 q. 1) |
| `supabase/migrations/0009_create_household.sql` | Création du premier foyer, **bridée** pour rester sur invitation (D7) |
| `supabase/config.toml` | **À éditer, pas seulement à générer** : `site_url`, redirections, `verify_jwt`, auto-inscription |
| `supabase/functions/_shared/cors.ts` | En-têtes CORS et préflight — sans quoi le front ne peut rien appeler |
| `supabase/functions/invite/index.ts` | Crée une invitation, l'envoie via Resend |
| `supabase/functions/accept-invite/index.ts` | Consomme un token, rattache l'utilisateur au foyer |
| `tests/helpers/db.ts` | Deux foyers, deux utilisateurs, clients authentifiés |
| `tests/isolation.test.ts` | **Le livrable central**, et il doit rougir si on retire la RLS |
| `tests/class-b-guard.test.ts` | Écriture tracée, champs sûrs protégés, INSERT/DELETE refusés |
| `tests/invitation.test.ts`, `tests/llm-budget.test.ts`, `tests/rgpd.test.ts` | Le reste |
| `src/lib/supabase.ts` · `src/pages/*.tsx` | Porte d'entrée + trois écrans |

**Un fichier de migration = une responsabilité.** C'est sur elles que porte l'audit d'isolation.

---

### Task 1 : Échafaudage du projet

⚠️ **Le dépôt n'est PAS vide** : il contient `docs/`. `npm create vite@latest .` y refuse de travailler, et sa seule option (`--overwrite`) **supprimerait `docs/`**, donc le spec et ce plan. On échafaude dans un sous-dossier puis on déplace.

**Files:**
- Create: `package.json`, `vite.config.ts`, `tsconfig*.json`, `index.html`, `src/`, `.env.example`, `.gitignore`

- [ ] **Step 1 : Échafauder hors du dépôt racine, puis déplacer**

```bash
cd <racine du dépôt>
npm create vite@latest .scaffold -- --template react-ts
cp -r .scaffold/. .
rm -rf .scaffold
ls package.json src/App.tsx docs/superpowers/specs/  # les trois doivent exister
```

Attendu : `package.json` et `src/App.tsx` créés, **et `docs/` intact**. Si `docs/` a disparu, `git checkout -- docs/` immédiatement.

- [ ] **Step 2 : Installer les dépendances, CLI Supabase comprise**

```bash
npm install
npm install @supabase/supabase-js
npm install -D vitest dotenv supabase
npx supabase --version   # doit répondre : le CLI est en devDependency, pas global
```

> Le CLI **doit** être une devDependency : sans lui, tous les `npm run db:reset` du plan échouent.

- [ ] **Step 3 : Initialiser Supabase en local**

```bash
npx supabase init
npx supabase start
```

Noter `API URL`, `anon key`, `service_role key`.

- [ ] **Step 4 : `.env.example`, `.env`, `.gitignore`**

```bash
cat > .env.example <<'EOF'
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
EOF
mkdir -p supabase/functions
cat > supabase/functions/.env.example <<'EOF'
RESEND_API_KEY=
APP_BASE_URL=http://localhost:5173
EOF
printf '%s\n' 'node_modules/' 'dist/' '.env' '.env.local' '.scaffold/' \
  'supabase/.temp/' 'supabase/functions/.env' '.DS_Store' > .gitignore
cp .env.example .env
cp supabase/functions/.env.example supabase/functions/.env
```

Renseigner `.env` avec les clés du Step 3. **`supabase/functions/.env` est lu automatiquement par `supabase functions serve`.**

- [ ] **Step 4bis : Corriger `supabase/config.toml` — sans quoi rien ne fonctionne**

`supabase init` génère trois réglages incompatibles avec ce projet. **Vérifié** :

| Réglage généré | Problème | Valeur à poser |
|---|---|---|
| `site_url = "http://127.0.0.1:3000"` | L'app tourne sur `:5173`. Le lien magique **retombe sur un port où rien n'écoute** : tout le parcours du Step 11 de la Task 10 est bloqué. | `site_url = "http://localhost:5173"` |
| `additional_redirect_urls = ["https://127.0.0.1:3000"]` | `emailRedirectTo` n'est pas en liste blanche, GoTrue l'ignore. | y ajouter `"http://localhost:5173"` et `"http://localhost:5173/**"` |
| aucune section `[functions]` → `verify_jwt = true` | Le préflight CORS `OPTIONS` **ne porte pas d'`Authorization`** : il reçoit 401 et n'atteint jamais le code de la fonction. | ⚠️ **Se règle en Task 9**, pas ici — voir l'encadré ci-dessous |

```toml
[auth]
site_url = "http://localhost:5173"
additional_redirect_urls = ["http://localhost:5173", "http://localhost:5173/**"]
```

> ⚠️ **Constaté à l'exécution** : déclarer `[functions.invite]` / `[functions.accept-invite]`
> **avant que les fichiers existent** fait échouer `supabase start` —
> `failed to read file: open supabase/functions/accept-invite/index.ts: no such file or directory`.
> Le CLI tente d'empaqueter toute fonction déclarée. Ces deux sections sont donc ajoutées
> **en Task 9, Step 5bis**, une fois les fonctions écrites.

⚠️ **`enable_signup = true` est la valeur par défaut** : n'importe qui pourrait s'inscrire et créer
un foyer, ce qui contredit D7 (« multi-tenant **sur invitation** »). Le verrou est posé dans la
fonction `create_household()` de la Task 10, pas ici — on garde l'auto-inscription active parce
que les invités doivent pouvoir créer leur compte avant d'accepter.

```bash
npx supabase stop && npx supabase start   # config.toml n'est relu qu'au démarrage
```

- [ ] **Step 5 : Ajouter les scripts — FUSIONNER, ne pas remplacer le `package.json`**

Ouvrir `package.json` et **ajouter** ces clés à l'objet `scripts` existant, sans toucher à `dependencies`, `devDependencies`, ni au script `build` généré :

```json
"test": "vitest run --fileParallelism=false",
"db:reset": "supabase db reset"
```

> `--fileParallelism=false` : les fichiers de test partagent une seule base. En parallèle, certaines assertions deviennent dépendantes de l'ordre.

- [ ] **Step 6 : Vérifier**

```bash
npm run test -- --passWithNoTests && npx supabase status
```
Attendu : Vitest sort en 0, les services Supabase sont `RUNNING`.

- [ ] **Step 7 : Commit**

```bash
git add -A && git commit -m "chore(0a-1): échafaudage Vite + Supabase local"
```

---

### Task 2 : Socle de test — deux foyers, deux utilisateurs

Ce fichier définit ce que « isolation prouvée » veut dire. Il insère dans `household` et `user_profile` : c'est pourquoi **la classe C est la première migration**, contrairement à l'ordre de lecture du spec.

**Files:**
- Create: `tests/helpers/db.ts`

- [ ] **Step 1 : Écrire le helper**

```typescript
// tests/helpers/db.ts
import { createClient, SupabaseClient } from '@supabase/supabase-js'
import 'dotenv/config'

const URL = process.env.VITE_SUPABASE_URL!
const ANON = process.env.VITE_SUPABASE_ANON_KEY!
const SERVICE = process.env.SUPABASE_SERVICE_ROLE_KEY!

/** Client qui contourne RLS. Réservé à la préparation des données. */
export const admin = () =>
  createClient(URL, SERVICE, { auth: { persistSession: false } })

export type Actor = { client: SupabaseClient; userId: string; householdId: string; email: string }

const PASSWORD = 'test-password-12345'
const uniqueEmail = (p: string) =>
  `${p}-${Date.now()}-${Math.random().toString(36).slice(2)}@test.local`

/** Crée un foyer, un utilisateur confirmé, et le client authentifié correspondant. */
export async function makeActor(name: string): Promise<Actor> {
  const a = admin()
  const email = uniqueEmail(name)

  const { data: u, error: ue } = await a.auth.admin.createUser({
    email, password: PASSWORD, email_confirm: true,
  })
  if (ue) throw ue

  const { data: h, error: he } = await a
    .from('household').insert({ name: `foyer-${name}` }).select().single()
  if (he) throw he

  const { error: pe } = await a
    .from('user_profile').insert({ id: u.user.id, household_id: h.id, display_name: name })
  if (pe) throw pe

  const client = createClient(URL, ANON, { auth: { persistSession: false } })
  const { error: se } = await client.auth.signInWithPassword({ email, password: PASSWORD })
  if (se) throw se

  return { client, userId: u.user.id, householdId: h.id, email }
}

/** Authentifié mais SANS profil : doit ne rien voir. */
export async function makeOrphan(): Promise<{ client: SupabaseClient; userId: string }> {
  const a = admin()
  const email = uniqueEmail('orphan')
  const { data, error } = await a.auth.admin.createUser({
    email, password: PASSWORD, email_confirm: true,
  })
  if (error) throw error
  const client = createClient(URL, ANON, { auth: { persistSession: false } })
  await client.auth.signInWithPassword({ email, password: PASSWORD })
  return { client, userId: data.user.id }
}

/** Jeton d'accès brut, pour appeler les Edge Functions en fetch direct. */
export async function accessToken(client: SupabaseClient): Promise<string> {
  const { data } = await client.auth.getSession()
  if (!data.session) throw new Error('pas de session')
  return data.session.access_token
}
```

- [ ] **Step 2 : Commit**

```bash
git add tests/helpers/db.ts && git commit -m "test(0a-1): socle de test deux foyers"
```

---

### Task 3 : Classe C — données de foyer

**En premier**, parce que le socle de test en dépend. Point délicat : `nutrition_target` n'a pas de `household_id` naturel (sa clé est `user_profile_id`). §5.0.1 tranche : **on dénormalise**, la colonne est remplie par un trigger `BEFORE INSERT` — vérifié en PostgreSQL 15, `BEFORE` s'exécute avant la contrainte `NOT NULL` **et** avant le `WITH CHECK` de la policy.

**Files:**
- Create: `supabase/migrations/0001_class_c.sql`, `tests/isolation.test.ts`

- [ ] **Step 1 : Écrire le test qui échoue**

```typescript
// tests/isolation.test.ts
import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, makeOrphan, admin, type Actor } from './helpers/db'

let alice: Actor, bob: Actor
beforeAll(async () => { alice = await makeActor('alice'); bob = await makeActor('bob') })

describe('classe C — données de foyer', () => {
  it('un foyer ne voit que son propre household', async () => {
    const { data } = await alice.client.from('household').select('id')
    expect(data?.map(h => h.id)).toEqual([alice.householdId])
  })

  it("un foyer ne voit jamais les cibles d'un autre", async () => {
    // ⚠️ Assertion indispensable : sans elle, si l'amorce échoue (elle échoue
    // avant la Task 7, household_id étant NOT NULL sans trigger), alice voit 0
    // ligne et le test passe SANS RIEN AVOIR TESTÉ.
    const { error: seed } = await admin().from('nutrition_target').insert({
      user_profile_id: bob.userId,
      kcal: 2400, protein_g: 180, fiber_g: 30, carb_g: 250, fat_g: 70,
    })
    expect(seed, "l'amorce du test a échoué : le test serait vert à vide").toBeNull()
    const { data } = await alice.client
      .from('nutrition_target').select('*').eq('user_profile_id', bob.userId)
    expect(data ?? [], 'fuite entre foyers').toHaveLength(0)
  })

  it('les cibles sont historisées, pas écrasées', async () => {
    for (const kcal of [2000, 2100]) {
      const { error } = await alice.client.from('nutrition_target').insert({
        user_profile_id: alice.userId,
        kcal, protein_g: 150, fiber_g: 30, carb_g: 200, fat_g: 60,
      })
      expect(error).toBeNull()
    }
    const { data } = await alice.client
      .from('nutrition_target').select('kcal').eq('user_profile_id', alice.userId)
    expect(data!.length, 'une cible qui change ne doit pas effacer le passé')
      .toBeGreaterThanOrEqual(2)
  })

  it("un foyer ne peut pas écrire une cible chez un autre", async () => {
    const { error } = await alice.client.from('nutrition_target').insert({
      user_profile_id: bob.userId,
      kcal: 1, protein_g: 1, fiber_g: 1, carb_g: 1, fat_g: 1,
    })
    expect(error, 'écriture croisée acceptée').not.toBeNull()
  })

  // ↓↓↓ Les trois tests de SUPPRESSION. Sans eux, `for all` laissait un membre
  //     effacer son foyer entier, profils et cibles compris — mesuré. ↓↓↓
  it('un membre ne peut PAS supprimer son foyer', async () => {
    await alice.client.from('household').delete().eq('id', alice.householdId)
    const { data } = await admin().from('household').select('id').eq('id', alice.householdId)
    expect(data, 'un membre a effacé son foyer et tout ce qui cascade derrière').toHaveLength(1)
  })

  it('un membre ne peut PAS supprimer un profil, pas même le sien', async () => {
    await alice.client.from('user_profile').delete().eq('id', alice.userId)
    const { data } = await admin().from('user_profile').select('id').eq('id', alice.userId)
    expect(data, 'supprimer son profil permettrait de s’échapper du foyer').toHaveLength(1)
  })

  it('un membre ne peut PAS supprimer le profil de son colocataire', async () => {
    const a = admin()
    const { data: colo } = await a.from('user_profile')
      .insert({ id: (await a.auth.admin.createUser({
        email: `colo-${Date.now()}@test.local`, password: 'test-password-12345', email_confirm: true,
      })).data.user!.id, household_id: alice.householdId, display_name: 'colo' })
      .select().single()
    await alice.client.from('user_profile').delete().eq('id', colo!.id)
    const { data } = await a.from('user_profile').select('id').eq('id', colo!.id)
    expect(data, 'un membre a supprimé le profil d’un autre').toHaveLength(1)
  })

  // ↓↓↓ Portée PERSONNE : le foyer partage la lecture, pas l'écriture. ↓↓↓
  it("un membre ne peut PAS supprimer les cibles d'un autre membre", async () => {
    const a = admin()
    const { data: colo } = await a.auth.admin.createUser({
      email: `colo2-${Date.now()}@test.local`, password: 'test-password-12345', email_confirm: true })
    await a.from('user_profile').insert({
      id: colo.user!.id, household_id: alice.householdId, display_name: 'colo2' })
    const { data: cible, error: seed } = await a.from('nutrition_target').insert({
      user_profile_id: colo.user!.id,
      kcal: 2400, protein_g: 180, fiber_g: 30, carb_g: 250, fat_g: 70,
    }).select().single()
    expect(seed, "l'amorce a échoué : le test serait vert à vide").toBeNull()

    await alice.client.from('nutrition_target').delete().eq('id', cible!.id)
    const { data } = await a.from('nutrition_target').select('id').eq('id', cible!.id)
    expect(data, "un membre a effacé l'historique d'objectifs d'un autre").toHaveLength(1)
  })

  it("un membre ne peut PAS renommer un autre membre", async () => {
    const a = admin()
    const { data: colo } = await a.auth.admin.createUser({
      email: `colo3-${Date.now()}@test.local`, password: 'test-password-12345', email_confirm: true })
    await a.from('user_profile').insert({
      id: colo.user!.id, household_id: alice.householdId, display_name: 'intact' })

    await alice.client.from('user_profile')
      .update({ display_name: 'renommé de force' }).eq('id', colo.user!.id)
    const { data } = await a.from('user_profile')
      .select('display_name').eq('id', colo.user!.id).single()
    expect(data!.display_name, 'un membre a renommé un autre').toBe('intact')
  })

  it('un authentifié SANS profil ne voit aucune donnée de foyer', async () => {
    const { client: orphan } = await makeOrphan()
    for (const t of ['household', 'user_profile', 'nutrition_target', 'invitation']) {
      const { data } = await orphan.from(t).select('*')
      expect(data ?? [], `${t} visible par un orphelin`).toHaveLength(0)
    }
  })
})
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
npm run test -- tests/isolation.test.ts
```
Attendu : ÉCHEC dans `beforeAll` — `relation "public.household" does not exist`.

- [ ] **Step 3 : Écrire `0001_class_c.sql`**

```sql
-- supabase/migrations/0001_class_c.sql
-- Classe C : données de foyer, RLS stricte (spec §5.0, §5.0.1).

create extension if not exists "pgcrypto";

create table public.household (
  id                  uuid primary key default gen_random_uuid(),
  name                text not null,
  llm_monthly_cap_eur numeric not null default 5 check (llm_monthly_cap_eur >= 0),
  created_at          timestamptz not null default now()
);

create table public.user_profile (
  id           uuid primary key references auth.users(id) on delete cascade,
  household_id uuid not null references public.household(id) on delete cascade,
  display_name text not null,
  created_at   timestamptz not null default now()
);
create index on public.user_profile (household_id);

-- household_id est DÉNORMALISÉ (§5.0.1, forme 3) : rempli par trigger BEFORE INSERT.
-- Vérifié en PG15 : BEFORE s'exécute avant la vérification NOT NULL et avant le
-- WITH CHECK de la policy, donc un insert client sans household_id fonctionne.
create table public.nutrition_target (
  id              uuid primary key default gen_random_uuid(),
  user_profile_id uuid not null references public.user_profile(id) on delete cascade,
  household_id    uuid not null references public.household(id) on delete cascade,
  kcal      numeric not null check (kcal > 0),
  protein_g numeric not null check (protein_g >= 0),
  fiber_g   numeric not null check (fiber_g   >= 0),
  carb_g    numeric not null check (carb_g    >= 0),
  fat_g     numeric not null check (fat_g     >= 0),
  valid_from timestamptz not null default now()
);
create index on public.nutrition_target (household_id);
create index on public.nutrition_target (user_profile_id, valid_from desc);

create table public.invitation (
  id           uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.household(id) on delete cascade,
  email        text not null,
  token        uuid not null unique default gen_random_uuid(),
  expires_at   timestamptz not null default now() + interval '7 days',
  accepted_at  timestamptz,
  created_by   uuid references auth.users(id),
  created_at   timestamptz not null default now()
);
create index on public.invitation (household_id);
create unique index invitation_pending_unique
  on public.invitation (household_id, lower(email)) where accepted_at is null;
```

- [ ] **Step 4 : Appliquer et relancer**

```bash
npm run db:reset && npm run test -- tests/isolation.test.ts
```
Attendu : le `beforeAll` PASSE désormais. **Les assertions d'isolation ÉCHOUENT** — la RLS n'est posée qu'en Task 6, et le test « historisées » échoue aussi car `household_id` est `not null` sans trigger (Task 7). C'est l'échec attendu, pour la bonne raison.

- [ ] **Step 5 : Commit**

```bash
git add supabase/migrations/0001_class_c.sql tests/isolation.test.ts
git commit -m "feat(0a-1): schéma classe C, données de foyer"
```

---

### Task 4 : Classe A — référentiel et infrastructure

Onze tables, **créées vides**. Règle d'accès : lecture pour tout authentifié, **écriture réservée au rôle de service**.

⚠️ **Le test de lecture ne prouve presque rien** : Supabase accorde `authenticated` sur les tables `public` neuves, donc il passerait aussi sans RLS. **C'est le test d'écriture qui porte la preuve**, et il doit couvrir les 11 tables, pas une seule.

**Files:**
- Create: `supabase/migrations/0002_class_a.sql`

- [ ] **Step 1 : Ajouter le bloc de test à `tests/isolation.test.ts`**

```typescript
const TABLES_A = [
  'food', 'food_yield_factor', 'unit_weight', 'unit_conversion', 'density',
  'default_temperature', 'default_duration', 'typical_quantity',
  'appliance_catalog', 'ingestion_job', 'instance_setting',
] as const

// Une ligne RÉELLEMENT valide par table. ⚠️ Mesuré : avec un food_id inexistant,
// food_yield_factor et density échouent sur la clé étrangère même sans RLS —
// le test resterait vert alors qu'il ne teste rien. Il faut un vrai food_id.
let foodId: string
beforeAll(async () => {
  const { data } = await admin().from('food')
    .insert({ source: 'ciqual', source_code: `seed-${Date.now()}`, name: 'témoin' })
    .select().single()
  foodId = data!.id
})

const LIGNE_A = (): Record<string, Record<string, unknown>> => ({
  food: { source: 'ciqual', source_code: `pirate-${Date.now()}`, name: 'pirate' },
  food_yield_factor: { food_id: foodId, factor: 1 },
  unit_weight: { label: 'pirate', grams: 1 },
  unit_conversion: { unit_label: `pirate-${Date.now()}`, grams: 1 },
  density: { food_id: foodId, grams_per_ml: 1 },
  default_temperature: { preparation: 'pirate', temperature_c: 180 },
  default_duration: { verb: 'pirate', base_minutes: 1, load_type: 'actif' },
  typical_quantity: { ciqual_subgroup: 'pirate', grams: 1 },
  appliance_catalog: { code: `pirate-${Date.now()}`, label: 'Pirate' },
  ingestion_job: { url: `https://pirate.test/${Date.now()}` },
  instance_setting: { key: `pirate-${Date.now()}`, value: {} },
})

describe('classe A — référentiel', () => {
  it('est lisible par tout utilisateur authentifié', async () => {
    for (const t of TABLES_A) {
      const { error } = await alice.client.from(t).select('*').limit(1)
      expect(error, `lecture de ${t}`).toBeNull()
    }
  })

  it("n'est inscriptible par AUCUN utilisateur authentifié, sur les 11 tables", async () => {
    const lignes = LIGNE_A()
    for (const t of TABLES_A) {
      const { error } = await alice.client.from(t).insert(lignes[t])
      expect(error, `${t} accepte une écriture authentifiée`).not.toBeNull()
    }
  })

  it('est inscriptible par le rôle de service', async () => {
    const { error } = await admin()
      .from('appliance_catalog').insert({ code: `four-${Date.now()}`, label: 'Four' })
    expect(error).toBeNull()
  })
})
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
npm run test -- tests/isolation.test.ts
```
Attendu : ÉCHEC — `relation "public.food" does not exist`.

- [ ] **Step 3 : Écrire `0002_class_a.sql`**

```sql
-- supabase/migrations/0002_class_a.sql
-- Classe A : référentiel immuable et infrastructure (spec §5.0).
-- Créées VIDES : leur peuplement est le lot 0a-2.

create table public.food (
  id              uuid primary key default gen_random_uuid(),
  source          text not null check (source in ('ciqual','off')),
  source_code     text not null,
  name            text not null,
  state           text not null default 'cru' check (state in ('cru','cuit')),
  ciqual_group    text,
  ciqual_subgroup text,
  nutrients       jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  unique (source, source_code)
);
create index on public.food (ciqual_subgroup);
create index on public.food using gin (to_tsvector('french', name));

create table public.food_yield_factor (
  food_id uuid primary key references public.food(id) on delete cascade,
  factor  numeric not null check (factor > 0)
);

create table public.unit_weight (
  id         uuid primary key default gen_random_uuid(),
  food_id    uuid references public.food(id) on delete cascade,
  label      text not null,
  grams      numeric not null check (grams > 0),
  confidence numeric not null default 0.5 check (confidence between 0 and 1),
  source     text not null default 'usda'
);
create index on public.unit_weight (food_id);

create table public.unit_conversion (
  id              uuid primary key default gen_random_uuid(),
  unit_label      text not null,
  ciqual_subgroup text,
  grams           numeric not null check (grams > 0),
  unique (unit_label, ciqual_subgroup)
);

create table public.density (
  food_id      uuid primary key references public.food(id) on delete cascade,
  grams_per_ml numeric not null check (grams_per_ml > 0)
);

create table public.default_temperature (
  id            uuid primary key default gen_random_uuid(),
  preparation   text not null unique,
  temperature_c int not null check (temperature_c between 30 and 300)
);

-- D19 : clé (verbe, appareil), appliquée aux ACTIONS et non aux étapes.
create table public.default_duration (
  id             uuid primary key default gen_random_uuid(),
  verb           text not null,
  appliance_type text,
  base_minutes   numeric not null check (base_minutes > 0),
  load_type      text not null check (load_type in ('actif','passif','bloquant')),
  scaling        text not null default 'constant'
                 check (scaling in ('lineaire_plafonne','constant')),
  unique (verb, appliance_type)
);

-- D18 : borne haute des 16 % de lignes d'ingrédients sans quantité.
create table public.typical_quantity (
  ciqual_subgroup text primary key,
  grams           numeric not null check (grams > 0)
);

create table public.appliance_catalog (
  id               uuid primary key default gen_random_uuid(),
  code             text not null unique,
  label            text not null,
  default_capacity int not null default 1 check (default_capacity >= 1)
);

create table public.ingestion_job (
  id           uuid primary key default gen_random_uuid(),
  url          text not null unique,
  state        text not null default 'queued'
               check (state in ('queued','fetching','extracting','resolving','ready','needs_review','failed')),
  attempts     int not null default 0,
  error        text,
  content_hash text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index on public.ingestion_job (state);

create table public.instance_setting (
  key   text primary key,
  value jsonb not null
);
```

- [ ] **Step 4 : Appliquer et relancer**

```bash
npm run db:reset && npm run test -- tests/isolation.test.ts
```
Attendu : le test de **lecture** passe (privilèges Supabase par défaut), le test d'**écriture refusée** ÉCHOUE — la RLS n'existe pas encore. C'est précisément ce que la Task 6 vient corriger.

- [ ] **Step 5 : Commit**

```bash
git add supabase/migrations/0002_class_a.sql tests/isolation.test.ts
git commit -m "feat(0a-1): schéma classe A, référentiel et infrastructure"
```

---

### Task 5 : Classe B — catalogue partagé

Quatre tables **vides** (l'ingestion est le lot 0b). Toutes portent `edited_by_household_id` et `edited_at`.

⚠️ **Le piège du faux vert, mesuré** : en désactivant la RLS sur `recipe`, les tests de lecture et de traçabilité restent **tous verts** pendant qu'un utilisateur authentifié peut insérer et supprimer n'importe quelle ligne du catalogue. Il faut donc tester explicitement que **l'INSERT est refusé** et que le **DELETE affecte 0 ligne** — et, mesuré : RLS activée sans policy DELETE, le DELETE ne renvoie **aucune erreur**, il supprime simplement 0 ligne. **Asserter le compte, jamais `error`.**

**Files:**
- Create: `supabase/migrations/0003_class_b.sql`

- [ ] **Step 1 : Ajouter le bloc de test**

```typescript
describe('classe B — catalogue partagé', () => {
  const TABLES_B = ['recipe', 'recipe_ingredient', 'recipe_step', 'recipe_step_dependency'] as const

  const seedRecipe = async () => {
    const { data } = await admin().from('recipe')
      .insert({ source_url: `https://x/${Date.now()}-${Math.random()}`, yield_servings: 4 })
      .select().single()
    return data!
  }

  it('porte la traçabilité sur les quatre tables', async () => {
    for (const t of TABLES_B) {
      const { error } = await alice.client
        .from(t).select('edited_by_household_id, edited_at').limit(1)
      expect(error, `traçabilité manquante sur ${t}`).toBeNull()
    }
  })

  it('est lisible par les deux foyers', async () => {
    const r = await seedRecipe()
    for (const who of [alice, bob]) {
      const { data } = await who.client.from('recipe').select('id').eq('id', r.id)
      expect(data, 'le catalogue est partagé').toHaveLength(1)
    }
  })

  // ↓↓↓ Les deux tests qui empêchent le faux vert ↓↓↓
  it("REFUSE l'insertion par un utilisateur authentifié", async () => {
    const { error } = await alice.client
      .from('recipe').insert({ source_url: `https://pirate/${Date.now()}` })
    expect(error, 'un foyer peut créer une recette dans le catalogue partagé').not.toBeNull()
  })

  it('REFUSE la suppression par un utilisateur authentifié', async () => {
    const r = await seedRecipe()
    // Sans policy DELETE, PostgREST ne renvoie PAS d'erreur : il supprime 0 ligne.
    await alice.client.from('recipe').delete().eq('id', r.id)
    const { data } = await admin().from('recipe').select('id').eq('id', r.id)
    expect(data, 'la ligne a été supprimée par un foyer').toHaveLength(1)
  })
})
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
npm run test -- tests/isolation.test.ts
```
Attendu : ÉCHEC — `relation "public.recipe" does not exist`.

- [ ] **Step 3 : Écrire `0003_class_b.sql`**

```sql
-- supabase/migrations/0003_class_b.sql
-- Classe B : catalogue partagé, écriture authentifiée et tracée (spec §5.0).
-- Créées vides : l'ingestion est le lot 0b.

create table public.recipe (
  id                 uuid primary key default gen_random_uuid(),
  source_url         text unique,
  source_name        text,
  origin             text not null default 'importee'
                     check (origin in ('importee','generee','manuelle')),
  owner_household_id uuid,   -- NULL = importée ; non-NULL = créée par un foyer
  visibility         text not null default 'privee'
                     check (visibility in ('privee','partagee')),
  title              text,
  yield_servings     int check (yield_servings > 0),
  total_time_min     numeric,
  prep_time_min      numeric,
  cook_time_min      numeric,
  license_note       text,
  -- §5.3 exige que plannable soit maintenue par trigger. Son calcul dépend des
  -- durées des ACTIONS, qui n'existent qu'au lot 0b : le trigger y est reporté.
  -- Ici la colonne existe et reste false. NE PAS implémenter de trigger à vide.
  plannable          boolean not null default false,
  edited_by_household_id uuid,
  edited_at          timestamptz,
  created_at         timestamptz not null default now()
);
create index on public.recipe (plannable);
create index on public.recipe (owner_household_id);

create table public.recipe_ingredient (
  id        uuid primary key default gen_random_uuid(),
  recipe_id uuid not null references public.recipe(id) on delete cascade,
  ordinal   int not null,
  raw_text  text not null,
  food_id   uuid references public.food(id),
  qty       numeric,
  unit      text,
  grams_reference numeric,
  -- Résolution de RÉFÉRENCE seulement. La résolution par foyer vit en classe C
  -- (household_ingredient_resolution, lot 0c).
  resolution_source text check (resolution_source in ('reference','llm','aucune')),
  confidence numeric check (confidence between 0 and 1),
  edited_by_household_id uuid,
  edited_at timestamptz,
  unique (recipe_id, ordinal)
);
create index on public.recipe_ingredient (recipe_id);

create table public.recipe_step (
  id        uuid primary key default gen_random_uuid(),
  recipe_id uuid not null references public.recipe(id) on delete cascade,
  ordinal   int not null,
  text      text not null,
  duration_min       numeric,
  duration_source    text check (duration_source in ('declaree','defaut','llm','confirmee')),
  appliance_type     text,
  temperature_c      int,
  temperature_source text check (temperature_source in ('declaree','defaut','llm','confirmee')),
  load_type          text check (load_type in ('actif','passif','bloquant')),
  confidence numeric check (confidence between 0 and 1),
  edited_by_household_id uuid,
  edited_at timestamptz,
  unique (recipe_id, ordinal)
);
create index on public.recipe_step (recipe_id);

create table public.recipe_step_dependency (
  before_id uuid not null references public.recipe_step(id) on delete cascade,
  after_id  uuid not null references public.recipe_step(id) on delete cascade,
  origin    text not null default 'defaut' check (origin in ('defaut','llm','confirme')),
  edited_by_household_id uuid,
  edited_at timestamptz,
  primary key (before_id, after_id),
  check (before_id <> after_id)
);
```

- [ ] **Step 4 : Appliquer, commiter**

```bash
npm run db:reset && npm run test -- tests/isolation.test.ts
```
Attendu : **ROUGE, et c'est normal** — aucune RLS n'existe encore, donc tout ce qui doit être
*refusé* passe : écriture en classe A, INSERT et DELETE en classe B, lecture croisée en classe C.
Seuls les tests de lecture et de traçabilité sont verts. La Task 6 referme tout cela.

```bash
git add supabase/migrations/0003_class_b.sql tests/isolation.test.ts
git commit -m "feat(0a-1): schéma classe B, catalogue partagé et tracé"
```

---

### Task 6 : `current_household()` et les trois formes de policies

**Le cœur du lot.** `SECURITY DEFINER` contourne la RLS de `user_profile` **par ownership de table** — les migrations tournent sous `postgres`, propriétaire des tables, et le propriétaire d'une table n'est pas soumis à sa RLS. Cela **casserait** si quelqu'un posait `FORCE ROW LEVEL SECURITY` ou changeait le propriétaire : c'est écrit en commentaire dans la migration.

**Files:**
- Create: `supabase/migrations/0004_current_household.sql`, `supabase/migrations/0005_policies.sql`

- [ ] **Step 1 : Ajouter le test de non-récursion**

```typescript
describe('current_household()', () => {
  it('ne provoque pas de récursion de policy', async () => {
    const { data, error } = await alice.client.rpc('current_household')
    expect(error, 'code 42P17 = récursion de policy').toBeNull()
    expect(data).toBe(alice.householdId)
  })

  it('renvoie NULL pour un authentifié sans profil', async () => {
    const { client: orphan } = await makeOrphan()
    const { data } = await orphan.rpc('current_household')
    expect(data).toBeNull()
  })
})
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
npm run test -- tests/isolation.test.ts
```
Attendu : ÉCHEC — `function public.current_household does not exist`.

- [ ] **Step 3 : Écrire `0004_current_household.sql`**

```sql
-- supabase/migrations/0004_current_household.sql
-- SECURITY DEFINER : la fonction s'exécute avec les droits de son propriétaire
-- (postgres, propriétaire des tables), et le propriétaire d'une table n'est pas
-- soumis à sa RLS. C'est ce qui évite la récursion de policy (§5.0.1).
--
-- ⚠️ Cela cesse d'être vrai si l'on pose FORCE ROW LEVEL SECURITY sur
--    user_profile, ou si l'on change le propriétaire de la fonction. Ne pas le faire.
create or replace function public.current_household()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select household_id from public.user_profile where id = auth.uid()
$$;

revoke execute on function public.current_household() from public, anon;
grant   execute on function public.current_household() to authenticated, service_role;
```

- [ ] **Step 4 : Écrire `0005_policies.sql`**

```sql
-- supabase/migrations/0005_policies.sql
-- Les TROIS formes de prédicat de §5.0.1.

-- ── Classe A : lecture pour tout authentifié. AUCUNE policy d'écriture :
-- seul le rôle de service, qui contourne RLS, peut écrire.
do $$
declare t text;
begin
  foreach t in array array[
    'food','food_yield_factor','unit_weight','unit_conversion','density',
    'default_temperature','default_duration','typical_quantity',
    'appliance_catalog','ingestion_job','instance_setting'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (true)',
      t || '_read', t);
  end loop;
end $$;

-- ── Classe B : lecture par tous, UPDATE par tout authentifié.
-- Pas de policy INSERT ni DELETE : le catalogue est alimenté par le worker (0b).
-- La restriction aux champs peu sûrs n'est PAS exprimable en RLS : c'est le
-- trigger de la Task 7 qui la porte.
--
-- ⚠️ `using (true)` en lecture ignore visibility et owner_household_id. Sans effet
--    ici (tables vides) ; à resserrer au lot 4, quand des recettes privées existeront.
do $$
declare t text;
begin
  foreach t in array array[
    'recipe','recipe_ingredient','recipe_step','recipe_step_dependency'
  ] loop
    execute format('alter table public.%I enable row level security', t);
    execute format(
      'create policy %I on public.%I for select to authenticated using (true)',
      t || '_read', t);
    execute format(
      'create policy %I on public.%I for update to authenticated using (true) with check (true)',
      t || '_update', t);
  end loop;
end $$;

-- ⚠️⚠️ NE JAMAIS écrire `for all` sur household ni user_profile. Mesuré :
--    `for all` inclut DELETE, donc un simple membre peut envoyer
--    DELETE /rest/v1/household?id=eq.<son foyer> et la cascade efface TOUS les
--    profils et TOUTES les cibles du foyer. Et en supprimant son propre profil,
--    current_household() repasse à NULL, ce qui lui permet de recréer un foyer
--    et de s'échapper du sien. La suppression passe EXCLUSIVEMENT par
--    delete_my_account() (Task 11), qui est SECURITY DEFINER et contrôlée.

-- ── Classe C, forme 1 : la clé EST le foyer. Lecture et mise à jour seulement.
alter table public.household enable row level security;
create policy household_select on public.household
  for select to authenticated using (id = public.current_household());
create policy household_update on public.household
  for update to authenticated
  using (id = public.current_household())
  with check (id = public.current_household());
-- Pas de policy INSERT : la création passe par create_household() (Task 10).
-- Pas de policy DELETE : la suppression passe par delete_my_account() (Task 11).

-- ── Classe C, forme 2 : colonne household_id directe.
alter table public.user_profile enable row level security;
create policy user_profile_select on public.user_profile
  for select to authenticated using (household_id = public.current_household());
-- Mise à jour : SON PROPRE profil seulement. Cadrée sur le foyer, un membre
-- pourrait renommer son conjoint (mesuré). Le WITH CHECK interdit en outre de
-- se déplacer vers un autre foyer.
create policy user_profile_update on public.user_profile
  for update to authenticated
  using (id = auth.uid())
  with check (id = auth.uid() and household_id = public.current_household());
-- Ni INSERT ni DELETE : rattachement par accept-invite, départ par delete_my_account().

-- L'invitation, elle, se révoque légitimement : DELETE autorisé, portée foyer.
alter table public.invitation enable row level security;
create policy invitation_all on public.invitation
  for all to authenticated
  using (household_id = public.current_household())
  with check (household_id = public.current_household());

-- ── Classe C, forme 3 : household_id dénormalisé (rempli par trigger, Task 7).
--
-- ⚠️ PORTÉE PERSONNE, PAS FOYER. Mesuré : une policy cadrée sur le foyer laisse
--    un membre SUPPRIMER les cibles de son conjoint et les modifier. Or D4 dit
--    « cibles PAR PERSONNE ». La lecture reste au foyer — le bilan nutritionnel
--    du lot 1 en a besoin — mais toute écriture est limitée à soi.
alter table public.nutrition_target enable row level security;
create policy nutrition_target_select on public.nutrition_target
  for select to authenticated using (household_id = public.current_household());
create policy nutrition_target_insert on public.nutrition_target
  for insert to authenticated with check (user_profile_id = auth.uid());
create policy nutrition_target_update on public.nutrition_target
  for update to authenticated
  using (user_profile_id = auth.uid()) with check (user_profile_id = auth.uid());
create policy nutrition_target_delete on public.nutrition_target
  for delete to authenticated using (user_profile_id = auth.uid());
```

- [ ] **Step 5 : Appliquer**

```bash
npm run db:reset && npm run test -- tests/isolation.test.ts
```
Attendu, **précisément** :
- **Vert** : les quatre tests anti-faux-vert (classe A × 11, classe B INSERT et DELETE), les trois
  tests de suppression en classe C, l'orphelin, `current_household()`, et — mesuré —
  `écriture croisée`, qui passe **déjà** ici : l'insert est rejeté par le `WITH CHECK` de la
  policy (`household_id` NULL ≠ `current_household()`), pas par l'absence de trigger.
- **Rouge, et c'est normal** : `historisées` et `ne voit jamais les cibles d'un autre` — leur
  amorce insère dans `nutrition_target` sans `household_id`, ce que seul le trigger de la
  Task 7 rendra possible.

- [ ] **Step 6 : Commit**

```bash
git add supabase/migrations/0004_current_household.sql supabase/migrations/0005_policies.sql tests/isolation.test.ts
git commit -m "feat(0a-1): current_household en SECURITY DEFINER et les 3 formes de policies"
```

- [ ] **Step 7 : Prouver que les tests ne sont pas creux**

Prérequis : `psql` installé. L'URL locale est fixe — port `[db]` de `config.toml`, `54322` par défaut.

```bash
npx supabase db reset
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" \
  -c "alter table public.recipe disable row level security;
      alter table public.household disable row level security;"
npm run test -- tests/isolation.test.ts
```
Attendu : **au moins** « REFUSE l'insertion », « REFUSE la suppression » et « un membre ne peut
PAS supprimer son foyer » ÉCHOUENT.
D'autres rougiront aussi dans ce passage — supprimer une ligne `household` emporte ses profils et
leurs cibles en cascade. **C'est normal, ne pas chercher une régression ailleurs.**
S'ils passent encore, la suite ne prouve rien : ne pas continuer, corriger les tests.
Puis `npm run db:reset` pour revenir à l'état sain.

---

### Task 7 : Les triggers — ce que RLS ne sait pas exprimer

Trois triggers. Le premier porte la restriction d'écriture de la classe B, qui **dépend de la valeur de `confidence` de la ligne** — inexprimable en policy (§5.0.1).

**Files:**
- Create: `supabase/migrations/0006_triggers.sql`, `tests/class-b-guard.test.ts`

- [ ] **Step 1 : Écrire le test qui échoue**

```typescript
// tests/class-b-guard.test.ts
import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, admin, type Actor } from './helpers/db'

let alice: Actor
beforeAll(async () => { alice = await makeActor('alice-guard') })

async function seedStep(confidence: number) {
  const a = admin()
  const { data: r } = await a.from('recipe')
    .insert({ source_url: `https://x/${Date.now()}-${Math.random()}`, yield_servings: 4 })
    .select().single()
  const { data: s } = await a.from('recipe_step')
    .insert({ recipe_id: r!.id, ordinal: 1, text: 'Enfourner', duration_min: 25, confidence })
    .select().single()
  return s!
}

describe("garde d'écriture de la classe B", () => {
  it('autorise la correction d\'un champ peu sûr ET la trace', async () => {
    const step = await seedStep(0.4)
    const { error } = await alice.client
      .from('recipe_step').update({ duration_min: 30 }).eq('id', step.id)
    expect(error).toBeNull()

    const { data } = await admin().from('recipe_step')
      .select('duration_min, edited_by_household_id, edited_at').eq('id', step.id).single()
    expect(Number(data!.duration_min)).toBe(30)
    expect(data!.edited_by_household_id, 'traçabilité non posée').toBe(alice.householdId)
    expect(data!.edited_at).not.toBeNull()
  })

  it('refuse la modification d\'un champ à confiance élevée', async () => {
    const step = await seedStep(0.95)
    const { error } = await alice.client
      .from('recipe_step').update({ duration_min: 999 }).eq('id', step.id)
    expect(error, 'une ligne sûre est modifiable par un foyer').not.toBeNull()
  })

  it('laisse passer le rôle de service quelle que soit la confiance', async () => {
    const step = await seedStep(0.99)
    const { error } = await admin().from('recipe_step').update({ duration_min: 12 }).eq('id', step.id)
    expect(error).toBeNull()
  })

  it('fonctionne sur recipe, qui n\'a PAS de colonne confidence', async () => {
    const { data: r } = await admin().from('recipe')
      .insert({ source_url: `https://x/${Date.now()}-${Math.random()}` }).select().single()
    const { error } = await alice.client.from('recipe').update({ title: 'corrigé' }).eq('id', r!.id)
    expect(error, 'la garde ne doit pas planter sur une table sans confidence').toBeNull()
    const { data } = await admin().from('recipe')
      .select('edited_by_household_id').eq('id', r!.id).single()
    expect(data!.edited_by_household_id).toBe(alice.householdId)
  })

  it('remplit household_id de nutrition_target automatiquement', async () => {
    const { data, error } = await alice.client.from('nutrition_target').insert({
      user_profile_id: alice.userId,
      kcal: 2000, protein_g: 150, fiber_g: 30, carb_g: 200, fat_g: 60,
    }).select().single()
    expect(error, 'household_id doit être posé par trigger, pas par le client').toBeNull()
    expect(data!.household_id).toBe(alice.householdId)
  })
})
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
npm run test -- tests/class-b-guard.test.ts
```
Attendu : ÉCHEC — traçabilité `null`, ligne sûre modifiable, insert `nutrition_target` en violation de `not null`.

- [ ] **Step 3 : Écrire `0006_triggers.sql`**

```sql
-- supabase/migrations/0006_triggers.sql

-- PostgREST fait SET ROLE service_role : current_user suffit. Le claim JWT est
-- vérifié en second, par robustesse.
create or replace function public.is_service_role()
returns boolean language sql stable as $$
  select current_user = 'service_role'
      or coalesce(
           nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role',
           '') = 'service_role'
$$;

-- Garde de la classe B. Générique sur 4 tables aux colonnes différentes :
-- to_jsonb(old) ? 'confidence' saute simplement la vérification sur recipe et
-- recipe_step_dependency, qui n'ont pas cette colonne. Les 4 ont en revanche
-- edited_by_household_id, donc l'affectation est toujours valide.
create or replace function public.tg_class_b_guard()
returns trigger language plpgsql as $$
declare old_conf numeric;
begin
  if public.is_service_role() then
    return new;
  end if;

  if to_jsonb(old) ? 'confidence' then
    old_conf := nullif(to_jsonb(old) ->> 'confidence', '')::numeric;
    if old_conf is not null and old_conf >= 0.8 then
      raise exception 'ligne à confiance élevée (%), non modifiable par un foyer', old_conf
        using errcode = 'check_violation';
    end if;
  end if;

  new.edited_by_household_id := public.current_household();
  new.edited_at := now();
  return new;
end $$;

create trigger class_b_guard before update on public.recipe
  for each row execute function public.tg_class_b_guard();
create trigger class_b_guard before update on public.recipe_ingredient
  for each row execute function public.tg_class_b_guard();
create trigger class_b_guard before update on public.recipe_step
  for each row execute function public.tg_class_b_guard();
create trigger class_b_guard before update on public.recipe_step_dependency
  for each row execute function public.tg_class_b_guard();

-- Dénormalisation de nutrition_target.household_id (§5.0.1, forme 3).
-- SECURITY DEFINER : doit lire user_profile, qui est sous RLS.
-- BEFORE INSERT s'exécute avant la contrainte NOT NULL et avant le WITH CHECK
-- de la policy — vérifié en PG15.
create or replace function public.tg_nutrition_target_household()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  select household_id into new.household_id
  from public.user_profile where id = new.user_profile_id;
  if new.household_id is null then
    raise exception 'profil % introuvable', new.user_profile_id
      using errcode = 'foreign_key_violation';
  end if;
  return new;
end $$;

create trigger nutrition_target_household
  before insert or update of user_profile_id on public.nutrition_target
  for each row execute function public.tg_nutrition_target_household();

create or replace function public.tg_touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at := now(); return new; end $$;

create trigger ingestion_job_touch before update on public.ingestion_job
  for each row execute function public.tg_touch_updated_at();
```

- [ ] **Step 4 : Appliquer, tout doit passer**

```bash
npm run db:reset && npm run test
```
Attendu : `isolation.test.ts` et `class-b-guard.test.ts` entièrement verts.

- [ ] **Step 5 : Commit**

```bash
git add supabase/migrations/0006_triggers.sql tests/class-b-guard.test.ts
git commit -m "feat(0a-1): garde d'écriture classe B, dénormalisation, updated_at"
```

---

### Task 8 : Budget LLM — les deux plafonds

D11 : **deux budgets.** L'ingestion est mutualisée (D13) et tombe sur la ligne `household_id IS NULL`, plafonnée par `instance_setting`. La vision et les propositions tombent sur le foyer.

⚠️ **Piège de fuseau horaire, vérifié** : `new Date(y, m, 1).toISOString().slice(0,10)` renvoie **le mois précédent** en Europe/Paris (minuit local = 22 h UTC la veille). Utiliser la forme ci-dessous.

**Files:**
- Create: `supabase/migrations/0007_llm_budget.sql`, `tests/llm-budget.test.ts`

- [ ] **Step 1 : Écrire le test qui échoue**

```typescript
// tests/llm-budget.test.ts
import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, admin, type Actor } from './helpers/db'

let alice: Actor, bob: Actor
beforeAll(async () => { alice = await makeActor('alice-llm'); bob = await makeActor('bob-llm') })

// Premier jour du mois courant, en UTC. NE PAS utiliser new Date(y, m, 1) :
// en Europe/Paris, toISOString() renverrait le mois précédent.
const month = () => new Date().toISOString().slice(0, 8) + '01'

describe('budget LLM', () => {
  it('décompte la consommation du foyer de son plafond', async () => {
    const a = admin()
    await a.from('household').update({ llm_monthly_cap_eur: 5 }).eq('id', alice.householdId)
    await a.from('llm_usage').insert({
      household_id: alice.householdId, month: month(), kind: 'vision', calls: 10, cost_eur: 1.5,
    })
    const { data, error } = await alice.client.rpc('llm_budget_remaining')
    expect(error).toBeNull()
    expect(Number(data)).toBeCloseTo(3.5, 2)
  })

  it("un foyer ne voit pas la consommation d'un autre", async () => {
    const { data } = await bob.client.from('llm_usage').select('*')
    expect((data ?? []).some(r => r.household_id === alice.householdId)).toBe(false)
  })

  it("la ligne système n'est visible d'aucun foyer", async () => {
    await admin().from('llm_usage').insert({
      household_id: null, month: month(), kind: 'extraction', calls: 5000, cost_eur: 4,
    })
    for (const who of [alice, bob]) {
      const { data } = await who.client.from('llm_usage').select('*').is('household_id', null)
      expect(data ?? [], 'la consommation système ne regarde pas les foyers').toHaveLength(0)
    }
  })

  it('le plafond global décompte exactement la consommation système', async () => {
    const a = admin()
    await a.from('instance_setting')
      .upsert({ key: 'llm_global_monthly_cap_eur', value: { amount: 50 } })
    const { data: before, error: e1 } = await a.rpc('llm_global_budget_remaining')
    expect(e1, 'service_role doit pouvoir appeler cette fonction').toBeNull()

    // ⚠️ upsert() résout le conflit sur la clé PRIMAIRE (id, généré) et non sur
    // llm_usage_unique : sans onConflict, c'est un INSERT simple qui violera la
    // contrainte au second passage sans db:reset.
    await a.from('llm_usage').upsert({
      household_id: null, month: month(), kind: 'generation', calls: 1, cost_eur: 7,
    }, { onConflict: 'household_id,month,kind' })
    const { data: after } = await a.rpc('llm_global_budget_remaining')
    expect(Number(before) - Number(after)).toBeCloseTo(7, 2)
  })

  it("un foyer ne peut PAS appeler la fonction de budget global", async () => {
    const { error } = await alice.client.rpc('llm_global_budget_remaining')
    expect(error, 'le budget global ne regarde pas les foyers').not.toBeNull()
  })
})
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
npm run test -- tests/llm-budget.test.ts
```
Attendu : ÉCHEC — `relation "public.llm_usage" does not exist`.

- [ ] **Step 3 : Écrire `0007_llm_budget.sql`**

```sql
-- supabase/migrations/0007_llm_budget.sql
-- D11 : deux budgets. household_id NULL = consommation système (ingestion mutualisée).
-- `unique nulls not distinct` (PostgreSQL 15+) rend la ligne système unique par mois et kind.

create table public.llm_usage (
  id           uuid primary key default gen_random_uuid(),
  household_id uuid references public.household(id) on delete cascade,  -- NULL = système
  month        date not null,
  kind         text not null check (kind in ('extraction','vision','generation')),
  calls        int     not null default 0 check (calls >= 0),
  cost_eur     numeric not null default 0 check (cost_eur >= 0),
  updated_at   timestamptz not null default now(),
  constraint llm_usage_unique unique nulls not distinct (household_id, month, kind)
);
create index on public.llm_usage (household_id, month);

alter table public.llm_usage enable row level security;
-- Lecture des seules lignes du foyer. La ligne système (NULL) n'est lue par personne
-- d'autre que le rôle de service, qui contourne RLS.
create policy llm_usage_read on public.llm_usage
  for select to authenticated
  using (household_id = public.current_household());

create trigger llm_usage_touch before update on public.llm_usage
  for each row execute function public.tg_touch_updated_at();

create or replace function public.llm_budget_remaining()
returns numeric language sql stable security definer set search_path = public as $$
  select h.llm_monthly_cap_eur - coalesce((
    select sum(u.cost_eur) from public.llm_usage u
    where u.household_id = h.id and u.month = date_trunc('month', now())::date
  ), 0)
  from public.household h where h.id = public.current_household()
$$;
revoke execute on function public.llm_budget_remaining() from public, anon;
grant   execute on function public.llm_budget_remaining() to authenticated, service_role;

-- Budget global d'ingestion (D11/D13). RÉSERVÉ au rôle de service : le revoke
-- seul ne suffit pas sous Supabase, qui accorde EXECUTE par défaut à anon et
-- authenticated. Il faut révoquer ces deux rôles NOMMÉMENT, puis accorder.
create or replace function public.llm_global_budget_remaining()
returns numeric language sql stable security definer set search_path = public as $$
  select coalesce((select (value ->> 'amount')::numeric from public.instance_setting
                   where key = 'llm_global_monthly_cap_eur'), 0)
       - coalesce((select sum(cost_eur) from public.llm_usage
                   where household_id is null
                     and month = date_trunc('month', now())::date), 0)
$$;
revoke execute on function public.llm_global_budget_remaining() from public, anon, authenticated;
grant   execute on function public.llm_global_budget_remaining() to service_role;
```

- [ ] **Step 4 : Appliquer, vérifier**

```bash
npm run db:reset && npm run test
```

- [ ] **Step 5 : Commit**

```bash
git add supabase/migrations/0007_llm_budget.sql tests/llm-budget.test.ts
git commit -m "feat(0a-1): compteur llm_usage et les deux plafonds"
```

---

### Task 9 : Flux d'invitation

Deux Edge Functions. **Le CORS n'est pas optionnel** : le front envoie `Authorization` et `Content-Type: application/json`, ce qui déclenche un préflight `OPTIONS`. Sans réponse à ce préflight, l'écran d'invitation ne peut rien appeler depuis `localhost:5173`.

**Files:**
- Create: `supabase/functions/_shared/cors.ts`, `supabase/functions/invite/index.ts`, `supabase/functions/accept-invite/index.ts`, `tests/invitation.test.ts`

- [ ] **Step 1 : Écrire le test qui échoue**

```typescript
// tests/invitation.test.ts
import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, makeOrphan, admin, accessToken, type Actor } from './helpers/db'

let alice: Actor
beforeAll(async () => { alice = await makeActor('alice-invit') })

const fn = (name: string) => `${process.env.VITE_SUPABASE_URL}/functions/v1/${name}`

describe('invitation', () => {
  it('un foyer crée une invitation pour lui-même', async () => {
    const { data, error } = await alice.client.from('invitation')
      .insert({ household_id: alice.householdId, email: 'copine@test.local' })
      .select().single()
    expect(error).toBeNull()
    expect(data!.token).toBeTruthy()
    expect(new Date(data!.expires_at).getTime()).toBeGreaterThan(Date.now())
  })

  it('un foyer ne peut pas inviter chez un autre foyer', async () => {
    const other = await makeActor('other-invit')
    const { error } = await alice.client.from('invitation')
      .insert({ household_id: other.householdId, email: 'pirate@test.local' })
    expect(error, 'invitation croisée acceptée').not.toBeNull()
  })

  it('répond au préflight CORS', async () => {
    const res = await fetch(fn('accept-invite'), {
      method: 'OPTIONS',
      headers: {
        Origin: 'http://localhost:5173',
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization, content-type',
      },
    })
    expect(res.status, 'sans préflight, le front ne peut rien appeler').toBeLessThan(300)
    expect(res.headers.get('access-control-allow-origin')).toBeTruthy()
  })

  it('accept-invite rattache l\'invité au foyer et consomme le token', async () => {
    const a = admin()
    const { data: inv } = await a.from('invitation')
      .insert({ household_id: alice.householdId, email: 'nouveau@test.local' })
      .select().single()

    const { client: guest } = await makeOrphan()
    const res = await fetch(fn('accept-invite'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${await accessToken(guest)}`,
      },
      body: JSON.stringify({ token: inv!.token }),
    })
    expect(res.status, await res.clone().text()).toBe(200)

    const { data: hh } = await guest.rpc('current_household')
    expect(hh).toBe(alice.householdId)

    const { data: after } = await a.from('invitation')
      .select('accepted_at').eq('id', inv!.id).single()
    expect(after!.accepted_at, 'le token doit être consommé').not.toBeNull()
  })

  it('refuse un token expiré', async () => {
    const { data: inv } = await admin().from('invitation').insert({
      household_id: alice.householdId, email: 'tard@test.local',
      expires_at: new Date(Date.now() - 1000).toISOString(),
    }).select().single()

    const { client: guest } = await makeOrphan()
    const res = await fetch(fn('accept-invite'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${await accessToken(guest)}`,
      },
      body: JSON.stringify({ token: inv!.token }),
    })
    expect(res.status).toBe(410)
  })
})
```

- [ ] **Step 2 : Démarrer le serveur de fonctions, lancer, vérifier l'échec**

Dans un **second terminal**, laissé ouvert jusqu'à la fin de la tâche :

```bash
npx supabase functions serve
```

Puis :
```bash
npm run test -- tests/invitation.test.ts
```
Attendu : ÉCHEC — 404 sur `accept-invite`.

- [ ] **Step 3 : Écrire le module CORS partagé**

```typescript
// supabase/functions/_shared/cors.ts
export const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

export const preflight = (req: Request) =>
  req.method === 'OPTIONS' ? new Response('ok', { headers: corsHeaders }) : null

export const reply = (body: unknown, status = 200) =>
  new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, 'Content-Type':
      typeof body === 'string' ? 'text/plain' : 'application/json' },
  })
```

- [ ] **Step 4 : Écrire `accept-invite`**

```typescript
// supabase/functions/accept-invite/index.ts
import { createClient } from 'jsr:@supabase/supabase-js@2'
import { preflight, reply } from '../_shared/cors.ts'

Deno.serve(async (req) => {
  const pre = preflight(req); if (pre) return pre
  if (req.method !== 'POST') return reply('Method not allowed', 405)

  const jwt = (req.headers.get('Authorization') ?? '').replace('Bearer ', '')
  if (!jwt) return reply('Non authentifié', 401)

  const admin = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  )

  const { data: userRes, error: userErr } = await admin.auth.getUser(jwt)
  if (userErr || !userRes.user) return reply('Non authentifié', 401)
  const user = userRes.user

  const { token } = await req.json().catch(() => ({ token: null }))
  if (!token) return reply('Token manquant', 400)

  const { data: inv } = await admin.from('invitation').select('*').eq('token', token).maybeSingle()
  if (!inv) return reply('Invitation inconnue', 404)
  if (inv.accepted_at) return reply('Invitation déjà utilisée', 409)
  if (new Date(inv.expires_at) < new Date()) return reply('Invitation expirée', 410)

  const { data: existing } = await admin
    .from('user_profile').select('id').eq('id', user.id).maybeSingle()
  if (existing) return reply('Déjà rattaché à un foyer', 409)

  const { error: pe } = await admin.from('user_profile').insert({
    id: user.id,
    household_id: inv.household_id,
    display_name: (user.email ?? 'invité').split('@')[0],
  })
  if (pe) return reply(pe.message, 500)

  await admin.from('invitation')
    .update({ accepted_at: new Date().toISOString() }).eq('id', inv.id)

  return reply({ household_id: inv.household_id })
})
```

- [ ] **Step 5 : Écrire `invite`**

```typescript
// supabase/functions/invite/index.ts
import { createClient } from 'jsr:@supabase/supabase-js@2'
import { preflight, reply } from '../_shared/cors.ts'

Deno.serve(async (req) => {
  const pre = preflight(req); if (pre) return pre
  if (req.method !== 'POST') return reply('Method not allowed', 405)

  const jwt = (req.headers.get('Authorization') ?? '').replace('Bearer ', '')
  if (!jwt) return reply('Non authentifié', 401)

  const admin = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  )
  const { data: userRes } = await admin.auth.getUser(jwt)
  if (!userRes?.user) return reply('Non authentifié', 401)

  const { data: profile } = await admin
    .from('user_profile').select('household_id').eq('id', userRes.user.id).maybeSingle()
  if (!profile) return reply('Aucun foyer', 403)

  const { email } = await req.json().catch(() => ({ email: null }))
  if (!email) return reply('Email manquant', 400)

  const { data: inv, error } = await admin.from('invitation')
    .insert({ household_id: profile.household_id, email, created_by: userRes.user.id })
    .select().single()
  if (error) return reply(error.message, 409)

  const link = `${Deno.env.get('APP_BASE_URL')}/invite/${inv.token}`
  const key = Deno.env.get('RESEND_API_KEY')

  if (key) {
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: 'invitation@batchcooking.local',
        to: [email],
        subject: 'Invitation à rejoindre le foyer',
        html: `<p>Vous êtes invité·e.</p><p><a href="${link}">Rejoindre le foyer</a></p>
               <p>Ce lien expire dans 7 jours.</p>`,
      }),
    })
    // L'invitation reste valide si l'e-mail échoue : le lien est renvoyable.
    if (!r.ok) console.error('Resend a échoué :', await r.text())
  }

  return reply({ token: inv.token, link })
})
```

- [ ] **Step 5bis : Déclarer les fonctions dans `config.toml`, maintenant qu'elles existent**

Sans cela, `verify_jwt = true` s'applique et le préflight `OPTIONS` — qui ne porte pas
d'en-tête `Authorization` — reçoit 401 avant d'atteindre le code de la fonction.

```bash
cat >> supabase/config.toml <<'EOF'

# Les deux fonctions valident elles-mêmes le JWT via admin.auth.getUser(jwt).
# Désactiver la vérification de la passerelle est donc sans danger, et c'est la
# seule façon de laisser passer le préflight OPTIONS.
[functions.invite]
verify_jwt = false

[functions.accept-invite]
verify_jwt = false
EOF
npx supabase stop && npx supabase start   # config.toml n'est relu qu'au démarrage
```

- [ ] **Step 6 : Relancer (le serveur de fonctions du Step 2 doit toujours tourner)**

```bash
npm run test -- tests/invitation.test.ts
```
Attendu : PASS sur les cinq cas, préflight compris.

- [ ] **Step 7 : Commit**

```bash
git add supabase/functions tests/invitation.test.ts
git commit -m "feat(0a-1): flux d'invitation, CORS, Edge Functions et envoi Resend"
```

---

### Task 10 : Le front — porte d'entrée et trois écrans

⚠️ **Deux manques à combler, sans quoi l'application livrée est inutilisable** : il n'y a aucun **chemin d'authentification**, et aucune **porte d'entrée pour créer le tout premier foyer**. Le livrable §10 est « deux comptes, un foyer » : il doit exister dans l'app, pas seulement dans les tests.

**Files:**
- Create: `src/lib/supabase.ts`, `src/pages/SignIn.tsx`, `src/pages/Onboarding.tsx`, `src/pages/Targets.tsx`, `src/pages/Settings.tsx`, `src/pages/AcceptInvite.tsx`
- Modify: `src/App.tsx`
- Create: `supabase/migrations/0009_create_household.sql`

- [ ] **Step 1 : Le client**

```typescript
// src/lib/supabase.ts
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
)
```

- [ ] **Step 2 : Test de la création du premier foyer**

Ajouter à `tests/isolation.test.ts` :

```typescript
describe('création du premier foyer', () => {
  // ⚠️ Indispensable : makeActor() a déjà créé des foyers dans le beforeAll global,
  // donc le repli `not exists (household)` vaut false et l'instance serait fermée.
  // Sans ce réglage, le test d'évasion ci-dessous passe À VIDE — il resterait vert
  // même si l'on remettait `for all` sur user_profile, c'est-à-dire exactement la
  // régression qu'il est censé interdire.
  beforeAll(async () => {
    await admin().from('instance_setting')
      .upsert({ key: 'allow_household_creation', value: { enabled: true } })
  })

  it('un authentifié sans profil peut créer son foyer, une seule fois', async () => {
    const { client: solo } = await makeOrphan()
    const { data, error } = await solo.rpc('create_household', { p_name: 'Chez nous' })
    expect(error).toBeNull()
    expect(data).toBeTruthy()

    const { data: hh } = await solo.rpc('current_household')
    expect(hh).toBe(data)

    // Deuxième appel : refusé.
    const { error: e2 } = await solo.rpc('create_household', { p_name: 'Évasion' })
    expect(e2, 'un utilisateur déjà rattaché ne doit pas pouvoir créer un foyer').not.toBeNull()
  })

  it("ne peut PAS être contournée en supprimant son propre profil", async () => {
    // Mesuré : avec une policy DELETE sur user_profile, l'utilisateur efface son
    // profil, current_household() repasse à NULL, et create_household() réussit à
    // nouveau — il s'échappe de son foyer. La Task 6 retire cette policy ; ce test
    // garantit qu'on ne la réintroduira pas.
    const { client: evade } = await makeOrphan()
    const { data: hh1, error: e1 } = await evade.rpc('create_household', { p_name: 'Premier' })
    expect(e1, "l'amorce a échoué : tout le test dégénérerait en expect(null).toBe(null)").toBeNull()
    expect(hh1).toBeTruthy()
    const { data: me } = await evade.auth.getUser()

    await evade.from('user_profile').delete().eq('id', me.user!.id)
    const { data: still } = await evade.rpc('current_household')
    expect(still, 'le profil a pu être supprimé : évasion possible').toBe(hh1)

    const { error } = await evade.rpc('create_household', { p_name: 'Évasion' })
    expect(error, 'évasion réussie vers un second foyer').not.toBeNull()
    // Et l'erreur doit venir du garde « déjà rattaché », pas du verrou d'instance :
    // sinon le test ne prouverait rien sur l'absence de policy DELETE.
    expect(String((error as any).message)).toContain('rattaché')
  })

  it("refuse la création quand l'instance est verrouillée (D7)", async () => {
    const a = admin()
    await a.from('instance_setting')
      .upsert({ key: 'allow_household_creation', value: { enabled: false } })
    const { client: tard } = await makeOrphan()
    const { error } = await tard.rpc('create_household', { p_name: 'Trop tard' })
    expect(error, "l'instance est sur invitation : la création doit être refusée").not.toBeNull()
    await a.from('instance_setting')
      .upsert({ key: 'allow_household_creation', value: { enabled: true } })
  })
})
```

- [ ] **Step 3 : Écrire `0009_create_household.sql`**

```sql
-- supabase/migrations/0009_create_household.sql
-- Porte d'entrée : un utilisateur authentifié SANS profil crée son foyer.
-- SECURITY DEFINER car il doit écrire dans household et user_profile alors que
-- current_household() vaut encore NULL, donc que les policies le bloqueraient.
create or replace function public.create_household(p_name text)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare v_uid uuid := auth.uid(); v_id uuid; v_open boolean;
begin
  if v_uid is null then
    raise exception 'non authentifié' using errcode = 'insufficient_privilege';
  end if;
  if exists (select 1 from public.user_profile where id = v_uid) then
    raise exception 'déjà rattaché à un foyer' using errcode = 'unique_violation';
  end if;

  -- D7 : l'instance est sur invitation. L'auto-inscription reste active (un
  -- invité doit pouvoir créer son compte), mais la création d'un FOYER est
  -- bridée par un réglage d'instance. Ouverte tant qu'aucun foyer n'existe
  -- (amorçage), puis fermable d'un UPDATE. Sans ce garde, n'importe qui
  -- s'inscrirait et se créerait un foyer, ce qui contredirait D7.
  select coalesce((select (value ->> 'enabled')::boolean from public.instance_setting
                   where key = 'allow_household_creation'),
                  not exists (select 1 from public.household))
    into v_open;
  if not v_open then
    raise exception 'création de foyer fermée : cette instance est sur invitation'
      using errcode = 'insufficient_privilege';
  end if;

  insert into public.household (name) values (coalesce(nullif(p_name,''), 'Mon foyer'))
    returning id into v_id;
  insert into public.user_profile (id, household_id, display_name)
    values (v_uid, v_id,
            split_part(coalesce((select email from auth.users where id = v_uid), 'moi'), '@', 1));
  return v_id;
end $$;

revoke execute on function public.create_household(text) from public, anon;
grant   execute on function public.create_household(text) to authenticated;

-- Semé explicitement à TRUE : ne pas dépendre du repli `not exists (household)`,
-- qui bascule dès le premier foyer créé et rendrait l'amorçage imprévisible.
-- ⚠️ À passer à false une fois vos deux comptes en place (Task 12, Step 3bis).
insert into public.instance_setting (key, value)
values ('allow_household_creation', '{"enabled": true}'::jsonb)
on conflict (key) do nothing;
```

- [ ] **Step 4 : Vérifier**

```bash
npm run db:reset && npm run test -- tests/isolation.test.ts
```
Attendu : les **quatre** tests du describe PASSENT — création, refus du second appel, non-contournement par suppression du profil, et refus quand l'instance est verrouillée.

- [ ] **Step 5 : Écran de connexion**

```tsx
// src/pages/SignIn.tsx
import { useState } from 'react'
import { supabase } from '../lib/supabase'

export function SignIn({ redirectTo }: { redirectTo?: string }) {
  const [email, setEmail] = useState('')
  const [msg, setMsg] = useState('')

  async function send() {
    const { error } = await supabase.auth.signInWithOtp({
      email, options: { emailRedirectTo: redirectTo ?? window.location.href },
    })
    setMsg(error ? error.message : 'Lien envoyé. Ouvrez-le depuis cet appareil.')
  }

  return (
    <main>
      <h1>Connexion</h1>
      <input type="email" value={email} placeholder="votre e-mail"
             onChange={e => setEmail(e.target.value)} />
      <button onClick={send}>Recevoir un lien de connexion</button>
      <p role="status">{msg}</p>
    </main>
  )
}
```

- [ ] **Step 6 : Écran d'amorçage — créer son foyer ou attendre une invitation**

```tsx
// src/pages/Onboarding.tsx
import { useState } from 'react'
import { supabase } from '../lib/supabase'

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('Notre foyer')
  const [msg, setMsg] = useState('')

  async function create() {
    const { error } = await supabase.rpc('create_household', { p_name: name })
    if (error) return setMsg(error.message)
    onDone()
  }

  return (
    <main>
      <h1>Créer votre foyer</h1>
      <p>Si quelqu’un vous a déjà invité·e, ouvrez plutôt le lien reçu par e-mail.</p>
      <input value={name} onChange={e => setName(e.target.value)} />
      <button onClick={create}>Créer le foyer</button>
      <p role="status">{msg}</p>
    </main>
  )
}
```

- [ ] **Step 7 : Écran « mes objectifs »** — historisé : chaque enregistrement est un `insert`, jamais un `update`

```tsx
// src/pages/Targets.tsx
import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

const CHAMPS = ['kcal', 'protein_g', 'fiber_g', 'carb_g', 'fat_g'] as const

export function Targets({ userId }: { userId: string }) {
  const [v, setV] = useState<Record<string, number>>(
    { kcal: 2000, protein_g: 150, fiber_g: 30, carb_g: 200, fat_g: 60 })
  const [hist, setHist] = useState<any[]>([])
  const [msg, setMsg] = useState('')

  async function load() {
    const { data } = await supabase.from('nutrition_target')
      .select('*').eq('user_profile_id', userId).order('valid_from', { ascending: false })
    setHist(data ?? [])
  }
  useEffect(() => { load() }, [userId])

  async function save() {
    // INSERT, jamais UPDATE : les cibles sont historisées (spec §5.1).
    const { error } = await supabase.from('nutrition_target')
      .insert({ user_profile_id: userId, ...v })
    setMsg(error ? error.message : 'Objectif enregistré.')
    if (!error) load()
  }

  return (
    <main>
      <h1>Mes objectifs</h1>
      {CHAMPS.map(c => (
        <label key={c}>{c}
          <input type="number" value={v[c]}
                 onChange={e => setV({ ...v, [c]: Number(e.target.value) })} />
        </label>
      ))}
      <button onClick={save}>Enregistrer</button>
      <p role="status">{msg}</p>
      <h2>Historique</h2>
      <ul>{hist.map(h => (
        <li key={h.id}>
          {new Date(h.valid_from).toLocaleDateString('fr-FR')} — {h.kcal} kcal, {h.protein_g} g de protéines
        </li>))}
      </ul>
    </main>
  )
}
```

- [ ] **Step 8 : Écran « réglages »** — plafond LLM, invitation, export et suppression

```tsx
// src/pages/Settings.tsx
import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

const fn = (n: string) => `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/${n}`

export function Settings() {
  const [cap, setCap] = useState(5)
  const [left, setLeft] = useState<number | null>(null)
  const [invitee, setInvitee] = useState('')
  const [msg, setMsg] = useState('')

  async function load() {
    const { data: h } = await supabase.from('household')
      .select('llm_monthly_cap_eur').maybeSingle()
    if (h) setCap(Number(h.llm_monthly_cap_eur))
    const { data: r } = await supabase.rpc('llm_budget_remaining')
    setLeft(r === null ? null : Number(r))
  }
  useEffect(() => { load() }, [])

  async function saveCap() {
    const { data: hh } = await supabase.rpc('current_household')
    const { error } = await supabase.from('household')
      .update({ llm_monthly_cap_eur: cap }).eq('id', hh)
    setMsg(error ? error.message : 'Plafond enregistré.')
    if (!error) load()
  }

  async function invite() {
    const { data: s } = await supabase.auth.getSession()
    const res = await fetch(fn('invite'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${s.session!.access_token}`,
      },
      body: JSON.stringify({ email: invitee }),
    })
    setMsg(res.ok ? 'Invitation envoyée.' : await res.text())
  }

  async function exportData() {
    const { data, error } = await supabase.rpc('export_my_data')
    if (error) return setMsg(error.message)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'mes-donnees.json'
    a.click()
  }

  async function deleteAccount() {
    if (!confirm('Supprimer définitivement votre compte et vos données ? Action irréversible.')) return
    const { error } = await supabase.rpc('delete_my_account')
    if (error) return setMsg(error.message)
    await supabase.auth.signOut()
    window.location.href = '/'
  }

  return (
    <main>
      <h1>Réglages</h1>

      <h2>Budget IA</h2>
      <label>Plafond mensuel (€)
        <input type="number" step="0.5" value={cap}
               onChange={e => setCap(Number(e.target.value))} />
      </label>
      <button onClick={saveCap}>Enregistrer</button>
      <p>Budget restant ce mois-ci : {left === null ? '—' : `${left.toFixed(2)} €`}</p>

      <h2>Inviter quelqu’un dans le foyer</h2>
      <input type="email" value={invitee} placeholder="son e-mail"
             onChange={e => setInvitee(e.target.value)} />
      <button onClick={invite}>Envoyer l’invitation</button>

      <h2>Mes données</h2>
      <button onClick={exportData}>Exporter mes données</button>
      <button onClick={deleteAccount}>Supprimer mon compte</button>

      <p role="status">{msg}</p>
    </main>
  )
}
```

- [ ] **Step 9 : Écran « accepter une invitation »**

```tsx
// src/pages/AcceptInvite.tsx
import { useState } from 'react'
import { supabase } from '../lib/supabase'

export function AcceptInvite({ token }: { token: string }) {
  const [msg, setMsg] = useState('')

  async function accept() {
    const { data } = await supabase.auth.getSession()
    if (!data.session) return setMsg('Connectez-vous d’abord.')
    const res = await fetch(
      `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/accept-invite`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${data.session.access_token}`,
        },
        body: JSON.stringify({ token }),
      })
    if (res.ok) { window.location.href = '/' } else { setMsg(await res.text()) }
  }

  return (
    <main>
      <h1>Rejoindre le foyer</h1>
      <button onClick={accept}>Rejoindre</button>
      <p role="status">{msg}</p>
    </main>
  )
}
```

- [ ] **Step 10 : `App.tsx` — la porte d'entrée qui manquait**

```tsx
// src/App.tsx
import { useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './lib/supabase'
import { SignIn } from './pages/SignIn'
import { Onboarding } from './pages/Onboarding'
import { Targets } from './pages/Targets'
import { Settings } from './pages/Settings'
import { AcceptInvite } from './pages/AcceptInvite'

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [household, setHousehold] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  async function refresh() {
    const { data } = await supabase.auth.getSession()
    setSession(data.session)
    if (data.session) {
      const { data: hh } = await supabase.rpc('current_household')
      setHousehold(hh ?? null)
    }
    setReady(true)
  }

  useEffect(() => {
    refresh()
    const { data: sub } = supabase.auth.onAuthStateChange(() => refresh())
    return () => sub.subscription.unsubscribe()
  }, [])

  if (!ready) return <main><p>Chargement…</p></main>

  const invite = window.location.pathname.match(/^\/invite\/(.+)$/)

  // 1. Pas de session → connexion (en conservant la cible d'invitation).
  if (!session) return <SignIn redirectTo={window.location.href} />
  // 2. Session + lien d'invitation → acceptation.
  if (invite) return <AcceptInvite token={invite[1]} />
  // 3. Session sans foyer → amorçage.
  if (!household) return <Onboarding onDone={refresh} />
  // 4. Nominal.
  if (window.location.pathname.startsWith('/settings')) return <Settings />
  return <Targets userId={session.user.id} />
}
```

- [ ] **Step 11 : Vérification manuelle du parcours complet**

```bash
npm run db:reset   # sinon les foyers laissés par les tests ferment l'amorçage (D7)
npm run dev
```
1. `/` → écran de connexion. Récupérer le lien magique dans le serveur SMTP local — **Mailpit**, section `[local_smtp]` de `config.toml` (`http://127.0.0.1:54324`).
2. Après connexion → écran d'amorçage. Créer le foyer.
3. → Écran des objectifs. Enregistrer, vérifier que l'historique s'allonge.
4. `/settings` → régler le plafond, inviter une seconde adresse.
5. Ouvrir le lien d'invitation dans une **fenêtre privée** → se connecter → rejoindre.
6. Vérifier que le second compte voit bien le même foyer.

**Aucune erreur CORS ne doit apparaître dans la console.** S'il y en a, la Task 9 est incomplète.

- [ ] **Step 12 : Commit**

```bash
git add src supabase/migrations/0009_create_household.sql tests/isolation.test.ts
git commit -m "feat(0a-1): porte d'entrée, création de foyer et les trois écrans"
```

---

### Task 11 : Export et suppression de compte (RGPD, §11 q. 1)

**Pourquoi maintenant, alors que le RGPD ne s'applique pas encore** : en usage strictement domestique (vous deux), l'exemption de l'art. 2.2.c joue et rien n'est obligatoire. Ces deux fonctions sont livrées ici parce qu'elles font **20 lignes de SQL**, qu'elles servent de sauvegarde dès le premier jour, et qu'elles éviteront de reprendre le schéma le jour où un foyer tiers se connectera (D7). C'est de la prévoyance bon marché, pas une mise en conformité.

**Files:**
- Create: `supabase/migrations/0008_rgpd.sql`, `tests/rgpd.test.ts`

- [ ] **Step 1 : Écrire le test qui échoue**

```typescript
// tests/rgpd.test.ts
import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, admin, type Actor } from './helpers/db'

let alice: Actor
beforeAll(async () => {
  alice = await makeActor('alice-rgpd')
  await alice.client.from('nutrition_target').insert({
    user_profile_id: alice.userId,
    kcal: 2000, protein_g: 150, fiber_g: 30, carb_g: 200, fat_g: 60,
  })
})

describe('RGPD', () => {
  it('exporte les données du foyer, et rien d\'autre', async () => {
    const { data, error } = await alice.client.rpc('export_my_data')
    expect(error).toBeNull()
    expect(data.household.id).toBe(alice.householdId)
    expect(data.nutrition_targets.length).toBeGreaterThanOrEqual(1)
    expect(data.profiles.every((p: any) => p.household_id === alice.householdId)).toBe(true)
  })

  it('supprime le compte et ses données en cascade', async () => {
    const victim = await makeActor('victime')
    await victim.client.from('nutrition_target').insert({
      user_profile_id: victim.userId,
      kcal: 1, protein_g: 1, fiber_g: 1, carb_g: 1, fat_g: 1,
    })
    const { error } = await victim.client.rpc('delete_my_account')
    expect(error).toBeNull()

    const a = admin()
    const { data: prof } = await a.from('user_profile').select('id').eq('id', victim.userId)
    expect(prof, 'le profil doit avoir disparu').toHaveLength(0)
    const { data: tg } = await a.from('nutrition_target')
      .select('id').eq('user_profile_id', victim.userId)
    expect(tg, 'les cibles doivent avoir disparu en cascade').toHaveLength(0)
    const { data: u } = await a.auth.admin.getUserById(victim.userId)
    expect(u.user, "le compte d'authentification doit avoir disparu").toBeNull()
  })
})
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
npm run test -- tests/rgpd.test.ts
```
Attendu : ÉCHEC — `function public.export_my_data does not exist`.

- [ ] **Step 3 : Écrire `0008_rgpd.sql`**

```sql
-- supabase/migrations/0008_rgpd.sql
-- §11 q. 1 : export et suppression, livrés dans ce lot.

create or replace function public.export_my_data()
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'exported_at',       now(),
    'household',         (select to_jsonb(h) from public.household h
                          where h.id = public.current_household()),
    'profiles',          (select coalesce(jsonb_agg(to_jsonb(p)), '[]'::jsonb)
                          from public.user_profile p
                          where p.household_id = public.current_household()),
    'nutrition_targets', (select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb)
                          from public.nutrition_target t
                          where t.household_id = public.current_household()),
    'invitations',       (select coalesce(jsonb_agg(to_jsonb(i)), '[]'::jsonb)
                          from public.invitation i
                          where i.household_id = public.current_household()),
    'llm_usage',         (select coalesce(jsonb_agg(to_jsonb(u)), '[]'::jsonb)
                          from public.llm_usage u
                          where u.household_id = public.current_household())
  )
$$;
revoke execute on function public.export_my_data() from public, anon;
grant   execute on function public.export_my_data() to authenticated;

-- Supprime le profil (donc les cibles en cascade), puis le compte d'auth.
-- Le foyer n'est supprimé que s'il ne reste personne dedans.
create or replace function public.delete_my_account()
returns void language plpgsql security definer set search_path = public as $$
declare v_uid uuid := auth.uid(); v_hh uuid;
begin
  if v_uid is null then
    raise exception 'non authentifié' using errcode = 'insufficient_privilege';
  end if;

  select household_id into v_hh from public.user_profile where id = v_uid;
  delete from public.user_profile where id = v_uid;

  if v_hh is not null
     and not exists (select 1 from public.user_profile where household_id = v_hh) then
    delete from public.household where id = v_hh;
  end if;

  delete from auth.users where id = v_uid;
end $$;
revoke execute on function public.delete_my_account() from public, anon;
grant   execute on function public.delete_my_account() to authenticated;
```

> **Si le test de suppression du compte d'authentification échoue** : `delete from auth.users`
> court-circuite GoTrue et suppose que `postgres` a le DELETE et que toutes les tables filles du
> schéma `auth` cascadent. C'est le cas sous Supabase, mais si ce n'est pas vérifié, la voie
> supportée est `auth.admin.deleteUser()` depuis une Edge Function. Ne pas laisser un profil
> supprimé et un compte orphelin.

- [ ] **Step 4 : Appliquer, vérifier**

```bash
npm run db:reset && npm run test
```
Attendu : la suite entière est verte.

- [ ] **Step 5 : Commit**

```bash
git add supabase/migrations/0008_rgpd.sql tests/rgpd.test.ts
git commit -m "feat(0a-1): export et suppression de compte (RGPD)"
```

---

### Task 12 : Déploiement en région UE

⚠️ **Ne PAS rejouer la suite complète contre la production** : elle crée des utilisateurs, des foyers et des lignes via l'API d'administration, sans nettoyage. Créer un **second projet Supabase de recette** (même région), y rejouer la suite, et ne faire contre la production qu'une vérification en lecture.

**Files:**
- Create: `README.md`

- [ ] **Step 1 : Créer les projets en région européenne**

Dans le tableau de bord Supabase, créer **deux** projets en région UE (`eu-west-3` Paris ou `eu-central-1` Francfort) : `batchcooking-recette` et `batchcooking-prod`. **Vérifier que la version de PostgreSQL est ≥ 15** : `unique nulls not distinct` (Task 8) n'existe pas avant.
**La région n'est pas modifiable après coup** — c'est une contrainte du spec (§11 q. 1).

- [ ] **Step 2 : Pousser sur la recette et y rejouer toute la suite**

```bash
npx supabase link --project-ref <REF_RECETTE>
npx supabase db push
npx supabase functions deploy invite accept-invite
npx supabase secrets set RESEND_API_KEY=<clé> APP_BASE_URL=<url>

VITE_SUPABASE_URL=<url-recette> VITE_SUPABASE_ANON_KEY=<anon-recette> \
SUPABASE_SERVICE_ROLE_KEY=<service-recette> npm run test
```
Attendu : **toute la suite passe en distant.** Une policy qui marche en local et pas en distant est un échec du lot, pas un détail de configuration.

- [ ] **Step 3 : Pousser en production, et n'y vérifier qu'en lecture**

```bash
npx supabase link --project-ref <REF_PROD>
npx supabase db push
npx supabase functions deploy invite accept-invite
npx supabase secrets set RESEND_API_KEY=<clé> APP_BASE_URL=<url-prod>
```

Vérification en lecture seule, sans rien créer :
```bash
psql "<DB_URL_PROD>" -c "
  select tablename, rowsecurity from pg_tables
  where schemaname='public' order by tablename;"
```
Attendu : **`rowsecurity = true` sur les 20 tables.** Aucune exception.

- [ ] **Step 3bis : Fermer la création de foyer une fois vos comptes en place**

L'instance est livrée ouverte pour permettre l'amorçage. Une fois votre foyer créé et votre
invitation acceptée, **la refermer** — sans quoi toute personne qui s'inscrit peut se créer un
foyer, ce qui contredit D7 :

```bash
psql "<DB_URL_PROD>" -c "
  update public.instance_setting
  set value = '{\"enabled\": false}'::jsonb
  where key = 'allow_household_creation';"
```

Vérifier ensuite qu'un nouveau compte se voit refuser la création. Les invitations, elles,
continuent de fonctionner : elles passent par `accept-invite`, pas par `create_household()`.

- [ ] **Step 4 : Écrire le `README.md`**

Documenter : prérequis, `npx supabase start`, `npm run db:reset`, `npm run test`, le second terminal pour `functions serve`, les variables d'environnement, **la règle de région UE**, et la distinction recette/production.

- [ ] **Step 5 : Commit**

```bash
git add README.md && git commit -m "docs(0a-1): déploiement UE et mode d'emploi"
```

---

### Task 13 : Vérification de fin de lot

- [ ] **Step 1 : La suite complète passe**

```bash
npm run db:reset && npm run test
```

- [ ] **Step 2 : Prouver une dernière fois que les tests mordent**

Refaire la manipulation de la Task 6, Step 7 : désactiver la RLS sur `recipe` **et** sur `nutrition_target`, relancer, vérifier que **des tests rougissent**. Puis `npm run db:reset`.

Un lot dont les tests restent verts quand on retire la sécurité n'a rien prouvé.

- [ ] **Step 3 : Liste de contrôle du spec §10**

| Livrable | Vérifié par |
|---|---|
| Projet Supabase région UE | Task 12, étape 1 |
| Schéma classes A et B, tables foyer de §5.1 | Tasks 3, 4, 5 |
| `current_household()` en `SECURITY DEFINER` | Task 6 + test de non-récursion |
| Les 3 formes de policies (§5.0.1) | Task 6 + `isolation.test.ts` + Task 6 Step 7 |
| Trigger `BEFORE UPDATE` classe B | Task 7 + `class-b-guard.test.ts` |
| Flux d'invitation via Resend | Task 9 + `invitation.test.ts` (CORS compris) |
| CRUD profils et cibles historisées | Tasks 3, 10 |
| Compteur `llm_usage` et les deux plafonds | Task 8 + `llm-budget.test.ts` |
| Export et suppression de compte (§11 q. 1) | Task 11 + `rgpd.test.ts` |
| Trois écrans + porte d'entrée | Task 10, vérification manuelle Step 11 |

- [ ] **Step 4 : Commit de clôture**

```bash
git add -A && git commit -m "feat(0a-1): lot terminé — isolation prouvée par des tests qui mordent"
```

---

## Ce que ce lot ne livre pas, volontairement

- **Les référentiels sont vides.** CIQUAL, Open Food Facts et les tables de conversion sont le lot 0a-2.
- **Aucune recette.** L'ingestion est le lot 0b, précédée de R1, R1b et R1c.
- **Aucun appel LLM.** Le compteur existe, rien ne l'incrémente encore.
- **`recipe.plannable` n'a pas de trigger.** Reporté au lot 0b, où les durées des actions existeront.
- **La policy de lecture de la classe B ignore `visibility`.** À resserrer au lot 4.
- **Aucun soin visuel.** Des écrans fonctionnels, rien de plus.

## Critère de réussite

**Un foyer ne peut voir aucune donnée de foyer d'un autre foyer, et les tests le prouvent — en local comme en distant — en rougissant dès qu'on retire la RLS.**

C'est la seule formulation honnête : le catalogue partagé (classe B) est, lui, délibérément visible de tous, et il est vide à ce stade.
